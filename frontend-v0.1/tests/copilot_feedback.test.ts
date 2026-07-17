/**
 * F4.1 · Copilot v2 turn feedback client tests.
 */
import assert from 'node:assert';
import test from 'node:test';

const calls: Array<{
  url: string; method: string; body?: string;
}> = [];
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
  TurnStats, approvalRate, clearFeedback, formatScore,
  getIntentScoreboard, getMyFeedback, getRecentNegative, getTurnStats,
  scoreTier, submitFeedback, toggleFeedback,
} from '../lib/copilot_feedback';

// ---------- REST ----------

test('submitFeedback POST includes rating + comment', async () => {
  reset();
  push(() => jsonResp(201, {
    id: 'f1', turn_id: 't1', user_id: 'u',
    rating: 'up', comment: '好', updated: false,
    created_at: null, updated_at: null,
  }));
  const r = await submitFeedback('t1', 'up', '好');
  assert.strictEqual(r.rating, 'up');
  assert.strictEqual(calls[0].method, 'POST');
  const body = JSON.parse(calls[0].body!);
  assert.strictEqual(body.rating, 'up');
  assert.strictEqual(body.comment, '好');
});

test('clearFeedback DELETE', async () => {
  reset();
  push(() => new Response(null, { status: 204 }));
  await clearFeedback('t1');
  assert.strictEqual(calls[0].method, 'DELETE');
});

test('getMyFeedback returns null rating when none', async () => {
  reset();
  push(() => jsonResp(200, { turn_id: 't1', rating: null }));
  const r = await getMyFeedback('t1');
  assert.strictEqual(r.rating, null);
});

test('getTurnStats', async () => {
  reset();
  push(() => jsonResp(200, {
    total: 4, up: 3, down: 1, score: 0.5,
  }));
  const r = await getTurnStats('t1');
  assert.strictEqual(r.up, 3);
  assert.strictEqual(r.score, 0.5);
});

test('getRecentNegative with filter', async () => {
  reset();
  push(() => jsonResp(200, []));
  await getRecentNegative({ limit: 5, intent: 'report' });
  assert.match(calls[0].url, /limit=5/);
  assert.match(calls[0].url, /intent=report/);
});

test('getIntentScoreboard uses min_total', async () => {
  reset();
  push(() => jsonResp(200, []));
  await getIntentScoreboard(10);
  assert.match(calls[0].url, /min_total=10/);
});

test('HTTP error surfaces', async () => {
  reset();
  push(() => jsonResp(400, { detail: 'x' }));
  await assert.rejects(
    () => submitFeedback('t', 'up'), /HTTP 400/,
  );
});

// ---------- Toggle ----------

test('toggleFeedback: same rating → clear', async () => {
  reset();
  push(() => new Response(null, { status: 204 }));
  const r = await toggleFeedback('t1', 'up', 'up');
  assert.strictEqual(r.rating, null);
  assert.strictEqual(calls[0].method, 'DELETE');
});

test('toggleFeedback: no prior → submit', async () => {
  reset();
  push(() => jsonResp(201, {
    id: 'f', turn_id: 't', user_id: 'u',
    rating: 'up', comment: null, updated: false,
    created_at: null, updated_at: null,
  }));
  const r = await toggleFeedback('t1', null, 'up');
  assert.strictEqual(r.rating, 'up');
  assert.strictEqual(calls[0].method, 'POST');
});

test('toggleFeedback: switch up→down submits new', async () => {
  reset();
  push(() => jsonResp(201, {
    id: 'f', turn_id: 't', user_id: 'u',
    rating: 'down', comment: null, updated: true,
    created_at: null, updated_at: null,
  }));
  const r = await toggleFeedback('t1', 'up', 'down');
  assert.strictEqual(r.rating, 'down');
  assert.strictEqual(calls[0].method, 'POST');
});

test('toggleFeedback: same rating + comment still submits', async () => {
  reset();
  push(() => jsonResp(201, {
    id: 'f', turn_id: 't', user_id: 'u',
    rating: 'up', comment: '更详细的意见', updated: true,
    created_at: null, updated_at: null,
  }));
  const r = await toggleFeedback('t1', 'up', 'up', '更详细的意见');
  assert.strictEqual(r.rating, 'up');
  assert.strictEqual(calls[0].method, 'POST');
});

// ---------- Pure helpers ----------

test('scoreTier boundaries', () => {
  assert.strictEqual(scoreTier(0.9).label, '好');
  assert.strictEqual(scoreTier(0.5).label, '好');
  assert.strictEqual(scoreTier(0.4).label, '一般');
  assert.strictEqual(scoreTier(0).label, '一般');
  assert.strictEqual(scoreTier(-0.1).label, '差');
  assert.strictEqual(scoreTier(-1).color, 'red');
});

test('approvalRate handles zero total', () => {
  const s: TurnStats = { total: 0, up: 0, down: 0, score: 0 };
  assert.strictEqual(approvalRate(s), 0);
});

test('approvalRate positive', () => {
  const s: TurnStats = { total: 4, up: 3, down: 1, score: 0.5 };
  assert.strictEqual(approvalRate(s), 0.75);
});

test('formatScore signs', () => {
  assert.strictEqual(formatScore(0.5), '+50%');
  assert.strictEqual(formatScore(0), '0%');
  assert.strictEqual(formatScore(-0.5), '-50%');
});

test('formatScore rounds', () => {
  assert.strictEqual(formatScore(0.334), '+33%');
});
