/**
 * E2.5b · Airspace calendar API client tests.
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
  checkAirspaceConflicts, createCalendarEntry,
  deleteCalendarEntry, listCalendarEntries,
} from '../lib/airspace_calendar';

function reset() {
  calls.length = 0;
  responder = () => new Response('{}', { status: 200 });
}

async function runTests() {

  await test('listCalendarEntries no filters, no querystring', async () => {
    reset();
    responder = () => jsonResp(200, []);
    await listCalendarEntries();
    assert.ok(calls[0].url.endsWith('/airspace-calendar'));
  });

  await test('listCalendarEntries filters propagate', async () => {
    reset();
    responder = () => jsonResp(200, []);
    await listCalendarEntries({
      start_ts: '2026-01-01T00:00:00Z',
      end_ts: '2026-12-31T23:59:59Z',
      source: 'uom', limit: 50,
    });
    assert.match(calls[0].url, /start_ts=2026-01-01/);
    assert.match(calls[0].url, /source=uom/);
    assert.match(calls[0].url, /limit=50/);
  });

  await test('createCalendarEntry POST full payload', async () => {
    reset();
    responder = () => jsonResp(201, { id: 'x' });
    await createCalendarEntry({
      source: 'local',
      title: 'test',
      geo_polygon: [[103.0, 30.5], [103.1, 30.5], [103.1, 30.6]],
      start_ts: '2026-07-16T08:00:00Z',
      end_ts: '2026-07-16T10:00:00Z',
      min_alt_m: 30,
      max_alt_m: 120,
    });
    assert.strictEqual(calls[0].init?.method, 'POST');
    const body = JSON.parse((calls[0].init?.body as string) ?? '{}');
    assert.strictEqual(body.title, 'test');
    assert.strictEqual(body.max_alt_m, 120);
  });

  await test('createCalendarEntry throws on 400', async () => {
    reset();
    responder = () => new Response('bad', { status: 400 });
    await assert.rejects(
      () => createCalendarEntry({
        title: 'x',
        geo_polygon: [],
        start_ts: '2026-07-16T08:00:00Z',
        end_ts: '2026-07-16T07:00:00Z',
      }),
      /HTTP 400/,
    );
  });

  await test('deleteCalendarEntry DELETE + 204 resolves', async () => {
    reset();
    responder = () => new Response(null, { status: 204 });
    await deleteCalendarEntry('id-1');
    assert.strictEqual(calls[0].init?.method, 'DELETE');
  });

  await test('checkAirspaceConflicts POST + return shape', async () => {
    reset();
    responder = () => jsonResp(200, {
      count: 2,
      conflicts: [
        { id: 'a', source: 'uom', title: 't1' },
        { id: 'b', source: 'notam', title: 't2' },
      ],
    });
    const res = await checkAirspaceConflicts({
      geo_polygon: [[103.0, 30.5]],
      start_ts: '2026-07-16T08:00:00Z',
      end_ts: '2026-07-16T10:00:00Z',
    });
    assert.strictEqual(res.count, 2);
    assert.strictEqual(res.conflicts[0].source, 'uom');
    assert.match(calls[0].url, /check-conflicts$/);
  });

  await test('checkAirspaceConflicts propagates alt + exclude_ids', async () => {
    reset();
    responder = () => jsonResp(200, { count: 0, conflicts: [] });
    await checkAirspaceConflicts({
      geo_polygon: [[103.0, 30.5]],
      start_ts: 't1', end_ts: 't2',
      min_alt_m: 100, max_alt_m: 200,
      exclude_ids: ['id-self'],
    });
    const body = JSON.parse((calls[0].init?.body as string) ?? '{}');
    assert.strictEqual(body.min_alt_m, 100);
    assert.deepStrictEqual(body.exclude_ids, ['id-self']);
  });
}

runTests()
  .then(() => { globalThis.fetch = origFetch; })
  .catch((err) => {
    globalThis.fetch = origFetch;
    console.error(err);
    process.exit(1);
  });
