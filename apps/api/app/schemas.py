"""Frozen API contract. Owned by PM. Other agents import, do not edit."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Side(str, Enum):
    LONG = "LONG"


class OrderType(str, Enum):
    MARKET = "MARKET"


class PositionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class SignalStatus(str, Enum):
    NEW = "NEW"
    TAKEN = "TAKEN"
    SKIPPED = "SKIPPED"


class Candle(BaseModel):
    symbol: str
    interval: str
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_closed: bool


class Ticker(BaseModel):
    symbol: str
    price: float
    ts: int


class AccountSnapshot(BaseModel):
    cash: float
    equity: float
    starting_balance: float = 10_000.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    win_rate: float = 0.0
    avg_profit: float = 0.0
    kill_switch_until: Optional[int] = None


class Position(BaseModel):
    id: str
    symbol: str
    side: Side = Side.LONG
    qty: float
    entry: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    status: PositionStatus = PositionStatus.OPEN
    opened_at: int
    closed_at: Optional[int] = None
    realized_pnl: Optional[float] = None


class OrderRequest(BaseModel):
    symbol: str
    quote_amount: Optional[float] = None
    qty: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


class Fill(BaseModel):
    id: str
    symbol: str
    side: Side
    qty: float
    price: float
    fee: float
    ts: int


class Signal(BaseModel):
    id: str
    symbol: str
    side: Side = Side.LONG
    entry: float
    stop_loss: float
    take_profit: float
    confidence: float = Field(ge=0, le=100)
    size_pct: float
    reason: str
    status: SignalStatus = SignalStatus.NEW
    ts: int


class WsEventType(str, Enum):
    HELLO = "hello"
    TICKER = "ticker"
    KLINE = "kline"
    SIGNAL = "signal"
    ACCOUNT = "account"
    POSITION = "position"


class WsEvent(BaseModel):
    """Fan-out frame on GET/WS /ws. payload is the matching schema dump."""

    type: str
    payload: dict
