import React, { useState, useEffect } from 'react';
import { Plus, Play, Pause, RefreshCw, CheckCircle, XCircle, Clock, AlertTriangle } from 'lucide-react';
import { api } from '../utils/api';
import { TaskChain, TaskChainStatus, TaskStep } from './types';

interface TaskChainListProps {
  orgId: string;
  onSelectChain: (chain: TaskChain) => void;
  onCreateNew: () => void;
}

const StatusBadge: React.FC<{ status: TaskChainStatus }> = ({ status }) => {
  const statusMap = {
    draft: { label: '草稿', color: 'bg-gray-200 text-gray-700' },
    planning: { label: '规划中', color: 'bg-blue-100 text-blue-700' },
    running: { label: '执行中', color: 'bg-yellow-100 text-yellow-700' },
    paused: { label: '已暂停', color: 'bg-orange-100 text-orange-700' },
    pending_approval: { label: '待审批', color: 'bg-purple-100 text-purple-700' },
    completed: { label: '已完成', color: 'bg-green-100 text-green-700' },
    failed: { label: '失败', color: 'bg-red-100 text-red-700' },
    cancelled: { label: '已取消', color: 'bg-gray-300 text-gray-700' },
  };

  const { label, color } = statusMap[status] || statusMap.draft;
  return (
    <span className={`px-2 py-1 rounded-full text-xs font-medium ${color}`}>
      {label}
    </span>
  );
};

export const TaskChainList: React.FC<TaskChainListProps> = ({ orgId, onSelectChain, onCreateNew }) => {
  const [chains, setChains] = useState<TaskChain[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadChains = async () => {
    try {
      setLoading(true);
      const response = await api.get(`/api/v1/copilot/chains?org_id=${orgId}`);
      setChains(response.data);
      setError(null);
    } catch (err) {
      setError('加载任务链失败');
      console.error('Failed to load task chains:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadChains();
  }, [orgId]);

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleString('zh-CN');
  };

  const getStepProgress = (chain: TaskChain) => {
    if (!chain.steps || chain.steps.length === 0) return 0;
    const completed = chain.steps.filter(s => s.status === 'completed').length;
    return Math.round((completed / chain.steps.length) * 100);
  };

  return (
    <div className="p-4">
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-xl font-bold">Copilot 任务链</h2>
        <button
          onClick={onCreateNew}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
        >
          <Plus size={16} />
          新建任务链
        </button>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg flex items-center gap-2 text-red-700">
          <AlertTriangle size={18} />
          {error}
          <button onClick={loadChains} className="ml-auto text-sm underline">重试</button>
        </div>
      )}

      {loading ? (
        <div className="flex justify-center items-center py-12 text-gray-500">
          <RefreshCw size={20} className="animate-spin mr-2" />
          加载中...
        </div>
      ) : chains.length === 0 ? (
        <div className="text-center py-12 text-gray-500">
          <p className="mb-4">暂无任务链</p>
          <button
            onClick={onCreateNew}
            className="text-blue-600 hover:underline"
          >
            创建第一个任务链
          </button>
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {chains.map(chain => (
            <div
              key={chain.id}
              onClick={() => onSelectChain(chain)}
              className="border rounded-lg p-4 hover:shadow-md transition-shadow cursor-pointer bg-white"
            >
              <div className="flex justify-between items-start mb-2">
                <h3 className="font-semibold text-gray-900 truncate pr-2">
                  {chain.name || '未命名任务链'}
                </h3>
                <StatusBadge status={chain.status} />
              </div>

              {chain.description && (
                <p className="text-sm text-gray-600 mb-3 line-clamp-2">
                  {chain.description}
                </p>
              )}

              {chain.steps && chain.steps.length > 0 && (
                <div className="mb-3">
                  <div className="flex justify-between text-xs text-gray-500 mb-1">
                    <span>进度</span>
                    <span>{getStepProgress(chain)}% ({chain.steps.filter(s => s.status === 'completed').length}/{chain.steps.length})</span>
                  </div>
                  <div className="w-full bg-gray-200 rounded-full h-2">
                    <div
                      className="bg-blue-600 h-2 rounded-full transition-all"
                      style={{ width: `${getStepProgress(chain)}%` }}
                    />
                  </div>
                </div>
              )}

              <div className="flex items-center justify-between text-xs text-gray-500">
                <div className="flex items-center gap-1">
                  <Clock size={12} />
                  {formatDate(chain.created_at)}
                </div>
                {chain.requires_approval && (
                  <span className="px-1.5 py-0.5 bg-purple-50 text-purple-600 rounded">需审批</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
