/**
 * E2.6 · Copilot Workflow Marketplace API 客户端.
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
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
  if (res.status === 204) return null as T;
  return res.json();
}

export type Visibility = 'public' | 'org' | 'private';

export interface Listing {
  id: string;
  workflow_id: string;
  workflow_version: number;
  org_id: string | null;
  author_user_id: string | null;
  title: string;
  summary: string;
  tags: string[] | null;
  visibility: Visibility;
  install_count: number;
  avg_rating: number;
  rating_count: number;
  published_at: string | null;
}

export interface ListingDetail extends Listing {
  dsl_yaml_snapshot: string;
}

export interface Rating {
  id: string;
  listing_id: string;
  rater_user_id: string;
  stars: number;
  comment: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface Install {
  id: string;
  installer_user_id: string;
  installer_org_id: string | null;
  new_workflow_id: string;
  installed_at: string | null;
}

// --- REST ---

export function publish(body: {
  workflow_id: string;
  title: string;
  summary?: string;
  tags?: string[];
  visibility?: Visibility;
}): Promise<Listing> {
  return _do<Listing>('/copilot/workflow-marketplace/publish', {
    method: 'POST', body: JSON.stringify(body),
  });
}

export function unpublish(listingId: string): Promise<null> {
  return _do<null>(
    `/copilot/workflow-marketplace/listings/${listingId}/unpublish`,
    { method: 'POST' },
  );
}

export function browse(params: {
  q?: string;
  tag?: string;
  order_by?: 'install_count' | 'avg_rating' | 'published_at';
  limit?: number;
  offset?: number;
} = {}): Promise<{ total: number; items: Listing[] }> {
  const p = new URLSearchParams();
  if (params.q) p.set('q', params.q);
  if (params.tag) p.set('tag', params.tag);
  if (params.order_by) p.set('order_by', params.order_by);
  if (params.limit) p.set('limit', String(params.limit));
  if (params.offset) p.set('offset', String(params.offset));
  return _do(`/copilot/workflow-marketplace/listings?${p}`);
}

export function getListing(id: string): Promise<ListingDetail> {
  return _do<ListingDetail>(`/copilot/workflow-marketplace/listings/${id}`);
}

export function installListing(
  id: string, body: { new_name?: string } = {},
): Promise<{
  workflow_id: string;
  workflow_name: string;
  install_id: string;
  listing_install_count: number;
}> {
  return _do(
    `/copilot/workflow-marketplace/listings/${id}/install`,
    { method: 'POST', body: JSON.stringify(body) },
  );
}

export function rate(
  id: string, body: { stars: number; comment?: string },
): Promise<Rating> {
  return _do<Rating>(
    `/copilot/workflow-marketplace/listings/${id}/rate`,
    { method: 'POST', body: JSON.stringify(body) },
  );
}

export function listRatings(
  id: string, limit = 20, offset = 0,
): Promise<{ items: Rating[] }> {
  const p = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return _do(`/copilot/workflow-marketplace/listings/${id}/ratings?${p}`);
}

export function getMyRating(id: string): Promise<Rating | null> {
  return _do<Rating | null>(
    `/copilot/workflow-marketplace/listings/${id}/my-rating`,
  );
}

export function listInstalls(id: string): Promise<{ items: Install[] }> {
  return _do(`/copilot/workflow-marketplace/listings/${id}/installs`);
}

// --- helpers ---

export function starEmoji(stars: number): string {
  const s = Math.max(0, Math.min(5, Math.round(stars)));
  return '★'.repeat(s) + '☆'.repeat(5 - s);
}

export function visibilityBadge(v: Visibility): { text: string; color: string } {
  switch (v) {
    case 'public': return { text: '公开', color: 'green' };
    case 'org': return { text: '组织内', color: 'blue' };
    case 'private': return { text: '私有', color: 'default' };
  }
}

export function formatRating(avg: number, count: number): string {
  if (count === 0) return '暂无评分';
  return `${avg.toFixed(1)} (${count})`;
}
