/**
 * E2.4 · Copilot Task Chain API 客户端.
 */
const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

function token(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('access_token');
}

async function _do<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(init?.headers as Record<string, string> | undefined),
  };
  const t = token();
  if (t) headers['Authorization'] = `Bearer ${t}`;
  const res = await fetch(`${API}/api/v1${path}`, { ...init, headers });
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
  return res.json();
}

export type ChainStatus = 'draft' | 'running' | 'paused' | 'completed' | 'failed' | 'cancelled';
export type StepStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'skipped' | 'paused';

export interface Subtask {
  title: string;
  tool: string;
  args: Record<string, unknown>;
  why?: string;
}

export interface Chain {
  id: string;
  org_id: string | null;
  owner_user_id: string;
  conversation_id: string | null;
  goal: string;
  plan_json: Subtask[] | null;
  status: ChainStatus;
  current_index: number;
  reflection_notes: string | null;
  error: string | null;
  created_at: string | null;
  updated_at: string | null;
  completed_at: string | null;
}

export interface Step {
  id: string;
  chain_id: string;
  step_index: number;
  title: string;
  tool: string;
  args_planned: Record<string, unknown> | null;
  args_resolved: Record<string, unknown> | null;
  output_json: unknown;
  status: StepStatus;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface Revision {
  id: string;
  chain_id: string;
  at_step_index: number;
  kind: 'append_step' | 'replace_remaining' | 'mark_completed' | 'abort';
  prev_plan: Subtask[] | null;
  new_plan: Subtask[] | null;
  reason: string;
  created_at: string | null;
}

export function createChain(body: {
  goal: string;
  plan: Subtask[];
  conversation_id?: string;
}): Promise<Chain> {
  return _do('/copilot/task-chains', {
    method: 'POST', body: JSON.stringify(body),
  });
}

export function listChains(params: {
  status?: ChainStatus;
  limit?: number;
} = {}): Promise<{ items: Chain[] }> {
  const p = new URLSearchParams();
  if (params.status) p.set('status', params.status);
  if (params.limit) p.set('limit', String(params.limit));
  const qs = p.toString();
  return _do(`/copilot/task-chains${qs ? `?${qs}` : ''}`);
}

export function getChain(id: string): Promise<{
  chain: Chain;
  steps: Step[];
  revisions: Revision[];
}> {
  return _do(`/copilot/task-chains/${id}`);
}

export function advanceStep(id: string): Promise<{ step: Step; chain: Chain }> {
  return _do(`/copilot/task-chains/${id}/advance`, { method: 'POST' });
}

export function runChain(id: string, maxSteps = 32): Promise<{
  chain: Chain; steps: Step[];
}> {
  return _do(
    `/copilot/task-chains/${id}/run?max_steps=${maxSteps}`,
    { method: 'POST' },
  );
}

export function reviseChain(id: string, body: {
  kind: Revision['kind'];
  new_tail?: Subtask[];
  reason: string;
}): Promise<Revision> {
  return _do(`/copilot/task-chains/${id}/revise`, {
    method: 'POST', body: JSON.stringify(body),
  });
}

export function cancelChain(id: string): Promise<Chain> {
  return _do(`/copilot/task-chains/${id}/cancel`, { method: 'POST' });
}

export function autoCreateChain(body: {
  goal: string;
  conversation_id?: string;
}): Promise<Chain> {
  return _do('/copilot/task-chains/auto', {
    method: 'POST', body: JSON.stringify(body),
  });
}

export function planChain(body: { goal: string }): Promise<{
  goal: string;
  plan: Subtask[];
}> {
  return _do('/copilot/task-chains/plan', {
    method: 'POST', body: JSON.stringify(body),
  });
}

export function reflectChain(id: string, body: {
  trigger?: 'step_failed' | 'user_reflect' | 'off_track';
  apply?: boolean;
}): Promise<{
  suggestion: {
    kind: Revision['kind'];
    new_tail: Subtask[] | null;
    reason: string;
  };
  applied?: Revision;
  apply_error?: string;
}> {
  return _do(`/copilot/task-chains/${id}/reflect`, {
    method: 'POST', body: JSON.stringify(body),
  });
}

export interface Approval {
  id: string;
  chain_id: string;
  step_id: string;
  step_index: number;
  tool_name: string;
  risk_level: string;
  permission: string;
  required_reason: string;
  args_snapshot: Record<string, unknown> | null;
  status: 'pending' | 'approved' | 'rejected' | 'expired';
  approver_id: string | null;
  decision_reason: string | null;
  modifications: Record<string, unknown> | null;
  created_at: string | null;
  decided_at: string | null;
}

export interface PendingApprovalItem {
  approval: Approval;
  chain: {
    id: string;
    goal: string;
    status: ChainStatus;
    current_index: number;
  };
}

export function listPendingApprovals(limit = 50): Promise<{
  items: PendingApprovalItem[];
}> {
  return _do(`/copilot/task-chains/approvals/pending?limit=${limit}`);
}

export function listChainApprovals(chainId: string): Promise<{
  items: Approval[];
}> {
  return _do(`/copilot/task-chains/${chainId}/approvals`);
}

export function decideApproval(
  approvalId: string,
  body: {
    decision: 'approved' | 'rejected';
    reason: string;
    modifications?: Record<string, unknown>;
  },
  resume = true,
): Promise<{
  approval: Approval;
  resumed_step?: Step;
  chain?: Chain;
  resume_error?: string;
}> {
  return _do(
    `/copilot/task-chains/approvals/${approvalId}/decide?resume=${resume}`,
    { method: 'POST', body: JSON.stringify(body) },
  );
}

// --- helpers ---

export function statusColor(s: ChainStatus | StepStatus): string {
  const m: Record<string, string> = {
    draft: 'default',
    running: 'processing',
    paused: 'warning',
    completed: 'success',
    failed: 'error',
    cancelled: 'default',
    succeeded: 'success',
    pending: 'default',
    skipped: 'default',
  };
  return m[s] ?? 'default';
}

export function statusLabel(s: ChainStatus | StepStatus): string {
  const m: Record<string, string> = {
    draft: '计划中',
    running: '执行中',
    paused: '已暂停',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
    succeeded: '成功',
    pending: '待执行',
    skipped: '已跳过',
  };
  return m[s] ?? s;
}

export function progressPercent(chain: Chain): number {
  const total = (chain.plan_json ?? []).length;
  if (total === 0) return 0;
  return Math.round((chain.current_index / total) * 100);
}
