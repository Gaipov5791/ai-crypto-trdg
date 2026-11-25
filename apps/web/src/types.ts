/** Frozen UI contract. Mirror of apps/api/app/schemas.py. Owned by PM. */

export type Side = "LONG";
export type PositionStatus = "OPEN" | "CLOSED";
export type SignalStatus = "NEW" | "TAKEN" | "SKIPPED";

export type Candle = {
  symbol: string;
  interval: string;
  open_time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  is_closed: boolean;
};

export type Ticker = {
  symbol: string;
  price: number;
  ts: number;
};

export type AccountSnapshot = {
  cash: number;
  equity: number;
  starting_balance: number;
  realized_pnl: number;
  unrealized_pnl: number;
  win_rate: number;
  avg_profit: number;
  kill_switch_until: number | null;
};

export type Position = {
  id: string;
  symbol: string;
  side: Side;
  qty: number;
  entry: number;
  stop_loss: number | null;
  take_profit: number | null;
  status: PositionStatus;
  opened_at: number;
  closed_at: number | null;
  realized_pnl: number | null;
};

export type OrderRequest = {
  symbol: string;
  quote_amount?: number | null;
  qty?: number | null;
  stop_loss?: number | null;
  take_profit?: number | null;
};

export type Fill = {
  id: string;
  symbol: string;
  side: Side;
  qty: number;
  price: number;
  fee: number;
  ts: number;
};

export type Signal = {
  id: string;
  symbol: string;
  side: Side;
  entry: number;
  stop_loss: number;
  take_profit: number;
  confidence: number;
  size_pct: number;
  reason: string;
  status: SignalStatus;
  ts: number;
};

export const API_BASE = "http://127.0.0.1:8000";
export const SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"] as const;

export type WsEventType =
  | "hello"
  | "ticker"
  | "kline"
  | "signal"
  | "account"
  | "position";

export type WsEvent = {
  type: WsEventType | string;
  payload: Record<string, unknown>;
};
