import React, { useState, useEffect } from 'react';
import { ArrowLeft, Play, Pause, RefreshCw, Edit, Send, Check, X, FileText } from 'lucide-react';
import { api } from '../utils/api';
import { TaskChain, TaskStep, AdvanceChainRequest, ReflectChainRequest } from './types';
import { TaskStepItem } from './TaskStepItem';

interface TaskChainDetailProps {
  chain: TaskChain;
  orgId: string;
  onBack: () => void;
  onUpdate: () => void;
}

export const TaskChainDetail: React.FC<TaskChainDetailProps> = ({ chain, orgId, onBack, onUpdate }) => {
  const [currentChain, setCurrentChain] = useState<TaskChain>(chain);
  const [loading, setLoading] = useState(false);
  const [editingPlan, setEditingPlan] = useState(false);
  const [editedPlan, setEditedPlan] = useState(chain.plan || '');
  const [reflectText, setReflectText] = useState('');
  const [showAllResults, setShowAllResults] = useState(false);

  const refreshChain = async () => {
    try {
      setLoading(true);
      const response = await api.get(`/api/v1/copilot/chains/${currentChain.id}?org_id=${orgId}`);
      setCurrentChain(response.data);
      onUpdate();
    } catch (err) {
      console.error('Failed to refresh chain:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setCurrentChain(chain);
    setEditedPlan(chain.plan || '');
  }, [chain]);

  const handleAdvance = async () => {
    try {
      setLoading(true);
      await api.post(`/api/v1/copilot/chains/${currentChain.id}/advance`, {
        org_id: orgId,
      } as AdvanceChainRequest);
      await refreshChain();
    } catch (err) {
      console.error('Failed to advance chain:', err);
      alert('推进任务链失败');
    } finally {
      setLoading(false);
    }
  };

  const handleReflect = async () => {
    if (!reflectText.trim()) {
      alert('请输入反馈内容');
      return;
    }
    try {
      setLoading(true);
      await api.post(`/api/v1/copilot/chains/${currentChain.id}/reflect`, {
        org_id: orgId,
        feedback: reflectText.trim(),
      } as ReflectChainRequest);
      setReflectText('');
      await refreshChain();
    } catch (err) {
      console.error('Failed to reflect:', err);
      alert('反思更新失败');
    } finally {
      setLoading(false);
    }
  };

  const handleSavePlan = async () => {
    // 这里更新整个chain的plan，前端先改再刷新
    try {
      setLoading(true);
      await api.patch(`/api/v1/copilot/chains/${currentChain.id}`, {
        org_id: orgId,
        plan: editedPlan,
      });
      setEditingPlan(false);
      await refreshChain();
    } catch (err) {
      console.error('Failed to save plan:', err);
      alert('保存规划失败');
    } finally {
      setLoading(false);
    }
  };

  const handleCancel = async () => {
    if (!confirm('确定要取消此任务链吗？取消后无法恢复。')) return;
    try {
      setLoading(true);
      await api.post(`/api/v1/copilot/chains/${currentChain.id}/cancel`, {
        org_id: orgId,
      });
      await refreshChain();
      onUpdate();
    } catch (err) {
      console.error('Failed to cancel:', err);
      alert('取消失败');
    } finally {
      setLoading(false);
    }
  };

  const handleApprove = async (approved: boolean) => {
    try {
      setLoading(true);
      await api.post(`/api/v1/copilot/chains/${currentChain.id}/approve`, {
        org_id: orgId,
        approved: approved,
      });
      await refreshChain();
      onUpdate();
    } catch (err) {
      console.error('Failed to approve:', err);
      alert('审批操作失败');
    } finally {
      setLoading(false);
    }
  };

  const isRunningOrPending = currentChain.status === 'running' || currentChain.status === 'paused';
  const canAdvance = currentChain.status === 'paused' ||
    (currentChain.status === 'pending_approval' && currentChain.approved === false) ||
    (currentChain.status === 'running' && currentChain.current_step_index < (currentChain.steps?.length || 0));
  const needsApproval = currentChain.status === 'pending_approval';
  const isDone = currentChain.status === 'completed' || currentChain.status === 'cancelled' || currentChain.status === 'failed';

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
        <h1 className="text-2xl font-bold flex-1">{currentChain.name}</h1>
        <button
          onClick={refreshChain}
          disabled={loading}
          className="flex items-center gap-1 px-3 py-2 border rounded-lg hover:bg-gray-50 disabled:opacity-50"
        >
          <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          刷新
        </button>
      </div>

      {currentChain.description && (
        <div className="mb-6 p-4 bg-gray-50 rounded-lg">
          <p className="text-gray-700">{currentChain.description}</p>
        </div>
      )}

      {/* 规划部分 */}
      <div className="mb-6 border rounded-lg overflow-hidden">
        <div className="bg-gray-50 px-4 py-3 border-b flex items-center justify-between">
          <div className="flex items-center gap-2">
            <FileText size={18} />
            <h3 className="font-semibold">执行规划</h3>
          </div>
          {!isDone && !editingPlan && (
            <button
              onClick={() => setEditingPlan(true)}
              className="flex items-center gap-1 px-2 py-1 text-sm border rounded hover:bg-gray-100"
            >
              <Edit size={14} />
              编辑
            </button>
          )}
        </div>
        <div className="p-4">
          {editingPlan ? (
            <div className="space-y-3">
              <textarea
                value={editedPlan}
                onChange={(e) => setEditedPlan(e.target.value)}
                className="w-full h-32 p-2 border rounded font-mono text-sm"
                placeholder="在这里编辑任务执行规划..."
              />
              <div className="flex justify-end gap-2">
                <button
                  onClick={() => {
                    setEditingPlan(false);
                    setEditedPlan(currentChain.plan || '');
                  }}
                  className="px-3 py-1 border rounded hover:bg-gray-50"
                >
                  取消
                </button>
                <button
                  onClick={handleSavePlan}
                  disabled={loading}
                  className="px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
                >
                  保存
                </button>
              </div>
            </div>
          ) : (
            <pre className="whitespace-pre-wrap text-sm text-gray-700 font-sans">
              {currentChain.plan || '暂无规划'}
            </pre>
          )}
        </div>
      </div>

      {/* 反思结果 */}
      {currentChain.reflection && (
        <div className="mb-6 border rounded-lg overflow-hidden">
          <div className="bg-purple-50 px-4 py-3 border-b">
            <h3 className="font-semibold text-purple-900">反思总结</h3>
          </div>
          <div className="p-4">
            <pre className="whitespace-pre-wrap text-sm text-gray-700 font-sans">
              {currentChain.reflection}
            </pre>
          </div>
        </div>
      )}

      {/* 步骤列表 */}
      <div className="mb-6">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-semibold text-lg">执行步骤</h3>
          <label className="flex items-center gap-2 text-sm text-gray-600">
            <input
              type="checkbox"
              checked={showAllResults}
              onChange={(e) => setShowAllResults(e.target.checked)}
              className="rounded border-gray-300"
            />
            显示所有步骤结果
          </label>
        </div>
        <div className="space-y-3">
          {currentChain.steps?.map((step) => (
            <TaskStepItem
              key={step.id}
              step={step}
              isCurrent={step.index === currentChain.current_step_index}
              showResult={showAllResults || step.status !== 'pending'}
            />
          ))}
        </div>
      </div>

      {/* 审批区 */}
      {needsApproval && (
        <div className="mb-6 p-4 border-2 border-purple-200 bg-purple-50 rounded-lg">
          <h3 className="font-semibold text-purple-900 mb-3">此步骤需要审批</h3>
          <p className="text-sm text-purple-700 mb-4">
            当前第 {currentChain.approval_step_index! + 1} 步涉及敏感操作，需要人工审批后才能继续执行。
          </p>
          <div className="flex gap-3">
            <button
              onClick={() => handleApprove(true)}
              disabled={loading}
              className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50"
            >
              <Check size={18} />
              同意执行
            </button>
            <button
              onClick={() => handleApprove(false)}
              disabled={loading}
              className="flex items-center gap-2 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50"
            >
              <X size={18} />
              拒绝
            </button>
          </div>
        </div>
      )}

      {/* 反思输入区 */}
      {!isDone && (
        <div className="mb-6 border rounded-lg overflow-hidden">
          <div className="bg-blue-50 px-4 py-3 border-b">
            <h3 className="font-semibold text-blue-900">添加反馈与反思</h3>
          </div>
          <div className="p-4">
            <textarea
              value={reflectText}
              onChange={(e) => setReflectText(e.target.value)}
              placeholder="输入你对当前进度的反馈，LLM 将根据反思调整后续步骤..."
              className="w-full h-24 p-2 border rounded text-sm mb-3"
            />
            <div className="flex justify-end">
              <button
                onClick={handleReflect}
                disabled={loading || !reflectText.trim()}
                className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
              >
                <Send size={16} />
                提交反思
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 底部操作栏 */}
      <div className="flex items-center justify-between border-t pt-6">
        <div>
          {!isDone && (
            <button
              onClick={handleCancel}
              disabled={loading}
              className="px-4 py-2 text-red-600 border border-red-200 rounded-lg hover:bg-red-50 disabled:opacity-50"
            >
              取消任务链
            </button>
          )}
        </div>
        <div className="flex gap-3">
          {canAdvance && !needsApproval && (
            <button
              onClick={handleAdvance}
              disabled={loading}
              className="flex items-center gap-2 px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
            >
              <Play size={18} />
              {currentChain.status === 'paused' ? '继续执行' : '下一步'}
            </button>
          )}
          {currentChain.status === 'running' && (
            <button
              // 暂停
              disabled={loading}
              className="flex items-center gap-2 px-4 py-2 border border-orange-300 text-orange-700 rounded-lg hover:bg-orange-50 disabled:opacity-50"
            >
              <Pause size={18} />
              暂停
            </button>
          )}
        </div>
      </div>

      {/* 审批信息 */}
      {currentChain.approved_at && (
        <div className="mt-4 text-xs text-gray-500 text-right">
          {currentChain.approved ? '✅' : '❌'} 由 {currentChain.approved_by} 于 {new Date(currentChain.approved_at!).toLocaleString('zh-CN')} {currentChain.approved ? '批准' : '拒绝'}
        </div>
      )}
    </div>
  );
};
