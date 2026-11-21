'use client';

/**
 * PointCloudViewer — v2.1 T1.4.
 *
 * Renders a parsed PLY point cloud with three.js. Chosen over a full
 * Gaussian-splatting rasterizer because:
 *   1. No extra ~500KB dep (@mkkellogg/gaussian-splats-3d)
 *   2. Works on the sparse COLMAP output (before training completes)
 *   3. Enough for a "yes this is my site" preview before customer downloads .ply
 *
 * Full 3DGS rasterization can be added as a follow-up (T1.5) without
 * refactoring — this component focuses on point cloud preview only.
 */
import React, { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';

interface PointCloudViewerProps {
  buffer: ArrayBuffer | null;
  loading?: boolean;
  height?: number;
  maxPoints?: number;
  onStats?: (stats: { vertexCount: number; hasColor: boolean }) => void;
}

export function PointCloudViewer(props: PointCloudViewerProps) {
  const { buffer, loading, height = 500, maxPoints = 500_000, onStats } = props;
  const mountRef = useRef<HTMLDivElement>(null);
  const [err, setErr] = useState<string | null>(null);
  const [stats, setStats] = useState<{ vertexCount: number; hasColor: boolean } | null>(null);

  useEffect(() => {
    if (!buffer || !mountRef.current) return;
    const mount = mountRef.current;
    let disposed = false;

    // Dynamic import so we don't ship the parser to unrelated pages.
    (async () => {
      const { parsePLY, PLYParseError } = await import('@/lib/ply-parser');

      let cloud;
      try {
        cloud = parsePLY(buffer, { maxPoints });
      } catch (e) {
        setErr(e instanceof PLYParseError ? e.message : String(e));
        return;
      }
      if (disposed) return;

      const width = mount.clientWidth;
      const scene = new THREE.Scene();
      scene.background = new THREE.Color(0x0b0f19);

      const camera = new THREE.PerspectiveCamera(60, width / height, 0.01, 5000);
      const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
      renderer.setPixelRatio(window.devicePixelRatio);
      renderer.setSize(width, height);
      mount.innerHTML = '';
      mount.appendChild(renderer.domElement);

      // Center the cloud + auto-fit camera to bounding box.
      const geom = new THREE.BufferGeometry();
      geom.setAttribute('position', new THREE.BufferAttribute(cloud.positions, 3));
      if (cloud.colors) {
        const c = new Float32Array(cloud.colors.length);
        for (let i = 0; i < cloud.colors.length; i++) c[i] = cloud.colors[i] / 255;
        geom.setAttribute('color', new THREE.BufferAttribute(c, 3));
      }
      geom.computeBoundingBox();
      const bbox = geom.boundingBox!;
      const center = bbox.getCenter(new THREE.Vector3());
      const size = bbox.getSize(new THREE.Vector3());
      geom.translate(-center.x, -center.y, -center.z);
      const radius = Math.max(size.x, size.y, size.z);
      const camDist = radius * 1.8;
      camera.position.set(camDist, camDist * 0.6, camDist);
      camera.lookAt(0, 0, 0);

      const mat = new THREE.PointsMaterial({
        size: Math.max(0.005, radius * 0.001),
        vertexColors: !!cloud.colors,
        color: cloud.colors ? 0xffffff : 0x88ccff,
        sizeAttenuation: true,
      });
      const points = new THREE.Points(geom, mat);
      scene.add(points);

      // Simple manual orbit: mouse drag rotates around Y, wheel zooms.
      let isDown = false;
      let lx = 0, ly = 0, yaw = 0, pitch = 0.3;
      let zoom = camDist;
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
        zoom = Math.max(radius * 0.1, Math.min(radius * 20, zoom));
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

      setStats({ vertexCount: cloud.vertexCount, hasColor: cloud.hasColor });
      if (onStats) onStats({ vertexCount: cloud.vertexCount, hasColor: cloud.hasColor });

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
  }, [buffer, height, maxPoints]);

  return (
    <div style={{ position: 'relative' }}>
      <div
        ref={mountRef}
        style={{
          width: '100%', height,
          background: '#0b0f19',
          borderRadius: 8,
          overflow: 'hidden',
        }}
      />
      {loading && (
        <div style={_overlay}>
          <span>加载点云中…</span>
        </div>
      )}
      {err && (
        <div style={_overlay}>
          <span style={{ color: '#ff7875' }}>解析失败：{err}</span>
        </div>
      )}
      {stats && (
        <div style={_stats}>
          <span>{stats.vertexCount.toLocaleString()} 点</span>
          {stats.hasColor && <span style={{ marginLeft: 8, opacity: 0.7 }}>· 带 RGB</span>}
          <span style={{ marginLeft: 8, opacity: 0.6 }}>· 鼠标拖动旋转 · 滚轮缩放</span>
        </div>
      )}
    </div>
  );
}

const _overlay: React.CSSProperties = {
  position: 'absolute', top: 0, left: 0, right: 0, bottom: 0,
  display: 'flex', alignItems: 'center', justifyContent: 'center',
  color: '#fff', background: 'rgba(0,0,0,0.4)',
  fontSize: 14,
};

const _stats: React.CSSProperties = {
  position: 'absolute', bottom: 8, left: 12,
  color: '#e6f4ff', fontSize: 12,
  background: 'rgba(0,0,0,0.4)', padding: '4px 10px', borderRadius: 4,
};
