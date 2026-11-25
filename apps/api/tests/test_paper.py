import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.paper.engine import PaperEngine, reset_engine
from app.schemas import OrderRequest, PositionStatus

client = TestClient(app)

EPS = 1e-6
LAST_PRICE = 50_000.0
NOTIONAL = 1_000.0


@pytest.fixture
def engine(tmp_path):
    eng = PaperEngine(db_path=str(tmp_path / "paper.db"))
    reset_engine(eng)
    yield eng
    reset_engine(None)


def _buy_cost(last_price: float, quote: float) -> tuple[float, float, float]:
    fill_price = last_price * (1.0 + settings.slippage)
    qty = quote / fill_price
    fee = fill_price * qty * settings.taker_fee
    return fill_price, qty, fee


def test_starting_balance_10k(engine: PaperEngine):
    snap = engine.snapshot()
    assert snap.cash == pytest.approx(10_000.0, abs=EPS)
    assert snap.equity == pytest.approx(10_000.0, abs=EPS)
    assert snap.starting_balance == pytest.approx(settings.starting_balance, abs=EPS)
    assert snap.realized_pnl == pytest.approx(0.0, abs=EPS)
    assert snap.unrealized_pnl == pytest.approx(0.0, abs=EPS)
    assert snap.win_rate == pytest.approx(0.0, abs=EPS)
    assert snap.avg_profit == pytest.approx(0.0, abs=EPS)
    assert snap.kill_switch_until is None


def test_market_buy_notional_fee_slippage(engine: PaperEngine):
    fill_price, qty, fee = _buy_cost(LAST_PRICE, NOTIONAL)
    fill = engine.market_buy(
        OrderRequest(symbol="BTCUSDT", quote_amount=NOTIONAL),
        LAST_PRICE,
    )
    assert fill.symbol == "BTCUSDT"
    assert fill.price == pytest.approx(fill_price, abs=EPS)
    assert fill.qty == pytest.approx(qty, abs=EPS)
    assert fill.fee == pytest.approx(fee, abs=EPS)

    snap = engine.snapshot()
    assert snap.cash == pytest.approx(10_000.0 - NOTIONAL - fee, abs=EPS)

    positions = engine.positions(status=PositionStatus.OPEN.value)
    assert len(positions) == 1
    pos = positions[0]
    assert pos.qty == pytest.approx(qty, abs=EPS)
    assert pos.entry == pytest.approx(fill_price, abs=EPS)
    assert pos.status == PositionStatus.OPEN


def test_close_restores_cash_with_realized_pnl(engine: PaperEngine):
    engine.market_buy(OrderRequest(symbol="BTCUSDT", quote_amount=NOTIONAL), LAST_PRICE)
    pos = engine.positions(status=PositionStatus.OPEN.value)[0]
    exit_last = 51_000.0
    fill = engine.close_position(pos.id, exit_last)

    exit_price = exit_last * (1.0 - settings.slippage)
    assert fill.price == pytest.approx(exit_price, abs=EPS)
    assert fill.qty == pytest.approx(pos.qty, abs=EPS)
    assert fill.fee == pytest.approx(exit_price * pos.qty * settings.taker_fee, abs=EPS)

    snap = engine.snapshot()
    assert engine.positions(status=PositionStatus.OPEN.value) == []
    assert snap.cash == pytest.approx(snap.starting_balance + snap.realized_pnl, abs=EPS)
    assert snap.equity == pytest.approx(snap.cash, abs=EPS)
    assert snap.unrealized_pnl == pytest.approx(0.0, abs=EPS)
    assert snap.realized_pnl != pytest.approx(0.0, abs=EPS)


def test_sl_triggers_via_on_price(engine: PaperEngine):
    sl = 49_000.0
    engine.market_buy(
        OrderRequest(symbol="BTCUSDT", quote_amount=NOTIONAL, stop_loss=sl),
        LAST_PRICE,
    )
    no_hit = engine.on_price("BTCUSDT", sl + 1.0, ts=1)
    assert no_hit == []
    assert len(engine.positions(status=PositionStatus.OPEN.value)) == 1

    fills = engine.on_price("BTCUSDT", sl, ts=2)
    assert len(fills) == 1
    assert fills[0].price == pytest.approx(sl * (1.0 - settings.slippage), abs=EPS)
    assert engine.positions(status=PositionStatus.OPEN.value) == []
    closed = engine.positions(status=PositionStatus.CLOSED.value)
    assert len(closed) == 1
    assert closed[0].realized_pnl is not None
    assert closed[0].realized_pnl < 0


def test_tp_triggers_via_on_price(engine: PaperEngine):
    tp = 52_000.0
    engine.market_buy(
        OrderRequest(symbol="BTCUSDT", quote_amount=NOTIONAL, take_profit=tp),
        LAST_PRICE,
    )
    fills = engine.on_price("BTCUSDT", tp, ts=3)
    assert len(fills) == 1
    assert engine.positions(status=PositionStatus.OPEN.value) == []
    snap = engine.snapshot()
    assert snap.realized_pnl > 0
    assert snap.win_rate == pytest.approx(1.0, abs=EPS)


def test_survives_process_restart(tmp_path):
    db = str(tmp_path / "restart.db")
    first = PaperEngine(db_path=db)
    first.market_buy(OrderRequest(symbol="ETHUSDT", quote_amount=NOTIONAL), 3_000.0)
    cash = first.snapshot().cash
    pos_id = first.positions(status=PositionStatus.OPEN.value)[0].id

    second = PaperEngine(db_path=db)
    snap = second.snapshot()
    assert snap.cash == pytest.approx(cash, abs=EPS)
    open_pos = second.positions(status=PositionStatus.OPEN.value)
    assert len(open_pos) == 1
    assert open_pos[0].id == pos_id
    assert open_pos[0].symbol == "ETHUSDT"


def test_account_endpoint_not_501(engine: PaperEngine):
    res = client.get("/paper/account")
    assert res.status_code == 200
    body = res.json()
    assert body["cash"] == pytest.approx(10_000.0, abs=EPS)
    assert body["kill_switch_until"] is None


def test_positions_endpoint_open_and_all(engine: PaperEngine):
    engine.market_buy(OrderRequest(symbol="BTCUSDT", quote_amount=NOTIONAL), LAST_PRICE)
    res = client.get("/paper/positions")
    assert res.status_code == 200
    assert len(res.json()) == 1
    pos_id = res.json()[0]["id"]
    engine.close_position(pos_id, LAST_PRICE)
    assert client.get("/paper/positions").json() == []
    history = client.get("/paper/positions", params={"all": "true"})
    assert history.status_code == 200
    assert len(history.json()) == 1
    assert history.json()[0]["status"] == "CLOSED"


def test_market_order_503_without_ticker(engine: PaperEngine):
    res = client.post(
        "/paper/orders/market",
        json={"symbol": "BTCUSDT", "quote_amount": 1000},
    )
    assert res.status_code == 503
    assert "Last price unavailable" in res.json()["detail"]
