import { API_BASE } from "./types";
import type {
  AccountSnapshot,
  Candle,
  Position,
  Signal,
  Ticker,
  WsEvent,
} from "./types";

function wsUrl(): string {
  if (import.meta.env.DEV) {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${window.location.host}/ws`;
  }
  const url = new URL("/ws", API_BASE);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value != null && typeof value === "object" && !Array.isArray(value);
}

export function parseWsEvent(raw: string): WsEvent | null {
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!isRecord(parsed) || typeof parsed.type !== "string") return null;
    const payload = isRecord(parsed.payload) ? parsed.payload : {};
    return { type: parsed.type, payload };
  } catch {
    return null;
  }
}

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function str(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

export function asTicker(payload: Record<string, unknown>): Ticker | null {
  const symbol = str(payload.symbol);
  const price = num(payload.price);
  const ts = num(payload.ts);
  if (symbol == null || price == null || ts == null) return null;
  return { symbol, price, ts };
}

export function asCandle(payload: Record<string, unknown>): Candle | null {
  const symbol = str(payload.symbol);
  const interval = str(payload.interval);
  const open_time = num(payload.open_time);
  const open = num(payload.open);
  const high = num(payload.high);
  const low = num(payload.low);
  const close = num(payload.close);
  const volume = num(payload.volume);
  if (
    symbol == null ||
    interval == null ||
    open_time == null ||
    open == null ||
    high == null ||
    low == null ||
    close == null ||
    volume == null
  ) {
    return null;
  }
  return {
    symbol,
    interval,
    open_time,
    open,
    high,
    low,
    close,
    volume,
    is_closed: payload.is_closed === true,
  };
}

export function asAccount(payload: Record<string, unknown>): AccountSnapshot | null {
  const cash = num(payload.cash);
  const equity = num(payload.equity);
  if (cash == null || equity == null) return null;
  return {
    cash,
    equity,
    starting_balance: num(payload.starting_balance) ?? 0,
    realized_pnl: num(payload.realized_pnl) ?? 0,
    unrealized_pnl: num(payload.unrealized_pnl) ?? 0,
    win_rate: num(payload.win_rate) ?? 0,
    avg_profit: num(payload.avg_profit) ?? 0,
    kill_switch_until: num(payload.kill_switch_until),
  };
}

export function asSignal(payload: Record<string, unknown>): Signal | null {
  const id = str(payload.id);
  const symbol = str(payload.symbol);
  const entry = num(payload.entry);
  const stop_loss = num(payload.stop_loss);
  const take_profit = num(payload.take_profit);
  const confidence = num(payload.confidence);
  const size_pct = num(payload.size_pct);
  const reason = str(payload.reason);
  const ts = num(payload.ts);
  const side = payload.side === "LONG" ? "LONG" : null;
  const status =
    payload.status === "NEW" || payload.status === "TAKEN" || payload.status === "SKIPPED"
      ? payload.status
      : null;
  if (
    id == null ||
    symbol == null ||
    side == null ||
    entry == null ||
    stop_loss == null ||
    take_profit == null ||
    confidence == null ||
    size_pct == null ||
    reason == null ||
    status == null ||
    ts == null
  ) {
    return null;
  }
  return {
    id,
    symbol,
    side,
    entry,
    stop_loss,
    take_profit,
    confidence,
    size_pct,
    reason,
    status,
    ts,
  };
}

export function asPosition(payload: Record<string, unknown>): Position | null {
  const id = str(payload.id);
  const symbol = str(payload.symbol);
  const qty = num(payload.qty);
  const entry = num(payload.entry);
  const opened_at = num(payload.opened_at);
  if (id == null || symbol == null || qty == null || entry == null || opened_at == null) {
    return null;
  }
  return {
    id,
    symbol,
    side: "LONG",
    qty,
    entry,
    stop_loss: num(payload.stop_loss),
    take_profit: num(payload.take_profit),
    status: payload.status === "CLOSED" ? "CLOSED" : "OPEN",
    opened_at,
    closed_at: num(payload.closed_at),
    realized_pnl: num(payload.realized_pnl),
  };
}

export function connectMarketStream(opts: {
  onEvent: (event: WsEvent) => void;
  onStatus: (connected: boolean) => void;
}): () => void {
  let stopped = false;
  let socket: WebSocket | null = null;
  let timer: number | null = null;
  let delay = 1000;

  const open = () => {
    if (stopped) return;
    const ws = new WebSocket(wsUrl());
    socket = ws;
    ws.onopen = () => {
      delay = 1000;
      opts.onStatus(true);
    };
    ws.onmessage = (ev) => {
      if (typeof ev.data !== "string") return;
      const event = parseWsEvent(ev.data);
      if (event) opts.onEvent(event);
    };
    ws.onclose = () => {
      opts.onStatus(false);
      if (stopped) return;
      timer = window.setTimeout(open, delay);
      delay = Math.min(delay * 2, 15_000);
    };
    ws.onerror = () => {
      ws.close();
    };
  };

  open();

  return () => {
    stopped = true;
    if (timer != null) window.clearTimeout(timer);
    opts.onStatus(false);
    socket?.close();
  };
}
