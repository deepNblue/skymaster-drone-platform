/**
 * T11.3 · Community Playbook API client tests.
 *
 * Uses the same fetch-monkey-patch pattern as copilot_workflows.test.ts.
 */
import assert from 'node:assert';
import test from 'node:test';

interface FetchCall {
  url: string;
  init?: RequestInit;
}
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

// Import under test AFTER fetch is stubbed.
import {
  deleteCommunityPlaybook,
  getCommunityPlaybook,
  installCommunityPlaybook,
  listCommunityPlaybooks,
  moderateCommunityPlaybook,
  submitCommunityPlaybook,
} from '../lib/community_playbooks';

function reset() {
  calls.length = 0;
  responder = () => new Response('{}', { status: 200 });
}

async function runTests() {

  await test('submitCommunityPlaybook POSTs full payload', async () => {
    reset();
    responder = () => jsonResp(201, {
      slug: 'user-mine', name: 'n', description: '', dsl_yaml: 'x',
      sample_inputs: {}, tags: [], status: 'pending',
      rejected_reason: null, install_count: 0,
      author_user_id: 'u', org_id: 'o',
      created_at: '', updated_at: '',
    });
    const row = await submitCommunityPlaybook({
      slug: 'mine',
      name: 'n',
      description: 'd',
      dsl_yaml: 'version: "0.1"\nname: n\nsteps: []',
      sample_inputs: { foo: 1 },
      tags: ['t1', 't2'],
    });
    assert.strictEqual(row.slug, 'user-mine');
    assert.strictEqual(calls[0].init?.method, 'POST');
    const body = JSON.parse((calls[0].init?.body as string) ?? '{}');
    assert.strictEqual(body.slug, 'mine');
    assert.strictEqual(body.name, 'n');
    assert.strictEqual(body.description, 'd');
    assert.deepStrictEqual(body.sample_inputs, { foo: 1 });
    assert.deepStrictEqual(body.tags, ['t1', 't2']);
  });

  await test('submitCommunityPlaybook throws on 400 with body', async () => {
    reset();
    responder = () => new Response('slug taken', { status: 400 });
    await assert.rejects(
      () => submitCommunityPlaybook({
        slug: 'x', name: 'x', dsl_yaml: 'x',
      }),
      /HTTP 400/,
    );
  });

  await test('listCommunityPlaybooks default calls with no params', async () => {
    reset();
    responder = () => jsonResp(200, []);
    await listCommunityPlaybooks();
    // no query string at all
    assert.ok(calls[0].url.endsWith('/community-playbooks'));
  });

  await test('listCommunityPlaybooks propagates all filters', async () => {
    reset();
    responder = () => jsonResp(200, []);
    await listCommunityPlaybooks({
      status: 'approved',
      include_own: true,
      limit: 20,
    });
    assert.match(calls[0].url, /status=approved/);
    assert.match(calls[0].url, /include_own=true/);
    assert.match(calls[0].url, /limit=20/);
  });

  await test('getCommunityPlaybook URL-encodes slug', async () => {
    reset();
    responder = () => jsonResp(200, {
      slug: 'user-name', name: 'n', description: '', dsl_yaml: '',
      sample_inputs: {}, tags: [], status: 'approved',
      rejected_reason: null, install_count: 0,
      author_user_id: 'u', org_id: 'o',
      created_at: '', updated_at: '',
    });
    await getCommunityPlaybook('user name');
    assert.ok(calls[0].url.endsWith('user%20name'));
  });

  await test('getCommunityPlaybook throws on 404', async () => {
    reset();
    responder = () => new Response('nope', { status: 404 });
    await assert.rejects(
      () => getCommunityPlaybook('missing'),
      /HTTP 404/,
    );
  });

  await test('deleteCommunityPlaybook 204 resolves without throwing', async () => {
    reset();
    responder = () => new Response(null, { status: 204 });
    await deleteCommunityPlaybook('slug1');
    assert.strictEqual(calls[0].init?.method, 'DELETE');
  });

  await test('deleteCommunityPlaybook 403 throws with detail', async () => {
    reset();
    responder = () => new Response('not yours', { status: 403 });
    await assert.rejects(
      () => deleteCommunityPlaybook('slug1'),
      /HTTP 403/,
    );
  });

  await test('moderateCommunityPlaybook approve without reason', async () => {
    reset();
    responder = () => jsonResp(200, {
      slug: 'user-mine', name: 'n', description: '', dsl_yaml: '',
      sample_inputs: {}, tags: [], status: 'approved',
      rejected_reason: null, install_count: 0,
      author_user_id: 'u', org_id: 'o',
      created_at: '', updated_at: '',
    });
    const row = await moderateCommunityPlaybook('user-mine', true);
    assert.strictEqual(row.status, 'approved');
    assert.strictEqual(calls[0].init?.method, 'POST');
    assert.match(calls[0].url, /\/moderate$/);
    const body = JSON.parse((calls[0].init?.body as string) ?? '{}');
    assert.strictEqual(body.approve, true);
    assert.strictEqual(body.reason, null);
  });

  await test('moderateCommunityPlaybook reject requires reason in body', async () => {
    reset();
    responder = () => jsonResp(200, {
      slug: 'user-mine', name: 'n', description: '', dsl_yaml: '',
      sample_inputs: {}, tags: [], status: 'rejected',
      rejected_reason: '涉密工具, 禁止公开', install_count: 0,
      author_user_id: 'u', org_id: 'o',
      created_at: '', updated_at: '',
    });
    const row = await moderateCommunityPlaybook(
      'user-mine', false, '涉密工具, 禁止公开',
    );
    assert.strictEqual(row.status, 'rejected');
    assert.strictEqual(row.rejected_reason, '涉密工具, 禁止公开');
    const body = JSON.parse((calls[0].init?.body as string) ?? '{}');
    assert.strictEqual(body.approve, false);
    assert.strictEqual(body.reason, '涉密工具, 禁止公开');
  });

  await test('installCommunityPlaybook returns workflow info', async () => {
    reset();
    responder = () => jsonResp(200, {
      workflow_id: 'wf-1', workflow_name: 'installed',
    });
    const result = await installCommunityPlaybook('user-shared');
    assert.strictEqual(result.workflow_id, 'wf-1');
    assert.strictEqual(result.workflow_name, 'installed');
    assert.strictEqual(calls[0].init?.method, 'POST');
    assert.match(calls[0].url, /\/install$/);
  });

  await test('installCommunityPlaybook throws with detail on 403', async () => {
    reset();
    responder = () => new Response('cannot fork non-approved', { status: 403 });
    await assert.rejects(
      () => installCommunityPlaybook('user-x'),
      /HTTP 403/,
    );
  });
}

runTests()
  .then(() => {
    globalThis.fetch = origFetch;
  })
  .catch((err) => {
    globalThis.fetch = origFetch;
    console.error(err);
    process.exit(1);
  });
