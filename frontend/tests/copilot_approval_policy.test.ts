/** E2.5 · 双签/多签客户端测试. */
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
  approvalStatus, finalBadge, getPolicy, progressPct, riskColor, signApproval,
  upsertPolicy, type ApprovalStatus,
} from '../lib/copilot_approval_policy';

test('getPolicy GET /me', async () => {
  reset();
  push(() => jsonResp(200, { org_id: 'o', dual_sign_tools: ['a'] }));
  await getPolicy();
  assert.strictEqual(calls[0].method, 'GET');
  assert.ok(calls[0].url.endsWith('/copilot/approval-policy/me'));
});

test('upsertPolicy PUT /me with body', async () => {
  reset();
  push(() => jsonResp(200, { org_id: 'o' }));
  await upsertPolicy({
    dual_sign_tools: ['t1'], dual_sign_min_risk: 'high',
    required_roles: ['admin'], bypass_roles: null,
  });
  assert.strictEqual(calls[0].method, 'PUT');
  const body = JSON.parse(calls[0].body!);
  assert.strictEqual(body.dual_sign_min_risk, 'high');
});

test('signApproval POST body', async () => {
  reset();
  push(() => jsonResp(200, {
    final_decision: 'approve', needs_signs: 2, done_signs: 2,
  }));
  const r = await signApproval('abc', {
    decision: 'approve', tool_name: 'abort_mission', risk_level: 'high',
    comment: 'ok',
  });
  assert.strictEqual(calls[0].method, 'POST');
  const body = JSON.parse(calls[0].body!);
  assert.strictEqual(body.decision, 'approve');
  assert.strictEqual(body.tool_name, 'abort_mission');
  assert.strictEqual(r.final_decision, 'approve');
});

test('approvalStatus GET with query params', async () => {
  reset();
  push(() => jsonResp(200, {
    approval_id: 'x', needs_signs: 2, done_signs: 1,
    required_roles: [], reason: 'r', final_decision: null, signoffs: [],
  }));
  await approvalStatus('x', 'abort_mission', 'critical');
  const u = new URL(calls[0].url);
  assert.strictEqual(u.searchParams.get('tool_name'), 'abort_mission');
  assert.strictEqual(u.searchParams.get('risk_level'), 'critical');
});

test('riskColor covers all levels', () => {
  for (const r of ['low', 'medium', 'high', 'critical'] as const) {
    assert.ok(riskColor(r).length > 0);
  }
  assert.strictEqual(riskColor(null), 'default');
});

test('progressPct computes correctly', () => {
  const s: ApprovalStatus = {
    approval_id: 'x', needs_signs: 2, done_signs: 1,
    required_roles: [], reason: 'r', final_decision: null, signoffs: [],
  };
  assert.strictEqual(progressPct(s), 50);
  assert.strictEqual(progressPct({ ...s, done_signs: 2 }), 100);
  assert.strictEqual(progressPct({ ...s, needs_signs: 0 }), 0);
});

test('finalBadge maps decision to label', () => {
  assert.strictEqual(finalBadge('approve').text, '已批准');
  assert.strictEqual(finalBadge('reject').text, '已拒绝');
  assert.strictEqual(finalBadge(null).text, '待签');
});
