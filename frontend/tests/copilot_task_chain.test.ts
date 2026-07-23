/**
 * Copilot Task Chain REST client tests · v2.1 E2.4c (frontend side)
 *
 * Same style as copilot_workflows.test.ts: node:assert + global fetch stub.
 */
import assert from 'node:assert';

interface FetchCall {
  url: string;
  init: RequestInit | undefined;
}

const calls: FetchCall[] = [];
let responder: (call: FetchCall) => Response = () =>
  new Response(null, { status: 500 });

(global as any).fetch = (url: string, init?: RequestInit) => {
  calls.push({ url, init });
  return Promise.resolve(responder({ url, init }));
};

(global as any).window = {} as any;
(global as any).localStorage = {
  _tok: 'test-jwt',
  getItem(k: string) {
    return k === 'access_token' ? this._tok : null;
  },
} as any;

import {
  createChain,
  listChains,
  getChain,
  advanceStep,
  runChain,
  reviseChain,
  cancelChain,
  planChain,
  autoCreateChain,
  reflectChain,
  progressPercent,
  statusColor,
  statusLabel,
} from '../lib/copilot_task_chain';

function reset() {
  calls.length = 0;
  responder = () => new Response(null, { status: 500 });
}

function jsonResp(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function lastReqBody(): unknown {
  const raw = calls[calls.length - 1]?.init?.body as string | undefined;
  return raw ? JSON.parse(raw) : undefined;
}

let ran = 0, failed = 0;
async function test(name: string, fn: () => Promise<void> | void) {
  ran++;
  reset();
  try {
    await fn();
    console.log(`  ✓ ${name}`);
  } catch (e) {
    failed++;
    console.log(`  ✗ ${name}\n    ${e instanceof Error ? e.message : e}`);
  }
}

// ============ mock helpers ============
const mockChain = {
  id: 'c-1', org_id: 'o-1', owner_user_id: 'u-1',
  conversation_id: null,
  goal: '看看无人机',
  plan_json: [{ title: 's1', tool: 'list_drones', args: {}, why: '' }],
  status: 'draft' as const,
  current_index: 0,
  reflection_notes: null,
  error: null,
  created_at: '2026-07-18T00:00:00Z',
  updated_at: '2026-07-18T00:00:00Z',
  completed_at: null,
};

const mockStep = {
  id: 's-1', chain_id: 'c-1', step_index: 0,
  title: 's1', tool: 'list_drones',
  args_planned: {}, args_resolved: {}, output_json: { total: 3 },
  status: 'succeeded' as const, error: null,
  started_at: '2026-07-18T00:00:00Z',
  finished_at: '2026-07-18T00:00:00Z',
};

// ============ tests ============
async function main() {
  console.log('copilot_task_chain client tests');

  // ---- createChain ----
  await test('createChain POST /copilot/task-chains with body', async () => {
    responder = () => jsonResp(200, mockChain);
    const r = await createChain({
      goal: 'g', plan: [{ title: 's', tool: 'list_drones', args: {} }],
    });
    assert.strictEqual(r.id, 'c-1');
    assert.strictEqual(calls[0].init?.method, 'POST');
    assert.ok(calls[0].url.endsWith('/api/v1/copilot/task-chains'));
    const body = lastReqBody() as any;
    assert.strictEqual(body.goal, 'g');
    assert.strictEqual(body.plan.length, 1);
  });

  await test('createChain surfaces error text', async () => {
    responder = () => new Response('bad plan', { status: 400 });
    await assert.rejects(
      createChain({ goal: 'x', plan: [] }),
      /HTTP 400: bad plan/,
    );
  });

  await test('createChain attaches bearer token', async () => {
    responder = () => jsonResp(200, mockChain);
    await createChain({ goal: 'g', plan: [] as any });
    const h = calls[0].init?.headers as Record<string, string>;
    assert.strictEqual(h['Authorization'], 'Bearer test-jwt');
  });

  // ---- listChains ----
  await test('listChains with status+limit uses query params', async () => {
    responder = () => jsonResp(200, { items: [] });
    await listChains({ status: 'running', limit: 20 });
    assert.match(calls[0].url, /\?status=running&limit=20$/);
  });

  await test('listChains without params omits query string', async () => {
    responder = () => jsonResp(200, { items: [mockChain] });
    const r = await listChains();
    assert.ok(calls[0].url.endsWith('/api/v1/copilot/task-chains'));
    assert.strictEqual(r.items.length, 1);
  });

  // ---- getChain ----
  await test('getChain returns chain+steps+revisions', async () => {
    responder = () => jsonResp(200, {
      chain: mockChain, steps: [mockStep], revisions: [],
    });
    const r = await getChain('c-1');
    assert.strictEqual(r.chain.id, 'c-1');
    assert.strictEqual(r.steps.length, 1);
    assert.ok(calls[0].url.endsWith('/api/v1/copilot/task-chains/c-1'));
  });

  // ---- advanceStep ----
  await test('advanceStep POST /advance', async () => {
    responder = () => jsonResp(200, { step: mockStep, chain: mockChain });
    const r = await advanceStep('c-1');
    assert.strictEqual(r.step.status, 'succeeded');
    assert.ok(calls[0].url.endsWith('/api/v1/copilot/task-chains/c-1/advance'));
    assert.strictEqual(calls[0].init?.method, 'POST');
  });

  // ---- runChain ----
  await test('runChain POST /run with max_steps default 32', async () => {
    responder = () => jsonResp(200, { chain: mockChain, steps: [] });
    await runChain('c-1');
    assert.match(calls[0].url, /\/run\?max_steps=32$/);
  });

  await test('runChain honours custom max_steps', async () => {
    responder = () => jsonResp(200, { chain: mockChain, steps: [] });
    await runChain('c-1', 5);
    assert.match(calls[0].url, /\/run\?max_steps=5$/);
  });

  // ---- reviseChain ----
  await test('reviseChain POST /revise passes kind+reason', async () => {
    responder = () => jsonResp(200, {
      id: 'r-1', chain_id: 'c-1', at_step_index: 0,
      kind: 'append_step',
      prev_plan: [], new_plan: [], reason: 'because',
      created_at: null,
    });
    const r = await reviseChain('c-1', {
      kind: 'append_step',
      new_tail: [{ title: 't', tool: 'list_missions', args: {} }],
      reason: 'because',
    });
    assert.strictEqual(r.kind, 'append_step');
    const body = lastReqBody() as any;
    assert.strictEqual(body.reason, 'because');
    assert.strictEqual(body.new_tail.length, 1);
  });

  // ---- cancelChain ----
  await test('cancelChain POST /cancel returns updated chain', async () => {
    responder = () => jsonResp(200, { ...mockChain, status: 'cancelled' });
    const r = await cancelChain('c-1');
    assert.strictEqual(r.status, 'cancelled');
    assert.ok(calls[0].url.endsWith('/api/v1/copilot/task-chains/c-1/cancel'));
  });

  // ---- planChain (dry-run) ----
  await test('planChain POST /plan without persisting', async () => {
    responder = () => jsonResp(200, {
      goal: 'g', plan: [{ title: 'x', tool: 'list_drones', args: {}, why: 'y' }],
    });
    const r = await planChain({ goal: 'g' });
    assert.strictEqual(r.plan.length, 1);
    assert.ok(calls[0].url.endsWith('/api/v1/copilot/task-chains/plan'));
  });

  // ---- autoCreateChain ----
  await test('autoCreateChain POST /auto persists a chain', async () => {
    responder = () => jsonResp(200, mockChain);
    const r = await autoCreateChain({ goal: 'g' });
    assert.strictEqual(r.status, 'draft');
    assert.ok(calls[0].url.endsWith('/api/v1/copilot/task-chains/auto'));
  });

  // ---- reflectChain ----
  await test('reflectChain default apply=true returns suggestion+applied', async () => {
    responder = () => jsonResp(200, {
      suggestion: { kind: 'append_step', new_tail: [], reason: 'r' },
      applied: {
        id: 'r-1', chain_id: 'c-1', at_step_index: 0,
        kind: 'append_step', prev_plan: [], new_plan: [], reason: 'r',
        created_at: null,
      },
    });
    const r = await reflectChain('c-1', { trigger: 'user_reflect', apply: true });
    assert.strictEqual(r.suggestion.kind, 'append_step');
    assert.ok(r.applied);
  });

  await test('reflectChain apply=false returns suggestion only', async () => {
    responder = () => jsonResp(200, {
      suggestion: { kind: 'abort', new_tail: null, reason: 'stop' },
    });
    const r = await reflectChain('c-1', { apply: false });
    assert.strictEqual(r.applied, undefined);
  });

  // ---- helpers ----
  await test('progressPercent 0/2 = 0, 1/2 = 50', () => {
    const c1 = { ...mockChain, current_index: 0,
      plan_json: [{}, {}] as any };
    const c2 = { ...mockChain, current_index: 1,
      plan_json: [{}, {}] as any };
    assert.strictEqual(progressPercent(c1 as any), 0);
    assert.strictEqual(progressPercent(c2 as any), 50);
  });

  await test('progressPercent empty plan = 0', () => {
    assert.strictEqual(
      progressPercent({ ...mockChain, plan_json: [] } as any), 0,
    );
  });

  await test('statusColor / statusLabel cover major statuses', () => {
    assert.strictEqual(statusColor('completed'), 'success');
    assert.strictEqual(statusColor('failed'), 'error');
    assert.strictEqual(statusLabel('running'), '执行中');
    assert.strictEqual(statusLabel('cancelled'), '已取消');
  });

  // ---- Approval SDK (E2.5) ----
  await test('listPendingApprovals GET /approvals/pending with limit', async () => {
    responder = () => jsonResp(200, {
      items: [{
        approval: {
          id: 'a-1', chain_id: 'c-1', step_id: 's-1', step_index: 0,
          tool_name: 'create_mission', risk_level: 'high',
          permission: 'sensitive', required_reason: 'policy',
          args_snapshot: {}, status: 'pending',
          approver_id: null, decision_reason: null, modifications: null,
          created_at: null, decided_at: null,
        },
        chain: { id: 'c-1', goal: 'g', status: 'paused', current_index: 0 },
      }],
    });
    const r = await (await import('../lib/copilot_task_chain'))
      .listPendingApprovals(10);
    assert.strictEqual(r.items.length, 1);
    assert.match(calls[0].url, /approvals\/pending\?limit=10$/);
  });

  await test('listChainApprovals GET /{id}/approvals', async () => {
    responder = () => jsonResp(200, { items: [] });
    const { listChainApprovals } = await import('../lib/copilot_task_chain');
    const r = await listChainApprovals('c-1');
    assert.strictEqual(r.items.length, 0);
    assert.ok(calls[0].url.endsWith('/api/v1/copilot/task-chains/c-1/approvals'));
  });

  await test('decideApproval defaults resume=true', async () => {
    responder = () => jsonResp(200, {
      approval: {
        id: 'a-1', chain_id: 'c-1', step_id: 's-1', step_index: 0,
        tool_name: 'x', risk_level: 'high', permission: 'sensitive',
        required_reason: 'r', args_snapshot: null, status: 'approved',
        approver_id: 'u-1', decision_reason: 'ok', modifications: null,
        created_at: null, decided_at: null,
      },
    });
    const { decideApproval } = await import('../lib/copilot_task_chain');
    const r = await decideApproval('a-1', {
      decision: 'approved', reason: 'ok',
    });
    assert.strictEqual(r.approval.status, 'approved');
    assert.match(calls[0].url, /\/decide\?resume=true$/);
    const body = lastReqBody() as any;
    assert.strictEqual(body.decision, 'approved');
    assert.strictEqual(body.reason, 'ok');
  });

  await test('decideApproval respects resume=false', async () => {
    responder = () => jsonResp(200, { approval: { status: 'rejected' } });
    const { decideApproval } = await import('../lib/copilot_task_chain');
    await decideApproval('a-1', { decision: 'rejected', reason: 'no' }, false);
    assert.match(calls[0].url, /\/decide\?resume=false$/);
  });

  console.log(`\n${ran - failed}/${ran} passed`);
  if (failed) process.exit(1);
}

void main();
