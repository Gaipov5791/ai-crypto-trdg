import { useCallback, useEffect, useState } from "react";
import { closePosition, fetchPositions } from "../api";
import { asPosition } from "../stream";
import { useMarketStream } from "../streamContext";
import { formatPx, formatTs, pnlClass, signedUsd } from "../format";
import type { Position } from "../types";

export default function Positions() {
  const { connected, subscribe } = useMarketStream();
  const [rows, setRows] = useState<Position[]>([]);
  const [offline, setOffline] = useState(false);
  const [closingId, setClosingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    const result = await fetchPositions(signal);
    if (result.aborted) return;
    setOffline(result.offline);
    setRows(Array.isArray(result.data) ? result.data : []);
  }, []);

  useEffect(() => {
    const ac = new AbortController();

    const poll = async () => {
      await refresh(ac.signal);
    };

    void poll();
    const id = window.setInterval(() => {
      if (connected) return;
      void poll();
    }, 5000);

    return () => {
      ac.abort();
      window.clearInterval(id);
    };
  }, [refresh, connected]);

  useEffect(() => {
    return subscribe((event) => {
      if (event.type !== "position") return;
      const pos = asPosition(event.payload);
      if (!pos) return;
      setOffline(false);
      setRows((prev) => {
        const without = prev.filter((row) => row.id !== pos.id);
        return [pos, ...without];
      });
    });
  }, [subscribe]);

  async function onClose(id: string) {
    setError(null);
    setClosingId(id);
    const result = await closePosition(id);
    setClosingId(null);
    if (result.aborted) return;
    if (result.offline) {
      setError("Close failed — API offline.");
      return;
    }
    if (result.data == null) {
      setError(result.error ?? "Close failed.");
      return;
    }
    await refresh();
  }

  return (
    <section className="page">
      <div className="page-head">
        <h1>Positions</h1>
        <p className="muted">Open book and closed history</p>
      </div>

      {offline && (
        <div className="banner warn" role="status">
          API offline
        </div>
      )}
      {error && (
        <div className="banner danger" role="status">
          {error}
        </div>
      )}

      {rows.length === 0 ? (
        <div className="empty-state">
          <span>No positions</span>
          <span className="muted">
            {offline ? "Book unavailable until the API is up." : "No open or closed paper positions."}
          </span>
        </div>
      ) : (
        <>
          <div className="table-wrap pos-table">
          <table className="data-table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Side</th>
                <th>Qty</th>
                <th>Entry</th>
                <th>SL</th>
                <th>TP</th>
                <th>Status</th>
                <th>PnL</th>
                <th>Opened</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((pos) => (
                <tr key={pos.id}>
                  <td className="mono">{pos.symbol}</td>
                  <td>{pos.side}</td>
                  <td className="mono">{pos.qty}</td>
                  <td className="mono">{formatPx(pos.entry)}</td>
                  <td className="mono">{pos.stop_loss == null ? "—" : formatPx(pos.stop_loss)}</td>
                  <td className="mono">{pos.take_profit == null ? "—" : formatPx(pos.take_profit)}</td>
                  <td>
                    <span className={`status-tag ${pos.status.toLowerCase()}`}>{pos.status}</span>
                  </td>
                  <td className={`mono ${pnlClass(pos.realized_pnl ?? 0)}`}>
                    {pos.realized_pnl == null ? "—" : signedUsd(pos.realized_pnl)}
                  </td>
                  <td className="muted">{formatTs(pos.opened_at)}</td>
                  <td>
                    {pos.status === "OPEN" && (
                      <button
                        type="button"
                        className="btn-close"
                        disabled={closingId === pos.id}
                        onClick={() => {
                          void onClose(pos.id);
                        }}
                      >
                        {closingId === pos.id ? "Closing…" : "Close"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <ul className="pos-cards">
          {rows.map((pos) => (
            <li key={pos.id} className="pos-card">
              <div className="pos-card-head">
                <span className="mono">{pos.symbol}</span>
                <span className={`status-tag ${pos.status.toLowerCase()}`}>{pos.status}</span>
                <span className={`mono ${pnlClass(pos.realized_pnl ?? 0)}`}>
                  {pos.realized_pnl == null ? "—" : signedUsd(pos.realized_pnl)}
                </span>
              </div>
              <div className="pos-card-grid">
                <span>
                  Side <strong>{pos.side}</strong>
                </span>
                <span>
                  Qty <strong className="mono">{pos.qty}</strong>
                </span>
                <span>
                  Entry <strong className="mono">{formatPx(pos.entry)}</strong>
                </span>
                <span>
                  SL <strong className="mono">{pos.stop_loss == null ? "—" : formatPx(pos.stop_loss)}</strong>
                </span>
                <span>
                  TP <strong className="mono">{pos.take_profit == null ? "—" : formatPx(pos.take_profit)}</strong>
                </span>
                <span>
                  Opened <strong>{formatTs(pos.opened_at)}</strong>
                </span>
              </div>
              {pos.status === "OPEN" && (
                <button
                  type="button"
                  className="btn-close"
                  disabled={closingId === pos.id}
                  onClick={() => {
                    void onClose(pos.id);
                  }}
                >
                  {closingId === pos.id ? "Closing…" : "Close"}
                </button>
              )}
            </li>
          ))}
        </ul>
        </>
      )}
    </section>
  );
}
