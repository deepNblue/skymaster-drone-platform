/**
 * v2.1 · Scene annotation API client.
 */
const baseURL =
  process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8080';

function authHeaders(): HeadersInit {
  if (typeof window === 'undefined') return {};
  const t = window.localStorage.getItem('access_token');
  return t ? { Authorization: `Bearer ${t}` } : {};
}

export type GeomKind = 'point' | 'line' | 'polygon' | 'volume';
export type Severity =
  | 'info' | 'low' | 'medium' | 'high' | 'critical';

export interface GeometrySummary {
  kind: GeomKind;
  n_vertices: number;
  length_m?: number;
  perimeter_m?: number;
  area_m2?: number;
  footprint_area_m2?: number;
}

export interface Annotation {
  id: string;
  scene_id: string;
  org_id: string;
  author_id: string;
  geom_kind: GeomKind;
  geom_vertices: number[][];
  color: string;
  label: string;
  description: string | null;
  severity: Severity;
  frame_index: number | null;
  layer: string;
  meta: Record<string, unknown>;
  resolved: boolean;
  geometry_summary: GeometrySummary;
  created_at: string;
  updated_at: string;
}

export interface CreateAnnotationPayload {
  geom_kind: GeomKind;
  geom_vertices: number[][];
  label: string;
  description?: string | null;
  color?: string;
  severity?: Severity;
  frame_index?: number | null;
  layer?: string;
  meta?: Record<string, unknown>;
}

export interface UpdateAnnotationPayload {
  label?: string;
  description?: string | null;
  color?: string;
  severity?: Severity;
  resolved?: boolean;
  layer?: string;
  meta?: Record<string, unknown>;
}

export interface AnnotationReply {
  id: string;
  annotation_id: string;
  author_id: string;
  body: string;
  created_at: string;
}

export interface AnnotationStats {
  scene_id: string;
  total: number;
  unresolved: number;
  by_severity: Record<Severity, number>;
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

// ---- Client-side geometry helpers (mirror backend semantics) --------

export function lineLengthM(verts: number[][]): number {
  let s = 0;
  for (let i = 1; i < verts.length; i++) {
    const a = verts[i - 1], b = verts[i];
    s += Math.sqrt(
      (a[0] - b[0]) ** 2 +
      (a[1] - b[1]) ** 2 +
      (a[2] - b[2]) ** 2,
    );
  }
  return s;
}

export function polygonAreaM2(verts: number[][]): number {
  if (verts.length < 3) return 0;
  let s = 0;
  for (let i = 0; i < verts.length; i++) {
    const a = verts[i];
    const b = verts[(i + 1) % verts.length];
    s += a[0] * b[1] - b[0] * a[1];
  }
  return Math.abs(s) / 2;
}

export const SEVERITY_COLOR: Record<Severity, string> = {
  info: 'default',
  low: 'blue',
  medium: 'gold',
  high: 'orange',
  critical: 'red',
};

export const SEVERITY_LABEL: Record<Severity, string> = {
  info: '信息',
  low: '低',
  medium: '中',
  high: '高',
  critical: '紧急',
};

export const GEOM_KIND_LABEL: Record<GeomKind, string> = {
  point: '点',
  line: '线',
  polygon: '面',
  volume: '体',
};

// ---- API operations -------------------------------------------------

export function listAnnotations(
  sceneId: string,
  opts: {
    layer?: string;
    severity?: Severity;
    only_unresolved?: boolean;
    frame_index?: number;
  } = {},
): Promise<Annotation[]> {
  const p = new URLSearchParams();
  if (opts.layer) p.set('layer', opts.layer);
  if (opts.severity) p.set('severity', opts.severity);
  if (opts.only_unresolved) p.set('only_unresolved', 'true');
  if (opts.frame_index != null) {
    p.set('frame_index', String(opts.frame_index));
  }
  const qs = p.toString();
  return _do(
    `/scenes/${encodeURIComponent(sceneId)}/annotations${qs ? '?' + qs : ''}`,
  );
}

export function createAnnotation(
  sceneId: string, payload: CreateAnnotationPayload,
): Promise<Annotation> {
  return _do(
    `/scenes/${encodeURIComponent(sceneId)}/annotations`,
    { method: 'POST', body: JSON.stringify(payload) },
  );
}

export function updateAnnotation(
  annId: string, payload: UpdateAnnotationPayload,
): Promise<Annotation> {
  return _do(
    `/annotations/${encodeURIComponent(annId)}`,
    { method: 'PATCH', body: JSON.stringify(payload) },
  );
}

export function deleteAnnotation(annId: string): Promise<void> {
  return _do(
    `/annotations/${encodeURIComponent(annId)}`,
    { method: 'DELETE' },
  );
}

export function getAnnotationStats(
  sceneId: string,
): Promise<AnnotationStats> {
  return _do(
    `/scenes/${encodeURIComponent(sceneId)}/annotation-stats`,
  );
}

export function listReplies(annId: string): Promise<AnnotationReply[]> {
  return _do(
    `/annotations/${encodeURIComponent(annId)}/replies`,
  );
}

export function createReply(
  annId: string, body: string,
): Promise<AnnotationReply> {
  return _do(
    `/annotations/${encodeURIComponent(annId)}/replies`,
    { method: 'POST', body: JSON.stringify({ body }) },
  );
}
