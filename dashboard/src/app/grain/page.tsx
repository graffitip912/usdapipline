"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { GrainChart, type ChartSeries } from "@/components/grain-chart";
import {
  getGrainPrices,
  getGrainSupply,
  getGrainInventory,
  getGtrIndices,
  getGrainAvailable,
  type GrainRecord,
  type DataAvailability,
} from "@/lib/api";

// USER-CONFIG: available commodities for filtering
const COMMODITIES = ["corn", "soybeans", "wheat"] as const;

// USER-CONFIG: date range presets (label, years back from today)
const DATE_RANGES = [
  { label: "1Y", years: 1 },
  { label: "3Y", years: 3 },
  { label: "5Y", years: 5 },
  { label: "10Y", years: 10 },
  { label: "All", years: 0 },
] as const;

const COMMODITY_COLORS: Record<string, string> = {
  corn: "#f59e0b",
  soybeans: "#10b981",
  wheat: "#6366f1",
};

const GTR_COLORS: Record<string, string> = {
  Truck: "#ef4444",
  Rail: "#3b82f6",
  Barge: "#10b981",
  "Gulf Ocean": "#f59e0b",
  Pacific: "#8b5cf6",
};

function dateNYearsAgo(n: number): string {
  const d = new Date();
  d.setFullYear(d.getFullYear() - n);
  return d.toISOString().slice(0, 10);
}

function pivotGtrData(records: GrainRecord[]): Record<string, unknown>[] {
  const byDate = new Map<string, Record<string, unknown>>();
  for (const r of records) {
    const key = r.obs_date;
    if (!byDate.has(key)) {
      byDate.set(key, { date: key });
    }
    const label = r.metric_label || r.metric;
    byDate.get(key)![label] = r.value;
  }
  return Array.from(byDate.values()).sort(
    (a, b) => String(a.date).localeCompare(String(b.date))
  );
}

function toSingleSeries(records: GrainRecord[]): Record<string, unknown>[] {
  return records.map((r) => ({
    date: r.obs_date,
    value: r.value,
  }));
}

function groupByMetric(records: GrainRecord[]): {
  data: Record<string, unknown>[];
  series: ChartSeries[];
} {
  const metricSet = new Set(records.map((r) => r.metric));
  if (metricSet.size <= 1) {
    return {
      data: toSingleSeries(records),
      series: [
        {
          key: "value",
          label: records[0]?.metric?.split("__").pop()?.replace(/_/g, " ") || "Value",
          color: "#3b82f6",
        },
      ],
    };
  }

  const colors = ["#3b82f6", "#ef4444", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899"];
  const metricList = Array.from(metricSet);
  const metricLabels = metricList.map(
    (m) => m.split("__").pop()?.replace(/_/g, " ") || m
  );

  const byDate = new Map<string, Record<string, unknown>>();
  for (const r of records) {
    if (!byDate.has(r.obs_date)) {
      byDate.set(r.obs_date, { date: r.obs_date });
    }
    const label = r.metric.split("__").pop()?.replace(/_/g, " ") || r.metric;
    byDate.get(r.obs_date)![label] = r.value;
  }

  return {
    data: Array.from(byDate.values()).sort((a, b) =>
      String(a.date).localeCompare(String(b.date))
    ),
    series: metricLabels.map((label, i) => ({
      key: label,
      label: label.charAt(0).toUpperCase() + label.slice(1),
      color: colors[i % colors.length],
    })),
  };
}

export default function GrainPage() {
  const [commodity, setCommodity] = useState<string>("corn");
  const [rangeIdx, setRangeIdx] = useState(2); // default 5Y
  const [showTable, setShowTable] = useState(false);

  const [prices, setPrices] = useState<GrainRecord[]>([]);
  const [supply, setSupply] = useState<GrainRecord[]>([]);
  const [inventory, setInventory] = useState<GrainRecord[]>([]);
  const [gtr, setGtr] = useState<GrainRecord[]>([]);
  const [availability, setAvailability] = useState<DataAvailability | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const dateRange = useMemo(() => {
    const r = DATE_RANGES[rangeIdx];
    if (r.years === 0) return undefined;
    return { from: dateNYearsAgo(r.years) };
  }, [rangeIdx]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [p, s, i, g, a] = await Promise.all([
        getGrainPrices(commodity, dateRange).catch(() => []),
        getGrainSupply(commodity, dateRange).catch(() => []),
        getGrainInventory(commodity, dateRange).catch(() => []),
        getGtrIndices(dateRange).catch(() => []),
        getGrainAvailable().catch(() => null),
      ]);
      setPrices(p);
      setSupply(s);
      setInventory(i);
      setGtr(g);
      setAvailability(a);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, [commodity, dateRange]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const cap = commodity.charAt(0).toUpperCase() + commodity.slice(1);
  const mainColor = COMMODITY_COLORS[commodity] || "#6366f1";
  const avail = availability?.commodities?.[commodity];

  const priceChart = useMemo(() => groupByMetric(prices), [prices]);
  const supplyChart = useMemo(() => groupByMetric(supply), [supply]);
  const inventoryChart = useMemo(() => groupByMetric(inventory), [inventory]);

  const gtrData = useMemo(() => pivotGtrData(gtr), [gtr]);
  const gtrSeries: ChartSeries[] = useMemo(() => {
    const labels = new Set(gtr.map((r) => r.metric_label || r.metric));
    return Array.from(labels).map((label) => ({
      key: label,
      label,
      color: GTR_COLORS[label] || "#6b7280",
    }));
  }, [gtr]);

  const allRecords = useMemo(
    () => [...prices, ...supply, ...inventory],
    [prices, supply, inventory]
  );

  return (
    <div className="space-y-6">
      {/* Header: commodity selector + date range + table toggle */}
      <div className="flex flex-wrap items-center gap-4">
        <h1 className="text-2xl font-bold text-gray-900 mr-auto">Grain Analysis</h1>

        <div className="flex gap-1 bg-gray-100 rounded-md p-1">
          {DATE_RANGES.map((r, idx) => (
            <button
              key={r.label}
              onClick={() => setRangeIdx(idx)}
              className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                rangeIdx === idx
                  ? "bg-white text-gray-900 shadow-sm"
                  : "text-gray-500 hover:text-gray-700"
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>

        <button
          onClick={() => setShowTable((v) => !v)}
          className={`px-3 py-1 rounded text-xs font-medium border transition-colors ${
            showTable
              ? "bg-gray-900 text-white border-gray-900"
              : "bg-white text-gray-600 border-gray-300 hover:bg-gray-50"
          }`}
        >
          {showTable ? "Hide Table" : "Show Table"}
        </button>

        <div className="flex gap-2">
          {COMMODITIES.map((c) => (
            <button
              key={c}
              onClick={() => setCommodity(c)}
              className={`px-4 py-2 rounded-md text-sm font-medium transition-colors capitalize ${
                commodity === c
                  ? "text-white"
                  : "bg-white border border-gray-300 text-gray-700 hover:bg-gray-50"
              }`}
              style={commodity === c ? { backgroundColor: COMMODITY_COLORS[c] } : undefined}
            >
              {c}
            </button>
          ))}
        </div>
      </div>

      {/* Availability info */}
      {avail && (
        <div className="flex gap-3 text-xs">
          {(["price", "supply", "stock"] as const).map((cat) => {
            const has = avail[`has_${cat}`];
            return (
              <span
                key={cat}
                className={`px-2 py-0.5 rounded-full ${
                  has ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-400"
                }`}
              >
                {cat.charAt(0).toUpperCase() + cat.slice(1)}: {has ? "Available" : "N/A"}
              </span>
            );
          })}
          {avail.date_range && (
            <span className="text-gray-400">
              Data: {avail.date_range[0]} ~ {avail.date_range[1]}
            </span>
          )}
        </div>
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-md p-4 text-red-700 text-sm">
          {error}
        </div>
      )}

      {loading ? (
        <div className="text-center py-12 text-gray-500">Loading data...</div>
      ) : (
        <>
          {/* Charts */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <GrainChart
              title={`${cap} — Price Trend`}
              data={priceChart.data}
              series={priceChart.series.map((s) => ({ ...s, color: mainColor }))}
              emptyMessage={`No price data for ${cap}`}
            />
            <GrainChart
              title={`${cap} — Supply & Production`}
              data={supplyChart.data}
              series={supplyChart.series}
            />
            <GrainChart
              title={`${cap} — Stocks (Beginning / Ending)`}
              data={inventoryChart.data}
              series={inventoryChart.series}
            />
            <GrainChart
              title="GTR Transportation Cost Index"
              data={gtrData}
              series={gtrSeries}
              emptyMessage="GTR index data not available"
            />
          </div>

          {/* Data Table */}
          {showTable && (
            <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
              <div className="px-4 py-3 border-b border-gray-200 bg-gray-50 flex items-center justify-between">
                <h3 className="text-sm font-semibold text-gray-700">
                  Raw Data — {cap} ({allRecords.length} records)
                </h3>
              </div>
              <div className="overflow-x-auto max-h-96 overflow-y-auto">
                <table className="min-w-full text-xs">
                  <thead className="bg-gray-50 sticky top-0">
                    <tr>
                      <th className="px-3 py-2 text-left font-medium text-gray-500">Date</th>
                      <th className="px-3 py-2 text-left font-medium text-gray-500">Metric</th>
                      <th className="px-3 py-2 text-right font-medium text-gray-500">Value</th>
                      <th className="px-3 py-2 text-left font-medium text-gray-500">Unit</th>
                      <th className="px-3 py-2 text-left font-medium text-gray-500">Source</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {allRecords.slice(0, 500).map((r, i) => (
                      <tr key={i} className="hover:bg-gray-50">
                        <td className="px-3 py-1.5 text-gray-600">{r.obs_date}</td>
                        <td className="px-3 py-1.5 text-gray-800 font-mono">
                          {r.metric.split("__").pop()?.replace(/_/g, " ")}
                        </td>
                        <td className="px-3 py-1.5 text-right tabular-nums text-gray-900">
                          {typeof r.value === "number"
                            ? r.value.toLocaleString(undefined, { maximumFractionDigits: 2 })
                            : r.value}
                        </td>
                        <td className="px-3 py-1.5 text-gray-500">{r.unit}</td>
                        <td className="px-3 py-1.5 text-gray-500">{r.source}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {allRecords.length > 500 && (
                  <div className="px-4 py-2 text-xs text-gray-400 text-center border-t">
                    Showing first 500 of {allRecords.length} records
                  </div>
                )}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
