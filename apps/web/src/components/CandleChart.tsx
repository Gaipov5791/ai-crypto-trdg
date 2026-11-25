import { useEffect, useRef } from "react";
import {
  CandlestickSeries,
  ColorType,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type CandlestickData,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import type { Candle } from "../types";

const BG = "#0b0d12";
const GRID = "#1a2030";
const TEXT = "#8b9bb4";
const UP = "#3dd68c";
const DOWN = "#f0616d";
const ENTRY = "#e8c547";
const SL = "#f0616d";
const TP = "#3dd68c";

export type ChartLevels = {
  entry?: number | null;
  stopLoss?: number | null;
  takeProfit?: number | null;
  entryTime?: number | null;
};

type Props = {
  candles: Candle[];
  livePrice?: number | null;
  offline?: boolean;
  levels?: ChartLevels;
};

function toUnix(openTime: number): UTCTimestamp {
  const sec = openTime > 1e12 ? Math.floor(openTime / 1000) : Math.floor(openTime);
  return sec as UTCTimestamp;
}

function toBars(candles: Candle[]): CandlestickData<UTCTimestamp>[] {
  const map = new Map<number, CandlestickData<UTCTimestamp>>();
  for (const c of candles) {
    if (!Number.isFinite(c.open_time) || !Number.isFinite(c.close)) continue;
    const time = toUnix(c.open_time);
    const high = Math.max(c.high, c.open, c.close, c.low);
    const low = Math.min(c.low, c.open, c.close, c.high);
    map.set(time, { time, open: c.open, high, low, close: c.close });
  }
  return [...map.values()].sort((a, b) => (a.time as number) - (b.time as number));
}

function nearestBarTime(ms: number, candles: Candle[]): UTCTimestamp | null {
  const sec = Math.floor(ms > 1e12 ? ms / 1000 : ms);
  let best: number | null = null;
  for (const c of candles) {
    const t = toUnix(c.open_time) as number;
    if (t <= sec) best = t;
  }
  return best == null ? null : (best as UTCTimestamp);
}

export default function CandleChart({ candles, livePrice, offline, levels }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const lastBarRef = useRef<CandlestickData<UTCTimestamp> | null>(null);
  const linesRef = useRef<IPriceLine[]>([]);
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);

  useEffect(() => {
    const el = hostRef.current;
    if (!el) return;

    const chart = createChart(el, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: BG },
        textColor: TEXT,
        fontFamily: '"Cascadia Code", "Consolas", ui-monospace, monospace',
      },
      grid: {
        vertLines: { color: GRID },
        horzLines: { color: GRID },
      },
      crosshair: {
        vertLine: { color: "#3d4a63", width: 1, style: 3, labelBackgroundColor: "#1a2233" },
        horzLine: { color: "#3d4a63", width: 1, style: 3, labelBackgroundColor: "#1a2233" },
      },
      rightPriceScale: { borderColor: GRID },
      timeScale: {
        borderColor: GRID,
        timeVisible: true,
        secondsVisible: false,
      },
    });

    const series = chart.addSeries(CandlestickSeries, {
      upColor: UP,
      downColor: DOWN,
      borderVisible: false,
      wickUpColor: UP,
      wickDownColor: DOWN,
    });

    chartRef.current = chart;
    seriesRef.current = series;
    markersRef.current = createSeriesMarkers(series, []);

    return () => {
      markersRef.current = null;
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      lastBarRef.current = null;
      linesRef.current = [];
    };
  }, []);

  useEffect(() => {
    const series = seriesRef.current;
    const chart = chartRef.current;
    if (!series || !chart) return;

    const bars = toBars(candles);
    lastBarRef.current = bars.at(-1) ?? null;
    series.setData(bars);
    if (bars.length > 0) {
      chart.timeScale().fitContent();
    }
  }, [candles]);

  useEffect(() => {
    const series = seriesRef.current;
    const last = lastBarRef.current;
    if (!series || !last || livePrice == null || !Number.isFinite(livePrice)) return;

    const next: CandlestickData<UTCTimestamp> = {
      ...last,
      close: livePrice,
      high: Math.max(last.high, livePrice),
      low: Math.min(last.low, livePrice),
    };
    lastBarRef.current = next;
    series.update(next);
  }, [livePrice]);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;

    for (const line of linesRef.current) {
      series.removePriceLine(line);
    }
    linesRef.current = [];

    const add = (price: number | null | undefined, color: string, title: string, style: LineStyle) => {
      if (price == null || !Number.isFinite(price) || price <= 0) return;
      linesRef.current.push(
        series.createPriceLine({
          price,
          color,
          lineWidth: 1,
          lineStyle: style,
          axisLabelVisible: true,
          title,
        }),
      );
    };

    add(levels?.entry, ENTRY, "ENTRY", LineStyle.Solid);
    add(levels?.stopLoss, SL, "SL", LineStyle.Dashed);
    add(levels?.takeProfit, TP, "TP", LineStyle.Dashed);

    const markers: SeriesMarker<Time>[] = [];
    if (levels?.entryTime != null) {
      const time = nearestBarTime(levels.entryTime, candles);
      if (time != null) {
        markers.push({
          time,
          position: "belowBar",
          color: ENTRY,
          shape: "arrowUp",
          text: "BUY",
        });
      }
    }
    markersRef.current?.setMarkers(markers);
  }, [levels, candles]);

  const empty = candles.length === 0;
  const hasLevels =
    (levels?.entry != null && levels.entry > 0) ||
    (levels?.stopLoss != null && levels.stopLoss > 0) ||
    (levels?.takeProfit != null && levels.takeProfit > 0);

  return (
    <div className="chart-wrap">
      <div className="chart-host" ref={hostRef} />
      {hasLevels && (
        <div className="chart-legend" aria-hidden>
          {levels?.entry != null && (
            <span>
              <i className="swatch entry" />
              ENTRY
            </span>
          )}
          {levels?.stopLoss != null && (
            <span>
              <i className="swatch sl" />
              SL
            </span>
          )}
          {levels?.takeProfit != null && (
            <span>
              <i className="swatch tp" />
              TP
            </span>
          )}
        </div>
      )}
      {empty && (
        <div className="chart-empty">
          <span className="chart-empty-title">NO MARKET DATA</span>
          <span className="muted">
            {offline ? "API offline — empty chart" : "Waiting for 1m klines"}
          </span>
        </div>
      )}
    </div>
  );
}
