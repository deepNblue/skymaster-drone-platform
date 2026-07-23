import React, { useState } from 'react';
import { X } from 'lucide-react';
import { api } from '../utils/api';
import { SceneCreateRequest } from './types_3dgs';

interface CreateSceneModalProps {
  orgId: string;
  onClose: () => void;
  onCreated: (sceneId: string) => void;
}

export const CreateSceneModal: React.FC<CreateSceneModalProps> = ({ orgId, onClose, onCreated }) => {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [sceneKind, setSceneKind] = useState<'3dgs' | '4dgs'>('3dgs');
  const [coordSystem, setCoordSystem] = useState('wgs84');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) {
      setError('请输入场景名称');
      return;
    }

    try {
      setLoading(true);
      setError(null);
      const response = await api.post('/api/v1/scenes', {
        name: name.trim(),
        description: description.trim() || undefined,
        scene_kind: sceneKind,
        coord_system: coordSystem.trim() || undefined,
      } as SceneCreateRequest);
      onCreated(response.data.id);
    } catch (err) {
      console.error('Failed to create scene:', err);
      setError('创建场景失败，请重试');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between px-6 py-4 border-b">
          <h2 className="text-xl font-bold">新建 3DGS 重建场景</h2>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700">
            <X size={24} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {error && (
            <div className="p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">
              {error}
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              场景名称 <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              placeholder="例如：应急演练场地巡检"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              场景描述
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              placeholder="简单描述这个重建场景的用途和来源"
              rows={3}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
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
                <span>3DGS（静态场景，单视角集）</span>
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="radio"
                  checked={sceneKind === '4dgs'}
                  onChange={() => setSceneKind('4dgs')}
                  className="text-blue-600"
                />
                <span>4DGS（动态时序，多帧视频）</span>
              </label>
            </div>
            <p className="text-xs text-gray-500 mt-1">
              4DGS 是 v2.1 新增的动态重建能力，适合无人机视频序列重建动态场景
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              坐标系
            </label>
            <select
              value={coordSystem}
              onChange={(e) => setCoordSystem(e.target.value)}
              className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            >
              <option value="wgs84">WGS84 (GPS/无人机默认)</option>
              <option value="gcj02">GCJ-02 (国测局加密)</option>
              <option value="enu">局部 ENU</option>
              <option value="relative">相对模型坐标系</option>
            </select>
          </div>

          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 border rounded-lg hover:bg-gray-50"
              disabled={loading}
            >
              取消
            </button>
            <button
              type="submit"
              disabled={loading}
              className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
            >
              {loading ? '创建中...' : '创建场景'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
