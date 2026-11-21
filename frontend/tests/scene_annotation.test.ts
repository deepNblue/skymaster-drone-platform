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
  listReplies, polygonAreaM2, searchAnnotations,
  suggestAnnotation, updateAnnotation,
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

  await test('searchAnnotations forwards query + limit', async () => {
    reset();
    responder = () => jsonResp(200, {
      parsed: {
        raw: '裂缝', keywords: ['裂缝'],
        geom_kinds: ['line'], severities: [], layers: [],
      },
      hits: [{
        annotation: { id: 'a1', label: '断裂', geom_kind: 'line' },
        score: 5,
        matched_reasons: ['label 命中 裂缝'],
      }],
    });
    const r = await searchAnnotations('s1', '裂缝', 10);
    assert.match(calls[0].url, /annotation-search\/scenes\/s1/);
    assert.match(calls[0].url, /query=%E8%A3%82%E7%BC%9D/);
    assert.match(calls[0].url, /limit=10/);
    assert.strictEqual(r.hits.length, 1);
    assert.strictEqual(r.hits[0].score, 5);
  });

  await test('suggestAnnotation returns suggestion', async () => {
    reset();
    responder = () => jsonResp(200, {
      query: '淤积区严重',
      suggestion: {
        geom_kind: 'polygon',
        severity: 'critical',
        layer: 'default',
        label: '淤积区严重',
      },
    });
    const r = await suggestAnnotation('淤积区严重');
    assert.strictEqual(r.suggestion?.geom_kind, 'polygon');
    assert.strictEqual(r.suggestion?.severity, 'critical');
  });
}

runTests()
  .then(() => { globalThis.fetch = origFetch; })
  .catch((err) => {
    globalThis.fetch = origFetch;
    console.error(err);
    process.exit(1);
  });
