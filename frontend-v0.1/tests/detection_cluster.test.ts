/**
 * E3.2 · Detection cluster analytics tests.
 */
import assert from 'node:assert';
import test from 'node:test';

const calls: Array<{ url: string; method: string }> = [];
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
  calls.push({ url, method: (init?.method ?? 'GET').toUpperCase() });
  return Promise.resolve(responder());
};
(globalThis as any).window = {} as any;
(globalThis as any).localStorage = {
  _s: { skymaster_token: 't' } as Record<string, string>,
  getItem(k: string) { return this._s[k] ?? null; },
} as any;

import {
  CLUSTER_SEV_COLOR, ClusterAnalytics, DetectionCluster,
  getClusterAnalytics, severityForCluster, toHeatmapGrid, topLabels,
} from '../lib/detection_cluster';

// -- REST ----------------------------------------------------------

test('getClusterAnalytics no opts', async () => {
  reset();
  responder = () => jsonResp(200, {
    window_seconds: 3600, total_detections: 0,
    cluster_count: 0, clusters: [], by_label: [],
  });
  const r = await getClusterAnalytics();
  assert.strictEqual(r.total_detections, 0);
  assert.strictEqual(calls[0].url.includes('?'), false);
});

test('getClusterAnalytics forwards all params', async () => {
  reset();
  responder = () => jsonResp(200, {
    window_seconds: 60, total_detections: 0,
    cluster_count: 0, clusters: [], by_label: [],
  });
  await getClusterAnalytics({
    label: 'person', since_seconds: 60,
    geo_tol_m: 100, time_tol_s: 45,
  });
  assert.match(calls[0].url, /label=person/);
  assert.match(calls[0].url, /since_seconds=60/);
  assert.match(calls[0].url, /geo_tol_m=100/);
  assert.match(calls[0].url, /time_tol_s=45/);
});

test('HTTP error surfaces', async () => {
  reset();
  responder = () => new Response('bad', { status: 403 });
  await assert.rejects(() => getClusterAnalytics(), /HTTP 403/);
});

// -- Pure helpers --------------------------------------------------

function mkCluster(
  overrides: Partial<DetectionCluster> = {},
): DetectionCluster {
  return {
    label: 'person', member_count: 1,
    first_seen_at: '2026-07-17T03:00:00Z',
    last_seen_at: '2026-07-17T03:00:10Z',
    duration_s: 10,
    centroid_lat: 30.6, centroid_lng: 104.0,
    peak_confidence: 0.9,
    drone_ids: ['d1'], member_ids: ['a'],
    ...overrides,
  };
}

test('toHeatmapGrid empty', () => {
  assert.deepStrictEqual(toHeatmapGrid([]), []);
});

test('toHeatmapGrid buckets nearby clusters same cell', () => {
  const grid = toHeatmapGrid([
    mkCluster({ centroid_lat: 30.6000, centroid_lng: 104.0, member_count: 3 }),
    mkCluster({
      centroid_lat: 30.6002, centroid_lng: 104.0,   // <0.001 diff
      member_count: 5, label: 'vehicle',
    }),
  ], 0.01);
  assert.strictEqual(grid.length, 1);
  assert.strictEqual(grid[0].weight, 8);
  assert.deepStrictEqual(grid[0].labels.sort(), ['person', 'vehicle']);
});

test('toHeatmapGrid splits distant cells', () => {
  const grid = toHeatmapGrid([
    mkCluster({ centroid_lat: 30.6, centroid_lng: 104.0, member_count: 2 }),
    mkCluster({ centroid_lat: 30.7, centroid_lng: 104.0, member_count: 4 }),
  ]);
  assert.strictEqual(grid.length, 2);
  // Sorted by weight desc
  assert.strictEqual(grid[0].weight, 4);
});

test('topLabels sums member counts', () => {
  const cs = [
    mkCluster({ label: 'person', member_count: 3 }),
    mkCluster({ label: 'person', member_count: 5 }),
    mkCluster({ label: 'vehicle', member_count: 2 }),
  ];
  const top = topLabels(cs, 2);
  assert.strictEqual(top[0].label, 'person');
  assert.strictEqual(top[0].total, 8);
  assert.strictEqual(top[1].label, 'vehicle');
  assert.strictEqual(top[1].total, 2);
  assert.ok(Math.abs(top[0].share - 0.8) < 1e-9);
});

test('topLabels empty', () => {
  assert.deepStrictEqual(topLabels([]), []);
});

test('severityForCluster thresholds', () => {
  assert.strictEqual(severityForCluster(mkCluster({ member_count: 1 })),
    'low');
  assert.strictEqual(severityForCluster(mkCluster({ member_count: 5 })),
    'medium');
  assert.strictEqual(severityForCluster(mkCluster({ member_count: 12 })),
    'high');
  assert.strictEqual(severityForCluster(mkCluster({ member_count: 25 })),
    'critical');
  // peak_confidence critical override
  assert.strictEqual(
    severityForCluster(mkCluster({
      member_count: 2, peak_confidence: 0.97,
    })),
    'critical',
  );
});

test('CLUSTER_SEV_COLOR has all severities', () => {
  for (const s of ['low', 'medium', 'high', 'critical']) {
    assert.match(CLUSTER_SEV_COLOR[s], /^#/);
  }
});
