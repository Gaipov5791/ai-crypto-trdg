import { useEffect, useState } from "react";
import { fetchSignals } from "../api";
import { asSignal } from "../stream";
import { useMarketStream } from "../streamContext";
import { formatConfidence, formatPx, formatTs } from "../format";
import type { Signal } from "../types";

export default function AiFeed() {
  const { connected, subscribe } = useMarketStream();
  const [signals, setSignals] = useState<Signal[]>([]);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    const ac = new AbortController();

    const poll = async () => {
      const result = await fetchSignals(ac.signal);
      if (result.aborted) return;
      setOffline(result.offline);
      setSignals(Array.isArray(result.data) ? result.data : []);
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
  }, [connected]);

  useEffect(() => {
    return subscribe((event) => {
      if (event.type !== "signal") return;
      const sig = asSignal(event.payload);
      if (!sig) return;
      setOffline(false);
      setSignals((prev) => [sig, ...prev.filter((s) => s.id !== sig.id)].slice(0, 50));
    });
  }, [subscribe]);

  return (
    <section className="page">
      <div className="page-head">
        <h1>AI Feed</h1>
        <p className="muted">Signal log · reason · confidence · levels</p>
      </div>

      {offline && (
        <div className="banner warn" role="status">
          API offline
        </div>
      )}

      {signals.length === 0 ? (
        <div className="empty-state">
          <span>No signals</span>
          <span className="muted">
            {offline
              ? "Feed unavailable until the API is up."
              : "Waiting for bullish engulfing + confidence > 75 on 5m."}
          </span>
        </div>
      ) : (
        <ul className="feed-list">
          {signals.map((sig) => (
            <li key={sig.id} className="feed-item">
              <div className="feed-meta">
                <span className="pair-tag">{sig.symbol}</span>
                <span className="side-tag">{sig.side}</span>
                <span className={`status-tag ${sig.status.toLowerCase()}`}>{sig.status}</span>
                <span className="muted ts">{formatTs(sig.ts)}</span>
              </div>
              <p className="feed-reason">{sig.reason}</p>
              <div className="feed-levels">
                <span>
                  Conf <strong>{formatConfidence(sig.confidence)}</strong>
                </span>
                <span>
                  Entry <strong>{formatPx(sig.entry)}</strong>
                </span>
                <span>
                  SL <strong className="neg">{formatPx(sig.stop_loss)}</strong>
                </span>
                <span>
                  TP <strong className="pos">{formatPx(sig.take_profit)}</strong>
                </span>
              </div>
              <div className="conf-bar" aria-hidden>
                <div
                  className="conf-fill"
                  style={{ width: `${Math.max(0, Math.min(100, sig.confidence))}%` }}
                />
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
