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
