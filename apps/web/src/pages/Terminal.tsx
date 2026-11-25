import { useEffect, useMemo, useRef, useState } from "react";
import CandleChart from "../components/CandleChart";
import { fetchKlines, fetchPositions, fetchSignals, fetchTicker, placeMarketBuy } from "../api";
import { asCandle, asPosition, asSignal, asTicker } from "../stream";
import { useMarketStream } from "../streamContext";
import { formatPx, formatUsd } from "../format";
import { SYMBOLS } from "../types";
import type { Candle, OrderRequest, Position, Signal } from "../types";

type Pair = (typeof SYMBOLS)[number];

type BuyStatus = { kind: "ok" | "err"; text: string } | null;

function mergeKline(rows: Candle[], incoming: Candle): Candle[] {
  const next = [...rows];
  const last = next.at(-1);
  if (last && last.open_time === incoming.open_time) {
    next[next.length - 1] = incoming;
    return next;
  }
  if (!last || last.open_time < incoming.open_time) {
    next.push(incoming);
    return next;
  }
  const idx = next.findIndex((c) => c.open_time === incoming.open_time);
  if (idx >= 0) {
    next[idx] = incoming;
  }
  return next;
}

export default function Terminal() {
  const { connected, subscribe } = useMarketStream();
  const [symbol, setSymbol] = useState<Pair>(SYMBOLS[0]);
  const [klines, setKlines] = useState<{
    symbol: Pair;
    candles: Candle[];
    offline: boolean;
  }>({ symbol: SYMBOLS[0], candles: [], offline: false });
  const [tick, setTick] = useState<{ symbol: Pair; price: number } | null>(null);
  const [openPos, setOpenPos] = useState<Position | null>(null);
  const [signalLevels, setSignalLevels] = useState<Signal | null>(null);
  const [quote, setQuote] = useState("1000");
  const [stopLoss, setStopLoss] = useState("");
  const [takeProfit, setTakeProfit] = useState("");
  const [buying, setBuying] = useState(false);
  const [buyStatus, setBuyStatus] = useState<BuyStatus>(null);
  const buyAcRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const ac = new AbortController();

    const load = async () => {
      const result = await fetchKlines(symbol, "1m", ac.signal);
      if (result.aborted) return;
      const rows = Array.isArray(result.data) ? result.data : [];
      setKlines((prev) => {
        if (result.offline && prev.symbol === symbol && prev.candles.length > 0) {
          return { ...prev, offline: true };
        }
        return { symbol, candles: rows, offline: result.offline };
      });
    };

    void load();
    const id = window.setInterval(() => {
      void load();
    }, 60_000);

    return () => {
      ac.abort();
      window.clearInterval(id);
    };
  }, [symbol]);

  useEffect(() => {
    const ac = new AbortController();

    const poll = async () => {
      const result = await fetchTicker(symbol, ac.signal);
      if (result.aborted) return;
      if (result.offline || result.data == null) return;
      setTick({ symbol, price: result.data.price });
    };

    void poll();
    const id = window.setInterval(() => {
      if (connected) return;
      void poll();
    }, 2000);

    return () => {
      ac.abort();
      window.clearInterval(id);
    };
  }, [symbol, connected]);

  useEffect(() => {
    const ac = new AbortController();

    const loadLevels = async () => {
      const [posRes, sigRes] = await Promise.all([
        fetchPositions(ac.signal),
        fetchSignals(ac.signal),
      ]);
      if (ac.signal.aborted) return;
      const positions = Array.isArray(posRes.data) ? posRes.data : [];
      setOpenPos(
        positions.find((p) => p.symbol === symbol && p.status === "OPEN") ?? null,
      );
      const signals = Array.isArray(sigRes.data) ? sigRes.data : [];
      setSignalLevels(
        signals.find((s) => s.symbol === symbol && s.status !== "SKIPPED") ?? null,
      );
    };

    void loadLevels();
    return () => ac.abort();
  }, [symbol]);

  useEffect(() => {
    return subscribe((event) => {
      if (event.type === "ticker") {
        const ticker = asTicker(event.payload);
        if (ticker && ticker.symbol === symbol) {
          setTick({ symbol, price: ticker.price });
        }
        return;
      }
      if (event.type === "kline") {
        const candle = asCandle(event.payload);
        if (!candle || candle.symbol !== symbol || candle.interval !== "1m") return;
        setKlines((prev) => {
          if (prev.symbol !== symbol) return prev;
          return { ...prev, candles: mergeKline(prev.candles, candle), offline: false };
        });
        return;
      }
      if (event.type === "position") {
        const pos = asPosition(event.payload);
        if (!pos || pos.symbol !== symbol) return;
        setOpenPos(pos.status === "OPEN" ? pos : null);
        return;
      }
      if (event.type === "signal") {
        const sig = asSignal(event.payload);
        if (!sig || sig.symbol !== symbol || sig.status === "SKIPPED") return;
        setSignalLevels(sig);
      }
    });
  }, [subscribe, symbol]);

  useEffect(() => {
    const ac = new AbortController();
    buyAcRef.current = ac;
    setBuyStatus(null);
    setBuying(false);
    return () => ac.abort();
  }, [symbol]);

  const candles = klines.symbol === symbol ? klines.candles : [];
  const offline = klines.symbol === symbol ? klines.offline : false;
  const price = tick?.symbol === symbol ? tick.price : null;

  const levels = useMemo(() => {
    const src = openPos ?? signalLevels;
    if (src == null) return undefined;
    return {
      entry: src.entry,
      stopLoss: src.stop_loss,
      takeProfit: src.take_profit,
      entryTime: openPos?.opened_at ?? signalLevels?.ts ?? null,
    };
  }, [openPos, signalLevels]);

  async function onBuy() {
    const quote_amount = Number(quote);
    if (!Number.isFinite(quote_amount) || quote_amount <= 0) {
      setBuyStatus({ kind: "err", text: "Quote USDT must be a positive number." });
      return;
    }

    const body: OrderRequest = { symbol, quote_amount };
    const slRaw = stopLoss.trim();
    const tpRaw = takeProfit.trim();
    if (slRaw !== "") {
      const sl = Number(slRaw);
      if (!Number.isFinite(sl) || sl <= 0) {
        setBuyStatus({ kind: "err", text: "Stop loss must be a positive number." });
        return;
      }
      body.stop_loss = sl;
    }
    if (tpRaw !== "") {
      const tp = Number(tpRaw);
      if (!Number.isFinite(tp) || tp <= 0) {
        setBuyStatus({ kind: "err", text: "Take profit must be a positive number." });
        return;
      }
      body.take_profit = tp;
    }

    setBuying(true);
    setBuyStatus(null);
    const result = await placeMarketBuy(body, buyAcRef.current?.signal);
    setBuying(false);
    if (result.aborted) return;
    if (result.data) {
      const fill = result.data;
      setBuyStatus({
        kind: "ok",
        text: `Filled ${fill.qty} ${fill.symbol} @ ${formatPx(fill.price)} · fee ${formatUsd(fill.fee)}. See Positions.`,
      });
      const posRes = await fetchPositions();
      if (Array.isArray(posRes.data)) {
        setOpenPos(posRes.data.find((p) => p.symbol === symbol && p.status === "OPEN") ?? null);
      }
      return;
    }
    if (result.offline) {
      setBuyStatus({ kind: "err", text: "API offline — order not sent." });
      return;
    }
    setBuyStatus({ kind: "err", text: result.error ?? "Order rejected." });
  }

  return (
    <section className="page terminal-page">
      <div className="terminal-bar">
        <div className="pair-switch">
          {SYMBOLS.map((pair) => (
            <button
              key={pair}
              type="button"
              className={symbol === pair ? "chip active" : "chip"}
              onClick={() => setSymbol(pair)}
            >
              {pair}
            </button>
          ))}
        </div>
        <div className="last-px">
          <span className="muted">LAST</span>
          <strong className={price == null ? "flat" : "pos"}>
            {price == null ? "—" : formatPx(price)}
          </strong>
          <span className="interval">1m</span>
        </div>
      </div>

      {offline && candles.length === 0 && (
        <div className="banner warn" role="status">
          API offline
        </div>
      )}

      <CandleChart
        key={symbol}
        candles={candles}
        livePrice={price}
        offline={offline}
        levels={levels}
      />

      <form
        className="buy-bar"
        onSubmit={(e) => {
          e.preventDefault();
          void onBuy();
        }}
      >
        <div className="buy-pair">
          <span className="stat-label">Market buy</span>
          <strong className="buy-symbol">{symbol}</strong>
        </div>
        <label className="buy-field">
          <span>Quote USDT</span>
          <input
            type="number"
            min="0"
            step="any"
            required
            value={quote}
            onChange={(e) => setQuote(e.target.value)}
            aria-label="Quote USDT"
          />
        </label>
        <label className="buy-field">
          <span>Stop loss</span>
          <input
            type="number"
            min="0"
            step="any"
            value={stopLoss}
            onChange={(e) => setStopLoss(e.target.value)}
            placeholder="optional"
            aria-label="Stop loss"
          />
        </label>
        <label className="buy-field">
          <span>Take profit</span>
          <input
            type="number"
            min="0"
            step="any"
            value={takeProfit}
            onChange={(e) => setTakeProfit(e.target.value)}
            placeholder="optional"
            aria-label="Take profit"
          />
        </label>
        <button type="submit" className="btn-buy" disabled={buying}>
          {buying ? "Buying…" : "Buy"}
        </button>
      </form>

      {buyStatus && (
        <div className={buyStatus.kind === "ok" ? "banner ok" : "banner danger"} role="status">
          {buyStatus.text}
        </div>
      )}
    </section>
  );
}
