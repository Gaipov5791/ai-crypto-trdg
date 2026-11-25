"""OWNER: Paper agent. Account, positions, market buy, close."""

from fastapi import APIRouter, HTTPException, Query

from app.market.provider import provider
from app.paper.engine import PaperError, get_engine
from app.risk.manager import get_risk_manager
from app.routers.stream import account_payload
from app.schemas import AccountSnapshot, Fill, OrderRequest, Position, PositionStatus, WsEventType
from app.ws_hub import hub

router = APIRouter(prefix="/paper", tags=["paper"])


def _last_price(symbol: str) -> float:
    try:
        ticker = provider.get_ticker(symbol)
        return float(ticker.price)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Last price unavailable for {symbol}: {exc}",
        ) from exc


@router.get("/account")
def account() -> AccountSnapshot:
    snap = get_engine().snapshot()
    return snap.model_copy(
        update={"kill_switch_until": get_risk_manager().kill_switch_until}
    )


@router.get("/positions")
def positions(
    all: bool = Query(False, description="Include closed positions when true"),
) -> list[Position]:
    status = None if all else PositionStatus.OPEN.value
    return get_engine().positions(status=status)


@router.post("/orders/market")
def market_order(body: OrderRequest) -> Fill:
    last_price = _last_price(body.symbol)
    try:
        fill = get_engine().market_buy(body, last_price)
    except PaperError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    opened = [
        p
        for p in get_engine().positions(status=PositionStatus.OPEN.value)
        if p.symbol == body.symbol.upper()
    ]
    if opened:
        hub.publish(WsEventType.POSITION.value, opened[-1].model_dump())
    hub.publish(WsEventType.ACCOUNT.value, account_payload())
    return fill


@router.post("/positions/{position_id}/close")
def close_position(position_id: str) -> Fill:
    engine = get_engine()
    match = next((p for p in engine.positions() if p.id == position_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail=f"Position {position_id} not found")
    last_price = _last_price(match.symbol)
    try:
        fill = engine.close_position(position_id, last_price)
    except PaperError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    closed = next(
        (p for p in engine.positions(status=PositionStatus.CLOSED.value) if p.id == position_id),
        match.model_copy(update={"status": PositionStatus.CLOSED}),
    )
    hub.publish(WsEventType.POSITION.value, closed.model_dump())
    hub.publish(WsEventType.ACCOUNT.value, account_payload())
    return fill
