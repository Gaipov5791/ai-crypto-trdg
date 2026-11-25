"""Pure-Python indicators for 5m close series. No numpy / no network."""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas import Candle

RSI_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
EMA_PERIOD = 20
BB_PERIOD = 20
BB_STD = 2.0


@dataclass(frozen=True)
class IndicatorSnapshot:
    rsi: float
    macd: float
    macd_signal: float
    macd_hist: float
    prev_macd_hist: float | None
    ema20: float
    bb_mid: float
    bb_upper: float
    bb_lower: float


def ema_series(values: list[float], period: int) -> list[float | None]:
    """EMA seeded with SMA of the first `period` values (TradingView-style)."""
    n = len(values)
    out: list[float | None] = [None] * n
    if n < period or period <= 0:
        return out
    k = 2.0 / (period + 1)
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for i in range(period, n):
        prev = values[i] * k + prev * (1.0 - k)
        out[i] = prev
    return out


def rsi_wilder(closes: list[float], period: int = RSI_PERIOD) -> float | None:
    """Wilder RSI of the last close. Needs period+1 closes."""
    if len(closes) < period + 1:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0.0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def bollinger(
    closes: list[float], period: int = BB_PERIOD, k: float = BB_STD
) -> tuple[float, float, float] | None:
    """SMA middle ± k * population std of the last `period` closes."""
    if len(closes) < period:
        return None
    window = closes[-period:]
    mid = sum(window) / period
    var = sum((x - mid) ** 2 for x in window) / period
    std = var**0.5
    return mid, mid + k * std, mid - k * std


def macd_last(
    closes: list[float],
    fast: int = MACD_FAST,
    slow: int = MACD_SLOW,
    signal_period: int = MACD_SIGNAL,
) -> tuple[float, float, float, float | None] | None:
    """Return (macd, signal, hist, prev_hist) for the last bar, or None."""
    ema_fast = ema_series(closes, fast)
    ema_slow = ema_series(closes, slow)
    macd_line: list[float] = []
    for a, b in zip(ema_fast, ema_slow):
        if a is None or b is None:
            continue
        macd_line.append(a - b)
    if len(macd_line) < signal_period:
        return None
    signal_series = ema_series(macd_line, signal_period)
    macd = macd_line[-1]
    signal = signal_series[-1]
    if signal is None:
        return None
    hist = macd - signal
    prev_hist: float | None = None
    if len(macd_line) >= 2 and signal_series[-2] is not None:
        prev_hist = macd_line[-2] - signal_series[-2]
    return macd, signal, hist, prev_hist


def compute_indicators(closes: list[float]) -> IndicatorSnapshot | None:
    rsi = rsi_wilder(closes)
    macd_pack = macd_last(closes)
    ema20_series = ema_series(closes, EMA_PERIOD)
    bb = bollinger(closes)
    ema20 = ema20_series[-1] if ema20_series else None
    if rsi is None or macd_pack is None or ema20 is None or bb is None:
        return None
    macd, signal, hist, prev_hist = macd_pack
    mid, upper, lower = bb
    return IndicatorSnapshot(
        rsi=rsi,
        macd=macd,
        macd_signal=signal,
        macd_hist=hist,
        prev_macd_hist=prev_hist,
        ema20=ema20,
        bb_mid=mid,
        bb_upper=upper,
        bb_lower=lower,
    )


def is_bullish_engulfing(prev: Candle, curr: Candle) -> bool:
    """Current bullish body fully covers previous bearish body."""
    if prev.close >= prev.open:
        return False
    if curr.close <= curr.open:
        return False
    return curr.open <= prev.close and curr.close >= prev.open
