import React from 'react';
import { Scene } from './types_3dgs';
import { GaussianSplatViewer } from '../../components/three-viewer/GaussianSplatViewer';

interface ScenePreviewProps {
  scene: Scene;
  height?: number;
}

export const ScenePreview: React.FC<ScenePreviewProps> = ({ scene, height = 500 }) => {
  if (scene.status !== 'ready' || !scene.assets) {
    return (
      <div className="border rounded-lg p-8 text-center text-gray-500 bg-gray-50" style={{ height }}>
        {scene.status === 'ready' ? '暂无可预览模型' : '训练完成后可预览'}
      </div>
    );
  }

  const plyAsset = scene.assets.find(a => a.kind === 'gsplat_ply');
  if (!plyAsset) {
    return (
      <div className="border rounded-lg p-8 text-center text-gray-500 bg-gray-50" style={{ height }}>
        找不到 PLY 模型文件
      </div>
    );
  }

  const downloadUrl = `${process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'}/api/v1/scenes/assets/${plyAsset.id}/download`;

  return (
    <div className="border rounded-lg overflow-hidden">
      <GaussianSplatViewer
        plyUrl={downloadUrl}
        width={800}
        height={height}
      />
      <div className="p-2 text-xs text-gray-500 bg-gray-50 flex justify-between items-center">
        <span>
          {scene.n_gaussians?.toLocaleString()} Gaussians ·
          PSNR: {scene.psnr_train?.toFixed(2) || 'N/A'}
        </span>
        <a
          href={downloadUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="text-blue-600 hover:underline"
        >
          下载 PLY
        </a>
      </div>
    </div>
  );
};
