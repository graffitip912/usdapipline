"use client";

import { useEffect, useState } from "react";
import {
  getCollectorStatus,
  runCollector,
  getSchedules,
  pauseSchedules,
  resumeSchedules,
  getVerificationHistory,
  getChangeRequests,
  getDataPreview,
  resolveVerificationHistory,
  submitReview,
  createChangeRequest,
  applyChangeRequest,
  reCollect,
  verifyChangeRequest,
  type CollectorStatus,
  type DataPreview,
  type ScheduleItem,
  type VerificationHistory,
  type ChangeRequest,
} from "@/lib/api";

const STATUS_COLORS: Record<string, string> = {
  collecting: "bg-blue-50 text-blue-800 border-blue-300",
  success: "bg-green-100 text-green-800 border-green-200",
  failed: "bg-red-100 text-red-800 border-red-200",
  stale: "bg-orange-100 text-orange-800 border-orange-200",
  skipped: "bg-violet-50 text-violet-800 border-violet-200",
  never_run: "bg-gray-100 text-gray-600 border-gray-200",
  unknown: "bg-gray-100 text-gray-600 border-gray-200",
};

// 수집 상태 배지 — 검증 상태(pill)와 구분되는 진한 단색
const STATUS_BADGE: Record<string, string> = {
  collecting: "bg-blue-600 text-white",
  success: "bg-green-600 text-white",
  failed: "bg-red-600 text-white",
  stale: "bg-orange-500 text-white",
  skipped: "bg-violet-500 text-white",
  never_run: "bg-gray-400 text-white",
  unknown: "bg-gray-400 text-white",
};

const VERIFICATION_COLORS: Record<string, string> = {
  approved: "bg-green-50 text-green-700",
  change_requested: "bg-yellow-50 text-yellow-700",
  pending_review: "bg-blue-50 text-blue-700",
  rejected: "bg-red-50 text-red-700",
  not_verified: "bg-gray-50 text-gray-500",
};

export default function AdminPage() {
  const [statuses, setStatuses] = useState<CollectorStatus[]>([]);
  const [schedules, setSchedules] = useState<ScheduleItem[]>([]);
  const [vHistory, setVHistory] = useState<VerificationHistory[]>([]);
  const [changeReqs, setChangeReqs] = useState<ChangeRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [runningSource, setRunningSource] = useState<string | null>(null);
  const [reviewSource, setReviewSource] = useState<string | null>(null);
  const [reviewRemarks, setReviewRemarks] = useState("");
  const [crForm, setCrForm] = useState({ source: "", type: "content", description: "" });
  const [showCrForm, setShowCrForm] = useState(false);
  const [expandedHistory, setExpandedHistory] = useState<string | null>(null);
  const [banner, setBanner] = useState<{ kind: "info" | "error"; text: string } | null>(null);
  const [preview, setPreview] = useState<DataPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState<string | null>(null);
  // 실행 중인 수집: source -> Run 시점의 last_attempt (변하면 완료로 판정)
  const [collecting, setCollecting] = useState<Record<string, string | null>>({});
  const [resolveNote, setResolveNote] = useState("");

  const openPreview = async (source: string) => {
    setPreviewLoading(source);
    try {
      setPreview(await getDataPreview(source));
    } catch {
      setBanner({
        kind: "info",
        text: `${source}: 정규화 데이터 없음 — 원시 PDF/이미지 수집기이거나 아직 수집 전입니다.`,
      });
    } finally {
      setPreviewLoading(null);
    }
  };

  const refresh = () => {
    setLoading(true);
    Promise.all([
      getCollectorStatus().catch(() => []),
      getSchedules().catch(() => []),
      getVerificationHistory().catch(() => []),
      getChangeRequests().catch(() => []),
    ])
      .then(([s, sc, vh, cr]) => {
        setStatuses(s);
        setSchedules(sc);
        setVHistory(vh);
        setChangeReqs(cr);
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    refresh();
  }, []);

  // 수집 진행 폴링: collecting에 항목이 있는 동안 5초마다 상태 조회,
  // last_attempt가 Run 시점과 달라지면 완료로 판정
  useEffect(() => {
    if (Object.keys(collecting).length === 0) return;
    const iv = setInterval(async () => {
      const s = await getCollectorStatus().catch(() => null);
      if (!s) return;
      setStatuses(s);
      const done = Object.entries(collecting)
        .filter(([src, baseline]) => {
          const cur = s.find((x) => x.source === src);
          return cur && cur.last_attempt !== baseline;
        })
        .map(([src]) => src);
      if (done.length > 0) {
        setCollecting((prev) => {
          const next = { ...prev };
          done.forEach((d) => delete next[d]);
          return next;
        });
        const results = done
          .map((d) => `${d}: ${s.find((x) => x.source === d)?.status ?? "?"}`)
          .join(", ");
        setBanner({ kind: "info", text: `수집 완료 — ${results}` });
      }
    }, 5000);
    return () => clearInterval(iv);
  }, [collecting]);

  const handleRun = async (source: string) => {
    setRunningSource(source);
    setBanner(null);
    try {
      const res = await runCollector(source);
      if (res.status === "error") {
        setBanner({ kind: "error", text: `${source}: ${res.message}` });
        return;
      }
      const baseline = statuses.find((x) => x.source === source)?.last_attempt ?? null;
      setCollecting((prev) => ({ ...prev, [source]: baseline }));
      setBanner({ kind: "info", text: `${source} 수집이 시작되었습니다 — 완료 시 자동으로 알려드립니다.` });
    } catch (e) {
      setBanner({ kind: "error", text: `${source} 실행 요청 실패: ${e instanceof Error ? e.message : String(e)}` });
    } finally {
      setRunningSource(null);
    }
  };

  const handlePause = async () => {
    try {
      await pauseSchedules();
      refresh();
    } catch (e) {
      setBanner({ kind: "error", text: `일시정지 실패: ${e instanceof Error ? e.message : String(e)}` });
    }
  };

  const handleResume = async () => {
    try {
      await resumeSchedules();
      refresh();
    } catch (e) {
      setBanner({ kind: "error", text: `재개 실패: ${e instanceof Error ? e.message : String(e)}` });
    }
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

      {banner && (
        <div
          className={`px-4 py-2.5 rounded-md text-sm border flex items-start justify-between gap-3 ${
            banner.kind === "error"
              ? "bg-red-50 border-red-200 text-red-700"
              : "bg-blue-50 border-blue-200 text-blue-700"
          }`}
        >
          <span>{banner.text}</span>
          <button onClick={() => setBanner(null)} className="text-xs opacity-60 hover:opacity-100 shrink-0">
            닫기
          </button>
        </div>
      )}

      {loading ? (
        <div className="text-center py-12 text-gray-500">Loading...</div>
      ) : (
        <>
          <section>
            <h2 className="text-lg font-semibold text-gray-800 mb-4">Collector Status</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {statuses.map((s) => {
                const isCollecting = s.source in collecting;
                const displayStatus = isCollecting ? "collecting" : s.status;
                return (
                <div
                  key={s.source}
                  className={`p-4 rounded-lg border ${STATUS_COLORS[displayStatus] || STATUS_COLORS.unknown}`}
                >
                  <div className="flex justify-between items-start">
                    <div>
                      <h3 className="font-medium text-sm">{s.source}</h3>
                      <span className={`mt-1 inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold uppercase ${STATUS_BADGE[displayStatus] || STATUS_BADGE.unknown}`}>
                        {isCollecting && (
                          <span className="inline-block w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />
                        )}
                        {isCollecting ? "collecting" : s.status}
                      </span>
                    </div>
                    <button
                      onClick={() => handleRun(s.source)}
                      disabled={runningSource === s.source || isCollecting}
                      className="px-3 py-1 text-xs bg-white border rounded hover:bg-gray-50 disabled:opacity-50"
                    >
                      {isCollecting ? "수집 중..." : runningSource === s.source ? "요청 중..." : "Run"}
                    </button>
                  </div>
                  <div className="mt-2 text-xs space-y-1">
                    {s.last_success && (
                      <p>Last success: {new Date(s.last_success).toLocaleString()}</p>
                    )}
                    {s.last_attempt && (
                      <p>Last attempt: {new Date(s.last_attempt).toLocaleString()}</p>
                    )}
                    {s.retry_count > 0 && (
                      <p className="text-orange-700 font-medium">Retries: {s.retry_count}</p>
                    )}
                    {s.error_message && (
                      <p className="text-red-600 truncate" title={s.error_message}>
                        Error: {s.error_message}
                      </p>
                    )}
                    {s.verification_status && (
                      <p className="mt-1 flex flex-wrap items-center gap-1">
                        <span className={`px-1.5 py-0.5 rounded text-xs ${VERIFICATION_COLORS[s.verification_status] || VERIFICATION_COLORS.not_verified}`}>
                          {s.verification_status}
                        </span>
                        {(s.unresolved_failures ?? 0) > 0 && (
                          <span className="px-1.5 py-0.5 rounded text-xs bg-red-100 text-red-700 font-medium">
                            검증실패 {s.unresolved_failures}건
                          </span>
                        )}
                        {(s.open_change_requests ?? 0) > 0 && (
                          <span className="text-yellow-600">{s.open_change_requests} CR open</span>
                        )}
                      </p>
                    )}
                    {s.last_verification_failure && (
                      <p className="text-orange-600 truncate" title={s.last_verification_failure}>
                        Verify: {s.last_verification_failure}
                      </p>
                    )}
                  </div>
                </div>
                );
              })}
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

          {/* Verification History (AC-5: as-is → to-be) */}
          <section>
            <h2 className="text-lg font-semibold text-gray-800 mb-4">Verification History</h2>
            {vHistory.length === 0 ? (
              <p className="text-sm text-gray-500">No verification history yet.</p>
            ) : (
              <div className="bg-white rounded-lg border border-gray-200 overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 border-b">
                    <tr>
                      <th className="px-4 py-2 text-left font-medium text-gray-700">Source</th>
                      <th className="px-4 py-2 text-left font-medium text-gray-700">Failed At</th>
                      <th className="px-4 py-2 text-left font-medium text-gray-700">Reason</th>
                      <th className="px-4 py-2 text-left font-medium text-gray-700">As-Is</th>
                      <th className="px-4 py-2 text-left font-medium text-gray-700">To-Be</th>
                      <th className="px-4 py-2 text-left font-medium text-gray-700">Resolution</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {vHistory.slice(0, 20).map((h) => (
                      <tr
                        key={h.history_id}
                        className="cursor-pointer hover:bg-gray-50"
                        onClick={() => setExpandedHistory(expandedHistory === h.history_id ? null : h.history_id)}
                      >
                        <td className="px-4 py-2 font-medium">{h.source}</td>
                        <td className="px-4 py-2 text-gray-600 text-xs">
                          {new Date(h.failed_at).toLocaleString()}
                        </td>
                        <td className="px-4 py-2 text-red-600 text-xs max-w-48 truncate" title={h.failure_reason}>
                          {h.failure_reason}
                        </td>
                        <td className="px-4 py-2 text-xs font-mono max-w-32">
                          {Object.keys(h.as_is).length > 0
                            ? Object.entries(h.as_is).slice(0, 2).map(([k]) => k).join(", ") +
                              (Object.keys(h.as_is).length > 2 ? ` +${Object.keys(h.as_is).length - 2}` : "")
                            : "—"}
                        </td>
                        <td className="px-4 py-2 text-xs font-mono max-w-32">
                          {h.to_be && Object.keys(h.to_be).length > 0
                            ? Object.entries(h.to_be).slice(0, 2).map(([k]) => k).join(", ") +
                              (Object.keys(h.to_be).length > 2 ? ` +${Object.keys(h.to_be).length - 2}` : "")
                            : "—"}
                        </td>
                        <td className="px-4 py-2 text-xs">
                          <span className={h.resolved_at ? "text-green-700" : "text-orange-600"}>
                            {h.resolution_method || (h.resolved_at ? "resolved" : "unresolved")}
                          </span>
                          {h.linked_change_request && (
                            <span className="ml-1 text-blue-500" title={`CR: ${h.linked_change_request}`}>
                              CR
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {expandedHistory && vHistory.find((h) => h.history_id === expandedHistory) && (() => {
                  const h = vHistory.find((h) => h.history_id === expandedHistory)!;
                  return (
                    <div className="border-t border-gray-200 p-4 bg-gray-50">
                      <div className="flex items-center justify-between mb-3">
                        <span className="text-xs font-semibold text-gray-500 uppercase">
                          Detail — {h.source} ({h.history_id})
                        </span>
                        {h.linked_change_request && (
                          <span className="text-xs text-blue-600">
                            Linked CR: {h.linked_change_request}
                          </span>
                        )}
                      </div>
                      <p className="text-sm text-red-600 mb-3">{h.failure_reason}</p>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div>
                          <h4 className="text-xs font-semibold text-gray-500 uppercase mb-2">As-Is</h4>
                          {Object.keys(h.as_is).length > 0 ? (
                            <dl className="space-y-1">
                              {Object.entries(h.as_is).map(([k, v]) => (
                                <div key={k} className="flex text-xs">
                                  <dt className="font-medium text-gray-700 w-32 shrink-0">{k}</dt>
                                  <dd className="text-gray-600 font-mono break-all">{String(v)}</dd>
                                </div>
                              ))}
                            </dl>
                          ) : (
                            <p className="text-xs text-gray-400">No data</p>
                          )}
                        </div>
                        <div>
                          <h4 className="text-xs font-semibold text-gray-500 uppercase mb-2">To-Be</h4>
                          {h.to_be && Object.keys(h.to_be).length > 0 ? (
                            <dl className="space-y-1">
                              {Object.entries(h.to_be).map(([k, v]) => (
                                <div key={k} className="flex text-xs">
                                  <dt className="font-medium text-gray-700 w-32 shrink-0">{k}</dt>
                                  <dd className="text-green-700 font-mono break-all">{String(v)}</dd>
                                </div>
                              ))}
                            </dl>
                          ) : (
                            <p className="text-xs text-gray-400">Not resolved yet</p>
                          )}
                        </div>
                      </div>
                      {h.resolved_at ? (
                        <p className="mt-3 text-xs text-gray-500">
                          Resolved: {new Date(h.resolved_at).toLocaleString()}
                          {h.resolution_method && ` — ${h.resolution_method}`}
                        </p>
                      ) : (
                        <div className="mt-3 flex gap-2 items-center">
                          <input
                            value={resolveNote}
                            onChange={(e) => setResolveNote(e.target.value)}
                            placeholder="해결 방법/내용 (예: 의존성 설치 후 재실행 확인)"
                            className="flex-1 px-2 py-1.5 border border-gray-300 rounded text-xs"
                          />
                          <button
                            onClick={async () => {
                              if (!resolveNote.trim()) {
                                setBanner({ kind: "error", text: "해결 내용을 입력해야 합니다." });
                                return;
                              }
                              try {
                                await resolveVerificationHistory(
                                  h.history_id,
                                  { note: resolveNote.trim() },
                                  "manual_resolution",
                                );
                                setResolveNote("");
                                setExpandedHistory(null);
                                setBanner({ kind: "info", text: `이력 ${h.history_id} 해결 처리되었습니다.` });
                                refresh();
                              } catch (e) {
                                setBanner({ kind: "error", text: `해결 처리 실패: ${e instanceof Error ? e.message : String(e)}` });
                              }
                            }}
                            className="px-3 py-1.5 text-xs bg-green-600 text-white rounded hover:bg-green-700 shrink-0"
                          >
                            해결 처리
                          </button>
                        </div>
                      )}
                    </div>
                  );
                })()}
              </div>
            )}
          </section>

          {/* Change Requests (AC-6) */}
          <section>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold text-gray-800">Change Requests</h2>
              <button
                onClick={() => setShowCrForm(!showCrForm)}
                className="px-3 py-1.5 text-sm bg-blue-50 border border-blue-200 text-blue-700 rounded hover:bg-blue-100"
              >
                {showCrForm ? "Cancel" : "New Request"}
              </button>
            </div>

            {showCrForm && (
              <div className="bg-white p-4 rounded-lg border border-blue-200 mb-4 space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs font-medium text-gray-700 mb-1">Source</label>
                    <select
                      value={crForm.source}
                      onChange={(e) => setCrForm({ ...crForm, source: e.target.value })}
                      className="w-full px-2 py-1.5 border rounded text-sm"
                    >
                      <option value="">Select source</option>
                      {statuses.map((s) => (
                        <option key={s.source} value={s.source}>{s.source}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-700 mb-1">Type</label>
                    <select
                      value={crForm.type}
                      onChange={(e) => setCrForm({ ...crForm, type: e.target.value })}
                      className="w-full px-2 py-1.5 border rounded text-sm"
                    >
                      <option value="content">Content</option>
                      <option value="method">Method</option>
                      <option value="schema">Schema</option>
                      <option value="schedule">Schedule</option>
                    </select>
                  </div>
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Description</label>
                  <textarea
                    value={crForm.description}
                    onChange={(e) => setCrForm({ ...crForm, description: e.target.value })}
                    className="w-full px-2 py-1.5 border rounded text-sm"
                    rows={2}
                  />
                </div>
                <button
                  onClick={async () => {
                    if (!crForm.source || !crForm.description) return;
                    try {
                      await createChangeRequest({
                        target_source: crForm.source,
                        change_type: crForm.type,
                        description: crForm.description,
                      });
                      setCrForm({ source: "", type: "content", description: "" });
                      setShowCrForm(false);
                      refresh();
                    } catch (e) {
                      setBanner({ kind: "error", text: `변경 요청 생성 실패: ${e instanceof Error ? e.message : String(e)}` });
                    }
                  }}
                  className="px-4 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-700"
                >
                  Submit
                </button>
              </div>
            )}

            {changeReqs.length === 0 ? (
              <p className="text-sm text-gray-500">No change requests.</p>
            ) : (
              <div className="space-y-3">
                {changeReqs.slice(0, 20).map((cr) => (
                  <div key={cr.request_id} className="bg-white p-4 rounded-lg border border-gray-200">
                    <div className="flex items-start justify-between">
                      <div>
                        <span className="font-medium text-sm">{cr.target_source}</span>
                        <span className="ml-2 text-xs text-gray-500">{cr.change_type}</span>
                        <span className={`ml-2 px-2 py-0.5 rounded text-xs font-medium ${
                          cr.status === "verified" ? "bg-green-100 text-green-700" :
                          cr.status === "rejected" ? "bg-red-100 text-red-700" :
                          cr.status === "applied" ? "bg-blue-100 text-blue-700" :
                          "bg-yellow-100 text-yellow-700"
                        }`}>
                          {cr.status}
                        </span>
                      </div>
                      <div className="flex gap-2">
                        {cr.status === "pending" && (
                          <button
                            onClick={async () => {
                              try { await applyChangeRequest(cr.request_id); refresh(); }
                              catch (e) { setBanner({ kind: "error", text: `Apply 실패: ${e instanceof Error ? e.message : String(e)}` }); }
                            }}
                            className="px-2 py-1 text-xs bg-blue-50 border border-blue-200 text-blue-700 rounded hover:bg-blue-100"
                          >
                            Apply
                          </button>
                        )}
                        {cr.status === "applied" && (
                          <>
                            <button
                              onClick={async () => {
                                try { await reCollect(cr.request_id); refresh(); }
                                catch (e) { setBanner({ kind: "error", text: `Re-collect 실패: ${e instanceof Error ? e.message : String(e)}` }); }
                              }}
                              className="px-2 py-1 text-xs bg-green-50 border border-green-200 text-green-700 rounded hover:bg-green-100"
                            >
                              Re-collect
                            </button>
                            <button
                              onClick={async () => {
                                try { await verifyChangeRequest(cr.request_id, { user_verdict: "verified" }); refresh(); }
                                catch (e) { setBanner({ kind: "error", text: `Verify 실패: ${e instanceof Error ? e.message : String(e)}` }); }
                              }}
                              className="px-2 py-1 text-xs bg-green-50 border border-green-200 text-green-700 rounded hover:bg-green-100"
                            >
                              Verify
                            </button>
                            <button
                              onClick={async () => {
                                try { await verifyChangeRequest(cr.request_id, { user_verdict: "rejected" }); refresh(); }
                                catch (e) { setBanner({ kind: "error", text: `Reject 실패: ${e instanceof Error ? e.message : String(e)}` }); }
                              }}
                              className="px-2 py-1 text-xs bg-red-50 border border-red-200 text-red-700 rounded hover:bg-red-100"
                            >
                              Reject
                            </button>
                          </>
                        )}
                      </div>
                    </div>
                    <p className="mt-2 text-sm text-gray-600">{cr.description}</p>
                    <p className="mt-1 text-xs text-gray-400">
                      {new Date(cr.requested_at).toLocaleString()}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* User Review (AC-3: quick approve/reject) */}
          <section>
            <h2 className="text-lg font-semibold text-gray-800 mb-4">Quick Review</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {statuses.map((s) => (
                <div key={`review-${s.source}`} className="bg-white p-3 rounded-lg border border-gray-200">
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-sm">{s.source}</span>
                    <span className={`px-1.5 py-0.5 rounded text-xs ${VERIFICATION_COLORS[s.verification_status || "not_verified"]}`}>
                      {s.verification_status || "not_verified"}
                    </span>
                  </div>
                  <div className="mt-2 flex gap-1">
                    <button
                      onClick={() => openPreview(s.source)}
                      disabled={previewLoading === s.source}
                      className="flex-1 px-2 py-1 text-xs bg-blue-50 border border-blue-200 text-blue-700 rounded hover:bg-blue-100 disabled:opacity-50"
                    >
                      {previewLoading === s.source ? "..." : "Preview"}
                    </button>
                    <button
                      onClick={async () => {
                        try {
                          await submitReview({ source: s.source, user_verdict: "approved", remarks: "" });
                          setBanner({ kind: "info", text: `${s.source} 승인이 기록되었습니다.` });
                          refresh();
                        } catch (e) {
                          setBanner({ kind: "error", text: `${s.source} 승인 실패: ${e instanceof Error ? e.message : String(e)}` });
                        }
                      }}
                      className="flex-1 px-2 py-1 text-xs bg-green-50 border border-green-200 text-green-700 rounded hover:bg-green-100"
                    >
                      Approve
                    </button>
                    <button
                      onClick={() => { setReviewSource(s.source); setShowCrForm(true); setCrForm({ source: s.source, type: "content", description: "" }); }}
                      className="flex-1 px-2 py-1 text-xs bg-yellow-50 border border-yellow-200 text-yellow-700 rounded hover:bg-yellow-100"
                    >
                      Change
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </section>
        </>
      )}

      {/* Data Preview Modal (AC-3: 사용자 데이터 확인 게이트) */}
      {preview && (
        <div
          className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4"
          onClick={() => setPreview(null)}
        >
          <div
            className="bg-white rounded-lg shadow-xl max-w-6xl w-full max-h-[88vh] flex flex-col p-5"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-3 shrink-0">
              <h3 className="font-semibold text-gray-900">
                {preview.source} 데이터 미리보기
                <span className="ml-2 text-sm font-normal text-gray-500">
                  전체 {preview.row_count.toLocaleString()}행 중 최신 {preview.sample_rows.length}행 · {preview.column_names.length}컬럼
                </span>
                <span className={`ml-2 px-2 py-0.5 rounded text-xs font-medium ${
                  preview.schema_validation ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"
                }`}>
                  스키마 {preview.schema_validation ? "통과" : "실패"}
                </span>
              </h3>
              <button
                onClick={() => setPreview(null)}
                className="px-3 py-1 text-sm border border-gray-300 rounded hover:bg-gray-50"
              >
                닫기
              </button>
            </div>

            <div className="overflow-auto border border-gray-200 rounded grow min-h-0">
              <table className="w-full text-xs">
                <thead className="bg-gray-50 border-b sticky top-0 z-10">
                  <tr>
                    {preview.column_names.map((c) => (
                      <th key={c} className="px-2 py-1.5 text-left font-medium text-gray-700 whitespace-nowrap bg-gray-50">{c}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {preview.sample_rows.map((row, i) => (
                    <tr key={i} className="hover:bg-blue-50/40">
                      {preview.column_names.map((c) => {
                        const v = String(row[c] ?? "");
                        return (
                          <td key={c} className="px-2 py-1 whitespace-nowrap font-mono max-w-[14rem] truncate" title={v}>
                            {v}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-1 text-[11px] text-gray-400 shrink-0">
              가로 스크롤로 전체 컬럼 확인 · 잘린 값은 셀에 마우스를 올리면 전체 표시 · 최신(report_date 기준) 순 정렬
            </p>

            {preview.anomalies.length > 0 && (
              <div className="mt-3 text-xs text-orange-700 bg-orange-50 border border-orange-200 rounded p-2">
                통계적 이상치 플래그 {preview.anomalies.length}건 (z-score &gt; 3):{" "}
                {preview.anomalies.slice(0, 5).map((a) => `${a.column}=${a.value} (z=${a.z_score})`).join(", ")}
                {preview.anomalies.length > 5 && " …"}
              </div>
            )}

            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={async () => {
                  const src = preview.source;
                  try {
                    await submitReview({ source: src, user_verdict: "approved", remarks: "미리보기 확인 후 승인" });
                    setPreview(null);
                    setBanner({ kind: "info", text: `${src} 승인이 기록되었습니다.` });
                    refresh();
                  } catch (e) {
                    setBanner({ kind: "error", text: `${src} 승인 실패: ${e instanceof Error ? e.message : String(e)}` });
                  }
                }}
                className="px-4 py-1.5 text-sm bg-green-600 text-white rounded hover:bg-green-700"
              >
                확인 완료 — Approve
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
