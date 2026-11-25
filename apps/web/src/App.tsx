import { useState } from "react";
import { SYMBOLS } from "./types";
import { MarketStreamProvider, useMarketStream } from "./streamContext";
import Dashboard from "./pages/Dashboard";
import Terminal from "./pages/Terminal";
import AiFeed from "./pages/AiFeed";
import Positions from "./pages/Positions";
import "./App.css";

type Screen = "dashboard" | "terminal" | "feed" | "positions";

const SCREENS: { id: Screen; label: string }[] = [
  { id: "dashboard", label: "Dashboard" },
  { id: "terminal", label: "Terminal" },
  { id: "feed", label: "AI Feed" },
  { id: "positions", label: "Positions" },
];

function AppShell() {
  const [screen, setScreen] = useState<Screen>("dashboard");
  const { connected } = useMarketStream();

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-lockup">
            <span className="brand-mark" aria-hidden>
              ▮
            </span>
            <strong>CryptoAI Trader</strong>
          </span>
          <span className="brand-badges">
            <span className="badge">PAPER</span>
            <span className={connected ? "badge live" : "badge mute"} title={connected ? "WebSocket live" : "Polling REST"}>
              {connected ? "LIVE" : "POLL"}
            </span>
          </span>
        </div>
        <nav className="topnav" aria-label="Primary">
          {SCREENS.map((item) => (
            <button
              key={item.id}
              className={screen === item.id ? "nav active" : "nav"}
              onClick={() => setScreen(item.id)}
              type="button"
            >
              {item.label}
            </button>
          ))}
        </nav>
        <span className="pairs">{SYMBOLS.join(" · ")}</span>
      </header>
      <main className={screen === "terminal" ? "main terminal-main" : "main"}>
        {screen === "dashboard" && <Dashboard />}
        {screen === "terminal" && <Terminal />}
        {screen === "feed" && <AiFeed />}
        {screen === "positions" && <Positions />}
      </main>
      <footer className="disclaimer">
        Paper trading. Not financial advice.
      </footer>
    </div>
  );
}

export default function App() {
  return (
    <MarketStreamProvider>
      <AppShell />
    </MarketStreamProvider>
  );
}
