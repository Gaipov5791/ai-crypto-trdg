"""OWNER: Market agent. Implement GET /market/klines and GET /market/ticker."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query

from app.config import settings
from app.market.provider import provider
from app.schemas import Candle, Ticker

router = APIRouter(prefix="/market", tags=["market"])

_start_task: asyncio.Task[None] | None = None


async def ensure_started() -> None:
    """Lazy-start the market provider once (main.py lifespan is frozen)."""
    global _start_task
    if _start_task is None:
        _start_task = asyncio.create_task(provider.start())
    await _start_task


def _require_symbol(symbol: str) -> str:
    normalized = symbol.upper()
    if normalized not in settings.symbols:
        raise HTTPException(status_code=400, detail=f"symbol not allowed: {symbol}")
    return normalized


@router.get("/ticker")
async def ticker(symbol: str = Query(..., examples=["BTCUSDT"])) -> Ticker:
    normalized = _require_symbol(symbol)
    await ensure_started()
    try:
        return provider.get_ticker(normalized)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="ticker unavailable") from exc


@router.get("/klines")
async def klines(
    symbol: str = Query(..., examples=["BTCUSDT"]),
    interval: str = Query("1m"),
    limit: int = Query(500, ge=1, le=1000),
) -> list[Candle]:
    normalized = _require_symbol(symbol)
    await ensure_started()
    return provider.get_klines(normalized, interval, limit)
