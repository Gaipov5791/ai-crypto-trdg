"""OWNER: Market agent.

Implement Binance public REST klines + WS tickers for BTCUSDT, ETHUSDT, SOLUSDT.
Do not implement paper fills or signals here.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from typing import Any

import httpx

try:
    from websockets.asyncio.client import connect as ws_connect
except ImportError:  # websockets < 13
    from websockets import connect as ws_connect
from websockets.exceptions import ConnectionClosed

from app.config import settings
from app.market.mapping import (
    candle_from_rest_kline,
    candle_from_ws_kline,
    ticker_from_mini,
    ticker_from_price,
)
from app.schemas import Candle, Ticker

logger = logging.getLogger(__name__)

MAX_CANDLES = 1000
REST_LIMIT = 500
WS_BACKOFF_INITIAL = 1.0
WS_BACKOFF_MAX = 30.0
TRANSIENT_WS_ERRORS = (ConnectionClosed, ConnectionResetError, TimeoutError, OSError)


def configured_intervals() -> tuple[str, ...]:
    ordered: list[str] = []
    for interval in (settings.chart_timeframe, settings.signal_timeframe):
        if interval not in ordered:
            ordered.append(interval)
    return tuple(ordered) or ("1m", "5m")


def build_combined_stream_url(base: str, symbols: tuple[str, ...], intervals: tuple[str, ...]) -> str:
    streams: list[str] = []
    for symbol in symbols:
        lower = symbol.lower()
        for interval in intervals:
            streams.append(f"{lower}@kline_{interval}")
        streams.append(f"{lower}@miniTicker")
    joined = "/".join(streams)
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}streams={joined}"


class MarketProvider:
    def __init__(self) -> None:
        self._klines: dict[tuple[str, str], list[Candle]] = {}
        self._tickers: dict[str, Ticker] = {}
        self._started = False
        self._stopped = False
        self._start_lock = asyncio.Lock()
        self._ws_task: asyncio.Task[None] | None = None
        self.on_ticker: Callable[[Ticker], None] | None = None
        self.on_kline: Callable[[Candle], None] | None = None
        self.on_closed_kline: Callable[[Candle], None] | None = None

    @property
    def symbols(self) -> tuple[str, ...]:
        return settings.symbols

    @property
    def intervals(self) -> tuple[str, ...]:
        return configured_intervals()

    @property
    def started(self) -> bool:
        return self._started

    async def start(self) -> None:
        """Idempotent: REST bootstrap once, then a reconnecting WS loop."""
        if self._started:
            return
        async with self._start_lock:
            if self._started:
                return
            self._stopped = False
            await self._bootstrap_rest()
            self._ws_task = asyncio.create_task(self._run_ws_forever(), name="binance-ws")
            self._started = True

    async def stop(self) -> None:
        self._stopped = True
        self._started = False
        task = self._ws_task
        self._ws_task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    def get_klines(self, symbol: str, interval: str, limit: int = 500) -> list[Candle]:
        key = (symbol.upper(), interval)
        candles = self._klines.get(key, [])
        closed = [c for c in candles if c.is_closed]
        if limit < 1:
            return []
        if limit < len(closed):
            return closed[-limit:]
        return list(closed)

    def get_ticker(self, symbol: str) -> Ticker:
        ticker = self._tickers.get(symbol.upper())
        if ticker is None:
            raise KeyError(symbol)
        return ticker

    def handle_stream_message(self, payload: dict[str, Any]) -> None:
        """Apply a combined-stream (or raw) Binance WS message to the cache."""
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        if not isinstance(data, dict):
            return
        event = data.get("e")
        if event == "kline" or "k" in data:
            self._on_kline(data)
        elif event == "24hrMiniTicker":
            ticker = ticker_from_mini(data)
            self._tickers[ticker.symbol] = ticker
            self._emit_ticker(ticker)

    def reset_for_tests(self) -> None:
        self._klines.clear()
        self._tickers.clear()
        self._started = False
        self._stopped = False
        self._ws_task = None

    def _emit_ticker(self, ticker: Ticker) -> None:
        cb = self.on_ticker
        if cb is None:
            return
        try:
            cb(ticker)
        except Exception:
            logger.exception("on_ticker callback failed")

    def _emit_kline(self, candle: Candle) -> None:
        cb = self.on_kline
        if cb is None:
            return
        try:
            cb(candle)
        except Exception:
            logger.exception("on_kline callback failed")

    def _emit_closed_kline(self, candle: Candle) -> None:
        cb = self.on_closed_kline
        if cb is None:
            return
        try:
            cb(candle)
        except Exception:
            logger.exception("on_closed_kline callback failed")

    def inject_klines(self, symbol: str, interval: str, candles: list[Candle]) -> None:
        self._klines[(symbol.upper(), interval)] = list(candles)

    def inject_ticker(self, ticker: Ticker) -> None:
        self._tickers[ticker.symbol] = ticker

    async def _bootstrap_rest(self) -> None:
        timeout = httpx.Timeout(20.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            jobs = [
                self._fetch_klines(client, symbol, interval)
                for symbol in self.symbols
                for interval in self.intervals
            ]
            results = await asyncio.gather(*jobs, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                logger.warning("REST kline bootstrap failed: %s", result)

    async def _fetch_klines(self, client: httpx.AsyncClient, symbol: str, interval: str) -> None:
        url = f"{settings.binance_rest.rstrip('/')}/api/v3/klines"
        response = await client.get(
            url,
            params={"symbol": symbol, "interval": interval, "limit": REST_LIMIT},
        )
        response.raise_for_status()
        rows = response.json()
        now_ms = int(time.time() * 1000)
        candles = [
            candle_from_rest_kline(row, symbol, interval, now_ms=now_ms) for row in rows
        ]
        self._klines[(symbol, interval)] = candles
        if candles:
            last = candles[-1]
            self._tickers[symbol] = ticker_from_price(symbol, last.close, now_ms)

    async def _run_ws_forever(self) -> None:
        delay = WS_BACKOFF_INITIAL
        while not self._stopped:
            try:
                await self._consume_ws()
                delay = WS_BACKOFF_INITIAL
            except asyncio.CancelledError:
                raise
            except TRANSIENT_WS_ERRORS as exc:
                logger.warning(
                    "Binance websocket dropped (%s); reconnecting in %.0fs",
                    exc,
                    delay,
                )
            except Exception:
                logger.exception("Binance websocket failed; reconnecting in %.0fs", delay)
            if self._stopped:
                break
            await asyncio.sleep(delay)
            delay = min(delay * 2, WS_BACKOFF_MAX)
            try:
                await self._bootstrap_rest()
            except Exception:
                logger.warning("REST resync after websocket drop failed", exc_info=True)

    async def _consume_ws(self) -> None:
        url = build_combined_stream_url(
            settings.binance_ws, self.symbols, self.intervals
        )
        async with ws_connect(
            url,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=5,
            max_size=2**22,
        ) as ws:
            async for raw in ws:
                if self._stopped:
                    break
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    logger.debug("skipping non-json ws frame")
                    continue
                if isinstance(payload, dict):
                    self.handle_stream_message(payload)

    def _on_kline(self, data: dict[str, Any]) -> None:
        k = data.get("k")
        if not isinstance(k, dict):
            return
        symbol = str(data.get("s") or k.get("s") or "")
        if not symbol:
            return
        candle = candle_from_ws_kline(symbol, k)
        if candle.is_closed:
            self._upsert_candle(candle)
        else:
            self._upsert_open_candle(candle)
        event_ts = int(data.get("E") or k.get("T") or time.time() * 1000)
        ticker = ticker_from_price(symbol, candle.close, event_ts)
        self._tickers[symbol] = ticker
        self._emit_kline(candle)
        self._emit_ticker(ticker)
        if candle.is_closed:
            self._emit_closed_kline(candle)

    def _upsert_candle(self, candle: Candle) -> None:
        series = self._klines.setdefault((candle.symbol, candle.interval), [])
        if series and series[-1].open_time == candle.open_time:
            series[-1] = candle
        elif not series or series[-1].open_time < candle.open_time:
            series.append(candle)
        else:
            for i in range(len(series) - 1, -1, -1):
                if series[i].open_time == candle.open_time:
                    series[i] = candle
                    break
                if series[i].open_time < candle.open_time:
                    series.insert(i + 1, candle)
                    break
            else:
                series.insert(0, candle)
        overflow = len(series) - MAX_CANDLES
        if overflow > 0:
            del series[:overflow]

    def _upsert_open_candle(self, candle: Candle) -> None:
        """Keep at most one forming bar at the tail; get_klines ignores it."""
        series = self._klines.setdefault((candle.symbol, candle.interval), [])
        if series and not series[-1].is_closed and series[-1].open_time == candle.open_time:
            series[-1] = candle
            return
        if series and series[-1].open_time == candle.open_time:
            series[-1] = candle
            return
        if not series or series[-1].open_time < candle.open_time:
            series.append(candle)
            overflow = len(series) - MAX_CANDLES
            if overflow > 0:
                del series[:overflow]


provider = MarketProvider()
