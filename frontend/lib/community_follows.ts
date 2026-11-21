/**
 * F3.3 · Community follow client.
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

export interface FollowUser {
  user_id: string;
  email: string;
  role: string;
  followed_at: string;
}

export interface FollowStatus {
  target_id: string;
  following: boolean;
}

export interface FollowCounts {
  following: number;
  followers: number;
}

export interface FeedPost {
  post_id: string;
  title: string;
  tags: string[];
  author_id: string | null;
  author_email: string | null;
  like_count: number;
  view_count: number;
  comment_count: number;
  created_at: string | null;
}

export function followUser(
  target_id: string,
): Promise<{
  follower_id: string; followed_id: string;
  following: boolean; followed_at: string;
}> {
  return _do(
    `/community/follows/${encodeURIComponent(target_id)}`,
    { method: 'POST' },
  );
}

export function unfollowUser(target_id: string): Promise<void> {
  return _do<void>(
    `/community/follows/${encodeURIComponent(target_id)}`,
    { method: 'DELETE' },
  );
}

export function getFollowStatus(
  target_id: string,
): Promise<FollowStatus> {
  return _do<FollowStatus>(
    `/community/follows/${encodeURIComponent(target_id)}/status`,
  );
}

export function getMyFollowCounts(): Promise<FollowCounts> {
  return _do<FollowCounts>('/community/follows/me/counts');
}

export function listMyFollowing(opts?: {
  limit?: number; offset?: number;
}): Promise<FollowUser[]> {
  const p = new URLSearchParams();
  if (opts?.limit != null) p.set('limit', String(opts.limit));
  if (opts?.offset != null) p.set('offset', String(opts.offset));
  const qs = p.toString();
  return _do<FollowUser[]>(
    `/community/follows/me/following${qs ? '?' + qs : ''}`,
  );
}

export function listMyFollowers(opts?: {
  limit?: number; offset?: number;
}): Promise<FollowUser[]> {
  const p = new URLSearchParams();
  if (opts?.limit != null) p.set('limit', String(opts.limit));
  if (opts?.offset != null) p.set('offset', String(opts.offset));
  const qs = p.toString();
  return _do<FollowUser[]>(
    `/community/follows/me/followers${qs ? '?' + qs : ''}`,
  );
}

export function getFollowFeed(opts?: {
  within_hours?: number; limit?: number; offset?: number;
}): Promise<FeedPost[]> {
  const p = new URLSearchParams();
  if (opts?.within_hours != null)
    p.set('within_hours', String(opts.within_hours));
  if (opts?.limit != null) p.set('limit', String(opts.limit));
  if (opts?.offset != null) p.set('offset', String(opts.offset));
  const qs = p.toString();
  return _do<FeedPost[]>(
    `/community/follows/feed${qs ? '?' + qs : ''}`,
  );
}

/**
 * Toggle: if currently following, unfollow; else follow.
 * Returns the new state.
 */
export async function toggleFollow(
  target_id: string, currentlyFollowing: boolean,
): Promise<{ following: boolean }> {
  if (currentlyFollowing) {
    await unfollowUser(target_id);
    return { following: false };
  }
  await followUser(target_id);
  return { following: true };
}

// -- Pure helpers ------------------------------------------------

/** Determine mutual-follow status from two lists. */
export function mutualFollows(
  myFollowing: FollowUser[], myFollowers: FollowUser[],
): Set<string> {
  const followingIds = new Set(myFollowing.map((u) => u.user_id));
  return new Set(
    myFollowers
      .filter((f) => followingIds.has(f.user_id))
      .map((f) => f.user_id),
  );
}

/** Suggest new users to follow: my followers who I don't follow back. */
export function suggestedToFollowBack(
  myFollowing: FollowUser[], myFollowers: FollowUser[],
): FollowUser[] {
  const followingIds = new Set(myFollowing.map((u) => u.user_id));
  return myFollowers.filter((f) => !followingIds.has(f.user_id));
}

/** Group feed posts by author for a "digest per user" view. */
export function feedByAuthor(
  posts: FeedPost[],
): Array<{ author_id: string; author_email: string;
           posts: FeedPost[] }> {
  const map = new Map<string, FeedPost[]>();
  for (const p of posts) {
    if (!p.author_id) continue;
    const arr = map.get(p.author_id) ?? [];
    arr.push(p);
    map.set(p.author_id, arr);
  }
  return [...map.entries()].map(([author_id, ps]) => ({
    author_id,
    author_email: ps[0].author_email ?? '',
    posts: ps,
  }));
}
