import React, { useState, useEffect } from 'react';
import { X, RefreshCw } from 'lucide-react';
import { api } from '../utils/api';

interface ImportFromMissionModalProps {
  orgId: string;
  onClose: () => void;
  onImported: (sceneId: string) => void;
}

interface MissionListItem {
  id: string;
  name: string;
  created_at: string;
  n_assets: number;
}

export const ImportFromMissionModal: React.FC<ImportFromMissionModalProps> = ({
  orgId,
  onClose,
  onImported,
}) => {
  const [loading, setLoading] = useState(true);
  const [missions, setMissions] = useState<MissionListItem[]>([]);
  const [selectedMissionId, setSelectedMissionId] = useState<string | null>(null);
  const [sceneName, setSceneName] = useState('');
  const [sceneKind, setSceneKind] = useState<'3dgs' | '4dgs'>('3dgs');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadMissions = async () => {
    try {
      setLoading(true);
      // Load completed missions for this org
      const response = await api.get(`/api/v1/missions?org_id=${orgId}&status=completed`);
      // simplify to list with count assets
      const items = (response.data as any[])
        .filter((m: any) => m.status === 'completed')
        .map((m: any) => ({
          id: m.id,
          name: m.name,
          created_at: m.created_at,
          n_assets: m.n_images || 0,
        }));
      setMissions(items);
      setError(null);
    } catch (err) {
      console.error('Failed to load missions:', err);
      setError('加载任务列表失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadMissions();
  }, [orgId]);

  const handleSubmit = async () => {
    if (!selectedMissionId) {
      setError('请选择一个已完成任务');
      return;
    }
    try {
      setSubmitting(true);
      setError(null);
      const response = await api.post('/api/v1/scenes-import/from-mission', {
        mission_id: selectedMissionId,
        name: sceneName.trim() || undefined,
        scene_kind: sceneKind,
      });
      onImported(response.data.scene_id);
    } catch (err) {
      console.error('Import failed:', err);
      setError('导入失败，请重试');
    } finally {
      setSubmitting(false);
    }
  };

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleDateString('zh-CN');
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between px-6 py-4 border-b">
          <h2 className="text-xl font-bold">从无人机任务导入重建场景</h2>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700">
            <X size={24} />
          </button>
        </div>

        <div className="p-6 space-y-4">
          {error && (
            <div className="p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">
              {error}
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              重建类型
            </label>
            <div className="flex gap-4">
              <label className="flex items-center gap-2">
                <input
                  type="radio"
                  checked={sceneKind === '3dgs'}
                  onChange={() => setSceneKind('3dgs')}
                  className="text-blue-600"
                />
                <span>3DGS（静态场景，多图重建）</span>
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="radio"
                  checked={sceneKind === '4dgs'}
                  onChange={() => setSceneKind('4dgs')}
                  className="text-blue-600"
                />
                <span>4DGS（动态时序，视频重建）</span>
              </label>
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              场景名称（可选，默认用任务名称）
            </label>
            <input
              type="text"
              value={sceneName}
              onChange={(e) => setSceneName(e.target.value)}
              className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              placeholder="留空将使用原任务名称"
            />
          </div>

          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="block text-sm font-medium text-gray-700">
                选择已完成任务 <span className="text-red-500">*</span>
              </label>
              <button
                onClick={loadMissions}
                disabled={loading}
                className="flex items-center gap-1 text-xs text-blue-600 hover:underline disabled:opacity-50"
              >
                <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
                刷新
              </button>
            </div>

            {loading ? (
              <div className="text-center py-6 text-gray-500">
                <RefreshCw size={24} className="animate-spin mx-auto mb-2" />
                加载中...
              </div>
            ) : missions.length === 0 ? (
              <div className="text-center py-6 text-gray-500 border rounded-lg">
                当前组织暂无已完成任务，请先完成一次无人机飞行任务
              </div>
            ) : (
              <div className="max-h-64 overflow-y-auto border rounded-lg divide-y">
                {missions.map((m) => (
                  <div
                    key={m.id}
                    className={`p-3 cursor-pointer ${
                      selectedMissionId === m.id
                        ? 'bg-blue-50 border-l-4 border-l-blue-600'
                        : 'hover:bg-gray-50'
                    }`}
                    onClick={() => {
                      setSelectedMissionId(m.id);
                      if (!sceneName.trim()) {
                        setSceneName(m.name);
                      }
                    }}
                  >
                    <div className="flex justify-between items-start">
                      <div>
                        <div className="font-medium">{m.name}</div>
                        <div className="text-xs text-gray-500">
                          {formatDate(m.created_at)} · {m.n_assets} 张图像
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 border rounded-lg hover:bg-gray-50"
              disabled={submitting}
            >
              取消
            </button>
            <button
              onClick={handleSubmit}
              disabled={submitting || !selectedMissionId}
              className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
            >
              {submitting ? '导入中...' : '开始导入'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
