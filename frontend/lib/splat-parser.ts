/**
 * .splat format parser — v2.1 T1.5.
 *
 * The ".splat" format (Antimatter15's compact binary) is the de-facto
 * exchange format for 3DGS scenes: 32 bytes per gaussian, no header,
 * fixed layout:
 *
 *   offset  size  type    field
 *   ----------------------------------------
 *   0       12    3x f32  position (x, y, z)
 *   12      12    3x f32  scale    (sx, sy, sz)
 *   24      4     4x u8   color    (r, g, b, opacity)
 *   28      4     4x u8   rotation (quaternion, xyzw, mapped from [0..255])
 *
 * Ref: https://github.com/antimatter15/splat/blob/main/main.js
 *
 * This parser is intentionally small — no DOM, no Three.js, no fetch — so
 * it can be unit-tested in the standalone bash runner alongside ply-parser.
 */

export interface SplatCloud {
  count: number;
  positions: Float32Array;   // xyz, length = 3 * count
  scales: Float32Array;      // sx, sy, sz, length = 3 * count
  colors: Uint8Array;        // rgba, length = 4 * count
  quats: Int8Array;          // xyzw quaternion, -1..1 range remapped, length = 4 * count
}

export class SplatParseError extends Error {
  constructor(msg: string) {
    super(`[SplatParseError] ${msg}`);
  }
}

const ROW_SIZE = 32;

/**
 * Parse an entire .splat ArrayBuffer.
 *
 * @param buffer  Raw file bytes
 * @param options.maxSplats  If set >0, decimate uniformly to at most this many
 */
export function parseSplat(
  buffer: ArrayBuffer,
  options: { maxSplats?: number } = {},
): SplatCloud {
  if (buffer.byteLength % ROW_SIZE !== 0) {
    throw new SplatParseError(
      `buffer size ${buffer.byteLength} is not a multiple of ${ROW_SIZE}`,
    );
  }
  const total = buffer.byteLength / ROW_SIZE;
  if (total === 0) {
    return {
      count: 0,
      positions: new Float32Array(0),
      scales: new Float32Array(0),
      colors: new Uint8Array(0),
      quats: new Int8Array(0),
    };
  }

  const maxN = options.maxSplats && options.maxSplats > 0 ? options.maxSplats : total;
  const stride = total > maxN ? Math.floor(total / maxN) : 1;
  const outN = Math.floor(total / stride);

  const positions = new Float32Array(outN * 3);
  const scales = new Float32Array(outN * 3);
  const colors = new Uint8Array(outN * 4);
  const quats = new Int8Array(outN * 4);

  const dv = new DataView(buffer);
  const u8 = new Uint8Array(buffer);
  let out = 0;
  for (let i = 0; i < total; i++) {
    if (i % stride !== 0 || out >= outN) continue;
    const base = i * ROW_SIZE;
    // position
    positions[out * 3 + 0] = dv.getFloat32(base + 0, true);
    positions[out * 3 + 1] = dv.getFloat32(base + 4, true);
    positions[out * 3 + 2] = dv.getFloat32(base + 8, true);
    // scale
    scales[out * 3 + 0] = dv.getFloat32(base + 12, true);
    scales[out * 3 + 1] = dv.getFloat32(base + 16, true);
    scales[out * 3 + 2] = dv.getFloat32(base + 20, true);
    // color rgba
    colors[out * 4 + 0] = u8[base + 24];
    colors[out * 4 + 1] = u8[base + 25];
    colors[out * 4 + 2] = u8[base + 26];
    colors[out * 4 + 3] = u8[base + 27];
    // quaternion (u8 → i8 for signed centering: v - 128)
    quats[out * 4 + 0] = (u8[base + 28] - 128) as number;
    quats[out * 4 + 1] = (u8[base + 29] - 128) as number;
    quats[out * 4 + 2] = (u8[base + 30] - 128) as number;
    quats[out * 4 + 3] = (u8[base + 31] - 128) as number;
    out++;
  }

  return { count: outN, positions, scales, colors, quats };
}

/**
 * Compute bounding-box center + max extent for camera fitting.
 * Reused by the viewer to auto-frame the scene.
 */
export function splatBoundingBox(cloud: SplatCloud): {
  center: [number, number, number];
  radius: number;
} {
  if (cloud.count === 0) return { center: [0, 0, 0], radius: 1 };
  let minX = Infinity, minY = Infinity, minZ = Infinity;
  let maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity;
  const p = cloud.positions;
  for (let i = 0; i < cloud.count; i++) {
    const x = p[i * 3];
    const y = p[i * 3 + 1];
    const z = p[i * 3 + 2];
    if (x < minX) minX = x;
    if (y < minY) minY = y;
    if (z < minZ) minZ = z;
    if (x > maxX) maxX = x;
    if (y > maxY) maxY = y;
    if (z > maxZ) maxZ = z;
  }
  const cx = (minX + maxX) / 2;
  const cy = (minY + maxY) / 2;
  const cz = (minZ + maxZ) / 2;
  const radius = Math.max(maxX - minX, maxY - minY, maxZ - minZ) / 2 || 1;
  return { center: [cx, cy, cz], radius };
}
