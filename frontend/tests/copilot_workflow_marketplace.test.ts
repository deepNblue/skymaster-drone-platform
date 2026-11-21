/** E2.6 · Marketplace 客户端测试. */
import assert from 'node:assert';
import test from 'node:test';

const calls: Array<{ url: string; method: string; body?: string }> = [];
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
  calls.push({
    url,
    method: (init?.method ?? 'GET').toUpperCase(),
    body: typeof init?.body === 'string' ? init.body : undefined,
  });
  const fn = respQ.shift();
  return Promise.resolve(fn ? fn() : jsonResp(200, {}));
};
(globalThis as any).window = {} as any;
(globalThis as any).localStorage = {
  _s: { skymaster_token: 't' } as Record<string, string>,
  getItem(k: string) { return this._s[k] ?? null; },
} as any;

import {
  browse, formatRating, getListing, getMyRating, installListing, listRatings,
  publish, rate, starEmoji, unpublish, visibilityBadge,
} from '../lib/copilot_workflow_marketplace';

test('publish POSTs body', async () => {
  reset();
  push(() => jsonResp(200, { id: 'l1', title: 't' }));
  await publish({
    workflow_id: 'w1', title: 't', summary: 's', tags: ['a'],
    visibility: 'public',
  });
  assert.strictEqual(calls[0].method, 'POST');
  assert.ok(calls[0].url.endsWith('/copilot/workflow-marketplace/publish'));
  const body = JSON.parse(calls[0].body!);
  assert.strictEqual(body.workflow_id, 'w1');
});

test('unpublish returns null on 204', async () => {
  reset();
  push(() => new Response(null, { status: 204 }));
  const r = await unpublish('l1');
  assert.strictEqual(r, null);
});

test('browse builds query params', async () => {
  reset();
  push(() => jsonResp(200, { total: 0, items: [] }));
  await browse({ q: 'ins', tag: 'agri', order_by: 'avg_rating', limit: 10, offset: 20 });
  const u = new URL(calls[0].url);
  assert.strictEqual(u.searchParams.get('q'), 'ins');
  assert.strictEqual(u.searchParams.get('tag'), 'agri');
  assert.strictEqual(u.searchParams.get('order_by'), 'avg_rating');
  assert.strictEqual(u.searchParams.get('limit'), '10');
  assert.strictEqual(u.searchParams.get('offset'), '20');
});

test('getListing GETs detail path', async () => {
  reset();
  push(() => jsonResp(200, {
    id: 'l1', title: 't', dsl_yaml_snapshot: 'yaml',
    workflow_id: 'w', workflow_version: 1, org_id: null,
    author_user_id: null, summary: '', tags: null, visibility: 'public',
    install_count: 0, avg_rating: 0, rating_count: 0, published_at: null,
  }));
  const r = await getListing('l1');
  assert.strictEqual(r.dsl_yaml_snapshot, 'yaml');
});

test('installListing POSTs new_name', async () => {
  reset();
  push(() => jsonResp(200, {
    workflow_id: 'w2', workflow_name: 'x',
    install_id: 'i1', listing_install_count: 1,
  }));
  const r = await installListing('l1', { new_name: 'custom' });
  const body = JSON.parse(calls[0].body!);
  assert.strictEqual(body.new_name, 'custom');
  assert.strictEqual(r.listing_install_count, 1);
});

test('rate POSTs stars/comment', async () => {
  reset();
  push(() => jsonResp(200, {
    id: 'r1', listing_id: 'l1', rater_user_id: 'u',
    stars: 5, comment: 'ok', created_at: null, updated_at: null,
  }));
  await rate('l1', { stars: 5, comment: 'ok' });
  const body = JSON.parse(calls[0].body!);
  assert.strictEqual(body.stars, 5);
  assert.strictEqual(body.comment, 'ok');
});

test('listRatings + getMyRating hit correct paths', async () => {
  reset();
  push(() => jsonResp(200, { items: [] }));
  await listRatings('l1');
  assert.ok(calls[0].url.includes('/ratings?'));

  push(() => jsonResp(200, null));
  const r = await getMyRating('l1');
  assert.strictEqual(r, null);
});

test('starEmoji renders 0-5 stars', () => {
  assert.strictEqual(starEmoji(0), '☆☆☆☆☆');
  assert.strictEqual(starEmoji(3), '★★★☆☆');
  assert.strictEqual(starEmoji(5), '★★★★★');
  assert.strictEqual(starEmoji(4.6), '★★★★★');   // rounds
  assert.strictEqual(starEmoji(-1), '☆☆☆☆☆');    // clamp
  assert.strictEqual(starEmoji(9), '★★★★★');
});

test('visibilityBadge covers all values', () => {
  assert.strictEqual(visibilityBadge('public').text, '公开');
  assert.strictEqual(visibilityBadge('org').text, '组织内');
  assert.strictEqual(visibilityBadge('private').text, '私有');
});

test('formatRating displays average or zero label', () => {
  assert.match(formatRating(4.55, 12), /^4\.[56] \(12\)$/);
  assert.strictEqual(formatRating(0, 0), '暂无评分');
});
