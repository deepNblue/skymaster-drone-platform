/**
 * F3.3 · Community follow client tests.
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
  FeedPost, FollowUser, feedByAuthor, followUser, getFollowFeed,
  getFollowStatus, getMyFollowCounts, listMyFollowers,
  listMyFollowing, mutualFollows, suggestedToFollowBack, toggleFollow,
  unfollowUser,
} from '../lib/community_follows';

// ---------- REST ----------

test('followUser POST', async () => {
  reset();
  push(() => jsonResp(201, {
    follower_id: 'me', followed_id: 'u2',
    following: true, followed_at: 't',
  }));
  const r = await followUser('u2');
  assert.strictEqual(r.following, true);
  assert.strictEqual(calls[0].method, 'POST');
});

test('unfollowUser DELETE', async () => {
  reset();
  push(() => new Response(null, { status: 204 }));
  const r = await unfollowUser('u2');
  assert.strictEqual(r, undefined);
  assert.strictEqual(calls[0].method, 'DELETE');
});

test('getFollowStatus', async () => {
  reset();
  push(() => jsonResp(200, {
    target_id: 'u2', following: true,
  }));
  const r = await getFollowStatus('u2');
  assert.strictEqual(r.following, true);
});

test('getMyFollowCounts', async () => {
  reset();
  push(() => jsonResp(200, { following: 5, followers: 7 }));
  const r = await getMyFollowCounts();
  assert.strictEqual(r.following, 5);
  assert.strictEqual(r.followers, 7);
});

test('listMyFollowing with pagination', async () => {
  reset();
  push(() => jsonResp(200, []));
  await listMyFollowing({ limit: 20, offset: 40 });
  assert.match(calls[0].url, /limit=20/);
  assert.match(calls[0].url, /offset=40/);
});

test('listMyFollowers', async () => {
  reset();
  push(() => jsonResp(200, [{
    user_id: 'u1', email: 'a@b.c',
    role: 'user', followed_at: 't',
  }]));
  const r = await listMyFollowers();
  assert.strictEqual(r.length, 1);
});

test('getFollowFeed default', async () => {
  reset();
  push(() => jsonResp(200, []));
  await getFollowFeed();
  assert.strictEqual(calls[0].url.includes('?'), false);
});

test('getFollowFeed with options', async () => {
  reset();
  push(() => jsonResp(200, []));
  await getFollowFeed({ within_hours: 48, limit: 10 });
  assert.match(calls[0].url, /within_hours=48/);
  assert.match(calls[0].url, /limit=10/);
});

test('toggleFollow: unfollowed → follows', async () => {
  reset();
  push(() => jsonResp(201, {
    follower_id: 'me', followed_id: 'u2',
    following: true, followed_at: 't',
  }));
  const r = await toggleFollow('u2', false);
  assert.strictEqual(r.following, true);
  assert.strictEqual(calls[0].method, 'POST');
});

test('toggleFollow: followed → unfollows', async () => {
  reset();
  push(() => new Response(null, { status: 204 }));
  const r = await toggleFollow('u2', true);
  assert.strictEqual(r.following, false);
  assert.strictEqual(calls[0].method, 'DELETE');
});

test('HTTP 404 self-follow surfaces', async () => {
  reset();
  push(() => jsonResp(400, { detail: 'cannot follow yourself' }));
  await assert.rejects(() => followUser('me'), /HTTP 400/);
});

// ---------- Pure helpers ----------

const _u = (id: string): FollowUser => ({
  user_id: id, email: `${id}@e.co`,
  role: 'user', followed_at: '',
});

test('mutualFollows finds intersection', () => {
  const following = [_u('a'), _u('b'), _u('c')];
  const followers = [_u('b'), _u('c'), _u('d')];
  const m = mutualFollows(following, followers);
  assert.deepStrictEqual([...m].sort(), ['b', 'c']);
});

test('mutualFollows empty when no overlap', () => {
  const m = mutualFollows([_u('a')], [_u('b')]);
  assert.strictEqual(m.size, 0);
});

test('suggestedToFollowBack: followers not in following', () => {
  const following = [_u('a')];
  const followers = [_u('a'), _u('b'), _u('c')];
  const s = suggestedToFollowBack(following, followers);
  assert.deepStrictEqual(s.map((x) => x.user_id), ['b', 'c']);
});

const _p = (author_id: string, title: string): FeedPost => ({
  post_id: 'p' + title, title, tags: [],
  author_id, author_email: `${author_id}@e.co`,
  like_count: 0, view_count: 0, comment_count: 0,
  created_at: null,
});

test('feedByAuthor groups posts', () => {
  const g = feedByAuthor([
    _p('a', 'x'), _p('a', 'y'),
    _p('b', 'z'),
    { ..._p('none', 'q'), author_id: null } as FeedPost,  // dropped
  ]);
  assert.strictEqual(g.length, 2);
  const a = g.find((x) => x.author_id === 'a');
  assert.strictEqual(a?.posts.length, 2);
  assert.strictEqual(a?.author_email, 'a@e.co');
});

test('feedByAuthor empty', () => {
  assert.deepStrictEqual(feedByAuthor([]), []);
});
