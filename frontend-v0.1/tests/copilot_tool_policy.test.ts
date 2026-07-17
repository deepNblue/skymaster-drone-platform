/**
 * F4.4 · Copilot tool policy + audit client tests.
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
  ToolCatalogItem, ToolPolicy, auditStats, flattenStats, getMyPolicy,
  listAudits, listTools, previewDecision, putMyPolicy, riskColor,
  riskLabel, statusColor, statusLabel, RISK_ORDER,
} from '../lib/copilot_tool_policy';

// ---------- REST ----------

test('listTools GET /tools', async () => {
  reset();
  push(() => jsonResp(200, [
    { name: 'list_drones', description: 'x', permission: 'readonly', risk_level: 'low' },
  ]));
  const r = await listTools();
  assert.strictEqual(r.length, 1);
  assert.strictEqual(r[0].name, 'list_drones');
  assert.ok(calls[0].url.endsWith('/copilot/tool-policy/tools'));
});

test('getMyPolicy returns null on empty', async () => {
  reset();
  push(() => jsonResp(200, null));
  const r = await getMyPolicy();
  assert.strictEqual(r, null);
});

test('putMyPolicy PUT body carries patch', async () => {
  reset();
  push(() => jsonResp(200, {
    org_id: 'o', allowlist: ['list_drones'], blocklist: null,
    max_risk_level: 'high', require_approval_above: 'medium',
    updated_at: null,
  }));
  const r = await putMyPolicy({
    allowlist: ['list_drones'],
    max_risk_level: 'high',
    require_approval_above: 'medium',
  });
  assert.strictEqual(calls[0].method, 'PUT');
  const body = JSON.parse(calls[0].body!);
  assert.strictEqual(body.max_risk_level, 'high');
  assert.deepStrictEqual(r.allowlist, ['list_drones']);
});

test('listAudits query params serialize', async () => {
  reset();
  push(() => jsonResp(200, []));
  await listAudits({
    tool_name: 'dispatch_mission',
    status: 'blocked',
    risk_level: 'critical',
    limit: 20, offset: 40,
  });
  const u = new URL(calls[0].url);
  assert.strictEqual(u.searchParams.get('tool_name'), 'dispatch_mission');
  assert.strictEqual(u.searchParams.get('status'), 'blocked');
  assert.strictEqual(u.searchParams.get('limit'), '20');
  assert.strictEqual(u.searchParams.get('offset'), '40');
});

test('auditStats returns nested map', async () => {
  reset();
  push(() => jsonResp(200, {
    executed: { list_drones: 5 },
    blocked: { dispatch_mission: 2 },
  }));
  const r = await auditStats();
  assert.strictEqual(r.executed.list_drones, 5);
});

// ---------- pure helpers ----------

test('RISK_ORDER monotonic', () => {
  assert.ok(RISK_ORDER.low < RISK_ORDER.medium);
  assert.ok(RISK_ORDER.medium < RISK_ORDER.high);
  assert.ok(RISK_ORDER.high < RISK_ORDER.critical);
});

test('riskColor / riskLabel cover all tiers', () => {
  for (const r of ['low', 'medium', 'high', 'critical'] as const) {
    assert.ok(riskColor(r).length > 0);
    assert.ok(riskLabel(r).length > 0);
  }
});

test('statusColor / statusLabel cover known statuses', () => {
  for (const s of ['executed', 'blocked', 'approval_required', 'rejected', 'error'] as const) {
    assert.ok(statusColor(s).length > 0);
    assert.ok(statusLabel(s).length > 0);
  }
});

test('previewDecision: blocklist wins', () => {
  const tool: ToolCatalogItem = {
    name: 'x', description: '', permission: 'readonly', risk_level: 'low',
  };
  const d = previewDecision(tool, { blocklist: ['x'] });
  assert.strictEqual(d.action, 'blocked');
});

test('previewDecision: allowlist gates non-listed tools', () => {
  const tool: ToolCatalogItem = {
    name: 'y', description: '', permission: 'readonly', risk_level: 'low',
  };
  const d = previewDecision(tool, { allowlist: ['x'] });
  assert.strictEqual(d.action, 'blocked');
});

test('previewDecision: max_risk_level caps tool risk', () => {
  const tool: ToolCatalogItem = {
    name: 'a', description: '', permission: 'readonly', risk_level: 'high',
  };
  const d = previewDecision(tool, { max_risk_level: 'medium' });
  assert.strictEqual(d.action, 'blocked');
});

test('previewDecision: sensitive tool forces approval', () => {
  const tool: ToolCatalogItem = {
    name: 'b', description: '', permission: 'sensitive', risk_level: 'high',
  };
  const d = previewDecision(tool, {});
  assert.strictEqual(d.action, 'approval_required');
});

test('previewDecision: gate promotes readonly to approval', () => {
  const tool: ToolCatalogItem = {
    name: 'c', description: '', permission: 'readonly', risk_level: 'high',
  };
  const d = previewDecision(tool, { require_approval_above: 'high' });
  assert.strictEqual(d.action, 'approval_required');
});

test('previewDecision: low-risk readonly is allowed by default', () => {
  const tool: ToolCatalogItem = {
    name: 'd', description: '', permission: 'readonly', risk_level: 'low',
  };
  const d = previewDecision(tool, {});
  assert.strictEqual(d.action, 'allowed');
});

test('flattenStats aggregates and sorts by blocked+approval', () => {
  const rows = flattenStats({
    executed: { list_drones: 10, dispatch_mission: 1 },
    blocked: { dispatch_mission: 3 },
    approval_required: { create_mission: 5 },
  });
  assert.strictEqual(rows.length, 3);
  // dispatch_mission has 3 blocked, create_mission has 5 approval => create_mission first
  assert.strictEqual(rows[0].tool, 'create_mission');
  assert.strictEqual(rows[0].approval_required, 5);
});
