"""OWNER: Signal agent.

Rule-based LONG signals on 5m closed candles.
Indicators: RSI, MACD, EMA, Bollinger. Pattern: bullish engulfing.
Emit Signal only if confidence > 75. Reason is a template string, not LLM.

Confidence (0-100), weights sum to 100:
  bullish engulfing          40  (required — without it max is 60)
  RSI(14)                    30  <=30 → 30; <=40 → 24; <=50 → 12; else 0
  MACD(12,26,9)              15  macd>signal → 15; hist rising → 10; else 0
  close > EMA(20)             8
  close < Bollinger middle    7  (discounted / lower-half zone)

Typical fire: engulfing + RSI oversold + below BB mid = 40+30+7 = 77 > 75.

SL: min(engulfing two-bar low, BB lower) if that is < entry; else pattern low.
    Must be strictly below entry or the signal is skipped.
TP: entry + 1.5 * (entry - SL)  so reward:risk == 1.5.

size_pct: recommended quote notional as a fraction of equity, from
    RiskManager.size_quote(1.0, entry, sl) which is
    max_risk * entry / (entry - sl)  i.e. 1.5% of equity at risk to SL.
    Paper should call size_quote(equity, entry, sl) for the USDT size.
"""

from __future__ import annotations

import uuid
from collections import deque

from app.config import settings
from app.risk.manager import RiskManager, get_risk_manager
from app.schemas import Candle, Side, Signal, SignalStatus
from app.signals.indicators import (
    compute_indicators,
    is_bullish_engulfing,
)

MIN_HISTORY = 60
MAX_STORED = 200
CONFIDENCE_THRESHOLD = 75.0
MIN_REWARD_RISK = 1.5

# Component weights (must sum to 100)
W_ENGULFING = 40.0
W_RSI = 30.0
W_MACD = 15.0
W_EMA = 8.0
W_BB = 7.0


def _combine(candle: Candle, history: list[Candle]) -> list[Candle]:
    if history and history[-1].open_time == candle.open_time:
        return list(history)
    return [*history, candle]


def _rsi_points(rsi: float) -> float:
    if rsi <= 30:
        return W_RSI
    if rsi <= 40:
        return 24.0
    if rsi <= 50:
        return 12.0
    return 0.0


def _macd_points(macd: float, signal: float, hist: float, prev_hist: float | None) -> float:
    if macd > signal:
        return W_MACD
    if prev_hist is not None and hist > prev_hist:
        return 10.0
    return 0.0


def score_confidence(
    *,
    engulfing: bool,
    rsi: float,
    macd: float,
    macd_signal: float,
    macd_hist: float,
    prev_macd_hist: float | None,
    close: float,
    ema20: float,
    bb_mid: float,
) -> float:
    """Weighted 0-100 score. See module docstring for the formula."""
    total = 0.0
    if engulfing:
        total += W_ENGULFING
    total += _rsi_points(rsi)
    total += _macd_points(macd, macd_signal, macd_hist, prev_macd_hist)
    if close > ema20:
        total += W_EMA
    if close < bb_mid:
        total += W_BB
    return max(0.0, min(100.0, total))


def _reason_parts(
    *,
    engulfing: bool,
    rsi: float,
    macd: float,
    macd_signal: float,
    macd_hist: float,
    prev_macd_hist: float | None,
    close: float,
    ema20: float,
    bb_mid: float,
) -> list[str]:
    parts: list[str] = []
    if engulfing:
        parts.append("Bullish engulfing")
    if rsi <= 30:
        parts.append("RSI oversold")
    elif rsi <= 40:
        parts.append("RSI recovering")
    if macd > macd_signal:
        parts.append("MACD bullish")
    elif prev_macd_hist is not None and macd_hist > prev_macd_hist:
        parts.append("MACD histogram rising")
    if close > ema20:
        parts.append("Price above EMA(20)")
    if close < bb_mid:
        parts.append("Below BB midline")
    return parts


class SignalEngine:
    def __init__(self, risk: RiskManager | None = None) -> None:
        self._risk = risk if risk is not None else get_risk_manager()
        self._signals: deque[Signal] = deque(maxlen=MAX_STORED)
        self._last_key: tuple[str, int] | None = None

    def on_candle_close(self, candle: Candle, history: list[Candle]) -> Signal | None:
        if not candle.is_closed:
            return None
        if candle.interval != settings.signal_timeframe:
            return None

        candles = _combine(candle, history)
        if len(candles) < MIN_HISTORY:
            return None
        if len(candles) < 2:
            return None

        key = (candle.symbol, candle.open_time)
        if key == self._last_key:
            return None

        prev, curr = candles[-2], candles[-1]
        engulfing = is_bullish_engulfing(prev, curr)
        if not engulfing:
            return None

        closes = [c.close for c in candles]
        snap = compute_indicators(closes)
        if snap is None:
            return None

        confidence = score_confidence(
            engulfing=True,
            rsi=snap.rsi,
            macd=snap.macd,
            macd_signal=snap.macd_signal,
            macd_hist=snap.macd_hist,
            prev_macd_hist=snap.prev_macd_hist,
            close=curr.close,
            ema20=snap.ema20,
            bb_mid=snap.bb_mid,
        )
        if confidence <= CONFIDENCE_THRESHOLD:
            return None

        entry = curr.close
        pattern_low = min(prev.low, curr.low)
        stop_loss = pattern_low
        if snap.bb_lower < entry:
            stop_loss = min(stop_loss, snap.bb_lower)
        if stop_loss >= entry:
            return None

        risk_dist = entry - stop_loss
        take_profit = entry + MIN_REWARD_RISK * risk_dist

        # size_pct = quote notional / equity at 1.5% risk-to-SL (see module docstring).
        size_pct = self._risk.size_quote(1.0, entry, stop_loss)

        parts = _reason_parts(
            engulfing=True,
            rsi=snap.rsi,
            macd=snap.macd,
            macd_signal=snap.macd_signal,
            macd_hist=snap.macd_hist,
            prev_macd_hist=snap.prev_macd_hist,
            close=curr.close,
            ema20=snap.ema20,
            bb_mid=snap.bb_mid,
        )
        reason = " + ".join(parts) if parts else "Bullish engulfing"

        signal = Signal(
            id=str(uuid.uuid4()),
            symbol=curr.symbol,
            side=Side.LONG,
            entry=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
            confidence=confidence,
            size_pct=size_pct,
            reason=reason,
            status=SignalStatus.NEW,
            ts=curr.open_time,
        )
        self._signals.append(signal)
        self._last_key = key
        return signal

    def list_signals(self, limit: int = 50) -> list[Signal]:
        newest_first = list(reversed(self._signals))
        if limit < 1:
            return []
        return newest_first[:limit]


_ENGINE: SignalEngine | None = None


def get_signal_engine() -> SignalEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = SignalEngine()
    return _ENGINE


def reset_signal_engine() -> SignalEngine:
    global _ENGINE
    _ENGINE = SignalEngine()
    return _ENGINE
