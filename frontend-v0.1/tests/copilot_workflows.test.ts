/**
 * Copilot Workflow REST client tests · v2.1 E2.1 (T10.6, frontend side)
 *
 * Dependency-free style matching tests/ply-parser.test.ts — we stub
 * `global.fetch` to record calls and return canned responses. No jest,
 * no vitest, just node:assert + node --loader ts-node.
 */
import assert from 'node:assert';

// ------- global stub scaffolding -------

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

// Stub minimal localStorage (module reads it at call time inside authHeaders).
(global as any).window = {} as any;
(global as any).localStorage = {
  _tok: 'test-jwt',
  getItem(k: string) {
    return k === 'access_token' ? this._tok : null;
  },
} as any;

// Import AFTER stubs so the module captures our fetch.
import {
  validateWorkflow,
  runInlineWorkflow,
  listWorkflows,
  getWorkflow,
  createWorkflow,
  updateWorkflow,
  deleteWorkflow,
  runStoredWorkflow,
  listWorkflowRunHistory,
  getWorkflowRunHistoryDetail,
  listPlaybooks,
  getPlaybook,
  listSchedules,
  createSchedule,
  updateSchedule,
  deleteSchedule,
} from '../lib/copilot_workflows';

// ------- helpers -------

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
    console.log(`  ok  · ${name}`);
  } catch (e: any) {
    failed++;
    console.error(`  FAIL · ${name}\n         ${e?.stack ?? e?.message ?? e}`);
  }
}

// ============================================================ validate ===

async function runTests() {
  console.log('--- validateWorkflow ---');

  await test('sends workflow_yaml and returns parsed diagnostics', async () => {
    responder = () =>
      jsonResp(200, {
        ok: true,
        name: 'sample',
        steps: ['s1'],
        tools_used: ['list_drones'],
        error_type: null,
        error: null,
      });
    const result = await validateWorkflow('version: "0.1"\nname: s\nsteps: []');
    assert.strictEqual(result.ok, true);
    assert.deepStrictEqual(result.steps, ['s1']);
    assert.strictEqual(calls.length, 1);
    assert.ok(calls[0].url.endsWith('/api/v1/copilot/workflows/validate'));
    const body = lastReqBody() as Record<string, unknown>;
    assert.ok('workflow_yaml' in body);
    assert.ok(!('workflow' in body));
  });

  await test('surfaces semantic errors as ok=false without throwing', async () => {
    responder = () =>
      jsonResp(200, {
        ok: false,
        name: 'bad',
        steps: [],
        tools_used: [],
        error_type: 'semantic',
        error: "unknown tool 'ghost'",
      });
    const result = await validateWorkflow('...');
    assert.strictEqual(result.ok, false);
    assert.strictEqual(result.error_type, 'semantic');
    assert.match(result.error!, /ghost/);
  });

  await test('forwards allowed_input_keys when given', async () => {
    responder = () =>
      jsonResp(200, {
        ok: true, name: 'x', steps: [], tools_used: [],
        error_type: null, error: null,
      });
    await validateWorkflow('doc', ['a', 'b']);
    const body = lastReqBody() as Record<string, unknown>;
    assert.deepStrictEqual(body.allowed_input_keys, ['a', 'b']);
  });

  await test('throws on 4xx envelope error', async () => {
    responder = () =>
      new Response('missing source', { status: 400 });
    await assert.rejects(
      () => validateWorkflow('...'),
      /HTTP 400/,
    );
  });

  await test('attaches Bearer auth from localStorage', async () => {
    responder = () =>
      jsonResp(200, {
        ok: true, name: 'x', steps: [], tools_used: [],
        error_type: null, error: null,
      });
    await validateWorkflow('...');
    const headers = calls[0].init?.headers as Record<string, string>;
    assert.strictEqual(headers['Authorization'], 'Bearer test-jwt');
    assert.strictEqual(headers['Content-Type'], 'application/json');
  });

  // ============================================================= run ===

  console.log('--- runInlineWorkflow ---');

  await test('returns parsed WorkflowRun with steps trace', async () => {
    responder = () =>
      jsonResp(200, {
        workflow_name: 'sample',
        status: 'ok',
        duration_ms: 42,
        error: null,
        steps: [{
          id: 's1', tool: 'list_drones', status: 'ok',
          resolved_args: {}, result: { count: 3 },
          error: null, duration_ms: 12,
        }],
      });
    const run = await runInlineWorkflow('doc', { probe: 'x' });
    assert.strictEqual(run.status, 'ok');
    assert.strictEqual(run.steps.length, 1);
    assert.strictEqual(run.steps[0].status, 'ok');
    assert.deepStrictEqual(run.steps[0].result, { count: 3 });
    const body = lastReqBody() as Record<string, unknown>;
    assert.deepStrictEqual(body.inputs, { probe: 'x' });
  });

  await test('preserves runtime-failed traces (200 body with failed status)', async () => {
    responder = () =>
      jsonResp(200, {
        workflow_name: 'w', status: 'failed', duration_ms: 3,
        error: "step 's' failed: interpolation: missing ${input.x}",
        steps: [{
          id: 's', tool: 'echo', status: 'failed',
          resolved_args: {}, result: null,
          error: 'interpolation: missing ${input.x}', duration_ms: 3,
        }],
      });
    const run = await runInlineWorkflow('doc');
    // 200 body → NO throw, caller gets diagnostic trace.
    assert.strictEqual(run.status, 'failed');
    assert.match(run.error!, /interpolation/);
  });

  await test('throws on 4xx authoring error', async () => {
    responder = () =>
      new Response('validate: unknown tool ghost', { status: 400 });
    await assert.rejects(
      () => runInlineWorkflow('doc'),
      /HTTP 400/,
    );
  });

  // ======================================================= list / get ===

  console.log('--- persistence CRUD ---');

  await test('listWorkflows GETs the collection', async () => {
    responder = () => jsonResp(200, [
      {
        id: 'a', name: 'x', description: '', dsl_yaml: 'y',
        version: 1, owner_user_id: null,
        created_at: '2026-07-16T00:00:00Z',
        updated_at: '2026-07-16T00:00:00Z',
      },
    ]);
    const rows = await listWorkflows();
    assert.strictEqual(rows.length, 1);
    assert.strictEqual(calls[0].init?.method, undefined);  // default GET
    assert.ok(calls[0].url.endsWith('/api/v1/copilot/workflows'));
  });

  await test('getWorkflow uses id in URL and returns the row', async () => {
    responder = () => jsonResp(200, {
      id: 'abc', name: 'n', description: 'd', dsl_yaml: 'yy',
      version: 3, owner_user_id: 'u',
      created_at: 'now', updated_at: 'now',
    });
    const wf = await getWorkflow('abc');
    assert.strictEqual(wf.version, 3);
    assert.ok(calls[0].url.endsWith('/api/v1/copilot/workflows/abc'));
  });

  await test('createWorkflow POSTs payload and surfaces 409 as thrown', async () => {
    // Success first.
    responder = () => jsonResp(201, {
      id: 'nw', name: 'n', description: '', dsl_yaml: 'y',
      version: 1, owner_user_id: 'u',
      created_at: 'now', updated_at: 'now',
    });
    const created = await createWorkflow({ name: 'n', dsl_yaml: 'y' });
    assert.strictEqual(created.version, 1);
    const body = lastReqBody() as Record<string, unknown>;
    assert.deepStrictEqual(body, { name: 'n', dsl_yaml: 'y' });

    // Now 409.
    responder = () => new Response('duplicate name', { status: 409 });
    await assert.rejects(
      () => createWorkflow({ name: 'dup', dsl_yaml: 'y' }),
      /HTTP 409/,
    );
  });

  await test('updateWorkflow includes required version and surfaces 409 stale', async () => {
    responder = () => jsonResp(200, {
      id: 'x', name: 'n', description: 'new', dsl_yaml: 'y',
      version: 2, owner_user_id: null,
      created_at: 'now', updated_at: 'now',
    });
    const updated = await updateWorkflow('x', { version: 1, description: 'new' });
    assert.strictEqual(updated.version, 2);
    const body = lastReqBody() as Record<string, unknown>;
    assert.strictEqual(body.version, 1);
    assert.strictEqual(body.description, 'new');
    assert.strictEqual(calls[0].init?.method, 'PUT');

    // Stale.
    responder = () => new Response('stale version', { status: 409 });
    await assert.rejects(
      () => updateWorkflow('x', { version: 1 }),
      /HTTP 409/,
    );
  });

  await test('deleteWorkflow handles 204 without body', async () => {
    responder = () => new Response(null, { status: 204 });
    await deleteWorkflow('gone');  // must not throw
    assert.strictEqual(calls[0].init?.method, 'DELETE');
    assert.ok(calls[0].url.endsWith('/api/v1/copilot/workflows/gone'));
  });

  await test('deleteWorkflow throws on non-2xx / non-204', async () => {
    responder = () => new Response('nope', { status: 404 });
    await assert.rejects(
      () => deleteWorkflow('missing'),
      /HTTP 404/,
    );
  });

  await test('runStoredWorkflow POSTs to /{id}/run with inputs', async () => {
    responder = () => jsonResp(200, {
      workflow_name: 'stored', status: 'ok', duration_ms: 5,
      error: null,
      steps: [{
        id: 's', tool: 'list_drones', status: 'ok',
        resolved_args: {}, result: { ok: true },
        error: null, duration_ms: 5,
      }],
    });
    const run = await runStoredWorkflow('the-id', { k: 1 });
    assert.strictEqual(run.status, 'ok');
    assert.ok(calls[0].url.endsWith('/api/v1/copilot/workflows/the-id/run'));
    const body = lastReqBody() as Record<string, unknown>;
    assert.deepStrictEqual(body.inputs, { k: 1 });
  });

  // ================================================ history endpoints ===

  console.log('--- history ---');

  await test('listWorkflowRunHistory sends limit + workflow_id params', async () => {
    responder = () => jsonResp(200, [
      {
        id: 'r1', workflow_id: 'w1', workflow_name: 'wf',
        status: 'ok', duration_ms: 10, error: null,
        started_at: '2026-07-16T00:00:00Z',
      },
    ]);
    const rows = await listWorkflowRunHistory({
      limit: 25, workflow_id: 'w1',
    });
    assert.strictEqual(rows.length, 1);
    assert.strictEqual(rows[0].status, 'ok');
    assert.match(calls[0].url, /\/history\?/);
    assert.match(calls[0].url, /limit=25/);
    assert.match(calls[0].url, /workflow_id=w1/);
  });

  await test('listWorkflowRunHistory with no opts omits querystring', async () => {
    responder = () => jsonResp(200, []);
    await listWorkflowRunHistory();
    // Should end exactly with /history (no trailing ?).
    assert.ok(
      calls[0].url.endsWith('/api/v1/copilot/workflows/history'),
      `unexpected url: ${calls[0].url}`,
    );
  });

  await test('listWorkflowRunHistory throws on 4xx', async () => {
    responder = () => new Response('nope', { status: 403 });
    await assert.rejects(
      () => listWorkflowRunHistory(),
      /HTTP 403/,
    );
  });

  await test('getWorkflowRunHistoryDetail returns trace with steps', async () => {
    responder = () => jsonResp(200, {
      id: 'r1', workflow_id: null, workflow_name: 'inline',
      status: 'ok', duration_ms: 10, error: null,
      started_at: '2026-07-16T00:00:00Z',
      trace: {
        workflow_name: 'inline', status: 'ok',
        duration_ms: 10, error: null,
        steps: [{
          id: 'a', tool: 'echo', status: 'ok',
          resolved_args: { msg: 'hi' }, result: { echo: 'hi' },
          error: null, duration_ms: 2,
        }],
      },
    });
    const detail = await getWorkflowRunHistoryDetail('r1');
    assert.strictEqual(detail.id, 'r1');
    assert.strictEqual(detail.workflow_id, null);
    const trace = detail.trace as any;
    assert.strictEqual(trace.steps[0].tool, 'echo');
    assert.ok(calls[0].url.endsWith('/api/v1/copilot/workflows/history/r1'));
  });

  await test('getWorkflowRunHistoryDetail throws on 404', async () => {
    responder = () => new Response('not found', { status: 404 });
    await assert.rejects(
      () => getWorkflowRunHistoryDetail('nope'),
      /HTTP 404/,
    );
  });

  // ================================================= playbooks (T11.1) ===

  console.log('--- playbooks ---');

  await test('listPlaybooks returns the seed catalog', async () => {
    responder = () => jsonResp(200, [
      {
        slug: 'morning-inspection',
        name: '早查',
        description: '...',
        dsl_yaml: '# ok\nversion: "0.1"\nname: x\nsteps: []',
        sample_inputs: {},
        tags: ['ops', 'readonly'],
      },
    ]);
    const rows = await listPlaybooks();
    assert.strictEqual(rows.length, 1);
    assert.strictEqual(rows[0].slug, 'morning-inspection');
    assert.deepStrictEqual(rows[0].tags, ['ops', 'readonly']);
    assert.ok(
      calls[0].url.endsWith('/api/v1/copilot/workflows/playbooks'),
    );
  });

  await test('listPlaybooks with tag param', async () => {
    responder = () => jsonResp(200, []);
    await listPlaybooks({ tag: 'domain' });
    assert.match(calls[0].url, /\/playbooks\?tag=domain$/);
  });

  await test('listPlaybooks with tag+q composes', async () => {
    responder = () => jsonResp(200, []);
    await listPlaybooks({ tag: 'domain', q: '巡' });
    assert.match(calls[0].url, /tag=domain/);
    assert.match(calls[0].url, /q=/); // urlencoded, don't assert value
  });

  await test('listPlaybooks throws on 500', async () => {
    responder = () => new Response('boom', { status: 500 });
    await assert.rejects(
      () => listPlaybooks(),
      /HTTP 500/,
    );
  });

  await test('getPlaybook returns DSL for a specific slug', async () => {
    responder = () => jsonResp(200, {
      slug: 'compliance-patrol',
      name: '合规巡查',
      description: '...',
      dsl_yaml: '# doc\nversion: "0.1"\nname: y\nsteps: []',
      sample_inputs: {},
      tags: ['ops', 'audit'],
    });
    const pb = await getPlaybook('compliance-patrol');
    assert.strictEqual(pb.slug, 'compliance-patrol');
    assert.match(pb.dsl_yaml, /^# doc/);
    assert.ok(
      calls[0].url.endsWith(
        '/api/v1/copilot/workflows/playbooks/compliance-patrol',
      ),
    );
  });

  await test('getPlaybook throws on 404', async () => {
    responder = () => new Response('nope', { status: 404 });
    await assert.rejects(
      () => getPlaybook('missing'),
      /HTTP 404/,
    );
  });

  // ================================================ T12.3: schedules ==

  await test('listSchedules returns rows', async () => {
    responder = () => jsonResp(200, [
      {
        id: 'sid1', workflow_id: 'wf1', cron_expr: '0 9 * * *',
        inputs: {}, enabled: true,
        created_at: '2026-07-16T00:00:00Z',
        updated_at: '2026-07-16T00:00:00Z',
        next_fire_at: '2026-07-17T09:00:00Z',
        last_fire_at: null, last_fire_status: null, last_fire_run_id: null,
      },
    ]);
    const rows = await listSchedules();
    assert.strictEqual(rows.length, 1);
    assert.strictEqual(rows[0].cron_expr, '0 9 * * *');
    assert.ok(calls[0].url.endsWith('/schedules'));
  });

  await test('listSchedules with workflow_id filter', async () => {
    responder = () => jsonResp(200, []);
    await listSchedules({ workflow_id: 'wf-abc', limit: 50 });
    assert.match(calls[0].url, /workflow_id=wf-abc/);
    assert.match(calls[0].url, /limit=50/);
  });

  await test('createSchedule POSTs the payload', async () => {
    responder = () => jsonResp(201, {
      id: 'newid', workflow_id: 'wf1', cron_expr: '0 9 * * *',
      inputs: { drone_id: 'x' }, enabled: true,
      created_at: 'x', updated_at: 'x',
      next_fire_at: 'x', last_fire_at: null,
      last_fire_status: null, last_fire_run_id: null,
    });
    const row = await createSchedule({
      workflow_id: 'wf1',
      cron_expr: '0 9 * * *',
      inputs: { drone_id: 'x' },
    });
    assert.strictEqual(row.id, 'newid');
    assert.strictEqual(calls[0].init?.method, 'POST');
    const body = lastReqBody() as any;
    assert.strictEqual(body.workflow_id, 'wf1');
    assert.strictEqual(body.cron_expr, '0 9 * * *');
    assert.deepStrictEqual(body.inputs, { drone_id: 'x' });
    assert.strictEqual(body.enabled, true);  // default applied
  });

  await test('createSchedule throws on 400 with detail', async () => {
    responder = () => new Response('invalid cron_expr', { status: 400 });
    await assert.rejects(
      () => createSchedule({
        workflow_id: 'wf1',
        cron_expr: 'bad',
      }),
      /HTTP 400/,
    );
  });

  await test('updateSchedule PATCHes and returns updated row', async () => {
    responder = () => jsonResp(200, {
      id: 'sid1', workflow_id: 'wf1', cron_expr: '0 9 * * *',
      inputs: {}, enabled: false,
      created_at: 'x', updated_at: 'y',
      next_fire_at: null, last_fire_at: null,
      last_fire_status: null, last_fire_run_id: null,
    });
    const row = await updateSchedule('sid1', { enabled: false });
    assert.strictEqual(row.enabled, false);
    assert.strictEqual(calls[0].init?.method, 'PATCH');
    assert.match(calls[0].url, /\/schedules\/sid1$/);
    const body = lastReqBody() as any;
    assert.strictEqual(body.enabled, false);
  });

  await test('updateSchedule 404 throws', async () => {
    responder = () => new Response('not found', { status: 404 });
    await assert.rejects(
      () => updateSchedule('missing', { enabled: true }),
      /HTTP 404/,
    );
  });

  await test('deleteSchedule 204 resolves', async () => {
    responder = () => new Response(null, { status: 204 });
    await deleteSchedule('sid1');  // should not throw
    assert.strictEqual(calls[0].init?.method, 'DELETE');
    assert.match(calls[0].url, /\/schedules\/sid1$/);
  });

  await test('deleteSchedule 404 throws', async () => {
    responder = () => new Response('gone', { status: 404 });
    await assert.rejects(
      () => deleteSchedule('missing'),
      /HTTP 404/,
    );
  });

  // ============================================================== summary =

  console.log(`\n${ran - failed}/${ran} passed`);
  if (failed) {
    process.exit(1);
  }
}

runTests();
