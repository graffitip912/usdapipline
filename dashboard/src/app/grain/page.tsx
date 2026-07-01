"use client";

import { useEffect, useState } from "react";
import { GrainChart } from "@/components/grain-chart";
import { getGrainPrices, getGrainSupply, getGrainInventory, getGtrIndices, type GrainRecord } from "@/lib/api";

// USER-CONFIG: available commodities for filtering
const COMMODITIES = ["corn", "soybeans", "wheat"];

const COLORS: Record<string, string> = {
  corn: "#f59e0b",
  soybeans: "#10b981",
  wheat: "#6366f1",
};

export default function GrainPage() {
  const [commodity, setCommodity] = useState("corn");
  const [prices, setPrices] = useState<GrainRecord[]>([]);
  const [supply, setSupply] = useState<GrainRecord[]>([]);
  const [inventory, setInventory] = useState<GrainRecord[]>([]);
  const [gtr, setGtr] = useState<GrainRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    Promise.all([
      getGrainPrices(commodity).catch(() => []),
      getGrainSupply(commodity).catch(() => []),
      getGrainInventory(commodity).catch(() => []),
      getGtrIndices().catch(() => []),
    ])
      .then(([p, s, i, g]) => {
        setPrices(p);
        setSupply(s);
        setInventory(i);
        setGtr(g);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [commodity]);

  const toChart = (data: GrainRecord[], label: string) => ({
    labels: data.map((d) => d.obs_date),
    datasets: [
      {
        label,
        data: data.map((d) => d.value),
        borderColor: COLORS[commodity] || "#6366f1",
      },
    ],
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Grain Analysis</h1>
        <div className="flex gap-2">
          {COMMODITIES.map((c) => (
            <button
              key={c}
              onClick={() => setCommodity(c)}
              className={`px-4 py-2 rounded-md text-sm font-medium transition-colors capitalize ${
                commodity === c
                  ? "bg-blue-600 text-white"
                  : "bg-white border border-gray-300 text-gray-700 hover:bg-gray-50"
              }`}
            >
              {c}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-md p-4 text-red-700 text-sm">
          {error}
        </div>
      )}

      {loading ? (
        <div className="text-center py-12 text-gray-500">Loading data...</div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <GrainChart
            title={`${commodity.charAt(0).toUpperCase() + commodity.slice(1)} — Price Trend`}
            {...toChart(prices, "Price")}
          />
          <GrainChart
            title={`${commodity.charAt(0).toUpperCase() + commodity.slice(1)} — Supply`}
            {...toChart(supply, "Supply")}
          />
          <GrainChart
            title={`${commodity.charAt(0).toUpperCase() + commodity.slice(1)} — Inventory`}
            {...toChart(inventory, "Inventory")}
          />
          <GrainChart
            title="GTR Transportation Index"
            labels={gtr.map((d) => d.obs_date)}
            datasets={[{ label: "GTR Index", data: gtr.map((d) => d.value), borderColor: "#ef4444" }]}
          />
        </div>
      )}
    </div>
  );
}
