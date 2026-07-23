// Copilot Task Chain 前端类型定义

export type TaskChainStatus =
  | 'draft'
  | 'planning'
  | 'running'
  | 'paused'
  | 'pending_approval'
  | 'completed'
  | 'failed'
  | 'cancelled';

export type StepStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'failed'
  | 'skipped';

export interface TaskStep {
  id: string;
  index: number;
  description: string;
  status: StepStatus;
  tool_name?: string;
  tool_args?: Record<string, any>;
  result?: string;
  error?: string;
  started_at?: string;
  completed_at?: string;
}

export interface TaskChain {
  id: string;
  org_id: string;
  name: string;
  description?: string;
  status: TaskChainStatus;
  steps: TaskStep[];
  current_step_index: number;
  plan: string;
  reflection?: string;
  created_by: string;
  requires_approval: boolean;
  approval_step_index?: number;
  approved_by?: string;
  approved_at?: string;
  approved?: boolean;
  created_at: string;
  updated_at: string;
  completed_at?: string;
}

export interface CreateChainRequest {
  name: string;
  description?: string;
  initial_plan?: string;
  steps?: Partial<TaskStep>[];
  requires_approval: boolean;
}

export interface PlanFromPromptRequest {
  prompt: string;
  org_id: string;
}

export interface AdvanceChainRequest {
  chain_id: string;
  revised_steps?: TaskStep[];
}

export interface ReflectChainRequest {
  chain_id: string;
  feedback: string;
}
