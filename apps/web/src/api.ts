import { API_BASE } from "./types";
import type { AccountSnapshot, Candle, Fill, OrderRequest, Position, Signal, Ticker } from "./types";

/** Same-origin + Vite proxy in `npm run dev`; absolute host for preview/prod. */
function root(): string {
  return import.meta.env.DEV ? "" : API_BASE;
}

export const EMPTY_ACCOUNT: AccountSnapshot = {
  cash: 0,
  equity: 0,
  starting_balance: 0,
  realized_pnl: 0,
  unrealized_pnl: 0,
  win_rate: 0,
  avg_profit: 0,
  kill_switch_until: null,
};

export type ApiResult<T> = {
  data: T | null;
  offline: boolean;
  aborted: boolean;
  error: string | null;
};

function abortedResult<T>(): ApiResult<T> {
  return { data: null, offline: false, aborted: true, error: null };
}

function offlineResult<T>(): ApiResult<T> {
  return { data: null, offline: true, aborted: false, error: null };
}

function isAbort(err: unknown): boolean {
  return err instanceof DOMException && err.name === "AbortError";
}

function detailFromBody(body: unknown, fallback: string): string {
  if (body == null || typeof body !== "object" || !("detail" in body)) {
    return fallback;
  }
  const detail = (body as { detail: unknown }).detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const parts = detail.map((item) => {
      if (typeof item === "string") return item;
      if (item && typeof item === "object" && "msg" in item) {
        const msg = (item as { msg: unknown }).msg;
        if (typeof msg === "string" && msg.trim()) return msg;
      }
      return "";
    }).filter(Boolean);
    if (parts.length > 0) return parts.join("; ");
  }
  return fallback;
}

async function request<T>(
  path: string,
  init?: RequestInit,
): Promise<ApiResult<T>> {
  try {
    const res = await fetch(`${root()}${path}`, init);
    if (res.status === 501 || !res.ok) {
      return offlineResult();
    }
    return { data: (await res.json()) as T, offline: false, aborted: false, error: null };
  } catch (err) {
    if (isAbort(err)) return abortedResult();
    return offlineResult();
  }
}

/** POST JSON: 2xx → data; 501 / network → offline; other HTTP → error from FastAPI detail. */
async function postJson<T>(
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<ApiResult<T>> {
  try {
    const res = await fetch(`${root()}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
    if (res.status === 501) {
      return offlineResult();
    }
    if (!res.ok) {
      let fallback = `Request failed (${res.status})`;
      try {
        fallback = detailFromBody(await res.json(), fallback);
      } catch {
        /* keep fallback */
      }
      return { data: null, offline: false, aborted: false, error: fallback };
    }
    return { data: (await res.json()) as T, offline: false, aborted: false, error: null };
  } catch (err) {
    if (isAbort(err)) return abortedResult();
    return offlineResult();
  }
}

export async function fetchAccount(
  signal?: AbortSignal,
): Promise<ApiResult<AccountSnapshot>> {
  return request<AccountSnapshot>("/paper/account", { signal });
}

export async function fetchKlines(
  symbol: string,
  interval = "1m",
  signal?: AbortSignal,
): Promise<ApiResult<Candle[]>> {
  const q = new URLSearchParams({ symbol, interval });
  return request<Candle[]>(`/market/klines?${q}`, { signal });
}

export async function fetchTicker(
  symbol: string,
  signal?: AbortSignal,
): Promise<ApiResult<Ticker>> {
  const q = new URLSearchParams({ symbol });
  return request<Ticker>(`/market/ticker?${q}`, { signal });
}

export async function fetchSignals(
  signal?: AbortSignal,
): Promise<ApiResult<Signal[]>> {
  return request<Signal[]>("/signals", { signal });
}

export async function fetchPositions(
  signal?: AbortSignal,
): Promise<ApiResult<Position[]>> {
  return request<Position[]>("/paper/positions?all=true", { signal });
}

export async function placeMarketBuy(
  body: OrderRequest,
  signal?: AbortSignal,
): Promise<ApiResult<Fill>> {
  return postJson<Fill>("/paper/orders/market", body, signal);
}

export async function closePosition(
  id: string,
  signal?: AbortSignal,
): Promise<ApiResult<Fill>> {
  return postJson<Fill>(
    `/paper/positions/${encodeURIComponent(id)}/close`,
    undefined,
    signal,
  );
}
