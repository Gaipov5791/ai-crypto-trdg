"""PM pipeline: ticker → SL/TP, closed 5m → signal → sized LONG."""

from app.pipeline import MIN_QUOTE, CASH_CAP, on_closed_kline, on_ticker
from app.paper.engine import PaperEngine, reset_engine
from app.risk.manager import RiskManager, reset_risk_manager
from app.schemas import OrderRequest, PositionStatus, SignalStatus, Ticker
from app.signals.engine import SignalEngine, reset_signal_engine
from tests.test_signals import declining_then_engulfing


def setup_function():
    reset_risk_manager()
    reset_signal_engine()


def teardown_function():
    from app.market.provider import provider

    provider.reset_for_tests()
    reset_engine(None)
    reset_risk_manager()
    reset_signal_engine()


def test_ticker_triggers_stop_loss(tmp_path):
    paper = PaperEngine(db_path=str(tmp_path / "p.db"))
    reset_engine(paper)
    paper.market_buy(
        OrderRequest(symbol="BTCUSDT", quote_amount=1000, stop_loss=49_000.0),
        50_000.0,
    )
    on_ticker(Ticker(symbol="BTCUSDT", price=49_000.0, ts=2))
    assert paper.positions(status=PositionStatus.OPEN.value) == []


def test_closed_5m_can_take_signal(tmp_path, monkeypatch):
    from app.market.provider import provider

    paper = PaperEngine(db_path=str(tmp_path / "p.db"))
    reset_engine(paper)
    engine = SignalEngine(risk=RiskManager())
    monkeypatch.setattr("app.pipeline.get_signal_engine", lambda: engine)

    history, last = declining_then_engulfing()
    series = [*history, last]
    provider.inject_klines("BTCUSDT", "5m", series)
    provider.inject_ticker(Ticker(symbol="BTCUSDT", price=last.close, ts=last.open_time))

    on_closed_kline(last)
    signals = engine.list_signals()
    assert signals
    sig = signals[0]
    assert sig.status == SignalStatus.TAKEN
    open_pos = paper.positions(status=PositionStatus.OPEN.value)
    assert len(open_pos) == 1
    assert open_pos[0].symbol == "BTCUSDT"
    assert open_pos[0].stop_loss == sig.stop_loss
    cash_used = 10_000.0 - paper.snapshot().cash
    assert cash_used >= MIN_QUOTE
    assert cash_used <= 10_000.0 * CASH_CAP + 1.0
