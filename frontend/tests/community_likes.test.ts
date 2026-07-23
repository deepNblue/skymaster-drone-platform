/**
 * F3.2 · Community like/trending client tests.
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
  ageDescription, getLikeStatus, getTrending, heatTierForPost,
  likePost, TrendingPost, toggleLike, trendingByTag, unlikePost,
} from '../lib/community_likes';

// ---------- REST ----------

test('likePost POST', async () => {
  reset();
  push(() => jsonResp(201, {
    post_id: 'p1', liked: true, like_count: 1,
  }));
  const r = await likePost('p1');
  assert.strictEqual(r.like_count, 1);
  assert.strictEqual(r.liked, true);
  assert.strictEqual(calls[0].method, 'POST');
});

test('unlikePost DELETE', async () => {
  reset();
  push(() => jsonResp(200, {
    post_id: 'p1', liked: false, like_count: 0,
  }));
  const r = await unlikePost('p1');
  assert.strictEqual(r.liked, false);
  assert.strictEqual(calls[0].method, 'DELETE');
});

test('getLikeStatus GET', async () => {
  reset();
  push(() => jsonResp(200, {
    post_id: 'p1', liked: true, like_count: 7,
  }));
  const r = await getLikeStatus('p1');
  assert.strictEqual(r.like_count, 7);
});

test('toggleLike routes based on currentlyLiked', async () => {
  reset();
  push(() => jsonResp(201, {
    post_id: 'p1', liked: true, like_count: 1,
  }));
  await toggleLike('p1', false);
  assert.strictEqual(calls[0].method, 'POST');

  reset();
  push(() => jsonResp(200, {
    post_id: 'p1', liked: false, like_count: 0,
  }));
  await toggleLike('p1', true);
  assert.strictEqual(calls[0].method, 'DELETE');
});

test('getTrending default', async () => {
  reset();
  push(() => jsonResp(200, []));
  await getTrending();
  assert.strictEqual(calls[0].url.includes('?'), false);
});

test('getTrending forwards options', async () => {
  reset();
  push(() => jsonResp(200, []));
  await getTrending({
    within_hours: 12, limit: 10, tenant_scope: true,
  });
  assert.match(calls[0].url, /within_hours=12/);
  assert.match(calls[0].url, /limit=10/);
  assert.match(calls[0].url, /tenant_scope=true/);
});

test('HTTP error surfaces', async () => {
  reset();
  push(() => jsonResp(404, { detail: 'x' }));
  await assert.rejects(() => likePost('missing'), /HTTP 404/);
});

// ---------- Pure helpers ----------

const _mk = (o: Partial<TrendingPost> = {}): TrendingPost => ({
  post_id: 'x', title: 't', tags: ['drone'],
  author_id: null, like_count: 0, view_count: 0,
  comment_count: 0, created_at: null,
  age_hours: 1, hot_score: 0, ...o,
});

test('heatTierForPost 4 bands', () => {
  assert.strictEqual(heatTierForPost(_mk({ hot_score: 6 })).tier,
    'blazing');
  assert.strictEqual(heatTierForPost(_mk({ hot_score: 3 })).tier,
    'hot');
  assert.strictEqual(heatTierForPost(_mk({ hot_score: 1 })).tier,
    'warm');
  assert.strictEqual(heatTierForPost(_mk({ hot_score: 0.1 })).tier,
    'lukewarm');
});

test('ageDescription', () => {
  assert.strictEqual(ageDescription(0.5), '30分钟前');
  assert.strictEqual(ageDescription(3), '3小时前');
  assert.strictEqual(ageDescription(50), '2天前');
});

test('trendingByTag groups by primary tag', () => {
  const buckets = trendingByTag([
    _mk({ tags: ['drone'], hot_score: 5 }),
    _mk({ tags: ['drone', 'safety'], hot_score: 3 }),
    _mk({ tags: ['safety'], hot_score: 4 }),
    _mk({ tags: [], hot_score: 100 }),  // dropped
  ]);
  assert.strictEqual(buckets.length, 2);
  // drone total = 5+3=8 > safety=4
  assert.strictEqual(buckets[0].tag, 'drone');
  assert.strictEqual(buckets[0].total_score, 8);
  assert.strictEqual(buckets[1].tag, 'safety');
});

test('trendingByTag empty', () => {
  assert.deepStrictEqual(trendingByTag([]), []);
});
