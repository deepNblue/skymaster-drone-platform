import React from 'react';
import { CheckCircle, XCircle, Play, Loader2, Clock, SkipForward } from 'lucide-react';
import { TaskStep, StepStatus } from './types';

interface TaskStepItemProps {
  step: TaskStep;
  isCurrent: boolean;
  showResult: boolean;
}

const StepStatusIcon: React.FC<{ status: StepStatus }> = ({ status }) => {
  switch (status) {
    case 'completed':
      return <CheckCircle size={18} className="text-green-600" />;
    case 'failed':
      return <XCircle size={18} className="text-red-600" />;
    case 'running':
      return <Loader2 size={18} className="text-yellow-600 animate-spin" />;
    case 'skipped':
      return <SkipForward size={18} className="text-gray-400" />;
    case 'pending':
    default:
      return <Clock size={18} className="text-gray-400" />;
  }
};

const StepStatusBg: React.FC<{ status: StepStatus; isCurrent: boolean; children: React.ReactNode }> = ({ status, isCurrent, children }) => {
  let bgClass = '';
  if (isCurrent) {
    bgClass = 'bg-yellow-50 border-yellow-200';
  } else if (status === 'completed') {
    bgClass = 'bg-green-50 border-green-200';
  } else if (status === 'failed') {
    bgClass = 'bg-red-50 border-red-200';
  } else if (status === 'skipped') {
    bgClass = 'bg-gray-50 border-gray-200';
  } else {
    bgClass = 'bg-white border-gray-200';
  }
  return (
    <div className={`border rounded-lg p-3 ${bgClass}`}>
      {children}
    </div>
  );
};

export const TaskStepItem: React.FC<TaskStepItemProps> = ({ step, isCurrent, showResult }) => {
  const hasResult = step.result && showResult;
  const hasError = step.error;

  return (
    <StepStatusBg status={step.status} isCurrent={isCurrent}>
      <div className="flex items-start gap-3">
        <div className="mt-0.5 flex-shrink-0">
          <StepStatusIcon status={step.status} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between mb-1">
            <p className={`text-sm font-medium ${
              step.status === 'failed' ? 'text-red-800' :
              step.status === 'completed' ? 'text-green-800' :
              isCurrent ? 'text-yellow-800' : 'text-gray-700'
            }`}>
              {step.index + 1}. {step.description}
            </p>
            {step.tool_name && (
              <span className="text-xs px-1.5 py-0.5 bg-gray-100 text-gray-600 rounded">
                {step.tool_name}
              </span>
            )}
          </div>

          {step.started_at && (
            <div className="text-xs text-gray-500 mb-1">
              开始: {new Date(step.started_at).toLocaleTimeString('zh-CN')}
              {step.completed_at && ` · 完成: ${new Date(step.completed_at).toLocaleTimeString('zh-CN')}`}
            </div>
          )}

          {hasError && (
            <div className="mt-2 p-2 bg-red-100 border border-red-200 rounded text-xs text-red-800 whitespace-pre-wrap">
              {step.error}
            </div>
          )}

          {hasResult && (
            <div className="mt-2 p-2 bg-gray-50 border border-gray-200 rounded text-xs text-gray-800 whitespace-pre-wrap max-h-60 overflow-y-auto">
              {step.result}
            </div>
          )}
        </div>
      </div>
    </StepStatusBg>
  );
};
