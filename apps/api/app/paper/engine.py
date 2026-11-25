"""OWNER: Paper agent.

Spot LONG paper account. Market fills with taker fee + slippage.
SQLite persistence. SL/TP triggers on price ticks from Market.
Do not fetch Binance data here — accept price via on_price().
"""

from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Iterator, Optional

from app.config import settings
from app.schemas import AccountSnapshot, Fill, OrderRequest, Position, PositionStatus, Side

_engine_lock = threading.Lock()
_engine: Optional["PaperEngine"] = None


class PaperError(Exception):
    """Domain error mapped to an HTTP status by the router."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def get_engine() -> "PaperEngine":
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = PaperEngine()
        return _engine


def reset_engine(engine: Optional["PaperEngine"] = None) -> None:
    """Replace the process-wide singleton (tests)."""
    global _engine
    with _engine_lock:
        _engine = engine


def _now_ms() -> int:
    return int(time.time() * 1000)


def _new_id() -> str:
    return uuid.uuid4().hex


class PaperEngine:
    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path if db_path is not None else settings.db_path
        self._lock = threading.Lock()
        self._init_db()

    @property
    def starting_balance(self) -> float:
        return settings.starting_balance

    @property
    def taker_fee(self) -> float:
        return settings.taker_fee

    @property
    def slippage(self) -> float:
        return settings.slippage

    def snapshot(self) -> AccountSnapshot:
        with self._lock, self._db() as conn:
            cash = self._cash(conn)
            open_rows = conn.execute(
                "SELECT * FROM positions WHERE status = ?",
                (PositionStatus.OPEN.value,),
            ).fetchall()
            prices = {
                row["symbol"]: row["price"]
                for row in conn.execute("SELECT symbol, price FROM last_prices")
            }
            closed = conn.execute(
                "SELECT realized_pnl FROM positions WHERE status = ?",
                (PositionStatus.CLOSED.value,),
            ).fetchall()

        unrealized = 0.0
        mtm_value = 0.0
        for row in open_rows:
            mark = prices.get(row["symbol"], row["entry"])
            qty = float(row["qty"])
            entry = float(row["entry"])
            mtm_value += mark * qty
            unrealized += (mark - entry) * qty

        pnls = [float(r["realized_pnl"] or 0.0) for r in closed]
        n_closed = len(pnls)
        realized = sum(pnls)
        wins = sum(1 for p in pnls if p > 0)
        win_rate = (wins / n_closed) if n_closed else 0.0
        avg_profit = (realized / n_closed) if n_closed else 0.0
        equity = cash + mtm_value

        return AccountSnapshot(
            cash=cash,
            equity=equity,
            starting_balance=self.starting_balance,
            realized_pnl=realized,
            unrealized_pnl=unrealized,
            win_rate=win_rate,
            avg_profit=avg_profit,
            kill_switch_until=None,
        )

    def positions(self, status: str | None = None) -> list[Position]:
        with self._lock, self._db() as conn:
            if status is None:
                rows = conn.execute(
                    "SELECT * FROM positions ORDER BY opened_at ASC"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM positions WHERE status = ? ORDER BY opened_at ASC",
                    (status,),
                ).fetchall()
        return [self._row_to_position(r) for r in rows]

    def market_buy(self, req: OrderRequest, last_price: float) -> Fill:
        if last_price <= 0:
            raise PaperError("last_price must be positive")
        if req.qty is None and req.quote_amount is None:
            raise PaperError("Provide qty or quote_amount")
        if req.qty is not None and req.qty <= 0:
            raise PaperError("qty must be positive")
        if req.quote_amount is not None and req.quote_amount <= 0:
            raise PaperError("quote_amount must be positive")

        fill_price = last_price * (1.0 + self.slippage)
        if req.qty is not None:
            qty = float(req.qty)
        else:
            qty = float(req.quote_amount) / fill_price
        quote_spent = fill_price * qty
        fee = quote_spent * self.taker_fee
        ts = _now_ms()
        fill_id = _new_id()

        with self._lock, self._db() as conn:
            cash = self._cash(conn)
            cost = quote_spent + fee
            if cost > cash + 1e-12:
                raise PaperError("Insufficient cash for market buy")

            self._upsert_price(conn, req.symbol, last_price, ts)
            existing = conn.execute(
                "SELECT * FROM positions WHERE symbol = ? AND status = ?",
                (req.symbol, PositionStatus.OPEN.value),
            ).fetchone()

            if existing is None:
                position_id = _new_id()
                conn.execute(
                    """
                    INSERT INTO positions (
                        id, symbol, side, qty, entry, entry_fee,
                        stop_loss, take_profit, status, opened_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        position_id,
                        req.symbol,
                        Side.LONG.value,
                        qty,
                        fill_price,
                        fee,
                        req.stop_loss,
                        req.take_profit,
                        PositionStatus.OPEN.value,
                        ts,
                    ),
                )
            else:
                position_id = existing["id"]
                old_qty = float(existing["qty"])
                old_entry = float(existing["entry"])
                old_fee = float(existing["entry_fee"])
                new_qty = old_qty + qty
                new_entry = (old_entry * old_qty + fill_price * qty) / new_qty
                sl = req.stop_loss if req.stop_loss is not None else existing["stop_loss"]
                tp = req.take_profit if req.take_profit is not None else existing["take_profit"]
                conn.execute(
                    """
                    UPDATE positions
                    SET qty = ?, entry = ?, entry_fee = ?, stop_loss = ?, take_profit = ?
                    WHERE id = ?
                    """,
                    (new_qty, new_entry, old_fee + fee, sl, tp, position_id),
                )

            conn.execute(
                """
                INSERT INTO fills (id, position_id, symbol, side, qty, price, fee, ts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (fill_id, position_id, req.symbol, Side.LONG.value, qty, fill_price, fee, ts),
            )
            conn.execute(
                "UPDATE account SET cash = cash - ? WHERE id = 1",
                (cost,),
            )

        return Fill(
            id=fill_id,
            symbol=req.symbol,
            side=Side.LONG,
            qty=qty,
            price=fill_price,
            fee=fee,
            ts=ts,
        )

    def close_position(self, position_id: str, last_price: float) -> Fill:
        if last_price <= 0:
            raise PaperError("last_price must be positive")
        ts = _now_ms()
        with self._lock, self._db() as conn:
            return self._close_locked(conn, position_id, last_price, ts)

    def on_price(self, symbol: str, price: float, ts: int) -> list[Fill]:
        if price <= 0:
            raise PaperError("price must be positive")
        fills: list[Fill] = []
        with self._lock, self._db() as conn:
            self._upsert_price(conn, symbol, price, ts)
            rows = conn.execute(
                """
                SELECT * FROM positions
                WHERE symbol = ? AND status = ?
                ORDER BY opened_at ASC
                """,
                (symbol, PositionStatus.OPEN.value),
            ).fetchall()
            for row in rows:
                sl = row["stop_loss"]
                tp = row["take_profit"]
                hit_sl = sl is not None and price <= float(sl)
                hit_tp = tp is not None and price >= float(tp)
                if hit_sl or hit_tp:
                    fills.append(self._close_locked(conn, row["id"], price, ts))
        return fills

    def _close_locked(
        self,
        conn: sqlite3.Connection,
        position_id: str,
        last_price: float,
        ts: int,
    ) -> Fill:
        row = conn.execute(
            "SELECT * FROM positions WHERE id = ?",
            (position_id,),
        ).fetchone()
        if row is None:
            raise PaperError(f"Position {position_id} not found", status_code=404)
        if row["status"] != PositionStatus.OPEN.value:
            raise PaperError(f"Position {position_id} is not open")

        qty = float(row["qty"])
        entry = float(row["entry"])
        entry_fee = float(row["entry_fee"])
        symbol = row["symbol"]
        exit_price = last_price * (1.0 - self.slippage)
        notional = exit_price * qty
        fee = notional * self.taker_fee
        proceeds = notional - fee
        realized = proceeds - (entry * qty + entry_fee)
        fill_id = _new_id()

        self._upsert_price(conn, symbol, last_price, ts)
        conn.execute(
            """
            UPDATE positions
            SET status = ?, closed_at = ?, realized_pnl = ?
            WHERE id = ?
            """,
            (PositionStatus.CLOSED.value, ts, realized, position_id),
        )
        conn.execute(
            """
            INSERT INTO fills (id, position_id, symbol, side, qty, price, fee, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (fill_id, position_id, symbol, Side.LONG.value, qty, exit_price, fee, ts),
        )
        conn.execute(
            "UPDATE account SET cash = cash + ? WHERE id = 1",
            (proceeds,),
        )
        return Fill(
            id=fill_id,
            symbol=symbol,
            side=Side.LONG,
            qty=qty,
            price=exit_price,
            fee=fee,
            ts=ts,
        )

    def _init_db(self) -> None:
        with self._lock, self._db() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS account (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    cash REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS positions (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    qty REAL NOT NULL,
                    entry REAL NOT NULL,
                    entry_fee REAL NOT NULL DEFAULT 0,
                    stop_loss REAL,
                    take_profit REAL,
                    status TEXT NOT NULL,
                    opened_at INTEGER NOT NULL,
                    closed_at INTEGER,
                    realized_pnl REAL
                );
                CREATE TABLE IF NOT EXISTS fills (
                    id TEXT PRIMARY KEY,
                    position_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    qty REAL NOT NULL,
                    price REAL NOT NULL,
                    fee REAL NOT NULL,
                    ts INTEGER NOT NULL,
                    FOREIGN KEY (position_id) REFERENCES positions(id)
                );
                CREATE TABLE IF NOT EXISTS last_prices (
                    symbol TEXT PRIMARY KEY,
                    price REAL NOT NULL,
                    ts INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_positions_status
                    ON positions(status);
                CREATE INDEX IF NOT EXISTS idx_positions_symbol_status
                    ON positions(symbol, status);
                """
            )
            conn.execute(
                "INSERT OR IGNORE INTO account (id, cash) VALUES (1, ?)",
                (self.starting_balance,),
            )

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _cash(conn: sqlite3.Connection) -> float:
        row = conn.execute("SELECT cash FROM account WHERE id = 1").fetchone()
        if row is None:
            raise PaperError("Account row missing", status_code=500)
        return float(row["cash"])

    @staticmethod
    def _upsert_price(conn: sqlite3.Connection, symbol: str, price: float, ts: int) -> None:
        conn.execute(
            """
            INSERT INTO last_prices (symbol, price, ts) VALUES (?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET price = excluded.price, ts = excluded.ts
            """,
            (symbol, price, ts),
        )

    @staticmethod
    def _row_to_position(row: sqlite3.Row) -> Position:
        return Position(
            id=row["id"],
            symbol=row["symbol"],
            side=Side(row["side"]),
            qty=float(row["qty"]),
            entry=float(row["entry"]),
            stop_loss=row["stop_loss"],
            take_profit=row["take_profit"],
            status=PositionStatus(row["status"]),
            opened_at=int(row["opened_at"]),
            closed_at=int(row["closed_at"]) if row["closed_at"] is not None else None,
            realized_pnl=(
                float(row["realized_pnl"]) if row["realized_pnl"] is not None else None
            ),
        )
