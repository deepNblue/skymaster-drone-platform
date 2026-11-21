import React, { useState, useEffect } from 'react';
import { Plus, RefreshCw, AlertTriangle, CloudUpload, CheckCircle, Zap, Archive } from 'lucide-react';
import { api } from '../utils/api';
import { Scene, SceneStatus } from './types';

interface SceneListProps {
  orgId: string;
  onSelectScene: (scene: Scene) => void;
  onCreateNew: () => void;
}

const StatusBadge: React.FC<{ status: SceneStatus }> = ({ status }) => {
  const statusMap = {
    draft: { label: '草稿', color: 'bg-gray-200 text-gray-700' },
    ingesting: { label: '上传中', color: 'bg-blue-100 text-blue-700' },
    ingested: { label: '已上传', color: 'bg-blue-200 text-blue-800' },
    colmap: { label: 'SfM重建中', color: 'bg-yellow-100 text-yellow-700' },
    colmap_done: { label: '稀疏重建完成', color: 'bg-yellow-200 text-yellow-800' },
    training: { label: 'GS训练中', color: 'bg-orange-100 text-orange-700' },
    ready: { label: '就绪', color: 'bg-green-100 text-green-700' },
    failed: { label: '失败', color: 'bg-red-100 text-red-700' },
    archived: { label: '已归档', color: 'bg-gray-300 text-gray-700' },
  };

  const { label, color } = statusMap[status] || statusMap.draft;
  return (
    <span className={`px-2 py-1 rounded-full text-xs font-medium ${color}`}>
      {label}
    </span>
  );
};

const KindBadge: React.FC<{ kind: string }> = ({ kind }) => {
  if (kind === '4dgs') {
    return <span className="px-2 py-1 rounded-full text-xs bg-purple-100 text-purple-700">4DGS</span>;
  }
  return <span className="px-2 py-1 rounded-full text-xs bg-gray-100 text-gray-600">3DGS</span>;
};

export const SceneList: React.FC<SceneListProps> = ({ orgId, onSelectScene, onCreateNew }) => {
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadScenes = async () => {
    try {
      setLoading(true);
      const response = await api.get(`/api/v1/scenes?org_id=${orgId}`);
      setScenes(response.data);
      setError(null);
    } catch (err) {
      setError('加载场景列表失败');
      console.error('Failed to load scenes:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadScenes();
  }, [orgId]);

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleString('zh-CN');
  };

  return (
    <div className="p-4">
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-xl font-bold">3DGS 重建场景</h2>
        <button
          onClick={onCreateNew}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
        >
          <Plus size={16} />
          新建场景
        </button>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg flex items-center gap-2 text-red-700">
          <AlertTriangle size={18} />
          {error}
          <button onClick={loadScenes} className="ml-auto text-sm underline">重试</button>
        </div>
      )}

      {loading ? (
        <div className="flex justify-center items-center py-12 text-gray-500">
          <RefreshCw size={20} className="animate-spin mr-2" />
          加载中...
        </div>
      ) : scenes.length === 0 ? (
        <div className="text-center py-12 text-gray-500">
          <p className="mb-4">暂无重建场景</p>
          <button
            onClick={onCreateNew}
            className="text-blue-600 hover:underline"
          >
            创建第一个重建场景
          </button>
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {scenes.map(scene => (
            <div
              key={scene.id}
              onClick={() => onSelectScene(scene)}
              className="border rounded-lg p-4 hover:shadow-md transition-shadow cursor-pointer bg-white"
            >
              <div className="flex justify-between items-start mb-2">
                <h3 className="font-semibold text-gray-900 truncate pr-2">
                  {scene.name}
                </h3>
                <div className="flex flex-col gap-1 items-end">
                  <StatusBadge status={scene.status} />
                  <KindBadge kind={scene.scene_kind || '3dgs'} />
                </div>
              </div>

              {scene.description && (
                <p className="text-sm text-gray-600 mb-3 line-clamp-2">
                  {scene.description}
                </p>
              )}

              <div className="space-y-1 text-xs text-gray-500 mb-3">
                {scene.n_source_images > 0 && (
                  <div>源图像: {scene.n_source_images} 张</div>
                )}
                {scene.n_gaussians && (
                  <div>Gaussians: {scene.n_gaussians.toLocaleString()} 个</div>
                )}
                {scene.psnr_train && (
                  <div>PSNR: {scene.psnr_train.toFixed(2)}</div>
                )}
              </div>

              <div className="flex items-center justify-between text-xs text-gray-500">
                <div className="flex items-center gap-1">
                  <CloudUpload size={12} />
                  {formatDate(scene.created_at)}
                </div>
                {scene.status === 'ready' && (
                  <CheckCircle size={14} className="text-green-600" />
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
