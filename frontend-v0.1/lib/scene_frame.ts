/**
 * D3.1/D3.2 · Scene Frame client — 4DGS timeline.
 *
 * Companion to lib/scene_annotation.ts but simpler:
 * frames don't have replies or attachments, they're
 * just per-frame temporal metadata.
 */

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? '/api/v1';

function token(): string {
  if (typeof window === 'undefined') return '';
  return localStorage.getItem('skymaster_token') ?? '';
}

async function _do<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${BASE}${url}`, {
    ...(init ?? {}),
    headers: {
      'Content-Type': 'application/json',
      Authorization: token() ? `Bearer ${token()}` : '',
      ...((init?.headers as Record<string, string>) ?? {}),
    },
  });
  if (!r.ok) {
    const body = await r.text();
    throw new Error(`HTTP ${r.status}: ${body}`);
  }
  if (r.status === 204) return undefined as unknown as T;
  return (await r.json()) as T;
}

// ---- Types --------------------------------------------------------

export type Lighting =
  | 'day' | 'dusk' | 'night' | 'overcast' | 'sunrise' | 'sunset';

export const LIGHTINGS: Lighting[] = [
  'day', 'dusk', 'night', 'overcast', 'sunrise', 'sunset',
];

export const LIGHTING_LABEL: Record<Lighting, string> = {
  day: '白天',
  dusk: '黄昏',
  night: '夜间',
  overcast: '阴天',
  sunrise: '日出',
  sunset: '日落',
};

export const LIGHTING_COLOR: Record<Lighting, string> = {
  day: 'gold',
  dusk: 'orange',
  night: 'geekblue',
  overcast: 'default',
  sunrise: 'volcano',
  sunset: 'magenta',
};

export interface SceneFrame {
  id: string;
  scene_id: string;
  frame_index: number;
  captured_at: string | null;
  is_keyframe: boolean;
  psnr_frame: number | null;
  lighting: Lighting | null;
  notes: string | null;
  meta: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface FrameCreate {
  frame_index: number;
  captured_at?: string | null;
  is_keyframe?: boolean;
  psnr_frame?: number | null;
  lighting?: Lighting | null;
  notes?: string | null;
  meta?: Record<string, unknown>;
}

export interface FrameUpdate {
  is_keyframe?: boolean;
  psnr_frame?: number | null;
  lighting?: Lighting | null;
  notes?: string | null;
  captured_at?: string | null;
  meta?: Record<string, unknown>;
}

export interface TimelineSummary {
  scene_id: string;
  total_frames: number;
  keyframe_count: number;
  keyframe_indices: number[];
  captured_at_start: string | null;
  captured_at_end: string | null;
  avg_psnr: number | null;
}

// ---- API ----------------------------------------------------------

export function listFrames(
  sceneId: string,
  opts?: { only_keyframes?: boolean; lighting?: Lighting },
): Promise<SceneFrame[]> {
  const p = new URLSearchParams();
  if (opts?.only_keyframes) p.set('only_keyframes', 'true');
  if (opts?.lighting) p.set('lighting', opts.lighting);
  const qs = p.toString();
  return _do(
    `/scenes/${encodeURIComponent(sceneId)}/frames${qs ? '?' + qs : ''}`,
  );
}

export function getFrame(
  sceneId: string, frameIndex: number,
): Promise<SceneFrame> {
  return _do(
    `/scenes/${encodeURIComponent(sceneId)}/frames/${frameIndex}`,
  );
}

export function createFrame(
  sceneId: string, payload: FrameCreate,
): Promise<SceneFrame> {
  return _do(
    `/scenes/${encodeURIComponent(sceneId)}/frames`,
    { method: 'POST', body: JSON.stringify(payload) },
  );
}

export function bulkCreateFrames(
  sceneId: string, frames: FrameCreate[],
): Promise<SceneFrame[]> {
  return _do(
    `/scenes/${encodeURIComponent(sceneId)}/frames/bulk`,
    { method: 'POST', body: JSON.stringify({ frames }) },
  );
}

export function updateFrame(
  sceneId: string, frameIndex: number, payload: FrameUpdate,
): Promise<SceneFrame> {
  return _do(
    `/scenes/${encodeURIComponent(sceneId)}/frames/${frameIndex}`,
    { method: 'PATCH', body: JSON.stringify(payload) },
  );
}

export function deleteFrame(
  sceneId: string, frameIndex: number,
): Promise<void> {
  return _do(
    `/scenes/${encodeURIComponent(sceneId)}/frames/${frameIndex}`,
    { method: 'DELETE' },
  );
}

export function getTimelineSummary(
  sceneId: string,
): Promise<TimelineSummary> {
  return _do(`/scenes/${encodeURIComponent(sceneId)}/timeline`);
}

// ---- Pure helpers -------------------------------------------------

/**
 * Given a list of frames sorted by frame_index and a target index,
 * return the nearest keyframe index (for scrubber snap). Returns
 * the target itself if it's already a keyframe or no keyframes exist.
 */
export function nearestKeyframe(
  frames: Pick<SceneFrame, 'frame_index' | 'is_keyframe'>[],
  target: number,
): number {
  const kfs = frames.filter((f) => f.is_keyframe).map((f) => f.frame_index);
  if (kfs.length === 0) return target;
  let best = kfs[0];
  let bestD = Math.abs(kfs[0] - target);
  for (const k of kfs) {
    const d = Math.abs(k - target);
    if (d < bestD) {
      best = k;
      bestD = d;
    }
  }
  return best;
}

/**
 * Compute average PSNR over a frame list. Skips frames without PSNR.
 * Returns null if all frames lack PSNR.
 */
export function averagePsnr(frames: SceneFrame[]): number | null {
  const vals = frames
    .map((f) => f.psnr_frame)
    .filter((v): v is number => typeof v === 'number');
  if (vals.length === 0) return null;
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}

// ---- D3.3 · Frame diff / change detection ------------------------

export type Severity = 'info' | 'low' | 'medium' | 'high' | 'critical';

export const SEVERITY_COLOR_DIFF: Record<Severity, string> = {
  info: '#94a3b8',
  low: '#fadb14',
  medium: '#fa8c16',
  high: '#f5222d',
  critical: '#a8071a',
};

export const SEVERITY_LABEL_DIFF: Record<Severity, string> = {
  info: '信息',
  low: '轻微',
  medium: '中等',
  high: '严重',
  critical: '紧急',
};

export interface ChangePoint {
  from_index: number;
  to_index: number;
  severity: Severity;
  reasons: string[];
  psnr_delta: number | null;
  time_gap_s: number | null;
  lighting_from: Lighting | null;
  lighting_to: Lighting | null;
}

export interface ChangeReport {
  scene_id: string;
  total_frames: number;
  change_points: ChangePoint[];
  critical_count: number;
  high_count: number;
  medium_count: number;
}

export function getFrameDiff(
  sceneId: string, a: number, b: number,
  thresholds?: {
    psnr_warn?: number; psnr_crit?: number;
    time_warn_s?: number; time_crit_s?: number;
  },
): Promise<ChangePoint> {
  const p = new URLSearchParams();
  p.set('a', String(a));
  p.set('b', String(b));
  if (thresholds?.psnr_warn != null)
    p.set('psnr_warn', String(thresholds.psnr_warn));
  if (thresholds?.psnr_crit != null)
    p.set('psnr_crit', String(thresholds.psnr_crit));
  if (thresholds?.time_warn_s != null)
    p.set('time_warn_s', String(thresholds.time_warn_s));
  if (thresholds?.time_crit_s != null)
    p.set('time_crit_s', String(thresholds.time_crit_s));
  return _do(
    `/scenes/${encodeURIComponent(sceneId)}/frames/diff?${p.toString()}`,
  );
}

export function getChangeReport(
  sceneId: string,
  opts?: {
    min_severity?: Severity;
    psnr_warn?: number; psnr_crit?: number;
    time_warn_s?: number; time_crit_s?: number;
  },
): Promise<ChangeReport> {
  const p = new URLSearchParams();
  if (opts?.min_severity) p.set('min_severity', opts.min_severity);
  if (opts?.psnr_warn != null) p.set('psnr_warn', String(opts.psnr_warn));
  if (opts?.psnr_crit != null) p.set('psnr_crit', String(opts.psnr_crit));
  if (opts?.time_warn_s != null)
    p.set('time_warn_s', String(opts.time_warn_s));
  if (opts?.time_crit_s != null)
    p.set('time_crit_s', String(opts.time_crit_s));
  const qs = p.toString();
  return _do(
    `/scenes/${encodeURIComponent(sceneId)}/frames/changes` +
      (qs ? '?' + qs : ''),
  );
}

// Pure helpers -----------------------------------------------------

/**
 * Given a change report, produce ordered severity ranks for
 * Slider mark rendering.
 */
export function pointsToMarks(
  points: ChangePoint[],
): Record<number, { color: string; label: string; severity: Severity }> {
  const m: Record<number, {
    color: string; label: string; severity: Severity;
  }> = {};
  for (const p of points) {
    // Attach at to_index (change happens moving into this frame).
    const idx = p.to_index;
    const existing = m[idx];
    // Keep worst severity if two changes land on same index.
    if (existing) {
      const order: Severity[] = [
        'info', 'low', 'medium', 'high', 'critical',
      ];
      if (order.indexOf(p.severity) <= order.indexOf(existing.severity))
        continue;
    }
    m[idx] = {
      color: SEVERITY_COLOR_DIFF[p.severity],
      severity: p.severity,
      label: `●${idx}`,
    };
  }
  return m;
}

/**
 * Group frames into contiguous runs of the same lighting condition.
 * Useful for coloring the timeline background bar.
 */
export function lightingRuns(
  frames: SceneFrame[],
): Array<{
  lighting: Lighting | null; start: number; end: number;
}> {
  if (frames.length === 0) return [];
  const sorted = [...frames].sort(
    (a, b) => a.frame_index - b.frame_index,
  );
  const runs: Array<{
    lighting: Lighting | null; start: number; end: number;
  }> = [];
  let current = {
    lighting: sorted[0].lighting,
    start: sorted[0].frame_index,
    end: sorted[0].frame_index,
  };
  for (let i = 1; i < sorted.length; i++) {
    const f = sorted[i];
    if (f.lighting === current.lighting) {
      current.end = f.frame_index;
    } else {
      runs.push(current);
      current = {
        lighting: f.lighting,
        start: f.frame_index,
        end: f.frame_index,
      };
    }
  }
  runs.push(current);
  return runs;
}
