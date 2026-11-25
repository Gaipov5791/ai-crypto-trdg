"""SignalEngine: synthetic 5m candles so RSI + bullish engulfing can fire."""

from fastapi.testclient import TestClient

from app.main import app
from app.risk.manager import RiskManager
from app.schemas import Candle, Side, SignalStatus
from app.signals.engine import (
    MIN_HISTORY,
    MIN_REWARD_RISK,
    SignalEngine,
    get_signal_engine,
    reset_signal_engine,
)
from app.signals.indicators import is_bullish_engulfing, rsi_wilder

FIVE_MIN_MS = 5 * 60 * 1000
BASE_TS = 1_700_000_000_000


def _candle(
    i: int,
    open_: float,
    close: float,
    *,
    high: float | None = None,
    low: float | None = None,
    symbol: str = "BTCUSDT",
    interval: str = "5m",
    is_closed: bool = True,
) -> Candle:
    top = max(open_, close)
    bot = min(open_, close)
    return Candle(
        symbol=symbol,
        interval=interval,
        open_time=BASE_TS + i * FIVE_MIN_MS,
        open=open_,
        high=high if high is not None else top * 1.0005,
        low=low if low is not None else bot * 0.9995,
        close=close,
        volume=10.0,
        is_closed=is_closed,
    )


def declining_then_engulfing(
    n: int = MIN_HISTORY,
    start: float = 100.0,
    drop: float = 0.004,
    symbol: str = "BTCUSDT",
) -> tuple[list[Candle], Candle]:
    """n-1 bearish bars, then a bullish engulfing close. RSI lands oversold."""
    history: list[Candle] = []
    price = start
    for i in range(n - 1):
        o = price
        c = price * (1.0 - drop)
        history.append(_candle(i, o, c, symbol=symbol))
        price = c

    prev = history[-1]
    eng_open = prev.close * 0.999
    eng_close = prev.open * 1.001
    eng_low = min(eng_open, prev.low) * 0.998
    eng_high = eng_close * 1.001
    last = _candle(
        n - 1,
        eng_open,
        eng_close,
        high=eng_high,
        low=eng_low,
        symbol=symbol,
    )
    assert is_bullish_engulfing(prev, last)
    return history, last


def test_not_enough_history_returns_none():
    engine = SignalEngine(risk=RiskManager())
    history, last = declining_then_engulfing(n=20)
    assert engine.on_candle_close(last, history) is None


def test_open_candle_returns_none():
    engine = SignalEngine(risk=RiskManager())
    history, last = declining_then_engulfing()
    last = last.model_copy(update={"is_closed": False})
    assert engine.on_candle_close(last, history) is None


def test_non_5m_interval_returns_none():
    engine = SignalEngine(risk=RiskManager())
    history, last = declining_then_engulfing()
    last = last.model_copy(update={"interval": "1m"})
    assert engine.on_candle_close(last, history) is None


def test_no_engulfing_returns_none():
    engine = SignalEngine(risk=RiskManager())
    history, last = declining_then_engulfing()
    prev = history[-1]
    last = _candle(MIN_HISTORY - 1, prev.close, prev.close * 0.996)
    assert is_bullish_engulfing(prev, last) is False
    assert engine.on_candle_close(last, history) is None


def test_rsi_oversold_engulfing_emits_long():
    engine = SignalEngine(risk=RiskManager())
    history, last = declining_then_engulfing()
    closes = [c.close for c in history] + [last.close]
    rsi = rsi_wilder(closes)
    assert rsi is not None and rsi <= 30

    sig = engine.on_candle_close(last, history)
    assert sig is not None
    assert sig.side == Side.LONG
    assert sig.status == SignalStatus.NEW
    assert sig.symbol == "BTCUSDT"
    assert sig.entry == last.close
    assert sig.stop_loss < sig.entry
    assert sig.confidence > 75
    assert sig.confidence <= 100
    risk = sig.entry - sig.stop_loss
    reward = sig.take_profit - sig.entry
    assert abs(reward / risk - MIN_REWARD_RISK) < 1e-9
    assert sig.ts == last.open_time
    assert "Bullish engulfing" in sig.reason
    assert "RSI oversold" in sig.reason
    assert sig.id

    rm = RiskManager()
    expected = rm.size_quote(1.0, sig.entry, sig.stop_loss)
    assert abs(sig.size_pct - expected) < 1e-12
    assert abs(sig.size_pct * 10_000 - rm.size_quote(10_000.0, sig.entry, sig.stop_loss)) < 1e-6


def test_list_signals_newest_first():
    engine = SignalEngine(risk=RiskManager())
    history, last = declining_then_engulfing(symbol="BTCUSDT")
    sig1 = engine.on_candle_close(last, history)
    assert sig1 is not None

    history2, last2 = declining_then_engulfing(symbol="ETHUSDT")
    last2 = last2.model_copy(update={"open_time": last.open_time + FIVE_MIN_MS})
    sig2 = engine.on_candle_close(last2, history2)
    assert sig2 is not None

    listed = engine.list_signals(limit=10)
    assert listed[0].id == sig2.id
    assert listed[1].id == sig1.id


def test_get_signals_not_501():
    reset_signal_engine()
    client = TestClient(app)
    res = client.get("/signals")
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body, list)
    assert body == []


def test_get_signals_returns_emitted_newest_first():
    engine = reset_signal_engine()
    history, last = declining_then_engulfing()
    sig = engine.on_candle_close(last, history)
    assert sig is not None

    client = TestClient(app)
    res = client.get("/signals", params={"limit": 10})
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert body[0]["id"] == sig.id
    assert body[0]["side"] == "LONG"
    assert body[0]["status"] == "NEW"
    assert get_signal_engine() is engine
