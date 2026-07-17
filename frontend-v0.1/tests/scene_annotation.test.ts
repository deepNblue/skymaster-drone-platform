/**
 * v2.1 · Scene annotation client tests.
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
  GEOM_KIND_LABEL, SEVERITY_COLOR, SEVERITY_LABEL,
  createAnnotation, createReply, deleteAnnotation,
  getAnnotationStats, lineLengthM, listAnnotations,
  listReplies, polygonAreaM2, updateAnnotation,
} from '../lib/scene_annotation';

function reset() {
  calls.length = 0;
  responder = () => new Response('{}', { status: 200 });
}

async function runTests() {

  await test('geometry helpers line length 3-4-5', () => {
    assert.strictEqual(lineLengthM([[0, 0, 0], [3, 4, 0]]), 5);
    // Multi-segment additive:
    assert.strictEqual(
      lineLengthM([[0, 0, 0], [3, 0, 0], [3, 4, 0]]),
      7,
    );
  });

  await test('geometry helper polygon area shoelace', () => {
    const rect = [[0, 0, 0], [10, 0, 0], [10, 5, 0], [0, 5, 0]];
    assert.strictEqual(polygonAreaM2(rect), 50);
    // <3 vertices -> 0
    assert.strictEqual(polygonAreaM2([[0, 0, 0], [1, 0, 0]]), 0);
  });

  await test('severity + geom_kind label maps', () => {
    assert.strictEqual(SEVERITY_COLOR.critical, 'red');
    assert.strictEqual(SEVERITY_LABEL.high, '高');
    assert.strictEqual(GEOM_KIND_LABEL.polygon, '面');
  });

  await test('listAnnotations propagates all filters', async () => {
    reset();
    responder = () => jsonResp(200, []);
    await listAnnotations('s1', {
      layer: 'defect',
      severity: 'critical',
      only_unresolved: true,
      frame_index: 5,
    });
    assert.match(calls[0].url, /layer=defect/);
    assert.match(calls[0].url, /severity=critical/);
    assert.match(calls[0].url, /only_unresolved=true/);
    assert.match(calls[0].url, /frame_index=5/);
  });

  await test('createAnnotation POSTs payload', async () => {
    reset();
    responder = () => jsonResp(201, { id: 'a1' });
    await createAnnotation('s1', {
      geom_kind: 'polygon',
      geom_vertices: [[0, 0, 0], [1, 0, 0], [1, 1, 0]],
      label: '范围',
      severity: 'high',
    });
    assert.strictEqual(calls[0].init?.method, 'POST');
    const body = JSON.parse((calls[0].init?.body as string) ?? '{}');
    assert.strictEqual(body.geom_kind, 'polygon');
    assert.strictEqual(body.severity, 'high');
  });

  await test('updateAnnotation PATCH', async () => {
    reset();
    responder = () => jsonResp(200, { id: 'a1', resolved: true });
    await updateAnnotation('a1', { resolved: true });
    assert.strictEqual(calls[0].init?.method, 'PATCH');
    assert.match(calls[0].url, /annotations\/a1$/);
  });

  await test('deleteAnnotation DELETE 204', async () => {
    reset();
    responder = () => new Response(null, { status: 204 });
    await deleteAnnotation('a1');
    assert.strictEqual(calls[0].init?.method, 'DELETE');
  });

  await test('getAnnotationStats', async () => {
    reset();
    responder = () => jsonResp(200, {
      scene_id: 's1', total: 4, unresolved: 3,
      by_severity: { info: 1, low: 0, medium: 0, high: 2, critical: 1 },
    });
    const r = await getAnnotationStats('s1');
    assert.strictEqual(r.total, 4);
    assert.strictEqual(r.unresolved, 3);
    assert.strictEqual(r.by_severity.critical, 1);
  });

  await test('replies list + create', async () => {
    reset();
    responder = () => jsonResp(200, []);
    await listReplies('a1');
    assert.match(calls[0].url, /replies$/);

    reset();
    responder = () => jsonResp(201, { id: 'r1' });
    await createReply('a1', '现场已核查');
    assert.strictEqual(calls[0].init?.method, 'POST');
    const body = JSON.parse((calls[0].init?.body as string) ?? '{}');
    assert.strictEqual(body.body, '现场已核查');
  });

  await test('http error surfaces', async () => {
    reset();
    responder = () => new Response('bad', { status: 400 });
    await assert.rejects(
      () => createAnnotation('s1', {
        geom_kind: 'point',
        geom_vertices: [[0, 0, 0]],
        label: 'x',
      }),
      /HTTP 400/,
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
