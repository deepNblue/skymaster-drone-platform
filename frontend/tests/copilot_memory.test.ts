/**
 * E2.3 · Copilot 长期记忆客户端测试.
 */
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
  createMemory, daysRemaining, deleteMemory, kindColor, kindLabel, memoryStats,
  searchMemory, snippet, type Memory,
} from '../lib/copilot_memory';

test('createMemory POST /copilot/memory', async () => {
  reset();
  push(() => jsonResp(200, {
    id: 'x', org_id: 'o', user_id: 'u',
    kind: 'preference', scope: 'user', key: null,
    content: 'hi', tags: null, meta: null, ttl_days: null,
    weight: 50, hit_count: 0, created_at: null, last_hit_at: null,
    source_trace_id: null,
  }));
  const r = await createMemory({ kind: 'preference', content: 'hi' });
  assert.strictEqual(calls[0].method, 'POST');
  const body = JSON.parse(calls[0].body!);
  assert.strictEqual(body.kind, 'preference');
  assert.strictEqual(r.kind, 'preference');
});

test('searchMemory serializes multi-value params', async () => {
  reset();
  push(() => jsonResp(200, []));
  await searchMemory({
    q: '巡检', kind: ['preference', 'fact'],
    tag: ['t1', 't2'], top_k: 10,
  });
  const u = new URL(calls[0].url);
  assert.strictEqual(u.searchParams.get('q'), '巡检');
  assert.deepStrictEqual(u.searchParams.getAll('kind'), ['preference', 'fact']);
  assert.deepStrictEqual(u.searchParams.getAll('tag'), ['t1', 't2']);
  assert.strictEqual(u.searchParams.get('top_k'), '10');
});

test('memoryStats GET /stats', async () => {
  reset();
  push(() => jsonResp(200, { preference: 3, fact: 1 }));
  const r = await memoryStats();
  assert.strictEqual(r.preference, 3);
});

test('deleteMemory DELETE by id', async () => {
  reset();
  push(() => jsonResp(200, { deleted: true }));
  const r = await deleteMemory('abc');
  assert.strictEqual(calls[0].method, 'DELETE');
  assert.ok(calls[0].url.endsWith('/copilot/memory/abc'));
  assert.strictEqual(r.deleted, true);
});

test('kindLabel / kindColor cover all kinds', () => {
  for (const k of ['preference', 'fact', 'task_history', 'insight'] as const) {
    assert.ok(kindLabel(k).length > 0);
    assert.ok(kindColor(k).length > 0);
  }
});

test('daysRemaining respects TTL and created_at', () => {
  const twoDaysAgo = new Date(Date.now() - 2 * 86400000).toISOString();
  const mem: Memory = {
    id: 'x', org_id: 'o', user_id: 'u', kind: 'fact', scope: 'user',
    key: null, content: '', tags: null, meta: null,
    ttl_days: 5, weight: 50, hit_count: 0,
    created_at: twoDaysAgo, last_hit_at: null, source_trace_id: null,
  };
  const r = daysRemaining(mem);
  assert.ok(r !== null);
  assert.ok(r >= 2 && r <= 3, `expected ~3 got ${r}`);
});

test('daysRemaining null when no TTL', () => {
  const mem: Memory = {
    id: 'x', org_id: 'o', user_id: 'u', kind: 'fact', scope: 'user',
    key: null, content: '', tags: null, meta: null,
    ttl_days: null, weight: 50, hit_count: 0,
    created_at: new Date().toISOString(),
    last_hit_at: null, source_trace_id: null,
  };
  assert.strictEqual(daysRemaining(mem), null);
});

test('snippet truncates long content', () => {
  assert.strictEqual(snippet('short'), 'short');
  const long = 'a'.repeat(150);
  const r = snippet(long, 50);
  assert.strictEqual(r.length, 50);
  assert.ok(r.endsWith('…'));
});
