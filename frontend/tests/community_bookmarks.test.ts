/**
 * F3.1 · Community bookmark tests.
 */
import assert from 'node:assert';
import test from 'node:test';

const calls: Array<{ url: string; method: string }> = [];
let responderQueue: Array<() => Response> = [];

function reset(): void {
  calls.length = 0;
  responderQueue = [];
}
function push(r: () => Response): void {
  responderQueue.push(r);
}
function jsonResp(status: number, obj: unknown): Response {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

(globalThis as any).fetch = (u: any, init?: RequestInit) => {
  const url = typeof u === 'string' ? u : u.url;
  calls.push({ url, method: (init?.method ?? 'GET').toUpperCase() });
  const fn = responderQueue.shift();
  return Promise.resolve(fn ? fn() : jsonResp(200, {}));
};
(globalThis as any).window = {} as any;
(globalThis as any).localStorage = {
  _s: { skymaster_token: 't' } as Record<string, string>,
  getItem(k: string) { return this._s[k] ?? null; },
} as any;

import {
  addBookmark, Bookmark, bookmarkTagCounts, getBookmarkStatus,
  listBookmarks, removeBookmark, toggleBookmark,
} from '../lib/community_bookmarks';

// -- REST --------------------------------------------------------

test('listBookmarks default', async () => {
  reset();
  push(() => jsonResp(200, []));
  const r = await listBookmarks();
  assert.deepStrictEqual(r, []);
  assert.strictEqual(calls[0].url.includes('?'), false);
});

test('listBookmarks with pagination', async () => {
  reset();
  push(() => jsonResp(200, []));
  await listBookmarks({ limit: 20, offset: 40 });
  assert.match(calls[0].url, /limit=20/);
  assert.match(calls[0].url, /offset=40/);
});

test('addBookmark POST', async () => {
  reset();
  push(() => jsonResp(201, {
    post_id: 'p1', bookmarked_at: '2026-07-17T00:00:00Z',
    total_bookmarks: 3,
  }));
  const r = await addBookmark('p1');
  assert.strictEqual(r.total_bookmarks, 3);
  assert.strictEqual(calls[0].method, 'POST');
  assert.match(calls[0].url, /\/community\/bookmarks\/p1$/);
});

test('removeBookmark DELETE 204', async () => {
  reset();
  push(() => new Response(null, { status: 204 }));
  const r = await removeBookmark('p1');
  assert.strictEqual(r, undefined);
  assert.strictEqual(calls[0].method, 'DELETE');
});

test('getBookmarkStatus GET', async () => {
  reset();
  push(() => jsonResp(200, {
    post_id: 'p1', bookmarked: true, total_bookmarks: 5,
  }));
  const r = await getBookmarkStatus('p1');
  assert.strictEqual(r.bookmarked, true);
  assert.strictEqual(r.total_bookmarks, 5);
});

test('HTTP 404 surfaces', async () => {
  reset();
  push(() => jsonResp(404, { detail: 'not found' }));
  await assert.rejects(() => addBookmark('missing'), /HTTP 404/);
});

// -- toggleBookmark ---------------------------------------------

test('toggleBookmark: unbookmarked → adds', async () => {
  reset();
  push(() => jsonResp(201, {
    post_id: 'p1', bookmarked_at: 'now', total_bookmarks: 1,
  }));
  const r = await toggleBookmark('p1', false);
  assert.strictEqual(r.bookmarked, true);
  assert.strictEqual(r.total_bookmarks, 1);
  assert.strictEqual(calls.length, 1);
  assert.strictEqual(calls[0].method, 'POST');
});

test('toggleBookmark: bookmarked → removes + re-fetches status', async () => {
  reset();
  push(() => new Response(null, { status: 204 }));  // delete
  push(() => jsonResp(200, {                         // status
    post_id: 'p1', bookmarked: false, total_bookmarks: 4,
  }));
  const r = await toggleBookmark('p1', true);
  assert.strictEqual(r.bookmarked, false);
  assert.strictEqual(r.total_bookmarks, 4);
  assert.strictEqual(calls[0].method, 'DELETE');
  assert.strictEqual(calls[1].method, 'GET');
});

// -- Pure helpers -----------------------------------------------

const _bm = (tags: string[]): Bookmark => ({
  post_id: 'x', bookmarked_at: '', title: '',
  tags,
  moderation_status: 'approved',
  view_count: 0, like_count: 0, comment_count: 0,
  created_at: '',
});

test('bookmarkTagCounts empty', () => {
  assert.deepStrictEqual(bookmarkTagCounts([]), []);
});

test('bookmarkTagCounts sums and sorts desc', () => {
  const counts = bookmarkTagCounts([
    _bm(['drone', 'flight']),
    _bm(['drone', 'safety']),
    _bm(['drone']),
    _bm(['safety']),
  ]);
  assert.strictEqual(counts[0].tag, 'drone');
  assert.strictEqual(counts[0].count, 3);
  assert.strictEqual(counts[1].tag, 'safety');
  assert.strictEqual(counts[1].count, 2);
  assert.strictEqual(counts[2].tag, 'flight');
});

test('bookmarkTagCounts handles missing tags array', () => {
  const bm: Bookmark = { ..._bm([]), tags: undefined as any };
  assert.deepStrictEqual(bookmarkTagCounts([bm]), []);
});
