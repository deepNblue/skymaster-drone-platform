/**
 * E3.2 · Vision Detection cluster analytics client.
 *
 * Wraps GET /api/v1/vision/analytics/clusters (backend E3.1).
 */
const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

function token(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('skymaster_token');
}

async function _do<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(init?.headers as Record<string, string> | undefined),
  };
  const t = token();
  if (t) headers['Authorization'] = `Bearer ${t}`;
  const res = await fetch(`${API}/api/v1${path}`, { ...init, headers });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${await res.text()}`);
  }
  return res.json();
}

export interface DetectionCluster {
  label: string;
  member_count: number;
  first_seen_at: string;
  last_seen_at: string;
  duration_s: number;
  centroid_lat: number;
  centroid_lng: number;
  peak_confidence: number;
  drone_ids: string[];
  member_ids: (string | null)[];
}

export interface LabelStat {
  label: string;
  count: number;
  avg_confidence: number;
  peak_confidence: number;
  distinct_drones: number;
}

export interface ClusterAnalytics {
  window_seconds: number;
  total_detections: number;
  cluster_count: number;
  clusters: DetectionCluster[];
  by_label: LabelStat[];
}

export function getClusterAnalytics(opts?: {
  label?: string;
  since_seconds?: number;
  geo_tol_m?: number;
  time_tol_s?: number;
}): Promise<ClusterAnalytics> {
  const p = new URLSearchParams();
  if (opts?.label) p.set('label', opts.label);
  if (opts?.since_seconds != null)
    p.set('since_seconds', String(opts.since_seconds));
  if (opts?.geo_tol_m != null) p.set('geo_tol_m', String(opts.geo_tol_m));
  if (opts?.time_tol_s != null)
    p.set('time_tol_s', String(opts.time_tol_s));
  const qs = p.toString();
  return _do<ClusterAnalytics>(
    `/vision/analytics/clusters${qs ? '?' + qs : ''}`,
  );
}

// Pure helpers ----------------------------------------------------

export interface HeatmapCell {
  lat: number;
  lng: number;
  weight: number;   // sum of member_count
  labels: string[];
}

/**
 * Bucket clusters into a lat/lng grid for a lightweight canvas heatmap.
 *
 * @param clusters — output of getClusterAnalytics.clusters
 * @param cellDeg — grid cell size in degrees (default 0.001 ~= 100m)
 */
export function toHeatmapGrid(
  clusters: DetectionCluster[],
  cellDeg = 0.001,
): HeatmapCell[] {
  if (!clusters.length) return [];
  const bucket = new Map<string, HeatmapCell>();
  for (const c of clusters) {
    const kx = Math.round(c.centroid_lat / cellDeg) * cellDeg;
    const ky = Math.round(c.centroid_lng / cellDeg) * cellDeg;
    const key = `${kx.toFixed(6)}:${ky.toFixed(6)}`;
    const cell = bucket.get(key);
    if (cell) {
      cell.weight += c.member_count;
      if (!cell.labels.includes(c.label)) cell.labels.push(c.label);
    } else {
      bucket.set(key, {
        lat: kx, lng: ky,
        weight: c.member_count,
        labels: [c.label],
      });
    }
  }
  return [...bucket.values()].sort((a, b) => b.weight - a.weight);
}

/** Rank labels by member-count share. */
export function topLabels(
  clusters: DetectionCluster[],
  n = 5,
): Array<{ label: string; share: number; total: number }> {
  const totals = new Map<string, number>();
  let grand = 0;
  for (const c of clusters) {
    totals.set(c.label, (totals.get(c.label) ?? 0) + c.member_count);
    grand += c.member_count;
  }
  if (grand === 0) return [];
  return [...totals.entries()]
    .map(([label, total]) => ({
      label,
      total,
      share: total / grand,
    }))
    .sort((a, b) => b.total - a.total)
    .slice(0, n);
}

export function severityForCluster(
  c: DetectionCluster,
): 'low' | 'medium' | 'high' | 'critical' {
  if (c.member_count >= 20 || c.peak_confidence >= 0.95) return 'critical';
  if (c.member_count >= 10) return 'high';
  if (c.member_count >= 3) return 'medium';
  return 'low';
}

export const CLUSTER_SEV_COLOR: Record<string, string> = {
  low: '#94a3b8',
  medium: '#faad14',
  high: '#fa541c',
  critical: '#a8071a',
};
