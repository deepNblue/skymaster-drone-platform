/**
 * F3.4 · Community notification client.
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

export type NotificationKind =
  'new_follower' | 'post_liked' | 'post_reply' | 'mention';

export interface Notification {
  id: string;
  kind: NotificationKind;
  actor_id: string | null;
  actor_email: string | null;
  post_id: string | null;
  comment_id: string | null;
  payload: { excerpt?: string } | null;
  read_at: string | null;
  created_at: string | null;
  read: boolean;
}

export interface UnreadSummary {
  new_follower: number;
  post_liked: number;
  post_reply: number;
  mention: number;
  total: number;
}

export function listNotifications(opts?: {
  only_unread?: boolean;
  kinds?: NotificationKind[];
  limit?: number;
  offset?: number;
}): Promise<Notification[]> {
  const p = new URLSearchParams();
  if (opts?.only_unread) p.set('only_unread', 'true');
  if (opts?.kinds?.length) {
    for (const k of opts.kinds) p.append('kinds', k);
  }
  if (opts?.limit != null) p.set('limit', String(opts.limit));
  if (opts?.offset != null) p.set('offset', String(opts.offset));
  const qs = p.toString();
  return _do<Notification[]>(
    `/community/notifications${qs ? '?' + qs : ''}`,
  );
}

export function getUnreadCount(): Promise<{ unread: number }> {
  return _do('/community/notifications/unread-count');
}

export function getUnreadSummary(): Promise<UnreadSummary> {
  return _do<UnreadSummary>(
    '/community/notifications/unread-summary',
  );
}

export function markRead(
  id: string,
): Promise<{ id: string; read: true }> {
  return _do(
    `/community/notifications/${encodeURIComponent(id)}/read`,
    { method: 'POST' },
  );
}

export function markAllRead(
  kinds?: NotificationKind[],
): Promise<{ updated: number }> {
  const p = new URLSearchParams();
  if (kinds?.length) for (const k of kinds) p.append('kinds', k);
  const qs = p.toString();
  return _do(
    `/community/notifications/read-all${qs ? '?' + qs : ''}`,
    { method: 'POST' },
  );
}

// -- Pure helpers ------------------------------------------------

const KIND_LABELS: Record<NotificationKind, string> = {
  new_follower: '关注了你',
  post_liked: '点赞了你的帖子',
  post_reply: '回复了你的帖子',
  mention: '在评论中提到你',
};

const KIND_ICONS: Record<NotificationKind, string> = {
  new_follower: '👥',
  post_liked: '👍',
  post_reply: '💬',
  mention: '📣',
};

export function labelFor(kind: NotificationKind): string {
  return KIND_LABELS[kind] ?? kind;
}

export function iconFor(kind: NotificationKind): string {
  return KIND_ICONS[kind] ?? '🔔';
}

/**
 * Group notifications by day bucket (YYYY-MM-DD, local time).
 * Returns [bucket, items[]] in reverse chronological order.
 */
export function groupByDay(
  items: Notification[],
): Array<{ day: string; items: Notification[] }> {
  const map = new Map<string, Notification[]>();
  for (const n of items) {
    const day = (n.created_at ?? '').slice(0, 10);
    const arr = map.get(day) ?? [];
    arr.push(n);
    map.set(day, arr);
  }
  return [...map.entries()]
    .sort((a, b) => (b[0] > a[0] ? 1 : -1))
    .map(([day, arr]) => ({ day, items: arr }));
}

/** Human-facing one-line description of a notification. */
export function describe(n: Notification): string {
  const who = n.actor_email ?? '匿名用户';
  const what = labelFor(n.kind);
  if (n.kind === 'post_reply' || n.kind === 'mention') {
    const exc = n.payload?.excerpt;
    return exc ? `${who} ${what}: "${exc}"` : `${who} ${what}`;
  }
  return `${who} ${what}`;
}
