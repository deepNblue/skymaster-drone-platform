import React, { useRef, useEffect, useState } from 'react';
import * as THREE from 'three';
import { Loader2 } from 'lucide-react';

// Minimal WebGL viewer for .ply Gaussian Splatting models
// Based on three.js example, simplified for SkyMaster embedded use

interface GaussianSplatViewerProps {
  plyUrl: string;
  width?: number;
  height?: number;
  className?: string;
}

export const GaussianSplatViewer: React.FC<GaussianSplatViewerProps> = ({
  plyUrl,
  width = 800,
  height = 600,
  className = '',
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    let scene: THREE.Scene;
    let camera: THREE.PerspectiveCamera;
    let renderer: THREE.WebGLRenderer;
    let points: THREE.Points;
    let animationFrameId: number;

    const init = async () => {
      try {
        // Basic scene setup
        scene = new THREE.Scene();
        scene.background = new THREE.Color(0xf0f0f0);

        camera = new THREE.PerspectiveCamera(
          75,
          width / height,
          0.1,
          1000
        );
        camera.position.set(0, 0, 5);

        renderer = new THREE.WebGLRenderer({ antialias: true });
        renderer.setSize(width, height);
        renderer.setPixelRatio(window.devicePixelRatio);
        containerRef.current!.appendChild(renderer.domElement);

        // Add lights
        const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
        scene.add(ambientLight);
        const directionalLight = new THREE.DirectionalLight(0xffffff, 0.8);
        directionalLight.position.set(1, 1, 1);
        scene.add(directionalLight);

        // Load PLY
        const loader = new THREE.PLYLoader();
        const geometry = await new Promise<THREE.BufferGeometry>((resolve, reject) => {
          loader.load(plyUrl, resolve, undefined, reject);
        });

        // Compute colors from geometry attributes
        const position = geometry.attributes.position;
        const colors = new Float32Array(position.count * 3);

        if (geometry.attributes.color) {
          // PLY already has colors
          for (let i = 0; i < position.count; i++) {
            colors[i * 3] = geometry.attributes.color.getX(i);
            colors[i * 3 + 1] = geometry.attributes.color.getY(i);
            colors[i * 3 + 2] = geometry.attributes.color.getZ(i);
          }
        } else {
          // Default gray
          for (let i = 0; i < position.count; i++) {
            colors[i * 3] = 0.5;
            colors[i * 3 + 1] = 0.5;
            colors[i * 3 + 2] = 0.5;
          }
        }

        geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));

        // Material for gaussian splats visualization (simplified point cloud)
        const material = new THREE.PointsMaterial({
          size: 0.01,
          vertexColors: true,
          sizeAttenuation: true,
          transparent: true,
          opacity: 0.9,
        });

        points = new THREE.Points(geometry, material);
        scene.add(points);

        // Auto-fit camera to bounding box
        geometry.computeBoundingBox();
        const box = geometry.boundingBox!;
        const center = box.getCenter(new THREE.Vector3());
        const size = box.getSize(new THREE.Vector3());
        const maxDim = Math.max(size.x, size.y, size.z);
        const fov = camera.fov * (Math.PI / 180);
        let cameraZ = Math.abs(maxDim / 2 / Math.tan(fov / 2));
        camera.position.copy(center);
        camera.position.z += cameraZ * 1.5;
        camera.lookAt(center);

        setLoading(false);
        setError(null);

        // Basic orbit control (simplified drag to rotate)
        let isDragging = false;
        let previousMouseX = 0;
        let previousMouseY = 0;
        let rotationX = 0;
        let rotationY = 0;

        const onMouseDown = (e: MouseEvent) => {
          isDragging = true;
          previousMouseX = e.clientX;
          previousMouseY = e.clientY;
        };

        const onMouseMove = (e: MouseEvent) => {
          if (!isDragging || !points) return;
          const deltaX = e.clientX - previousMouseX;
          const deltaY = e.clientY - previousMouseY;
          rotationY += deltaX * 0.01;
          rotationX += deltaY * 0.01;
          points.rotation.x = rotationX;
          points.rotation.y = rotationY;
          previousMouseX = e.clientX;
          previousMouseY = e.clientY;
        };

        const onMouseUp = () => {
          isDragging = false;
        };

        const onWheel = (e: WheelEvent) => {
          e.preventDefault();
          camera.position.z += e.deltaY * 0.01;
        };

        renderer.domElement.addEventListener('mousedown', onMouseDown);
        renderer.domElement.addEventListener('mousemove', onMouseMove);
        renderer.domElement.addEventListener('mouseup', onMouseUp);
        renderer.domElement.addEventListener('wheel', onWheel, { passive: false });

        // Animation loop
        const animate = () => {
          animationFrameId = requestAnimationFrame(animate);
          renderer.render(scene, camera);
        };
        animate();
      } catch (err) {
        console.error('Failed to initialize Gaussian Splat viewer:', err);
        setError('加载 3D 模型失败');
        setLoading(false);
      }
    };

    init();

    return () => {
      if (animationFrameId) {
        cancelAnimationFrame(animationFrameId);
      }
      if (renderer && containerRef.current) {
        containerRef.current.removeChild(renderer.domElement);
        renderer.dispose();
      }
    };
  }, [plyUrl, width, height]);

  return (
    <div
      ref={containerRef}
      className={`relative overflow-hidden rounded-lg border ${className}`}
      style={{ width, height }}
    >
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center bg-gray-50">
          <div className="flex flex-col items-center gap-2 text-gray-500">
            <Loader2 size={32} className="animate-spin" />
            <p className="text-sm">加载 3D 模型中...</p>
          </div>
        </div>
      )}
      {error && !loading && (
        <div className="absolute inset-0 flex items-center justify-center bg-red-50">
          <p className="text-red-600">{error}</p>
        </div>
      )}
    </div>
  );
};
