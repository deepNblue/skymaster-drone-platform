/**
 * D3.1/D3.2 · Scene frame client tests.
 * node --test compatible, mocks fetch (no top-level await).
 */
import assert from 'node:assert';
import test from 'node:test';

interface FetchCall {
  url: string;
  method: string;
  body: unknown;
}
const calls: FetchCall[] = [];
let responder: (c: FetchCall) => Response = () =>
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
  const c: FetchCall = {
    url,
    method: (init?.method ?? 'GET').toUpperCase(),
    body: init?.body ? JSON.parse(init.body as string) : undefined,
  };
  calls.push(c);
  return Promise.resolve(responder(c));
};

// Stub localStorage so token() doesn't blow up.
(globalThis as any).window = {} as any;
(globalThis as any).localStorage = {
  _s: { skymaster_token: 't' } as Record<string, string>,
  getItem(k: string) {
    return this._s[k] ?? null;
  },
} as any;

import {
  averagePsnr, bulkCreateFrames, createFrame, deleteFrame, getFrame,
  getTimelineSummary, LIGHTING_LABEL, lightingRuns, listFrames,
  nearestKeyframe, updateFrame,
} from '../lib/scene_frame';

test('listFrames without opts', async () => {
  reset();
  responder = () => jsonResp(200, []);
  await listFrames('s1');
  assert.match(calls[0].url, /\/scenes\/s1\/frames$/);
});

test('listFrames with filters', async () => {
  reset();
  responder = () => jsonResp(200, []);
  await listFrames('s1', { only_keyframes: true, lighting: 'day' });
  assert.match(calls[0].url, /only_keyframes=true/);
  assert.match(calls[0].url, /lighting=day/);
});

test('getFrame returns object', async () => {
  reset();
  responder = () => jsonResp(200, {
    id: 'f1', scene_id: 's1', frame_index: 3,
    is_keyframe: true, captured_at: null,
    psnr_frame: null, lighting: null, notes: null,
    meta: {}, created_at: '', updated_at: '',
  });
  const r = await getFrame('s1', 3);
  assert.strictEqual(r.frame_index, 3);
  assert.strictEqual(r.is_keyframe, true);
  assert.match(calls[0].url, /\/scenes\/s1\/frames\/3$/);
});

test('createFrame posts payload', async () => {
  reset();
  responder = () => jsonResp(201, { id: 'f1', frame_index: 5 });
  await createFrame('s1', {
    frame_index: 5, is_keyframe: true, lighting: 'night',
  });
  assert.strictEqual(calls[0].method, 'POST');
  assert.strictEqual((calls[0].body as any).frame_index, 5);
  assert.strictEqual((calls[0].body as any).lighting, 'night');
});

test('bulkCreateFrames envelopes frames', async () => {
  reset();
  responder = () => jsonResp(201, []);
  await bulkCreateFrames('s1', [
    { frame_index: 0 }, { frame_index: 1 },
  ]);
  assert.strictEqual((calls[0].body as any).frames.length, 2);
  assert.match(calls[0].url, /\/frames\/bulk$/);
});

test('updateFrame patches', async () => {
  reset();
  responder = () => jsonResp(200, { frame_index: 5, is_keyframe: true });
  await updateFrame('s1', 5, { is_keyframe: true });
  assert.strictEqual(calls[0].method, 'PATCH');
  assert.strictEqual((calls[0].body as any).is_keyframe, true);
});

test('deleteFrame issues DELETE', async () => {
  reset();
  responder = () => new Response(null, { status: 204 });
  await deleteFrame('s1', 5);
  assert.strictEqual(calls[0].method, 'DELETE');
  assert.match(calls[0].url, /\/frames\/5$/);
});

test('getTimelineSummary parses response', async () => {
  reset();
  responder = () => jsonResp(200, {
    scene_id: 's1', total_frames: 5, keyframe_count: 2,
    keyframe_indices: [0, 3], captured_at_start: null,
    captured_at_end: null, avg_psnr: 25.0,
  });
  const s = await getTimelineSummary('s1');
  assert.strictEqual(s.total_frames, 5);
  assert.deepStrictEqual(s.keyframe_indices, [0, 3]);
});

test('http error surfaces', async () => {
  reset();
  responder = () => new Response('bad', { status: 400 });
  await assert.rejects(
    () => createFrame('s1', { frame_index: 0 }), /HTTP 400/,
  );
});

// -- Pure helpers --------------------------------------------------

test('nearestKeyframe picks closest', () => {
  const frames = [
    { frame_index: 0, is_keyframe: true },
    { frame_index: 1, is_keyframe: false },
    { frame_index: 2, is_keyframe: false },
    { frame_index: 5, is_keyframe: true },
    { frame_index: 8, is_keyframe: false },
    { frame_index: 10, is_keyframe: true },
  ];
  assert.strictEqual(nearestKeyframe(frames, 3), 5);
  assert.strictEqual(nearestKeyframe(frames, 1), 0);
  assert.strictEqual(nearestKeyframe(frames, 9), 10);
  assert.strictEqual(nearestKeyframe(frames, 5), 5);
});

test('nearestKeyframe with no keyframes returns target', () => {
  const frames = [
    { frame_index: 0, is_keyframe: false },
    { frame_index: 1, is_keyframe: false },
  ];
  assert.strictEqual(nearestKeyframe(frames, 3), 3);
});

test('averagePsnr ignores null values', () => {
  const frames = [
    { psnr_frame: 20 }, { psnr_frame: null }, { psnr_frame: 30 },
  ] as any;
  assert.strictEqual(averagePsnr(frames), 25);
});

test('averagePsnr all null returns null', () => {
  const frames = [{ psnr_frame: null }, { psnr_frame: null }] as any;
  assert.strictEqual(averagePsnr(frames), null);
});

test('lightingRuns groups contiguous', () => {
  const frames = [
    { frame_index: 0, lighting: 'day' },
    { frame_index: 1, lighting: 'day' },
    { frame_index: 2, lighting: 'day' },
    { frame_index: 3, lighting: 'dusk' },
    { frame_index: 4, lighting: 'night' },
    { frame_index: 5, lighting: 'night' },
  ] as any;
  const runs = lightingRuns(frames);
  assert.strictEqual(runs.length, 3);
  assert.deepStrictEqual(runs[0], {
    lighting: 'day', start: 0, end: 2,
  });
  assert.deepStrictEqual(runs[1], {
    lighting: 'dusk', start: 3, end: 3,
  });
  assert.deepStrictEqual(runs[2], {
    lighting: 'night', start: 4, end: 5,
  });
});

test('lightingRuns empty', () => {
  assert.deepStrictEqual(lightingRuns([]), []);
});

test('LIGHTING_LABEL exposes Chinese labels', () => {
  assert.strictEqual(LIGHTING_LABEL.day, '白天');
  assert.strictEqual(LIGHTING_LABEL.dusk, '黄昏');
  assert.strictEqual(LIGHTING_LABEL.overcast, '阴天');
});
