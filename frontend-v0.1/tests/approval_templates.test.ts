/**
 * E2.5 · Approval templates API client tests.
 */
import assert from 'node:assert';
import test from 'node:test';

interface FetchCall { url: string; init?: RequestInit; }
const calls: FetchCall[] = [];
let responder: (call: FetchCall) => Response = () =>
  new Response('{}', { status: 200 });

const origFetch = globalThis.fetch;
globalThis.fetch = ((input: any, init?: RequestInit) => {
  const url = typeof input === 'string' ? input : input.url;
  calls.push({ url, init });
  return Promise.resolve(responder({ url, init }));
}) as any;

function jsonResp(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

import {
  applyApprovalTemplate,
  createApprovalTemplate,
  deleteApprovalTemplate,
  getApprovalTemplate,
  listApprovalTemplates,
  updateApprovalTemplate,
} from '../lib/approval_templates';

function reset() {
  calls.length = 0;
  responder = () => new Response('{}', { status: 200 });
}

const FAKE_ROW = {
  id: 'tmpl-1', org_id: 'o', author_user_id: 'u',
  name: '巡线', category: 'routine', purpose: null,
  pilot_name: null, pilot_license: null,
  aircraft_reg: null, aircraft_model: null,
  insurance_no: null, max_alt_m: null, min_alt_m: null,
  default_area_polygon: null, authorities_preset: [],
  checklist_json: [], apply_count: 0,
  created_at: '', updated_at: '',
};

async function runTests() {

  await test('createApprovalTemplate POSTs full payload', async () => {
    reset();
    responder = () => jsonResp(201, FAKE_ROW);
    await createApprovalTemplate({
      name: '巡线',
      category: 'routine',
      authorities_preset: [{ code: 'uom', name: 'UOM' }],
    });
    assert.strictEqual(calls[0].init?.method, 'POST');
    const body = JSON.parse((calls[0].init?.body as string) ?? '{}');
    assert.strictEqual(body.name, '巡线');
    assert.strictEqual(body.category, 'routine');
    assert.deepStrictEqual(body.authorities_preset,
      [{ code: 'uom', name: 'UOM' }]);
  });

  await test('createApprovalTemplate throws with detail on 400', async () => {
    reset();
    responder = () => new Response('duplicate name', { status: 400 });
    await assert.rejects(
      () => createApprovalTemplate({ name: 'x' }),
      /HTTP 400/,
    );
  });

  await test('listApprovalTemplates no params, no querystring', async () => {
    reset();
    responder = () => jsonResp(200, [FAKE_ROW]);
    await listApprovalTemplates();
    assert.ok(calls[0].url.endsWith('/approval-templates'));
  });

  await test('listApprovalTemplates propagates filters', async () => {
    reset();
    responder = () => jsonResp(200, []);
    await listApprovalTemplates({ category: 'night', limit: 5 });
    assert.match(calls[0].url, /category=night/);
    assert.match(calls[0].url, /limit=5/);
  });

  await test('getApprovalTemplate URL-encodes id', async () => {
    reset();
    responder = () => jsonResp(200, FAKE_ROW);
    await getApprovalTemplate('id with space');
    assert.ok(calls[0].url.endsWith('id%20with%20space'));
  });

  await test('updateApprovalTemplate PATCH partial body', async () => {
    reset();
    responder = () => jsonResp(200, FAKE_ROW);
    await updateApprovalTemplate('tmpl-1', { pilot_name: 'Alice' });
    assert.strictEqual(calls[0].init?.method, 'PATCH');
    const body = JSON.parse((calls[0].init?.body as string) ?? '{}');
    assert.strictEqual(body.pilot_name, 'Alice');
  });

  await test('deleteApprovalTemplate resolves on 204', async () => {
    reset();
    responder = () => new Response(null, { status: 204 });
    await deleteApprovalTemplate('tmpl-1');
    assert.strictEqual(calls[0].init?.method, 'DELETE');
  });

  await test('deleteApprovalTemplate throws on 403', async () => {
    reset();
    responder = () => new Response('nope', { status: 403 });
    await assert.rejects(
      () => deleteApprovalTemplate('tmpl-1'),
      /HTTP 403/,
    );
  });

  await test('applyApprovalTemplate returns approval_id + status', async () => {
    reset();
    responder = () => jsonResp(200, {
      approval_id: 'appr-1', status: 'draft',
    });
    const res = await applyApprovalTemplate('tmpl-1', {
      title: 'flight',
      start_ts: '2026-07-16T08:00:00Z',
      end_ts: '2026-07-16T10:00:00Z',
    });
    assert.strictEqual(res.approval_id, 'appr-1');
    assert.strictEqual(res.status, 'draft');
    assert.match(calls[0].url, /\/apply$/);
    assert.strictEqual(calls[0].init?.method, 'POST');
  });

  await test('applyApprovalTemplate propagates overrides', async () => {
    reset();
    responder = () => jsonResp(200, {
      approval_id: 'a', status: 'draft',
    });
    await applyApprovalTemplate('tmpl-1', {
      title: 'x',
      start_ts: 't1',
      end_ts: 't2',
      max_alt_m_override: 80.0,
      area_polygon_override: [[103.0, 30.5], [103.1, 30.6]],
    });
    const body = JSON.parse((calls[0].init?.body as string) ?? '{}');
    assert.strictEqual(body.max_alt_m_override, 80.0);
    assert.deepStrictEqual(
      body.area_polygon_override,
      [[103.0, 30.5], [103.1, 30.6]],
    );
  });

  await test('applyApprovalTemplate throws on 404 template missing', async () => {
    reset();
    responder = () => new Response('template not found', { status: 404 });
    await assert.rejects(
      () => applyApprovalTemplate('missing', {
        title: 'x', start_ts: 't', end_ts: 't',
      }),
      /HTTP 404/,
    );
  });
}

runTests()
  .then(() => { globalThis.fetch = origFetch; })
  .catch((err) => {
    globalThis.fetch = origFetch;
    console.error(err);
    process.exit(1);
  });
