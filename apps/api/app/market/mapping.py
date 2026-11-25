"""Map Binance public REST/WS payloads onto frozen Candle / Ticker schemas."""

from __future__ import annotations

import time

from app.schemas import Candle, Ticker


def candle_from_rest_kline(
    row: list,
    symbol: str,
    interval: str,
    *,
    now_ms: int | None = None,
    is_closed: bool | None = None,
) -> Candle:
    """Convert a Binance REST kline array into a Candle.

    REST row indexes: open_time, open, high, low, close, volume, close_time, ...
    Historical bars are closed; the current interval bar is still forming when
    close_time is in the future.
    """
    close_time = int(row[6])
    if is_closed is None:
        if now_ms is None:
            now_ms = int(time.time() * 1000)
        is_closed = close_time <= now_ms
    return Candle(
        symbol=symbol,
        interval=interval,
        open_time=int(row[0]),
        open=float(row[1]),
        high=float(row[2]),
        low=float(row[3]),
        close=float(row[4]),
        volume=float(row[5]),
        is_closed=bool(is_closed),
    )


def candle_from_ws_kline(symbol: str, k: dict) -> Candle:
    """Convert a Binance WS ``k`` payload into a Candle."""
    return Candle(
        symbol=symbol,
        interval=str(k["i"]),
        open_time=int(k["t"]),
        open=float(k["o"]),
        high=float(k["h"]),
        low=float(k["l"]),
        close=float(k["c"]),
        volume=float(k["v"]),
        is_closed=bool(k["x"]),
    )


def ticker_from_mini(data: dict) -> Ticker:
    return Ticker(
        symbol=str(data["s"]),
        price=float(data["c"]),
        ts=int(data["E"]),
    )


def ticker_from_price(symbol: str, price: float, ts: int) -> Ticker:
    return Ticker(symbol=symbol, price=float(price), ts=int(ts))
