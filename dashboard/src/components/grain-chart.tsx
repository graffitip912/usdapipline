"use client";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

export interface ChartSeries {
  key: string;
  label: string;
  color: string;
}

interface GrainChartProps {
  title: string;
  data: Record<string, unknown>[];
  series: ChartSeries[];
  xKey?: string;
  emptyMessage?: string;
}

export function GrainChart({
  title,
  data,
  series,
  xKey = "date",
  emptyMessage = "No data available",
}: GrainChartProps) {
  const hasData = data.length > 0 && series.length > 0;

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4">
      <h3 className="text-sm font-semibold text-gray-700 mb-3">{title}</h3>
      {hasData ? (
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
              <XAxis
                dataKey={xKey}
                tick={{ fontSize: 11 }}
                tickFormatter={(v: string) => {
                  if (!v) return "";
                  const d = new Date(v);
                  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
                }}
                minTickGap={40}
              />
              <YAxis tick={{ fontSize: 11 }} width={60} />
              <Tooltip
                labelFormatter={(v) => String(v)}
                formatter={(value, name) => [
                  typeof value === "number" ? value.toLocaleString(undefined, { maximumFractionDigits: 2 }) : String(value ?? ""),
                  String(name),
                ]}
              />
              <Legend />
              {series.map((s) => (
                <Line
                  key={s.key}
                  type="monotone"
                  dataKey={s.key}
                  name={s.label}
                  stroke={s.color}
                  dot={false}
                  strokeWidth={1.5}
                  connectNulls
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div className="h-72 flex items-center justify-center text-gray-400 text-sm">
          {emptyMessage}
        </div>
      )}
    </div>
  );
}
