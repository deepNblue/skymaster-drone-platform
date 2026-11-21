/**
 * F3.1 · Community bookmark client.
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

export interface Bookmark {
  post_id: string;
  bookmarked_at: string;
  title: string;
  tags: string[];
  moderation_status: string;
  view_count: number;
  like_count: number;
  comment_count: number;
  created_at: string;
}

export interface BookmarkStatus {
  post_id: string;
  bookmarked: boolean;
  total_bookmarks: number;
}

export function listBookmarks(
  opts?: { limit?: number; offset?: number },
): Promise<Bookmark[]> {
  const p = new URLSearchParams();
  if (opts?.limit != null) p.set('limit', String(opts.limit));
  if (opts?.offset != null) p.set('offset', String(opts.offset));
  const qs = p.toString();
  return _do<Bookmark[]>(`/community/bookmarks${qs ? '?' + qs : ''}`);
}

export function addBookmark(
  post_id: string,
): Promise<{ post_id: string; bookmarked_at: string; total_bookmarks: number }> {
  return _do(`/community/bookmarks/${encodeURIComponent(post_id)}`, {
    method: 'POST',
  });
}

export function removeBookmark(post_id: string): Promise<void> {
  return _do<void>(
    `/community/bookmarks/${encodeURIComponent(post_id)}`,
    { method: 'DELETE' },
  );
}

export function getBookmarkStatus(
  post_id: string,
): Promise<BookmarkStatus> {
  return _do<BookmarkStatus>(
    `/community/bookmarks/${encodeURIComponent(post_id)}/status`,
  );
}

/**
 * Toggle: if currently bookmarked, remove; else add. Returns the new
 * state (bookmarked?) plus the updated total.
 */
export async function toggleBookmark(
  post_id: string, currentlyBookmarked: boolean,
): Promise<{ bookmarked: boolean; total_bookmarks: number }> {
  if (currentlyBookmarked) {
    await removeBookmark(post_id);
    const s = await getBookmarkStatus(post_id);
    return { bookmarked: false, total_bookmarks: s.total_bookmarks };
  } else {
    const r = await addBookmark(post_id);
    return { bookmarked: true, total_bookmarks: r.total_bookmarks };
  }
}

// -- Pure helpers -------------------------------------------------

/** Group bookmarks by tag (returns [tag, count] descending). */
export function bookmarkTagCounts(
  bms: Bookmark[],
): Array<{ tag: string; count: number }> {
  const map = new Map<string, number>();
  for (const b of bms) {
    for (const t of b.tags ?? []) {
      map.set(t, (map.get(t) ?? 0) + 1);
    }
  }
  return [...map.entries()]
    .map(([tag, count]) => ({ tag, count }))
    .sort((a, b) => b.count - a.count);
}
