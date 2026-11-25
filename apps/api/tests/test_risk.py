"""RiskManager: 1.5% sizing and daily-DD kill switch. No network."""

from datetime import datetime, timedelta, timezone

from app.config import settings
from app.risk.manager import RiskManager


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def test_size_quote_exact_1pct_stop():
    rm = RiskManager()
    # stop_frac = (100-99)/100 = 0.01 → notional = 0.015 * 10000 / 0.01 = 15000
    assert rm.size_quote(10_000.0, 100.0, 99.0) == 15_000.0


def test_size_quote_exact_3pct_stop():
    rm = RiskManager()
    equity, entry, sl = 10_000.0, 50_000.0, 49_000.0
    stop_frac = (entry - sl) / entry  # 0.02
    expected = settings.max_risk_per_trade * equity / stop_frac  # 7500
    assert rm.size_quote(equity, entry, sl) == expected
    assert expected == 7_500.0


def test_size_quote_invalid_sl_returns_zero():
    rm = RiskManager()
    assert rm.size_quote(10_000.0, 100.0, 100.0) == 0.0
    assert rm.size_quote(10_000.0, 100.0, 101.0) == 0.0


def test_size_quote_matches_risk_identity():
    rm = RiskManager()
    equity, entry, sl = 10_000.0, 250.0, 245.0
    notional = rm.size_quote(equity, entry, sl)
    loss_if_sl = ((entry - sl) / entry) * notional
    assert abs(loss_if_sl - settings.max_risk_per_trade * equity) < 1e-9


def test_allow_trade_under_daily_dd():
    rm = RiskManager()
    t0 = datetime(2024, 6, 15, 12, 0, tzinfo=timezone.utc)
    rm.on_equity(10_000.0, _ms(t0))
    # 1% down — below 3%
    assert rm.allow_new_trade(9_900.0, _ms(t0 + timedelta(minutes=5))) is True


def test_kill_switch_at_exactly_3pct_for_24h():
    rm = RiskManager()
    t0 = datetime(2024, 6, 15, 12, 0, tzinfo=timezone.utc)
    rm.on_equity(10_000.0, _ms(t0))
    t_hit = t0 + timedelta(hours=1)
    assert rm.allow_new_trade(9_700.0, _ms(t_hit)) is False
    assert rm.kill_switch_until == _ms(t_hit) + 24 * 60 * 60 * 1000

    # Recovered equity, still inside 24h (next UTC day) — still frozen
    t_23h = t_hit + timedelta(hours=23)
    assert rm.allow_new_trade(10_000.0, _ms(t_23h)) is False

    # After 24h the freeze lifts
    t_after = t_hit + timedelta(hours=24, milliseconds=1)
    assert rm.allow_new_trade(10_000.0, _ms(t_after)) is True


def test_drawdown_just_under_3pct_still_allows():
    rm = RiskManager()
    t0 = datetime(2024, 6, 15, 12, 0, tzinfo=timezone.utc)
    rm.on_equity(10_000.0, _ms(t0))
    # 2.99%
    assert rm.allow_new_trade(9_701.0, _ms(t0 + timedelta(minutes=1))) is True


def test_new_utc_day_resets_day_start_equity():
    rm = RiskManager()
    day1 = datetime(2024, 6, 15, 22, 0, tzinfo=timezone.utc)
    rm.on_equity(10_000.0, _ms(day1))
    assert rm.allow_new_trade(9_800.0, _ms(day1 + timedelta(hours=1))) is True  # 2% DD

    # New UTC day: 9_800 becomes the day-start; another 2% is not a 3% day
    day2 = datetime(2024, 6, 16, 0, 5, tzinfo=timezone.utc)
    assert rm.allow_new_trade(9_800.0, _ms(day2)) is True
    assert rm.day_start_equity == 9_800.0
    assert rm.allow_new_trade(9_604.0, _ms(day2 + timedelta(minutes=10))) is True
