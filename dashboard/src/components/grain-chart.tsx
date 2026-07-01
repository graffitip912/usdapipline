"use client";

import { useEffect, useRef } from "react";
import { Chart, registerables } from "chart.js";

Chart.register(...registerables);

interface GrainChartProps {
  title: string;
  labels: string[];
  datasets: {
    label: string;
    data: number[];
    borderColor: string;
    backgroundColor?: string;
  }[];
}

export function GrainChart({ title, labels, datasets }: GrainChartProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const chartRef = useRef<Chart | null>(null);

  useEffect(() => {
    if (!canvasRef.current) return;

    if (chartRef.current) {
      chartRef.current.destroy();
    }

    chartRef.current = new Chart(canvasRef.current, {
      type: "line",
      data: {
        labels,
        datasets: datasets.map((ds) => ({
          ...ds,
          fill: false,
          tension: 0.1,
          pointRadius: 1,
        })),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          title: { display: true, text: title },
          legend: { position: "top" },
        },
        scales: {
          x: { display: true, title: { display: true, text: "Date" } },
          y: { display: true, title: { display: true, text: "Value" } },
        },
      },
    });

    return () => {
      chartRef.current?.destroy();
    };
  }, [title, labels, datasets]);

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4">
      <div className="h-80">
        <canvas ref={canvasRef} />
      </div>
    </div>
  );
}
