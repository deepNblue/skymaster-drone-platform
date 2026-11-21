import React, { useState, useEffect, useCallback, useRef } from 'react';
import { ArrowLeft, RefreshCw, CloudUpload, Play, Archive, Download, Trash2, AlertCircle, Plus } from 'lucide-react';
import { api } from '../utils/api';
import { Scene, SceneStatus, SceneAsset } from './types_3dgs';
import { StatusBadge } from './SceneList';
import { ScenePreview } from './ScenePreview';

interface SceneDetailProps {
  scene: Scene;
  orgId: string;
  onBack: () => void;
  onUpdate: () => void;
}

export const SceneDetail: React.FC<SceneDetailProps> = ({ scene, orgId, onBack, onUpdate }) => {
  const [currentScene, setCurrentScene] = useState<Scene>(scene);
  const [loading, setLoading] = useState(false);
  const [connected, setConnected] = useState(false);
  const [progressMsg, setProgressMsg] = useState<string | null>(null);

  const refreshScene = async () => {
    try {
      setLoading(true);
      const response = await api.get(`/api/v1/scenes/${currentScene.id}?org_id=${orgId}`);
      setCurrentScene(response.data);
      onUpdate();
    } catch (err) {
      console.error('Failed to refresh scene:', err);
    } finally {
      setLoading(false);
    }
  };

  // SSE 实时进度订阅
  useEffect(() => {
    const eventSource = new EventSource(
      `${process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'}/api/v1/scenes/${currentScene.id}/progress?org_id=${orgId}`
    );

    eventSource.onopen = () => {
      setConnected(true);
    };

    eventSource.onerror = () => {
      setConnected(false);
      eventSource.close();
    };

    eventSource.addEventListener('progress', (event) => {
      const data = JSON.parse(event.data);
      setProgressMsg(data.message || null);
      if (data.status) {
        setCurrentScene(prev => ({ ...prev, status: data.status }));
      }
      if (data.status === 'ready' || data.status === 'failed') {
        eventSource.close();
        setConnected(false);
        refreshScene();
      }
    });

    return () => {
      eventSource.close();
    };
  }, [currentScene.id, orgId]);

  const handleStartColmap = async () => {
    if (!confirm('确认启动 COLMAP 稀疏重建吗？这可能需要几分钟到几小时不等，取决于图片数量。')) return;
    try {
      setLoading(true);
      await api.post(`/api/v1/scenes/${currentScene.id}/colmap`, { org_id: orgId });
      await refreshScene();
    } catch (err) {
      console.error('Failed to start colmap:', err);
      alert('启动 COLMAP 失败');
    } finally {
      setLoading(false);
    }
  };

  const handleStartTraining = async () => {
    if (!confirm('确认启动 Gaussian Splatting 训练吗？这可能需要几小时，取决于分辨率和图片数量。')) return;
    try {
      setLoading(true);
      await api.post(`/api/v1/scenes/${currentScene.id}/train`, { org_id: orgId });
      await refreshScene();
    } catch (err) {
      console.error('Failed to start training:', err);
      alert('启动训练失败');
    } finally {
      setLoading(false);
    }
  };

  const handleArchive = async () => {
    if (!confirm('确认归档此场景吗？归档后不能再修改，但保留数据可下载。')) return;
    try {
      setLoading(true);
      await api.post(`/api/v1/scenes/${currentScene.id}/archive`, { org_id: orgId });
      await refreshScene();
      onUpdate();
    } catch (err) {
      console.error('Failed to archive:', err);
      alert('归档失败');
    } finally {
      setLoading(false);
    }
  };

  const handleReset = async () => {
    if (!confirm('确认重置此场景吗？会回到 draft 状态，可以重新上传素材。')) return;
    try {
      setLoading(true);
      await api.post(`/api/v1/scenes/${currentScene.id}/reset`, { org_id: orgId });
      await refreshScene();
      onUpdate();
    } catch (err) {
      console.error('Failed to reset:', err);
      alert('重置失败');
    } finally {
      setLoading(false);
    }
  };

  const canStartColmap = currentScene.status === 'ingested';
  const canStartTraining = currentScene.status === 'colmap_done';
  const isTerminal = currentScene.status === 'archived' || currentScene.status === 'ready';

  // Resumable chunked upload state
  const [uploadProgress, setUploadProgress] = useState<Map<string, {loaded: number, total: number}>>(new Map());

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;

    // For simplicity in the UI: single chunk upload (front-end dev simplified version)
    // Full resumable chunked upload is available on backend, can be added later
    for (const file of Array.from(files)) {
      try {
        // Step 1: start upload
        const startResp = await api.post(`/api/v1/scenes/${currentScene.id}/uploads`, {
          filename: file.name,
          size_bytes: file.size,
          sha256_hex: null, // backend will compute after assembly
          kind: guessAssetKind(file.name),
        });
        const uploadId = startResp.data.upload_id;

        // Track progress
        uploadProgress.set(file.name, {loaded: 0, total: file.size});
        setUploadProgress(new Map(uploadProgress));

        // Single chunk upload (full file as one chunk)
        const chunkBlob = file.slice(0, file.size);
        await api.put(
          `/api/v1/scenes/${currentScene.id}/uploads/${uploadId}/chunks/0`,
          chunkBlob,
          {
            headers: {'Content-Type': 'application/octet-stream'},
            onUploadProgress: (progressEvent) => {
              uploadProgress.set(file.name, {
                loaded: progressEvent.loaded,
                total: progressEvent.total || file.size,
              });
              setUploadProgress(new Map(uploadProgress));
            },
          }
        );

        // Step 3: complete
        await api.post(`/api/v1/scenes/${currentScene.id}/uploads/${uploadId}/complete`);
        // refresh scene to get new assets
        await refreshScene();
        // clear from progress
        uploadProgress.delete(file.name);
        setUploadProgress(new Map(uploadProgress));
      } catch (err) {
        console.error('Upload failed:', err);
        alert(`上传 ${file.name} 失败`);
        uploadProgress.delete(file.name);
        setUploadProgress(new Map(uploadProgress));
      }
    }
    // Reset input so same file can be uploaded again
    e.target.value = '';
  };

  const guessAssetKind = (filename: string): string => {
    const ext = filename.split('.').pop()?.toLowerCase() || '';
    if (['jpg', 'jpeg', 'png', 'webp', 'tif', 'tiff'].includes(ext)) {
      return 'source_image';
    }
    if (['mp4', 'mov', 'avi', 'mkv', 'webm'].includes(ext)) {
      return 'source_video';
    }
    if (['zip', 'tar', 'gz', 'tgz'].includes(ext)) {
      return 'colmap_sparse';
    }
    if (['ply', 'splat'].includes(ext)) {
      return 'gsplat_ply';
    }
    if (['ckpt', 'pt', 'pth', 'safetensors'].includes(ext)) {
      return 'gsplat_ckpt';
    }
    return 'log';
  };

  return (
    <div className="p-4 max-w-5xl mx-auto">
      <div className="flex items-center gap-4 mb-6">
        <button
          onClick={onBack}
          className="flex items-center gap-1 px-3 py-2 border rounded-lg hover:bg-gray-50"
        >
          <ArrowLeft size={16} />
          返回
        </button>
        <h1 className="text-2xl font-bold flex-1">{currentScene.name}</h1>
        <button
          onClick={refreshScene}
          disabled={loading}
          className="flex items-center gap-1 px-3 py-2 border rounded-lg hover:bg-gray-50 disabled:opacity-50"
        >
          <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          刷新
        </button>
      </div>

      {connected && (
        <div className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-lg flex items-center gap-2 text-blue-700">
          <RefreshCw size={18} className="animate-spin" />
          实时连接中... {progressMsg || '等待进度更新'}
        </div>
      )}

      {/* 3D 模型预览（就绪后显示）*/}
      {currentScene.status === 'ready' && (
        <div className="mb-6">
          <h3 className="font-semibold mb-3">模型预览</h3>
          <ScenePreview scene={currentScene} height={500} />
        </div>
      )}

      {currentScene.error_msg && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg flex items-start gap-2 text-red-700">
          <AlertCircle size={18} className="mt-0.5 flex-shrink-0" />
          <div>
            <div className="font-semibold mb-1">重建失败</div>
            <pre className="text-xs whitespace-pre-wrap bg-red-100 p-2 rounded">
              {currentScene.error_msg}
            </pre>
          </div>
        </div>
      )}

      {currentScene.description && (
        <div className="mb-6 p-4 bg-gray-50 rounded-lg">
          <p className="text-gray-700">{currentScene.description}</p>
        </div>
      )}

      {/* 基本信息卡 */}
      <div className="mb-6 grid grid-cols-2 gap-4">
        <div className="border rounded-lg p-4">
          <div className="text-sm text-gray-500 mb-1">类型</div>
          <div className="font-semibold">
            {currentScene.scene_kind === '4dgs' ? '4DGS 时序高斯Splatting' : '3DGS 静态高斯Splatting'}
          </div>
        </div>
        <div className="border rounded-lg p-4">
          <div className="text-sm text-gray-500 mb-1">状态</div>
          <div>
            <StatusBadge status={currentScene.status as any} />
          </div>
        </div>
        <div className="border rounded-lg p-4">
          <div className="text-sm text-gray-500 mb-1">源素材</div>
          <div className="font-semibold">{currentScene.n_source_images} 张图像</div>
          {currentScene.n_frames && (
            <div className="text-sm text-gray-500 mt-1">{currentScene.n_frames} 时序帧</div>
          )}
        </div>
        <div className="border rounded-lg p-4">
          <div className="text-sm text-gray-500 mb-1">重建结果</div>
          {currentScene.n_gaussians ? (
            <div className="font-semibold">{currentScene.n_gaussians.toLocaleString()} Gaussians</div>
          ) : (
            <div className="text-gray-500">尚未训练</div>
          )}
          {currentScene.psnr_train && (
            <div className="text-sm text-gray-500 mt-1">PSNR: {currentScene.psnr_train.toFixed(2)}</div>
          )}
        </div>
      </div>

      {/* 3D 预览 */}
      {currentScene.status === 'ready' && (
        <div className="mb-6">
          <h3 className="font-semibold mb-3">模型预览</h3>
          <ScenePreview scene={currentScene} height={500} />
        </div>
      )}

      {/* 素材资产列表 */}
      <div className="mb-6 border rounded-lg overflow-hidden">
        <div className="bg-gray-50 px-4 py-3 border-b flex items-center justify-between">
          <h3 className="font-semibold">素材资产 ({currentScene.assets?.length || 0})</h3>
          <label className="flex items-center gap-2 px-3 py-1.5 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 cursor-pointer transition-colors">
            <Plus size={16} />
            上传资产
            <input
              type="file"
              className="hidden"
              multiple
              onChange={handleFileUpload}
              disabled={loading || !['draft', 'ingested'].includes(currentScene.status)}
            />
          </label>
        </div>
        {uploadProgress.size > 0 && (
          <div className="p-3 bg-blue-50 border-b">
            {Array.from(uploadProgress.entries()).map(([name, {loaded, total}]) => (
              <div key={name} className="mb-2 last:mb-0">
                <div className="flex justify-between text-xs text-blue-700 mb-1">
                  <span>{name}</span>
                  <span>{Math.round((loaded / total) * 100)}%</span>
                </div>
                <div className="w-full bg-blue-200 rounded-full h-2">
                  <div
                    className="bg-blue-600 h-2 rounded-full transition-all"
                    style={{width: `${(loaded / total) * 100}%`}}
                  />
                </div>
              </div>
            ))}
          </div>
        )}
        <div className="divide-y">
          {currentScene.assets && currentScene.assets.length > 0 ? (
            currentScene.assets.map(asset => (
              <div key={asset.id} className="p-3 flex items-center justify-between">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-xs px-1.5 py-0.5 bg-gray-100 text-gray-600 rounded">
                      {asset.kind}
                    </span>
                    <span className="font-medium truncate">{asset.filename}</span>
                  </div>
                  {asset.size_bytes && (
                    <div className="text-xs text-gray-500 mt-1">
                      {(asset.size_bytes / (1024 * 1024)).toFixed(2)} MB
                    </div>
                  )}
                </div>
                <a
                  href={`${process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'}/api/v1/scenes/assets/${asset.id}/download`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1 px-3 py-1 text-sm border rounded hover:bg-gray-50"
                >
                  <Download size={14} />
                  下载
                </a>
              </div>
            ))
          ) : (
            <div className="p-6 text-center text-gray-500">
              暂无资产，请先上传素材
            </div>
          )}
        </div>
      </div>

      {/* 底部操作区 */}
      <div className="flex items-center justify-between border-t pt-6">
        <div>
          {currentScene.status === 'failed' && (
            <button
              onClick={handleReset}
              disabled={loading}
              className="px-4 py-2 border border-yellow-300 text-yellow-700 rounded-lg hover:bg-yellow-50 disabled:opacity-50"
            >
              重置场景
            </button>
          )}
          {!isTerminal && (
            <button
              onClick={handleArchive}
              disabled={loading}
              className="px-4 py-2 text-gray-600 border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50"
            >
              <Archive size={16} className="inline mr-1" />
              归档
            </button>
          )}
        </div>
        <div className="flex gap-3">
          {canStartColmap && (
            <button
              onClick={handleStartColmap}
              disabled={loading}
              className="flex items-center gap-2 px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
            >
              <Play size={18} />
              启动 COLMAP 重建
            </button>
          )}
          {canStartTraining && (
            <button
              onClick={handleStartTraining}
              disabled={loading}
              className="flex items-center gap-2 px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
            >
              <Zap size={18} />
              启动 GS 训练
            </button>
          )}
        </div>
      </div>
    </div>
  );
};
