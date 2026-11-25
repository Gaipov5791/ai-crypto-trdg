"""OWNER: PM. Live fan-out of ticker, kline, signal, account, position."""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.market.provider import provider
from app.paper.engine import get_engine
from app.risk.manager import get_risk_manager
from app.schemas import PositionStatus, WsEventType
from app.signals.engine import get_signal_engine
from app.ws_hub import hub

router = APIRouter(tags=["stream"])


def account_payload() -> dict:
    snap = get_engine().snapshot()
    return snap.model_copy(
        update={"kill_switch_until": get_risk_manager().kill_switch_until}
    ).model_dump()


async def send_snapshot(websocket: WebSocket) -> None:
    await websocket.send_json(
        {"type": WsEventType.HELLO.value, "payload": {"mode": "paper"}}
    )
    for symbol in provider.symbols:
        try:
            ticker = provider.get_ticker(symbol)
        except KeyError:
            continue
        await websocket.send_json(
            {"type": WsEventType.TICKER.value, "payload": ticker.model_dump()}
        )
    await websocket.send_json(
        {"type": WsEventType.ACCOUNT.value, "payload": account_payload()}
    )
    for pos in get_engine().positions(status=PositionStatus.OPEN.value):
        await websocket.send_json(
            {"type": WsEventType.POSITION.value, "payload": pos.model_dump()}
        )
    for signal in get_signal_engine().list_signals(limit=20):
        await websocket.send_json(
            {"type": WsEventType.SIGNAL.value, "payload": signal.model_dump()}
        )


@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    hub.attach(websocket)
    try:
        await send_snapshot(websocket)
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        hub.detach(websocket)
