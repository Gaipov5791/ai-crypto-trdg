export function formatUsd(n: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(n);
}

export function formatPx(n: number): string {
  const digits = n >= 1000 ? 2 : n >= 1 ? 4 : 6;
  return n.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: digits,
  });
}

export function formatWinRate(v: number): string {
  const pct = v > 0 && v <= 1 ? v * 100 : v;
  return `${pct.toFixed(1)}%`;
}

export function formatConfidence(v: number): string {
  return `${v.toFixed(0)}%`;
}

export function formatTs(ts: number): string {
  const ms = ts > 0 && ts < 1e12 ? ts * 1000 : ts;
  if (!Number.isFinite(ms) || ms <= 0) return "—";
  return new Date(ms).toLocaleString("en-US", {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

export function pnlClass(n: number): string {
  if (n > 0) return "pos";
  if (n < 0) return "neg";
  return "flat";
}

export function signedUsd(n: number): string {
  const formatted = formatUsd(Math.abs(n));
  if (n > 0) return `+${formatted}`;
  if (n < 0) return `-${formatted}`;
  return formatted;
}
