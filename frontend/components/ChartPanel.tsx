"use client";

import { useEffect, useRef } from "react";
import { ColorType, createChart } from "lightweight-charts";
import type { ChartBar } from "@/lib/types";

export function ChartPanel({ bars }: { bars: ChartBar[] }) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || bars.length === 0) return;

    const chart = createChart(container, {
      autoSize: true,
      height: 420,
      layout: {
        background: { type: ColorType.Solid, color: "#ffffff" },
        textColor: "#1f2937"
      },
      grid: {
        vertLines: { color: "#eef2f7" },
        horzLines: { color: "#eef2f7" }
      },
      rightPriceScale: {
        borderColor: "#d7dde8",
        scaleMargins: { top: 0.08, bottom: 0.24 }
      },
      timeScale: {
        borderColor: "#d7dde8",
        timeVisible: false
      },
      crosshair: {
        mode: 1
      }
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: "#0f9f6e",
      downColor: "#d64545",
      borderUpColor: "#0f9f6e",
      borderDownColor: "#d64545",
      wickUpColor: "#0f9f6e",
      wickDownColor: "#d64545"
    });

    const volumeSeries = chart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
      color: "#9aa7bd"
    });
    chart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.78, bottom: 0 }
    });

    const ma5 = chart.addLineSeries({ color: "#2563eb", lineWidth: 1, priceLineVisible: false });
    const ma25 = chart.addLineSeries({ color: "#f59e0b", lineWidth: 1, priceLineVisible: false });
    const ma75 = chart.addLineSeries({ color: "#7c3aed", lineWidth: 1, priceLineVisible: false });

    candleSeries.setData(
      bars
        .filter((bar) => bar.open !== null && bar.high !== null && bar.low !== null && bar.close !== null)
        .map((bar) => ({
          time: bar.date,
          open: Number(bar.open),
          high: Number(bar.high),
          low: Number(bar.low),
          close: Number(bar.close)
        }))
    );
    volumeSeries.setData(
      bars
        .filter((bar) => bar.volume !== null)
        .map((bar) => ({
          time: bar.date,
          value: Number(bar.volume),
          color: Number(bar.close ?? 0) >= Number(bar.open ?? 0) ? "rgba(15, 159, 110, 0.35)" : "rgba(214, 69, 69, 0.35)"
        }))
    );
    ma5.setData(bars.filter((bar) => bar.ma_5 !== null && bar.ma_5 !== undefined).map((bar) => ({ time: bar.date, value: Number(bar.ma_5) })));
    ma25.setData(bars.filter((bar) => bar.ma_25 !== null && bar.ma_25 !== undefined).map((bar) => ({ time: bar.date, value: Number(bar.ma_25) })));
    ma75.setData(bars.filter((bar) => bar.ma_75 !== null && bar.ma_75 !== undefined).map((bar) => ({ time: bar.date, value: Number(bar.ma_75) })));
    chart.timeScale().fitContent();

    return () => {
      chart.remove();
    };
  }, [bars]);

  if (bars.length === 0) {
    return <div className="chart-empty">価格データなし</div>;
  }

  return (
    <div className="chart-wrap">
      <div className="chart-legend">
        <span className="legend-item ma5">MA5</span>
        <span className="legend-item ma25">MA25</span>
        <span className="legend-item ma75">MA75</span>
        <span className="legend-item volume">Volume</span>
      </div>
      <div ref={containerRef} className="chart-container" />
    </div>
  );
}
