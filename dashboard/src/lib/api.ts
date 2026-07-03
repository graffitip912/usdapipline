// USER-CONFIG: FastAPI backend URL
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function fetchApi<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

// Collector
export interface CollectorStatus {
  source: string;
  status: string;
  last_success: string | null;
  last_attempt: string | null;
  retry_count: number;
  error_message: string;
  verification_status?: string;
  last_verification_failure?: string | null;
  open_change_requests?: number;
  unresolved_failures?: number;
}

export function getCollectorStatus(): Promise<CollectorStatus[]> {
  return fetchApi("/api/collector/status");
}

export function runCollector(source: string): Promise<{ status: string; message: string }> {
  return fetchApi(`/api/collector/run/${source}`, { method: "POST" });
}

export function getCollectorHistory(source: string): Promise<Record<string, unknown>[]> {
  return fetchApi(`/api/collector/history/${source}`);
}

// Grain
export interface GrainRecord {
  obs_date: string;
  commodity: string;
  metric: string;
  metric_label?: string;
  value: number;
  unit: string;
  source: string;
  report_date: string;
}

interface DateRange {
  from?: string;
  to?: string;
}

function grainParams(commodity: string, range?: DateRange): string {
  const params = new URLSearchParams({ commodity });
  if (range?.from) params.set("from", range.from);
  if (range?.to) params.set("to", range.to);
  return params.toString();
}

export function getGrainPrices(commodity: string, range?: DateRange): Promise<GrainRecord[]> {
  return fetchApi(`/api/grain/prices?${grainParams(commodity, range)}`);
}

export function getGrainSupply(commodity: string, range?: DateRange): Promise<GrainRecord[]> {
  return fetchApi(`/api/grain/supply?${grainParams(commodity, range)}`);
}

export function getGrainInventory(commodity: string, range?: DateRange): Promise<GrainRecord[]> {
  return fetchApi(`/api/grain/inventory?${grainParams(commodity, range)}`);
}

export function getGtrIndices(range?: DateRange): Promise<GrainRecord[]> {
  const params = new URLSearchParams();
  if (range?.from) params.set("from", range.from);
  if (range?.to) params.set("to", range.to);
  const qs = params.toString();
  return fetchApi(`/api/gtr/indices${qs ? `?${qs}` : ""}`);
}

export interface DataAvailability {
  commodities: Record<string, {
    has_price: boolean;
    has_supply: boolean;
    has_stock: boolean;
    date_range: [string, string] | null;
  }>;
  gtr: boolean;
}

export function getGrainAvailable(): Promise<DataAvailability> {
  return fetchApi("/api/grain/available");
}

// Images
export interface ImageItem {
  id: string;
  filename: string;
  source_pdf: string;
  pdf_date: string;
  category: string;
  region: string | null;
  page_text: string;
  ocr_text: string;
}

export interface ImageMeta extends ImageItem {
  width: number;
  height: number;
  area: number;
  page: number;
  section_header: string | null;
  filter_stage: string;
  extracted_at: string;
}

export function getImages(filters?: { from?: string; region?: string; category?: string }): Promise<ImageItem[]> {
  const params = new URLSearchParams();
  if (filters?.from) params.set("from", filters.from);
  if (filters?.region) params.set("region", filters.region);
  if (filters?.category) params.set("category", filters.category);
  const qs = params.toString();
  return fetchApi(`/api/images${qs ? `?${qs}` : ""}`);
}

export function getImageMeta(imageId: string): Promise<ImageMeta> {
  return fetchApi(`/api/images/${imageId}/meta`);
}

export function imageFileUrl(imageId: string): string {
  return `${API_BASE}/api/images/${imageId}/file`;
}

// Schedule
export interface ScheduleItem {
  source: string;
  schedule_type: string;
  cron_expression: string;
  next_run: string | null;
  paused: boolean;
}

export function getSchedules(): Promise<ScheduleItem[]> {
  return fetchApi("/api/schedule");
}

export function pauseSchedules(): Promise<{ status: string }> {
  return fetchApi("/api/schedule/pause", { method: "POST" });
}

export function resumeSchedules(): Promise<{ status: string }> {
  return fetchApi("/api/schedule/resume", { method: "POST" });
}

// Curation
export interface CurationMetadata {
  dataset: string;
  version: string;
  created_at: string;
  curator: string;
  stats: {
    total_approved: number;
    total_excluded: number;
    total_decisions: number;
    label_distribution: Record<string, number>;
    region_distribution: Record<string, number>;
    section_distribution: Record<string, number>;
  };
}

export function importCuration(
  decisions: Record<string, unknown>[],
  curator?: string,
): Promise<{ status: string; approved: number; excluded: number }> {
  return fetchApi("/api/images/curation/import", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decisions, curator: curator || "user" }),
  });
}

export function getCurationMetadata(): Promise<CurationMetadata> {
  return fetchApi("/api/images/curation/metadata");
}

// Verification
export interface VerificationHistory {
  history_id: string;
  source: string;
  failed_at: string;
  failure_reason: string;
  as_is: Record<string, unknown>;
  to_be: Record<string, unknown> | null;
  resolved_at: string | null;
  resolution_method: string;
  linked_change_request: string | null;
}

export interface ChangeRequest {
  request_id: string;
  requested_by: string;
  requested_at: string;
  target_source: string;
  change_type: string;
  description: string;
  status: string;
  linked_verification: string | null;
  resolved_at: string | null;
}

export interface UserReview {
  review_id: string;
  source: string;
  reviewed_at: string;
  reviewer: string;
  auto_validation_passed: boolean;
  sample_summary: Record<string, unknown>;
  user_verdict: string;
  remarks: string;
  linked_change_request: string | null;
}

export interface VerificationSummary {
  verification_status: string;
  last_review_verdict: string | null;
  last_review_at: string | null;
  last_verification_failure: string | null;
  open_change_requests: number;
  total_history_entries: number;
}

export interface DataPreview {
  source: string;
  row_count: number;
  column_names: string[];
  sample_rows: Record<string, unknown>[];
  stats: Record<string, { min: number; max: number; mean: number; null_pct: number }>;
  schema_validation: boolean;
  anomalies: { column: string; index: number; value: number; z_score: number }[];
}

export function getVerificationHistory(source?: string): Promise<VerificationHistory[]> {
  const qs = source ? `?source=${source}` : "";
  return fetchApi(`/api/verification/history${qs}`);
}

export function getVerificationSummary(source: string): Promise<VerificationSummary> {
  return fetchApi(`/api/verification/summary/${source}`);
}

export function getDataPreview(source: string, sampleRows = 50): Promise<DataPreview> {
  return fetchApi(`/api/verification/preview/${source}?sample_rows=${sampleRows}`);
}

export function resolveVerificationHistory(
  historyId: string,
  toBe: Record<string, unknown>,
  resolutionMethod: string,
): Promise<{ status: string; history_id: string }> {
  return fetchApi(`/api/verification/history/${historyId}/resolve`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ to_be: toBe, resolution_method: resolutionMethod }),
  });
}

export function submitReview(body: {
  source: string;
  user_verdict: string;
  remarks?: string;
  linked_change_request?: string;
}): Promise<UserReview> {
  return fetchApi("/api/verification/review", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function createChangeRequest(body: {
  target_source: string;
  change_type: string;
  description: string;
}): Promise<ChangeRequest> {
  return fetchApi("/api/verification/change-request", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function getChangeRequests(source?: string, status?: string): Promise<ChangeRequest[]> {
  const params = new URLSearchParams();
  if (source) params.set("source", source);
  if (status) params.set("status", status);
  const qs = params.toString();
  return fetchApi(`/api/verification/change-requests${qs ? `?${qs}` : ""}`);
}

export function applyChangeRequest(requestId: string): Promise<{ status: string }> {
  return fetchApi(`/api/verification/change-request/${requestId}/apply`, { method: "PUT" });
}

export function reCollect(requestId: string): Promise<{ status: string }> {
  return fetchApi(`/api/verification/change-request/${requestId}/re-collect`, { method: "POST" });
}

export function verifyChangeRequest(
  requestId: string,
  body: { user_verdict: string; remarks?: string },
): Promise<{ status: string }> {
  return fetchApi(`/api/verification/change-request/${requestId}/verify`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
