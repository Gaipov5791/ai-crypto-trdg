"""OWNER: PM. Wires Market ticks/closes into Paper SL/TP and Signal auto-entries."""

from __future__ import annotations

import logging
import time

from app.config import settings
from app.market.provider import provider
from app.paper.engine import PaperError, get_engine
from app.risk.manager import get_risk_manager
from app.routers.stream import account_payload
from app.schemas import Candle, OrderRequest, PositionStatus, SignalStatus, Ticker, WsEventType
from app.signals.engine import get_signal_engine
from app.ws_hub import hub

logger = logging.getLogger(__name__)

MIN_QUOTE = 10.0
CASH_CAP = 0.95
ACCOUNT_THROTTLE_S = 0.4

_last_account_pub = 0.0


def attach() -> None:
    provider.on_ticker = on_ticker
    provider.on_kline = on_kline
    provider.on_closed_kline = on_closed_kline


def detach() -> None:
    provider.on_ticker = None
    provider.on_kline = None
    provider.on_closed_kline = None


def _publish_account(force: bool = False) -> None:
    global _last_account_pub
    now = time.monotonic()
    if not force and now - _last_account_pub < ACCOUNT_THROTTLE_S:
        return
    _last_account_pub = now
    hub.publish(WsEventType.ACCOUNT.value, account_payload())


def on_kline(candle: Candle) -> None:
    hub.publish(WsEventType.KLINE.value, candle.model_dump())


def on_ticker(ticker: Ticker) -> None:
    paper = get_engine()
    open_ids = {
        p.id
        for p in paper.positions(status=PositionStatus.OPEN.value)
        if p.symbol == ticker.symbol
    }
    fills = paper.on_price(ticker.symbol, ticker.price, ticker.ts)
    snap = paper.snapshot()
    get_risk_manager().on_equity(snap.equity, ticker.ts)
    hub.publish(WsEventType.TICKER.value, ticker.model_dump())
    if fills:
        remaining = {p.id for p in paper.positions(status=PositionStatus.OPEN.value)}
        closed_ids = open_ids - remaining
        if closed_ids:
            for pos in paper.positions(status=PositionStatus.CLOSED.value):
                if pos.id in closed_ids:
                    hub.publish(WsEventType.POSITION.value, pos.model_dump())
        _publish_account(force=True)
    else:
        _publish_account()


def on_closed_kline(candle: Candle) -> None:
    if candle.interval != settings.signal_timeframe:
        return
    history = provider.get_klines(candle.symbol, candle.interval, 200)
    signal = get_signal_engine().on_candle_close(candle, history)
    if signal is None:
        return

    paper = get_engine()
    open_same = [
        p
        for p in paper.positions(status=PositionStatus.OPEN.value)
        if p.symbol == signal.symbol
    ]
    snap = paper.snapshot()
    risk = get_risk_manager()
    ts = ticker_ts(candle)

    if open_same or not risk.allow_new_trade(snap.equity, ts):
        signal.status = SignalStatus.SKIPPED
        hub.publish(WsEventType.SIGNAL.value, signal.model_dump())
        return

    quote = risk.size_quote(snap.equity, signal.entry, signal.stop_loss)
    quote = min(quote, snap.cash * CASH_CAP)
    if quote < MIN_QUOTE:
        signal.status = SignalStatus.SKIPPED
        hub.publish(WsEventType.SIGNAL.value, signal.model_dump())
        return

    try:
        last = provider.get_ticker(signal.symbol).price
        paper.market_buy(
            OrderRequest(
                symbol=signal.symbol,
                quote_amount=quote,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
            ),
            last,
        )
        signal.status = SignalStatus.TAKEN
        hub.publish(WsEventType.SIGNAL.value, signal.model_dump())
        opened = [
            p
            for p in paper.positions(status=PositionStatus.OPEN.value)
            if p.symbol == signal.symbol
        ]
        if opened:
            hub.publish(WsEventType.POSITION.value, opened[-1].model_dump())
        _publish_account(force=True)
    except (PaperError, KeyError) as exc:
        logger.info("auto-entry skipped: %s", exc)
        signal.status = SignalStatus.SKIPPED
        hub.publish(WsEventType.SIGNAL.value, signal.model_dump())


def ticker_ts(candle: Candle) -> int:
    try:
        return provider.get_ticker(candle.symbol).ts
    except KeyError:
        return candle.open_time
