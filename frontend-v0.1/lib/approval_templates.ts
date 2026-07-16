/**
 * E2.5 · Flight approval template API client.
 *
 * Backend endpoints (see backend-v0.1/app/api/v1/approval_templates.py):
 *
 *   POST   /approval-templates              create (201)
 *   GET    /approval-templates              list (org-scoped)
 *   GET    /approval-templates/{id}         get one
 *   PATCH  /approval-templates/{id}         partial update
 *   DELETE /approval-templates/{id}         soft delete
 *   POST   /approval-templates/{id}/apply   → new flight_approval
 */
const baseURL =
  process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8080';

function authHeaders(): HeadersInit {
  if (typeof window === 'undefined') return {};
  const t = window.localStorage.getItem('access_token');
  return t ? { Authorization: `Bearer ${t}` } : {};
}

export type ApprovalCategory =
  | 'routine'
  | 'high_altitude'
  | 'night'
  | 'sensitive_area'
  | 'emergency';

export interface AuthorityPreset {
  code: string;
  name: string;
  channel?: string;
  priority?: number;
}

export interface ChecklistItem {
  id: string;
  text: string;
}

export interface ApprovalTemplate {
  id: string;
  org_id: string;
  author_user_id: string;
  name: string;
  category: ApprovalCategory;
  purpose: string | null;
  pilot_name: string | null;
  pilot_license: string | null;
  aircraft_reg: string | null;
  aircraft_model: string | null;
  insurance_no: string | null;
  max_alt_m: number | null;
  min_alt_m: number | null;
  default_area_polygon: number[][] | null;
  authorities_preset: AuthorityPreset[];
  checklist_json: ChecklistItem[];
  apply_count: number;
  created_at: string;
  updated_at: string;
}

export interface CreateTemplatePayload {
  name: string;
  category?: ApprovalCategory;
  purpose?: string | null;
  pilot_name?: string | null;
  pilot_license?: string | null;
  aircraft_reg?: string | null;
  aircraft_model?: string | null;
  insurance_no?: string | null;
  max_alt_m?: number | null;
  min_alt_m?: number | null;
  default_area_polygon?: number[][] | null;
  authorities_preset?: AuthorityPreset[];
  checklist_json?: ChecklistItem[];
}

export interface ApplyPayload {
  title: string;
  start_ts: string;   // ISO 8601
  end_ts: string;
  area_polygon_override?: number[][] | null;
  max_alt_m_override?: number | null;
  min_alt_m_override?: number | null;
}

export interface ApplyResult {
  approval_id: string;
  status: string;
}

async function _do<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const resp = await fetch(`${baseURL}/api/v1${path}`, {
    ...init,
    headers: {
      ...authHeaders(),
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (!resp.ok && resp.status !== 204) {
    const detail = await resp.text();
    throw new Error(`HTTP ${resp.status} — ${detail}`);
  }
  if (resp.status === 204) return undefined as unknown as T;
  return resp.json();
}

export function listApprovalTemplates(opts: {
  category?: ApprovalCategory;
  limit?: number;
} = {}): Promise<ApprovalTemplate[]> {
  const params = new URLSearchParams();
  if (opts.category) params.set('category', opts.category);
  if (opts.limit != null) params.set('limit', String(opts.limit));
  const qs = params.toString();
  return _do(`/approval-templates${qs ? '?' + qs : ''}`);
}

export function getApprovalTemplate(id: string): Promise<ApprovalTemplate> {
  return _do(`/approval-templates/${encodeURIComponent(id)}`);
}

export function createApprovalTemplate(
  payload: CreateTemplatePayload,
): Promise<ApprovalTemplate> {
  return _do('/approval-templates', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function updateApprovalTemplate(
  id: string,
  patch: Partial<CreateTemplatePayload>,
): Promise<ApprovalTemplate> {
  return _do(`/approval-templates/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  });
}

export function deleteApprovalTemplate(id: string): Promise<void> {
  return _do(`/approval-templates/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  });
}

export function applyApprovalTemplate(
  id: string,
  payload: ApplyPayload,
): Promise<ApplyResult> {
  return _do(`/approval-templates/${encodeURIComponent(id)}/apply`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}
