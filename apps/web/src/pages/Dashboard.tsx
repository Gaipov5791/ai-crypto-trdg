import { useEffect, useState } from "react";
import { EMPTY_ACCOUNT, fetchAccount } from "../api";
import { asAccount } from "../stream";
import { useMarketStream } from "../streamContext";
import { formatTs, formatUsd, formatWinRate, pnlClass, signedUsd } from "../format";
import type { AccountSnapshot } from "../types";

type Card = {
  key: string;
  label: string;
  value: string;
  tone?: string;
};

export default function Dashboard() {
  const { connected, subscribe } = useMarketStream();
  const [account, setAccount] = useState<AccountSnapshot>(EMPTY_ACCOUNT);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    const ac = new AbortController();

    const poll = async () => {
      const result = await fetchAccount(ac.signal);
      if (result.aborted) return;
      setOffline(result.offline);
      setAccount(result.data ?? EMPTY_ACCOUNT);
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
      if (event.type !== "account") return;
      const snap = asAccount(event.payload);
      if (snap) {
        setOffline(false);
        setAccount(snap);
      }
    });
  }, [subscribe]);

  const cards: Card[] = [
    { key: "cash", label: "Cash", value: formatUsd(account.cash) },
    { key: "equity", label: "Equity", value: formatUsd(account.equity) },
    {
      key: "realized",
      label: "Realized PnL",
      value: signedUsd(account.realized_pnl),
      tone: pnlClass(account.realized_pnl),
    },
    {
      key: "unrealized",
      label: "Unrealized PnL",
      value: signedUsd(account.unrealized_pnl),
      tone: pnlClass(account.unrealized_pnl),
    },
    { key: "win", label: "Win rate", value: formatWinRate(account.win_rate) },
    {
      key: "avg",
      label: "Avg profit",
      value: signedUsd(account.avg_profit),
      tone: pnlClass(account.avg_profit),
    },
  ];

  const killUntil = account.kill_switch_until;

  return (
    <section className="page">
      <div className="page-head">
        <h1>Dashboard</h1>
        <p className="muted">Paper account snapshot</p>
      </div>

      {offline && (
        <div className="banner warn" role="status">
          API offline — showing zeros
        </div>
      )}

      {killUntil != null && (
        <div className="banner danger" role="status">
          Kill switch active until {formatTs(killUntil)}
        </div>
      )}

      <div className="stat-grid">
        {cards.map((card) => (
          <article key={card.key} className="stat-card">
            <span className="stat-label">{card.label}</span>
            <span className={`stat-value ${card.tone ?? ""}`}>{card.value}</span>
          </article>
        ))}
      </div>
    </section>
  );
}
