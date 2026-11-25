"""OWNER: Signal agent.

Position sizing: risk 1.5% of equity to the SL distance.
Kill switch: freeze auto-trading 24h if daily drawdown >= 3%.
Do not place orders — return size / allow / deny for Paper to consume.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.config import settings

_MS_PER_DAY = 24 * 60 * 60 * 1000


def _utc_date(ts_ms: int):
    return datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).date()


class RiskManager:
    def __init__(self) -> None:
        self._day_start_equity: float | None = None
        self._day_utc = None
        self._kill_until: int | None = None  # epoch ms, inclusive freeze until

    def size_quote(self, equity: float, entry: float, stop_loss: float) -> float:
        """USDT notional so that (entry-sl)/entry * notional ~= max_risk * equity.

        If stop_loss >= entry (invalid LONG SL), return 0.
        """
        if equity <= 0 or entry <= 0:
            return 0.0
        if stop_loss >= entry:
            return 0.0
        stop_frac = (entry - stop_loss) / entry
        if stop_frac <= 0:
            return 0.0
        return (self.max_risk * equity) / stop_frac

    def allow_new_trade(self, equity: float, ts: int) -> bool:
        """False while the 24h kill switch is active (daily DD >= 3%)."""
        self.on_equity(equity, ts)
        if self._kill_until is not None and ts < self._kill_until:
            return False
        return True

    def on_equity(self, equity: float, ts: int) -> None:
        """Snapshot UTC-day starting equity and arm kill switch on 3% DD."""
        day = _utc_date(ts)
        if self._day_utc != day:
            self._day_utc = day
            self._day_start_equity = equity

        start = self._day_start_equity
        if start is None or start <= 0:
            self._day_start_equity = equity
            return

        drawdown = (start - equity) / start
        if drawdown >= settings.max_daily_drawdown:
            if self._kill_until is None or ts >= self._kill_until:
                self._kill_until = ts + _MS_PER_DAY

    @property
    def kill_switch_until(self) -> int | None:
        return self._kill_until

    @property
    def day_start_equity(self) -> float | None:
        return self._day_start_equity

    @property
    def max_risk(self) -> float:
        return settings.max_risk_per_trade


_MANAGER: RiskManager | None = None


def get_risk_manager() -> RiskManager:
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = RiskManager()
    return _MANAGER


def reset_risk_manager() -> RiskManager:
    global _MANAGER
    _MANAGER = RiskManager()
    return _MANAGER
