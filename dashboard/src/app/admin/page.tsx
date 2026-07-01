"use client";

import { useEffect, useState } from "react";
import {
  getCollectorStatus,
  runCollector,
  getSchedules,
  pauseSchedules,
  resumeSchedules,
  type CollectorStatus,
  type ScheduleItem,
} from "@/lib/api";

const STATUS_COLORS: Record<string, string> = {
  success: "bg-green-100 text-green-800 border-green-200",
  failed: "bg-red-100 text-red-800 border-red-200",
  stale: "bg-orange-100 text-orange-800 border-orange-200",
  never_run: "bg-gray-100 text-gray-600 border-gray-200",
  unknown: "bg-gray-100 text-gray-600 border-gray-200",
};

export default function AdminPage() {
  const [statuses, setStatuses] = useState<CollectorStatus[]>([]);
  const [schedules, setSchedules] = useState<ScheduleItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [runningSource, setRunningSource] = useState<string | null>(null);

  const refresh = () => {
    setLoading(true);
    Promise.all([
      getCollectorStatus().catch(() => []),
      getSchedules().catch(() => []),
    ])
      .then(([s, sc]) => {
        setStatuses(s);
        setSchedules(sc);
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    refresh();
  }, []);

  const handleRun = async (source: string) => {
    setRunningSource(source);
    try {
      await runCollector(source);
      setTimeout(refresh, 2000);
    } finally {
      setRunningSource(null);
    }
  };

  const handlePause = async () => {
    await pauseSchedules();
    refresh();
  };

  const handleResume = async () => {
    await resumeSchedules();
    refresh();
  };

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Admin Monitor</h1>
        <button
          onClick={refresh}
          className="px-4 py-2 bg-white border border-gray-300 rounded-md text-sm hover:bg-gray-50"
        >
          Refresh
        </button>
      </div>

      {loading ? (
        <div className="text-center py-12 text-gray-500">Loading...</div>
      ) : (
        <>
          <section>
            <h2 className="text-lg font-semibold text-gray-800 mb-4">Collector Status</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {statuses.map((s) => (
                <div
                  key={s.source}
                  className={`p-4 rounded-lg border ${STATUS_COLORS[s.status] || STATUS_COLORS.unknown}`}
                >
                  <div className="flex justify-between items-start">
                    <div>
                      <h3 className="font-medium text-sm">{s.source}</h3>
                      <span className="text-xs font-semibold uppercase mt-1 inline-block">
                        {s.status}
                      </span>
                    </div>
                    <button
                      onClick={() => handleRun(s.source)}
                      disabled={runningSource === s.source}
                      className="px-3 py-1 text-xs bg-white border rounded hover:bg-gray-50 disabled:opacity-50"
                    >
                      {runningSource === s.source ? "Running..." : "Run"}
                    </button>
                  </div>
                  <div className="mt-2 text-xs space-y-1">
                    {s.last_success && (
                      <p>Last success: {new Date(s.last_success).toLocaleString()}</p>
                    )}
                    {s.last_attempt && (
                      <p>Last attempt: {new Date(s.last_attempt).toLocaleString()}</p>
                    )}
                    {s.retry_count > 0 && <p>Retries: {s.retry_count}</p>}
                    {s.error_message && (
                      <p className="text-red-600 truncate" title={s.error_message}>
                        Error: {s.error_message}
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold text-gray-800">Schedules</h2>
              <div className="flex gap-2">
                <button
                  onClick={handlePause}
                  className="px-3 py-1.5 text-sm bg-orange-50 border border-orange-200 text-orange-700 rounded hover:bg-orange-100"
                >
                  Pause All
                </button>
                <button
                  onClick={handleResume}
                  className="px-3 py-1.5 text-sm bg-green-50 border border-green-200 text-green-700 rounded hover:bg-green-100"
                >
                  Resume All
                </button>
              </div>
            </div>
            {schedules.length === 0 ? (
              <p className="text-sm text-gray-500">No schedules configured. Start the API server to see schedules.</p>
            ) : (
              <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 border-b">
                    <tr>
                      <th className="px-4 py-2 text-left font-medium text-gray-700">Source</th>
                      <th className="px-4 py-2 text-left font-medium text-gray-700">Type</th>
                      <th className="px-4 py-2 text-left font-medium text-gray-700">Schedule</th>
                      <th className="px-4 py-2 text-left font-medium text-gray-700">Next Run</th>
                      <th className="px-4 py-2 text-left font-medium text-gray-700">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {schedules.map((sc) => (
                      <tr key={sc.source}>
                        <td className="px-4 py-2 font-medium">{sc.source}</td>
                        <td className="px-4 py-2 text-gray-600">{sc.schedule_type}</td>
                        <td className="px-4 py-2 font-mono text-xs">{sc.cron_expression}</td>
                        <td className="px-4 py-2 text-gray-600">
                          {sc.next_run ? new Date(sc.next_run).toLocaleString() : "—"}
                        </td>
                        <td className="px-4 py-2">
                          <span
                            className={`px-2 py-0.5 rounded text-xs font-medium ${
                              sc.paused ? "bg-orange-100 text-orange-700" : "bg-green-100 text-green-700"
                            }`}
                          >
                            {sc.paused ? "Paused" : "Active"}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
