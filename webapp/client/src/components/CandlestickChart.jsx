import { useEffect, useRef } from "react";
import {
  createChart, CandlestickSeries, LineSeries, createSeriesMarkers,
} from "lightweight-charts";

export default function CandlestickChart({ candles, trades }) {
  const containerRef = useRef(null);
  const chartRef = useRef(null);

  useEffect(() => {
    if (!containerRef.current || !candles || candles.length === 0) return;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: 420,
      layout: { background: { color: "transparent" }, textColor: "#374151" },
      grid: {
        vertLines: { color: "#eef0f3" },
        horzLines: { color: "#eef0f3" },
      },
      timeScale: { borderColor: "#d1d5db" },
      rightPriceScale: { borderColor: "#d1d5db" },
    });
    chartRef.current = chart;

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#ef4444", downColor: "#10b981",
      borderVisible: false,
      wickUpColor: "#ef4444", wickDownColor: "#10b981",
    });
    // 国内习惯：红涨绿跌
    candleSeries.setData(
      candles.map((c) => ({
        time: c.date, open: c.open, high: c.high, low: c.low, close: c.close,
      }))
    );

    const fastSeries = chart.addSeries(LineSeries, {
      color: "#f59e0b", lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
    });
    fastSeries.setData(
      candles.filter((c) => c.ma_fast !== null).map((c) => ({ time: c.date, value: c.ma_fast }))
    );

    const slowSeries = chart.addSeries(LineSeries, {
      color: "#6366f1", lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
    });
    slowSeries.setData(
      candles.filter((c) => c.ma_slow !== null).map((c) => ({ time: c.date, value: c.ma_slow }))
    );

    if (trades && trades.length > 0) {
      const markers = trades.map((t) => ({
        time: t.date,
        position: t.action === "buy" ? "belowBar" : "aboveBar",
        color: t.action === "buy" ? "#ef4444" : "#10b981",
        shape: t.action === "buy" ? "arrowUp" : "arrowDown",
        text: t.action === "buy" ? "买" : "卖",
      }));
      createSeriesMarkers(candleSeries, markers);
    }

    chart.timeScale().fitContent();

    const handleResize = () => {
      chart.applyOptions({ width: containerRef.current.clientWidth });
    };
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
    };
  }, [candles, trades]);

  return (
    <div className="chart-panel">
      <h3>
        K线图 <span className="legend-fast">— 快线</span>{" "}
        <span className="legend-slow">— 慢线</span>
      </h3>
      <div ref={containerRef} />
    </div>
  );
}
