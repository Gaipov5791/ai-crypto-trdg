"""Market provider: Binance REST/WS mapping and in-memory cache."""

from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.main import app
from app.market.mapping import candle_from_rest_kline, candle_from_ws_kline
from app.market.provider import provider
from app.routers import market as market_router
from app.schemas import Candle, Ticker

client = TestClient(app)

# Binance REST kline array (see GET /api/v3/klines docs).
SAMPLE_REST_KLINE = [
    1_499_040_000_000,
    "0.01634790",
    "0.80000000",
    "0.01575800",
    "0.01577100",
    "148976.11427815",
    1_499_644_799_999,
    "2434.19055334",
    308,
    "1756.87402397",
    "28.46694368",
    "0",
]


def _closed_candle(
    symbol: str = "BTCUSDT",
    interval: str = "1m",
    open_time: int = 1_700_000_000_000,
    close: float = 42000.5,
) -> Candle:
    return Candle(
        symbol=symbol,
        interval=interval,
        open_time=open_time,
        open=41900.0,
        high=42100.0,
        low=41850.25,
        close=close,
        volume=12.5,
        is_closed=True,
    )


def setup_function() -> None:
    provider.reset_for_tests()
    market_router._start_task = None


def teardown_function() -> None:
    provider.reset_for_tests()
    market_router._start_task = None


def test_rest_kline_array_maps_to_candle() -> None:
    candle = candle_from_rest_kline(
        SAMPLE_REST_KLINE,
        "BTCUSDT",
        "1m",
        is_closed=True,
    )
    assert candle.symbol == "BTCUSDT"
    assert candle.interval == "1m"
    assert candle.open_time == 1_499_040_000_000
    assert candle.open == 0.01634790
    assert candle.high == 0.80000000
    assert candle.low == 0.01575800
    assert candle.close == 0.01577100
    assert candle.volume == 148976.11427815
    assert candle.is_closed is True


def test_ws_kline_maps_to_candle() -> None:
    k = {
        "t": 1_700_000_060_000,
        "T": 1_700_000_119_999,
        "s": "ETHUSDT",
        "i": "1m",
        "o": "3500.1",
        "c": "3502.4",
        "h": "3505.0",
        "l": "3499.0",
        "v": "10.25",
        "x": True,
    }
    candle = candle_from_ws_kline("ETHUSDT", k)
    assert candle.symbol == "ETHUSDT"
    assert candle.open_time == 1_700_000_060_000
    assert candle.close == 3502.4
    assert candle.is_closed is True


def test_get_klines_returns_closed_candles_from_cache() -> None:
    closed = _closed_candle(close=42110.0)
    forming = Candle(
        symbol="BTCUSDT",
        interval="1m",
        open_time=closed.open_time + 60_000,
        open=42110.0,
        high=42120.0,
        low=42100.0,
        close=42115.0,
        volume=1.0,
        is_closed=False,
    )
    provider.inject_klines("BTCUSDT", "1m", [closed, forming])

    result = provider.get_klines("BTCUSDT", "1m", limit=500)

    assert len(result) == 1
    got = result[0]
    assert got.is_closed is True
    assert got.symbol == "BTCUSDT"
    assert got.interval == "1m"
    assert got.open_time == closed.open_time
    assert got.open == closed.open
    assert got.high == closed.high
    assert got.low == closed.low
    assert got.close == 42110.0
    assert got.volume == closed.volume


def test_get_klines_respects_limit_newest_last() -> None:
    candles = [
        _closed_candle(open_time=1_700_000_000_000 + i * 60_000, close=float(i))
        for i in range(5)
    ]
    provider.inject_klines("BTCUSDT", "1m", candles)
    result = provider.get_klines("btcusdt", "1m", limit=2)
    assert [c.close for c in result] == [3.0, 4.0]
    assert result[-1].open_time > result[0].open_time


def test_closed_ws_kline_appends_cache() -> None:
    existing = _closed_candle(open_time=1_700_000_000_000)
    provider.inject_klines("BTCUSDT", "1m", [existing])
    provider.handle_stream_message(
        {
            "stream": "btcusdt@kline_1m",
            "data": {
                "e": "kline",
                "E": 1_700_000_120_500,
                "s": "BTCUSDT",
                "k": {
                    "t": 1_700_000_060_000,
                    "T": 1_700_000_119_999,
                    "s": "BTCUSDT",
                    "i": "1m",
                    "o": "42110.0",
                    "c": "42150.5",
                    "h": "42160.0",
                    "l": "42100.0",
                    "v": "3.2",
                    "x": True,
                },
            },
        }
    )
    result = provider.get_klines("BTCUSDT", "1m")
    assert len(result) == 2
    assert result[-1].close == 42150.5
    assert result[-1].is_closed is True
    assert provider.get_ticker("BTCUSDT").price == 42150.5


def test_mini_ticker_updates_last_price() -> None:
    provider.handle_stream_message(
        {
            "stream": "ethusdt@miniTicker",
            "data": {
                "e": "24hrMiniTicker",
                "E": 1_700_000_000_111,
                "s": "ETHUSDT",
                "c": "3510.25",
                "o": "3400.0",
                "h": "3600.0",
                "l": "3300.0",
                "v": "100",
                "q": "350000",
            },
        }
    )
    ticker = provider.get_ticker("ETHUSDT")
    assert ticker.symbol == "ETHUSDT"
    assert ticker.price == 3510.25
    assert ticker.ts == 1_700_000_000_111


def test_ticker_rejects_unknown_symbol() -> None:
    res = client.get("/market/ticker", params={"symbol": "DOGEUSDT"})
    assert res.status_code == 400


def test_klines_rejects_unknown_symbol() -> None:
    res = client.get(
        "/market/klines",
        params={"symbol": "DOGEUSDT", "interval": "1m", "limit": 10},
    )
    assert res.status_code == 400


def test_klines_endpoint_returns_injected_cache(monkeypatch) -> None:
    candle = _closed_candle()
    provider.inject_klines("BTCUSDT", "1m", [candle])
    monkeypatch.setattr(provider, "start", AsyncMock(return_value=None))

    res = client.get(
        "/market/klines",
        params={"symbol": "BTCUSDT", "interval": "1m", "limit": 10},
    )

    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert body[0]["symbol"] == "BTCUSDT"
    assert body[0]["interval"] == "1m"
    assert body[0]["open_time"] == candle.open_time
    assert body[0]["open"] == candle.open
    assert body[0]["high"] == candle.high
    assert body[0]["low"] == candle.low
    assert body[0]["close"] == candle.close
    assert body[0]["volume"] == candle.volume
    assert body[0]["is_closed"] is True


def test_ticker_endpoint_returns_injected_ticker(monkeypatch) -> None:
    provider.inject_ticker(Ticker(symbol="SOLUSDT", price=148.25, ts=1_700_000_000_000))
    monkeypatch.setattr(provider, "start", AsyncMock(return_value=None))

    res = client.get("/market/ticker", params={"symbol": "SOLUSDT"})

    assert res.status_code == 200
    body = res.json()
    assert body["symbol"] == "SOLUSDT"
    assert body["price"] == 148.25
    assert body["ts"] == 1_700_000_000_000
