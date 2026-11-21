/**
 * E2.5b · Airspace calendar API client.
 */
const baseURL =
  process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8080';

function authHeaders(): HeadersInit {
  if (typeof window === 'undefined') return {};
  const t = window.localStorage.getItem('access_token');
  return t ? { Authorization: `Bearer ${t}` } : {};
}

export type CalendarSource = 'uom' | 'notam' | 'local' | 'manual';

export interface CalendarEntry {
  id: string;
  org_id: string;
  source: CalendarSource;
  external_ref: string | null;
  approval_id: string | null;
  title: string;
  purpose: string | null;
  geo_polygon: number[][];
  bbox_min_lon: number;
  bbox_min_lat: number;
  bbox_max_lon: number;
  bbox_max_lat: number;
  min_alt_m: number | null;
  max_alt_m: number | null;
  start_ts: string;
  end_ts: string;
  priority: number;
  created_at: string;
}

export interface CreateCalendarPayload {
  source?: CalendarSource;
  title: string;
  purpose?: string | null;
  external_ref?: string | null;
  approval_id?: string | null;
  geo_polygon: number[][];
  start_ts: string;
  end_ts: string;
  min_alt_m?: number | null;
  max_alt_m?: number | null;
  priority?: number;
}

export interface ConflictProbe {
  geo_polygon: number[][];
  start_ts: string;
  end_ts: string;
  min_alt_m?: number | null;
  max_alt_m?: number | null;
  exclude_ids?: string[];
}

export interface ConflictSummary {
  id: string;
  source: string;
  title: string;
  start_ts: string;
  end_ts: string;
  min_alt_m: number | null;
  max_alt_m: number | null;
  priority: number;
  external_ref: string | null;
  approval_id: string | null;
}

export interface ConflictsResult {
  count: number;
  conflicts: ConflictSummary[];
}

async function _do<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${baseURL}/api/v1${path}`, {
    ...init,
    headers: {
      ...authHeaders(),
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (!resp.ok && resp.status !== 204) {
    throw new Error(`HTTP ${resp.status} — ${await resp.text()}`);
  }
  if (resp.status === 204) return undefined as unknown as T;
  return resp.json();
}

export function listCalendarEntries(opts: {
  start_ts?: string; end_ts?: string;
  source?: CalendarSource; limit?: number;
} = {}): Promise<CalendarEntry[]> {
  const p = new URLSearchParams();
  if (opts.start_ts) p.set('start_ts', opts.start_ts);
  if (opts.end_ts) p.set('end_ts', opts.end_ts);
  if (opts.source) p.set('source', opts.source);
  if (opts.limit != null) p.set('limit', String(opts.limit));
  const qs = p.toString();
  return _do(`/airspace-calendar${qs ? '?' + qs : ''}`);
}

export function createCalendarEntry(
  payload: CreateCalendarPayload,
): Promise<CalendarEntry> {
  return _do('/airspace-calendar', {
    method: 'POST', body: JSON.stringify(payload),
  });
}

export function deleteCalendarEntry(id: string): Promise<void> {
  return _do(`/airspace-calendar/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  });
}

export function checkAirspaceConflicts(
  probe: ConflictProbe,
): Promise<ConflictsResult> {
  return _do('/airspace-calendar/check-conflicts', {
    method: 'POST', body: JSON.stringify(probe),
  });
}
