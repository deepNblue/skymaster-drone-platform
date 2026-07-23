/**
 * E3.3 · Detection alert rule tests.
 */
import assert from 'node:assert';
import test from 'node:test';

const calls: Array<{ url: string; method: string; body?: string }> = [];
let responder: () => Response = () =>
  new Response('{}', { status: 200 });

function reset(): void {
  calls.length = 0;
}
function jsonResp(status: number, obj: unknown): Response {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

(globalThis as any).fetch = (u: any, init?: RequestInit) => {
  const url = typeof u === 'string' ? u : u.url;
  calls.push({
    url, method: (init?.method ?? 'GET').toUpperCase(),
    body: typeof init?.body === 'string' ? init.body : undefined,
  });
  return Promise.resolve(responder());
};
(globalThis as any).window = {} as any;
(globalThis as any).localStorage = {
  _s: { skymaster_token: 't' } as Record<string, string>,
  getItem(k: string) { return this._s[k] ?? null; },
} as any;

import {
  AlertRule, ALERT_ACTIONS, ALERT_ACTION_LABEL, createAlertRule,
  deleteAlertRule, evaluateAlerts, lastFiredAgo, listAlertRules,
  ruleSummary, updateAlertRule,
} from '../lib/detection_alerts';

const _mk = (o: Partial<AlertRule> = {}): AlertRule => ({
  id: 'r1', name: 'r', label: 'person',
  min_member_count: 3, min_peak_confidence: 0,
  action: 'log', cooldown_seconds: 300, enabled: true,
  last_fired_at: null, notes: null,
  created_at: '2026-07-17T03:00:00Z',
  updated_at: '2026-07-17T03:00:00Z',
  ...o,
});

// -- REST ----------------------------------------------------------

test('listAlertRules default', async () => {
  reset();
  responder = () => jsonResp(200, [_mk()]);
  const rs = await listAlertRules();
  assert.strictEqual(rs.length, 1);
  assert.strictEqual(calls[0].url.includes('enabled_only'), false);
});

test('listAlertRules enabled_only', async () => {
  reset();
  responder = () => jsonResp(200, []);
  await listAlertRules({ enabled_only: true });
  assert.match(calls[0].url, /enabled_only=true/);
});

test('createAlertRule POSTs JSON body', async () => {
  reset();
  responder = () => jsonResp(201, _mk({ name: 'crowd' }));
  const r = await createAlertRule({
    name: 'crowd', label: 'person',
    action: 'feishu', min_member_count: 5,
  });
  assert.strictEqual(r.name, 'crowd');
  assert.strictEqual(calls[0].method, 'POST');
  assert.ok(calls[0].body);
  const body = JSON.parse(calls[0].body!);
  assert.strictEqual(body.action, 'feishu');
  assert.strictEqual(body.min_member_count, 5);
});

test('updateAlertRule PATCH', async () => {
  reset();
  responder = () => jsonResp(200, _mk({ enabled: false }));
  const r = await updateAlertRule('r1', { enabled: false });
  assert.strictEqual(r.enabled, false);
  assert.strictEqual(calls[0].method, 'PATCH');
  assert.match(calls[0].url, /\/vision\/alerts\/r1/);
});

test('deleteAlertRule 204 returns undefined', async () => {
  reset();
  responder = () => new Response(null, { status: 204 });
  const r = await deleteAlertRule('r1');
  assert.strictEqual(r, undefined);
  assert.strictEqual(calls[0].method, 'DELETE');
});

test('evaluateAlerts POST + since_seconds', async () => {
  reset();
  responder = () => jsonResp(200, {
    evaluated_at: 60, total_clusters: 2,
    fires: [], fire_count: 0,
  });
  const r = await evaluateAlerts(60);
  assert.strictEqual(r.fire_count, 0);
  assert.strictEqual(calls[0].method, 'POST');
  assert.match(calls[0].url, /since_seconds=60/);
});

test('HTTP 400 surfaces', async () => {
  reset();
  responder = () => jsonResp(400, { detail: 'bad' });
  await assert.rejects(
    () => createAlertRule({ name: '', label: 'x' }),
    /HTTP 400/,
  );
});

// -- Pure helpers --------------------------------------------------

test('ALERT_ACTIONS/LABEL match up', () => {
  for (const a of ALERT_ACTIONS) {
    assert.ok(ALERT_ACTION_LABEL[a]);
  }
});

test('ruleSummary default rule', () => {
  const s = ruleSummary(_mk());
  assert.match(s, /类别=person/);
  assert.match(s, /成员≥3/);
  assert.match(s, /冷却300s/);
});

test('ruleSummary wildcard + no cooldown + peak conf', () => {
  const s = ruleSummary(_mk({
    label: '*', min_peak_confidence: 0.9, cooldown_seconds: 0,
  }));
  assert.match(s, /任意类别/);
  assert.match(s, /置信度≥0\.90/);
  assert.ok(!s.includes('冷却'));
});

test('lastFiredAgo never fired', () => {
  assert.strictEqual(lastFiredAgo(_mk()), '未触发');
});

test('lastFiredAgo secs / mins / hours / days', () => {
  const now = new Date('2026-07-17T12:00:00Z');
  assert.strictEqual(lastFiredAgo(_mk({
    last_fired_at: '2026-07-17T11:59:30Z',
  }), now), '30秒前');
  assert.strictEqual(lastFiredAgo(_mk({
    last_fired_at: '2026-07-17T11:45:00Z',
  }), now), '15分钟前');
  assert.strictEqual(lastFiredAgo(_mk({
    last_fired_at: '2026-07-17T09:00:00Z',
  }), now), '3小时前');
  assert.strictEqual(lastFiredAgo(_mk({
    last_fired_at: '2026-07-15T12:00:00Z',
  }), now), '2天前');
});
