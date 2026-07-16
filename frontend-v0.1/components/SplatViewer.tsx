'use client';

/**
 * SplatViewer — v2.1 T1.5.
 *
 * Renders a .splat file (Antimatter15 format) as size-attenuated colored
 * point sprites. This is a **light-weight splat renderer** — not a full
 * anisotropic gaussian rasterizer — but a big visual step up from raw
 * point clouds:
 *
 *   * per-splat color (from .splat rgba)
 *   * per-splat size (from scale magnitude → sprite radius)
 *   * per-splat opacity (from .splat alpha channel)
 *   * circular sprite (alpha-tested disc)
 *
 * Full anisotropic 3DGS rasterization is a T2.0+ optimization; this
 * viewer already gives the "yes-that's-my-site" preview quality needed
 * before customers download the full .ply/.splat for desktop tools.
 */
import React, { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';

interface SplatViewerProps {
  buffer: ArrayBuffer | null;
  loading?: boolean;
  height?: number;
  maxSplats?: number;
  onStats?: (stats: { count: number; downSampled: boolean }) => void;
}

// Circular sprite shader — draws colored disc with soft alpha edge.
const VERT = /* glsl */ `
attribute float aSize;
attribute vec3 aColor;
attribute float aAlpha;
varying vec3 vColor;
varying float vAlpha;
void main() {
  vColor = aColor;
  vAlpha = aAlpha;
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  gl_Position = projectionMatrix * mv;
  gl_PointSize = aSize * (300.0 / -mv.z);
}`;

const FRAG = /* glsl */ `
precision mediump float;
varying vec3 vColor;
varying float vAlpha;
void main() {
  vec2 uv = gl_PointCoord * 2.0 - 1.0;
  float d = dot(uv, uv);
  if (d > 1.0) discard;
  float falloff = smoothstep(1.0, 0.4, d);
  gl_FragColor = vec4(vColor, vAlpha * falloff);
}`;

export function SplatViewer(props: SplatViewerProps) {
  const { buffer, loading, height = 500, maxSplats = 300_000, onStats } = props;
  const mountRef = useRef<HTMLDivElement>(null);
  const [err, setErr] = useState<string | null>(null);
  const [stats, setStats] = useState<{ count: number; downSampled: boolean } | null>(null);

  useEffect(() => {
    if (!buffer || !mountRef.current) return;
    const mount = mountRef.current;
    let disposed = false;

    (async () => {
      const { parseSplat, splatBoundingBox, SplatParseError } = await import('@/lib/splat-parser');

      let cloud;
      try {
        cloud = parseSplat(buffer, { maxSplats });
      } catch (e) {
        setErr(e instanceof SplatParseError ? e.message : String(e));
        return;
      }
      if (disposed) return;

      const bb = splatBoundingBox(cloud);
      const width = mount.clientWidth;

      const scene = new THREE.Scene();
      scene.background = new THREE.Color(0x0a0d15);

      const camera = new THREE.PerspectiveCamera(60, width / height, 0.01, 5000);

      const renderer = new THREE.WebGLRenderer({ antialias: true, premultipliedAlpha: false });
      renderer.setPixelRatio(window.devicePixelRatio);
      renderer.setSize(width, height);
      mount.innerHTML = '';
      mount.appendChild(renderer.domElement);

      // Build attributes
      const geom = new THREE.BufferGeometry();
      geom.setAttribute('position', new THREE.BufferAttribute(cloud.positions, 3));

      const colorAttr = new Float32Array(cloud.count * 3);
      const alphaAttr = new Float32Array(cloud.count);
      const sizeAttr = new Float32Array(cloud.count);
      for (let i = 0; i < cloud.count; i++) {
        colorAttr[i * 3 + 0] = cloud.colors[i * 4 + 0] / 255;
        colorAttr[i * 3 + 1] = cloud.colors[i * 4 + 1] / 255;
        colorAttr[i * 3 + 2] = cloud.colors[i * 4 + 2] / 255;
        alphaAttr[i] = cloud.colors[i * 4 + 3] / 255;
        // Scale attribute: geometric mean of the 3D scales (gaussian "size")
        const sx = cloud.scales[i * 3 + 0];
        const sy = cloud.scales[i * 3 + 1];
        const sz = cloud.scales[i * 3 + 2];
        // Splats have log-scales; e^s gives real size. Clamp so tiny/huge don't dominate.
        const s = Math.exp((sx + sy + sz) / 3);
        sizeAttr[i] = Math.min(0.5, Math.max(0.001, s)) * 8;
      }
      geom.setAttribute('aColor', new THREE.BufferAttribute(colorAttr, 3));
      geom.setAttribute('aAlpha', new THREE.BufferAttribute(alphaAttr, 1));
      geom.setAttribute('aSize', new THREE.BufferAttribute(sizeAttr, 1));
      geom.translate(-bb.center[0], -bb.center[1], -bb.center[2]);

      const mat = new THREE.ShaderMaterial({
        vertexShader: VERT,
        fragmentShader: FRAG,
        transparent: true,
        depthWrite: false,
        blending: THREE.NormalBlending,
      });
      const points = new THREE.Points(geom, mat);
      scene.add(points);

      const camDist = bb.radius * 2.5;
      let yaw = 0, pitch = 0.3, zoom = camDist;

      let isDown = false, lx = 0, ly = 0;
      const onDown = (e: MouseEvent) => { isDown = true; lx = e.clientX; ly = e.clientY; };
      const onUp = () => { isDown = false; };
      const onMove = (e: MouseEvent) => {
        if (!isDown) return;
        yaw += (e.clientX - lx) * 0.005;
        pitch += (e.clientY - ly) * 0.005;
        pitch = Math.max(-1.4, Math.min(1.4, pitch));
        lx = e.clientX; ly = e.clientY;
      };
      const onWheel = (e: WheelEvent) => {
        e.preventDefault();
        zoom *= e.deltaY > 0 ? 1.1 : 0.9;
        zoom = Math.max(bb.radius * 0.1, Math.min(bb.radius * 20, zoom));
      };
      renderer.domElement.addEventListener('mousedown', onDown);
      window.addEventListener('mouseup', onUp);
      window.addEventListener('mousemove', onMove);
      renderer.domElement.addEventListener('wheel', onWheel, { passive: false });

      let raf = 0;
      const tick = () => {
        if (disposed) return;
        camera.position.x = zoom * Math.cos(pitch) * Math.sin(yaw);
        camera.position.y = zoom * Math.sin(pitch);
        camera.position.z = zoom * Math.cos(pitch) * Math.cos(yaw);
        camera.lookAt(0, 0, 0);
        renderer.render(scene, camera);
        raf = requestAnimationFrame(tick);
      };
      tick();

      const onResize = () => {
        const w = mount.clientWidth;
        camera.aspect = w / height;
        camera.updateProjectionMatrix();
        renderer.setSize(w, height);
      };
      window.addEventListener('resize', onResize);

      const s = { count: cloud.count, downSampled: cloud.count < (buffer.byteLength / 32) };
      setStats(s);
      onStats?.(s);

      return () => {
        disposed = true;
        cancelAnimationFrame(raf);
        renderer.domElement.removeEventListener('mousedown', onDown);
        window.removeEventListener('mouseup', onUp);
        window.removeEventListener('mousemove', onMove);
        renderer.domElement.removeEventListener('wheel', onWheel);
        window.removeEventListener('resize', onResize);
        geom.dispose();
        mat.dispose();
        renderer.dispose();
      };
    })();

    return () => { disposed = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [buffer, height, maxSplats]);

  return (
    <div style={{ position: 'relative' }}>
      <div
        ref={mountRef}
        style={{
          width: '100%', height,
          background: '#0a0d15',
          borderRadius: 8,
          overflow: 'hidden',
        }}
      />
      {loading && <div style={_overlay}><span>加载 splat 中…</span></div>}
      {err && <div style={_overlay}><span style={{ color: '#ff7875' }}>解析失败：{err}</span></div>}
      {stats && (
        <div style={_stats}>
          <span>{stats.count.toLocaleString()} 高斯</span>
          {stats.downSampled && <span style={{ marginLeft: 8, opacity: 0.7 }}>· 已抽样</span>}
          <span style={{ marginLeft: 8, opacity: 0.6 }}>· 拖动旋转 · 滚轮缩放</span>
        </div>
      )}
    </div>
  );
}

const _overlay: React.CSSProperties = {
  position: 'absolute', top: 0, left: 0, right: 0, bottom: 0,
  display: 'flex', alignItems: 'center', justifyContent: 'center',
  color: '#fff', background: 'rgba(0,0,0,0.4)', fontSize: 14,
};

const _stats: React.CSSProperties = {
  position: 'absolute', bottom: 8, left: 12,
  color: '#e6f4ff', fontSize: 12,
  background: 'rgba(0,0,0,0.4)', padding: '4px 10px', borderRadius: 4,
};
