/**
 * F3.2 · Community like + trending client.
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
  if (res.status === 204) return undefined as unknown as T;
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${await res.text()}`);
  }
  return res.json();
}

export interface LikeStatus {
  post_id: string;
  liked: boolean;
  like_count: number;
}

export interface TrendingPost {
  post_id: string;
  title: string;
  tags: string[];
  author_id: string | null;
  like_count: number;
  view_count: number;
  comment_count: number;
  created_at: string | null;
  age_hours: number;
  hot_score: number;
}

export function likePost(post_id: string): Promise<LikeStatus> {
  return _do<LikeStatus>(
    `/community/likes/${encodeURIComponent(post_id)}`,
    { method: 'POST' },
  );
}

export function unlikePost(post_id: string): Promise<LikeStatus> {
  return _do<LikeStatus>(
    `/community/likes/${encodeURIComponent(post_id)}`,
    { method: 'DELETE' },
  );
}

export function getLikeStatus(post_id: string): Promise<LikeStatus> {
  return _do<LikeStatus>(
    `/community/likes/${encodeURIComponent(post_id)}/status`,
  );
}

export async function toggleLike(
  post_id: string, currentlyLiked: boolean,
): Promise<LikeStatus> {
  return currentlyLiked ? unlikePost(post_id) : likePost(post_id);
}

export function getTrending(opts?: {
  within_hours?: number;
  limit?: number;
  tenant_scope?: boolean;
}): Promise<TrendingPost[]> {
  const p = new URLSearchParams();
  if (opts?.within_hours != null)
    p.set('within_hours', String(opts.within_hours));
  if (opts?.limit != null) p.set('limit', String(opts.limit));
  if (opts?.tenant_scope != null)
    p.set('tenant_scope', String(opts.tenant_scope));
  const qs = p.toString();
  return _do<TrendingPost[]>(
    `/community/trending${qs ? '?' + qs : ''}`,
  );
}

// -- Pure helpers ------------------------------------------------

export function heatTierForPost(p: TrendingPost): {
  tier: 'blazing' | 'hot' | 'warm' | 'lukewarm';
  color: string;
  label: string;
} {
  if (p.hot_score >= 5) {
    return { tier: 'blazing', color: '#a8071a', label: '🔥 爆款' };
  }
  if (p.hot_score >= 2) {
    return { tier: 'hot', color: '#fa541c', label: '🔥 热门' };
  }
  if (p.hot_score >= 0.5) {
    return { tier: 'warm', color: '#faad14', label: '📈 上升' };
  }
  return { tier: 'lukewarm', color: '#8c8c8c', label: '流动' };
}

export function ageDescription(hours: number): string {
  if (hours < 1) return `${Math.round(hours * 60)}分钟前`;
  if (hours < 24) return `${Math.round(hours)}小时前`;
  const d = Math.round(hours / 24);
  return `${d}天前`;
}

/** Group trending posts by top tag to build a "trending by category". */
export function trendingByTag(
  posts: TrendingPost[],
): Array<{ tag: string; posts: TrendingPost[]; total_score: number }> {
  const buckets = new Map<string, TrendingPost[]>();
  for (const p of posts) {
    const primary = p.tags?.[0];
    if (!primary) continue;
    const arr = buckets.get(primary) ?? [];
    arr.push(p);
    buckets.set(primary, arr);
  }
  return [...buckets.entries()]
    .map(([tag, ps]) => ({
      tag, posts: ps,
      total_score: ps.reduce((s, p) => s + p.hot_score, 0),
    }))
    .sort((a, b) => b.total_score - a.total_score);
}
