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
  value: number;
  unit: string;
  source: string;
  report_date: string;
}

export function getGrainPrices(commodity: string, from?: string, to?: string): Promise<GrainRecord[]> {
  const params = new URLSearchParams({ commodity });
  if (from) params.set("from", from);
  if (to) params.set("to", to);
  return fetchApi(`/api/grain/prices?${params}`);
}

export function getGrainSupply(commodity: string): Promise<GrainRecord[]> {
  return fetchApi(`/api/grain/supply?commodity=${commodity}`);
}

export function getGrainInventory(commodity: string): Promise<GrainRecord[]> {
  return fetchApi(`/api/grain/inventory?commodity=${commodity}`);
}

export function getGtrIndices(from?: string): Promise<GrainRecord[]> {
  const params = from ? `?from=${from}` : "";
  return fetchApi(`/api/gtr/indices${params}`);
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
