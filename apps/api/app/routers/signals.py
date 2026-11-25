"""OWNER: Signal agent. AI feed + latest signal."""

from fastapi import APIRouter, Query

from app.schemas import Signal
from app.signals.engine import get_signal_engine

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("")
def list_signals(limit: int = Query(50, ge=1, le=200)) -> list[Signal]:
    return get_signal_engine().list_signals(limit)
