import React, { useState } from 'react';
import { X } from 'lucide-react';
import { api } from '../utils/api';
import { CreateChainRequest, PlanFromPromptRequest } from './types';

interface CreateChainModalProps {
  orgId: string;
  onClose: () => void;
  onCreated: (chainId: string) => void;
}

type Mode = 'manual' | 'auto';

export const CreateChainModal: React.FC<CreateChainModalProps> = ({ orgId, onClose, onCreated }) => {
  const [mode, setMode] = useState<Mode>('auto');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [prompt, setPrompt] = useState('');
  const [requiresApproval, setRequiresApproval] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) {
      setError('请输入任务链名称');
      return;
    }

    if (mode === 'auto' && !prompt.trim()) {
      setError('请输入任务描述，Copilot 将根据描述生成规划');
      return;
    }

    try {
      setLoading(true);
      setError(null);

      if (mode === 'auto') {
        // LLM 自动规划
        const response = await api.post('/api/v1/copilot/planner/plan_from_prompt', {
          prompt: prompt.trim(),
          org_id: orgId,
          name: name.trim(),
          description: description.trim(),
          requires_approval: requiresApproval,
        } as PlanFromPromptRequest);
        onCreated(response.data.id);
      } else {
        // 手动创建
        const response = await api.post('/api/v1/copilot/chains', {
          name: name.trim(),
          description: description.trim(),
          requires_approval: requiresApproval,
        } as CreateChainRequest);
        onCreated(response.data.id);
      }
    } catch (err) {
      console.error('Failed to create chain:', err);
      setError('创建任务链失败，请重试');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between px-6 py-4 border-b">
          <h2 className="text-xl font-bold">新建 Copilot 任务链</h2>
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
              创建模式
            </label>
            <div className="flex gap-4">
              <label className="flex items-center gap-2">
                <input
                  type="radio"
                  checked={mode === 'auto'}
                  onChange={() => setMode('auto')}
                  className="text-blue-600"
                />
                <span>自动规划（LLM 根据你的需求生成步骤）</span>
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="radio"
                  checked={mode === 'manual'}
                  onChange={() => setMode('manual')}
                  className="text-blue-600"
                />
                <span>手动创建（自己写规划和步骤）</span>
              </label>
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              任务链名称 <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              placeholder="例如：每日无人机巡检计划"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              任务描述
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              placeholder="简单描述这个任务链的目标"
              rows={2}
            />
          </div>

          {mode === 'auto' && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                自然语言任务描述 <span className="text-red-500">*</span>
              </label>
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                placeholder="例如：帮我规划今日 3 架无人机的输电线路巡检任务，包括起飞前检查、航线上传、执行巡检、降落复盘四个步骤，发现异常需要自动触发告警..."
                rows={5}
                required
              />
              <p className="text-xs text-gray-500 mt-1">
                Copilot 使用 LLM 理解你的需求，自动分解为可执行的多步骤任务链
              </p>
            </div>
          )}

          <div>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={requiresApproval}
                onChange={(e) => setRequiresApproval(e.target.checked)}
                className="rounded border-gray-300 text-blue-600"
              />
              <span className="text-sm text-gray-700">敏感步骤需要人工审批（推荐开启）</span>
            </label>
            <p className="text-xs text-gray-500 mt-1">
              开启后，涉及起飞、调度、修改参数等敏感操作会暂停等待人工审批再继续
            </p>
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
              {loading ? '创建中...' : mode === 'auto' ? 'Copilot 规划' : '创建'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
