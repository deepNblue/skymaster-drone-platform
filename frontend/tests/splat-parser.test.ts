/**
 * v2.1 T1.5 · Standalone splat-parser tests.
 * Runs via tests/run-ply-tests.sh alongside PLY parser tests.
 */
import assert from 'node:assert';
import { parseSplat, splatBoundingBox, SplatParseError } from '../lib/splat-parser';

function makeSplatRow(
  pos: [number, number, number],
  scale: [number, number, number],
  color: [number, number, number, number],
  quat: [number, number, number, number],
): Uint8Array {
  const buf = new Uint8Array(32);
  const dv = new DataView(buf.buffer);
  dv.setFloat32(0, pos[0], true);
  dv.setFloat32(4, pos[1], true);
  dv.setFloat32(8, pos[2], true);
  dv.setFloat32(12, scale[0], true);
  dv.setFloat32(16, scale[1], true);
  dv.setFloat32(20, scale[2], true);
  buf[24] = color[0]; buf[25] = color[1]; buf[26] = color[2]; buf[27] = color[3];
  buf[28] = quat[0]; buf[29] = quat[1]; buf[30] = quat[2]; buf[31] = quat[3];
  return buf;
}

function concat(rows: Uint8Array[]): ArrayBuffer {
  const total = rows.reduce((s, r) => s + r.length, 0);
  const out = new Uint8Array(total);
  let off = 0;
  for (const r of rows) { out.set(r, off); off += r.length; }
  return out.buffer.slice(0, out.length);
}

let ran = 0, failed = 0;
function test(name: string, fn: () => void) {
  ran++;
  try { fn(); console.log(`  ok  · ${name}`); }
  catch (e: any) {
    failed++;
    console.error(`  FAIL · ${name}\n         ${e?.message ?? e}`);
  }
}

console.log('\n--- parseSplat ---');

test('rejects buffer with non-multiple-of-32 size', () => {
  const buf = new Uint8Array(45).buffer;
  assert.throws(() => parseSplat(buf), SplatParseError);
});

test('handles empty buffer', () => {
  const cloud = parseSplat(new ArrayBuffer(0));
  assert.equal(cloud.count, 0);
  assert.equal(cloud.positions.length, 0);
});

test('parses single splat row', () => {
  const row = makeSplatRow([1.5, 2.5, 3.5], [0.1, 0.2, 0.3], [255, 128, 64, 200], [128, 128, 128, 200]);
  const cloud = parseSplat(concat([row]));
  assert.equal(cloud.count, 1);
  assert.ok(Math.abs(cloud.positions[0] - 1.5) < 1e-6);
  assert.ok(Math.abs(cloud.positions[1] - 2.5) < 1e-6);
  assert.ok(Math.abs(cloud.positions[2] - 3.5) < 1e-6);
  assert.ok(Math.abs(cloud.scales[0] - 0.1) < 1e-6);
  assert.equal(cloud.colors[0], 255);
  assert.equal(cloud.colors[1], 128);
  assert.equal(cloud.colors[3], 200);
});

test('quaternion is signed-centered (u8 - 128)', () => {
  const row = makeSplatRow([0, 0, 0], [1, 1, 1], [0, 0, 0, 255], [0, 128, 255, 200]);
  const cloud = parseSplat(concat([row]));
  // 0 - 128 = -128, 128 - 128 = 0, 255 - 128 = 127, 200 - 128 = 72
  assert.equal(cloud.quats[0], -128);
  assert.equal(cloud.quats[1], 0);
  assert.equal(cloud.quats[2], 127);
  assert.equal(cloud.quats[3], 72);
});

test('parses multiple splats correctly', () => {
  const rows = [
    makeSplatRow([0, 0, 0], [1, 1, 1], [255, 0, 0, 255], [0, 0, 0, 255]),
    makeSplatRow([1, 1, 1], [2, 2, 2], [0, 255, 0, 200], [0, 0, 0, 200]),
    makeSplatRow([-1, -1, -1], [0.5, 0.5, 0.5], [0, 0, 255, 128], [0, 0, 0, 128]),
  ];
  const cloud = parseSplat(concat(rows));
  assert.equal(cloud.count, 3);
  assert.equal(cloud.colors[0], 255); // R of first
  assert.equal(cloud.colors[5], 255); // G of second
  assert.equal(cloud.colors[10], 255); // B of third
});

test('decimation via maxSplats reduces count', () => {
  const rows: Uint8Array[] = [];
  for (let i = 0; i < 100; i++) {
    rows.push(makeSplatRow([i, 0, 0], [1, 1, 1], [i, 0, 0, 255], [0, 0, 0, 255]));
  }
  const cloud = parseSplat(concat(rows), { maxSplats: 10 });
  // Stride = floor(100/10) = 10 → outCount = 10
  assert.equal(cloud.count, 10);
  assert.equal(cloud.positions[0], 0);
  assert.equal(cloud.positions[3], 10);
});

console.log('\n--- splatBoundingBox ---');

test('empty cloud returns radius=1 default', () => {
  const empty = parseSplat(new ArrayBuffer(0));
  const bb = splatBoundingBox(empty);
  assert.equal(bb.radius, 1);
  assert.deepStrictEqual(bb.center, [0, 0, 0]);
});

test('computes center and radius of 8-corner cube', () => {
  const rows: Uint8Array[] = [];
  for (const x of [-1, 1]) for (const y of [-1, 1]) for (const z of [-1, 1]) {
    rows.push(makeSplatRow([x, y, z], [1, 1, 1], [255, 255, 255, 255], [0, 0, 0, 255]));
  }
  const cloud = parseSplat(concat(rows));
  const bb = splatBoundingBox(cloud);
  assert.deepStrictEqual(bb.center, [0, 0, 0]);
  assert.equal(bb.radius, 1); // extent = 2 → radius = 1
});

test('computes center for offset cluster', () => {
  const rows: Uint8Array[] = [];
  for (const x of [10, 12]) for (const y of [5, 7]) {
    rows.push(makeSplatRow([x, y, 0], [1, 1, 1], [255, 255, 255, 255], [0, 0, 0, 255]));
  }
  const cloud = parseSplat(concat(rows));
  const bb = splatBoundingBox(cloud);
  assert.equal(bb.center[0], 11);
  assert.equal(bb.center[1], 6);
  assert.equal(bb.center[2], 0);
  assert.equal(bb.radius, 1); // max extent = 2 → radius = 1
});

console.log(`\n${ran - failed}/${ran} splat tests passed`);
if (failed) process.exit(1);
