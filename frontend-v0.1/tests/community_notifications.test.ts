/**
 * F3.4 · Community notification client tests.
 */
import assert from 'node:assert';
import test from 'node:test';

const calls: Array<{ url: string; method: string }> = [];
let respQ: Array<() => Response> = [];
function reset(): void { calls.length = 0; respQ = []; }
function push(r: () => Response): void { respQ.push(r); }
function jsonResp(status: number, obj: unknown): Response {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

(globalThis as any).fetch = (u: any, init?: RequestInit) => {
  const url = typeof u === 'string' ? u : u.url;
  calls.push({ url, method: (init?.method ?? 'GET').toUpperCase() });
  const fn = respQ.shift();
  return Promise.resolve(fn ? fn() : jsonResp(200, {}));
};
(globalThis as any).window = {} as any;
(globalThis as any).localStorage = {
  _s: { skymaster_token: 't' } as Record<string, string>,
  getItem(k: string) { return this._s[k] ?? null; },
} as any;

import {
  Notification, describe, getUnreadCount, getUnreadSummary, groupByDay,
  iconFor, labelFor, listNotifications, markAllRead, markRead,
} from '../lib/community_notifications';

// ---------- REST ----------

test('listNotifications default', async () => {
  reset();
  push(() => jsonResp(200, []));
  await listNotifications();
  assert.strictEqual(calls[0].url.includes('?'), false);
});

test('listNotifications with kinds and unread', async () => {
  reset();
  push(() => jsonResp(200, []));
  await listNotifications({
    only_unread: true,
    kinds: ['post_liked', 'new_follower'],
    limit: 10, offset: 5,
  });
  assert.match(calls[0].url, /only_unread=true/);
  assert.match(calls[0].url, /kinds=post_liked/);
  assert.match(calls[0].url, /kinds=new_follower/);
  assert.match(calls[0].url, /limit=10/);
  assert.match(calls[0].url, /offset=5/);
});

test('getUnreadCount', async () => {
  reset();
  push(() => jsonResp(200, { unread: 7 }));
  const r = await getUnreadCount();
  assert.strictEqual(r.unread, 7);
});

test('getUnreadSummary', async () => {
  reset();
  push(() => jsonResp(200, {
    new_follower: 2, post_liked: 5, post_reply: 0, mention: 1,
    total: 8,
  }));
  const r = await getUnreadSummary();
  assert.strictEqual(r.total, 8);
});

test('markRead POST', async () => {
  reset();
  push(() => jsonResp(200, { id: 'n1', read: true }));
  await markRead('n1');
  assert.strictEqual(calls[0].method, 'POST');
  assert.match(calls[0].url, /n1\/read/);
});

test('markAllRead default all kinds', async () => {
  reset();
  push(() => jsonResp(200, { updated: 5 }));
  const r = await markAllRead();
  assert.strictEqual(r.updated, 5);
  assert.strictEqual(calls[0].url.includes('kinds='), false);
});

test('markAllRead by kind', async () => {
  reset();
  push(() => jsonResp(200, { updated: 3 }));
  await markAllRead(['new_follower']);
  assert.match(calls[0].url, /kinds=new_follower/);
});

test('HTTP error surfaces', async () => {
  reset();
  push(() => jsonResp(404, { detail: 'x' }));
  await assert.rejects(() => markRead('missing'), /HTTP 404/);
});

// ---------- Pure helpers ----------

test('labelFor known kinds', () => {
  assert.strictEqual(labelFor('new_follower'), '关注了你');
  assert.strictEqual(labelFor('post_liked'), '点赞了你的帖子');
  assert.strictEqual(labelFor('post_reply'), '回复了你的帖子');
  assert.strictEqual(labelFor('mention'), '在评论中提到你');
});

test('iconFor known kinds', () => {
  assert.strictEqual(iconFor('new_follower'), '👥');
  assert.strictEqual(iconFor('post_liked'), '👍');
});

const _n = (o: Partial<Notification> = {}): Notification => ({
  id: 'x', kind: 'post_liked',
  actor_id: 'a', actor_email: 'a@e.co',
  post_id: 'p', comment_id: null, payload: null,
  read_at: null, created_at: '2026-07-17T10:00:00Z',
  read: false, ...o,
});

test('groupByDay sorts buckets descending', () => {
  const g = groupByDay([
    _n({ id: '1', created_at: '2026-07-15T10:00:00Z' }),
    _n({ id: '2', created_at: '2026-07-17T10:00:00Z' }),
    _n({ id: '3', created_at: '2026-07-17T11:00:00Z' }),
    _n({ id: '4', created_at: '2026-07-16T10:00:00Z' }),
  ]);
  assert.strictEqual(g.length, 3);
  assert.strictEqual(g[0].day, '2026-07-17');
  assert.strictEqual(g[0].items.length, 2);
  assert.strictEqual(g[1].day, '2026-07-16');
  assert.strictEqual(g[2].day, '2026-07-15');
});

test('groupByDay empty', () => {
  assert.deepStrictEqual(groupByDay([]), []);
});

test('describe uses excerpt for reply/mention', () => {
  const line = describe(_n({
    kind: 'post_reply', payload: { excerpt: '好文章' },
    actor_email: 'bob@e.co',
  }));
  assert.match(line, /bob@e.co/);
  assert.match(line, /好文章/);
});

test('describe without excerpt for like', () => {
  const line = describe(_n({ kind: 'post_liked' }));
  assert.match(line, /点赞了/);
  assert.doesNotMatch(line, /:/);
});

test('describe falls back to 匿名用户 when no actor', () => {
  const line = describe(_n({ actor_email: null }));
  assert.match(line, /匿名用户/);
});
