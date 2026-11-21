/**
 * F4.4 · Copilot tool policy + audit client.
 */
const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

function token(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('skymaster_token');
}

async function _do<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(init?.headers as Record<string, string> | undefined),
  };
  const t = token();
  if (t) headers['Authorization'] = `Bearer ${t}`;
  const res = await fetch(`${API}/api/v1${path}`, { ...init, headers });
  if (res.status === 204) return undefined as unknown as T;
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${await res.text()}`);
  }
  return res.json();
}

export type RiskLevel = 'low' | 'medium' | 'high' | 'critical';
export type ToolPermission = 'readonly' | 'sensitive';
export type AuditStatus =
  | 'executed'
  | 'blocked'
  | 'approval_required'
  | 'rejected'
  | 'error';

export interface ToolCatalogItem {
  name: string;
  description: string;
  permission: ToolPermission;
  risk_level: RiskLevel;
}

export interface ToolPolicy {
  org_id: string;
  allowlist: string[] | null;
  blocklist: string[] | null;
  max_risk_level: RiskLevel | null;
  require_approval_above: RiskLevel | null;
  updated_at: string | null;
}

export interface ToolPolicyPatch {
  allowlist?: string[] | null;
  blocklist?: string[] | null;
  max_risk_level?: RiskLevel | null;
  require_approval_above?: RiskLevel | null;
}

export interface ToolAudit {
  id: string;
  org_id: string;
  user_id: string;
  session_id: string | null;
  trace_id: string | null;
  tool_name: string;
  permission: ToolPermission;
  risk_level: RiskLevel;
  status: AuditStatus;
  arguments: Record<string, unknown> | null;
  result_preview: string | null;
  error: string | null;
  latency_ms: number | null;
  reason: string | null;
  created_at: string | null;
}

// -- API --------------------------------------------------------

export function listTools(): Promise<ToolCatalogItem[]> {
  return _do<ToolCatalogItem[]>('/copilot/tool-policy/tools');
}

export function getMyPolicy(): Promise<ToolPolicy | null> {
  return _do<ToolPolicy | null>('/copilot/tool-policy/me');
}

export function putMyPolicy(patch: ToolPolicyPatch): Promise<ToolPolicy> {
  return _do<ToolPolicy>('/copilot/tool-policy/me', {
    method: 'PUT',
    body: JSON.stringify(patch),
  });
}

export function listAudits(opts?: {
  tool_name?: string;
  status?: AuditStatus;
  risk_level?: RiskLevel;
  limit?: number;
  offset?: number;
}): Promise<ToolAudit[]> {
  const p = new URLSearchParams();
  if (opts?.tool_name) p.set('tool_name', opts.tool_name);
  if (opts?.status) p.set('status', opts.status);
  if (opts?.risk_level) p.set('risk_level', opts.risk_level);
  if (opts?.limit != null) p.set('limit', String(opts.limit));
  if (opts?.offset != null) p.set('offset', String(opts.offset));
  const qs = p.toString();
  return _do<ToolAudit[]>(
    `/copilot/tool-policy/audits${qs ? '?' + qs : ''}`,
  );
}

export function auditStats(): Promise<Record<string, Record<string, number>>> {
  return _do('/copilot/tool-policy/audits/stats');
}

// -- Pure helpers -----------------------------------------------

/** Order: low < medium < high < critical. */
export const RISK_ORDER: Record<RiskLevel, number> = {
  low: 0, medium: 1, high: 2, critical: 3,
};

/** UI tag color per risk tier. */
export function riskColor(r: RiskLevel): string {
  return { low: 'green', medium: 'gold', high: 'orange', critical: 'red' }[r];
}

/** UI tag color per audit status. */
export function statusColor(s: AuditStatus): string {
  return {
    executed: 'green',
    blocked: 'red',
    approval_required: 'gold',
    rejected: 'default',
    error: 'volcano',
  }[s];
}

/** Chinese label for risk tier. */
export function riskLabel(r: RiskLevel): string {
  return { low: '低', medium: '中', high: '高', critical: '致命' }[r];
}

/** Chinese label for audit status. */
export function statusLabel(s: AuditStatus): string {
  return {
    executed: '已执行',
    blocked: '被拦截',
    approval_required: '待审批',
    rejected: '已拒绝',
    error: '出错',
  }[s];
}

/** Would a given tool be blocked under a candidate policy? Client-side preview. */
export function previewDecision(
  tool: ToolCatalogItem, policy: ToolPolicyPatch,
): { action: 'allowed' | 'blocked' | 'approval_required'; reason?: string } {
  const blocklist = policy.blocklist ?? [];
  const allowlist = policy.allowlist ?? [];

  if (blocklist.includes(tool.name)) {
    return { action: 'blocked', reason: '在黑名单' };
  }
  if (allowlist.length > 0 && !allowlist.includes(tool.name)) {
    return { action: 'blocked', reason: '不在白名单' };
  }
  const cap = policy.max_risk_level;
  if (cap && RISK_ORDER[tool.risk_level] > RISK_ORDER[cap]) {
    return {
      action: 'blocked',
      reason: `风险 ${riskLabel(tool.risk_level)} 超过上限 ${riskLabel(cap)}`,
    };
  }
  if (tool.permission === 'sensitive') {
    return { action: 'approval_required', reason: '敏感工具' };
  }
  const gate = policy.require_approval_above;
  if (gate && RISK_ORDER[tool.risk_level] >= RISK_ORDER[gate]) {
    return { action: 'approval_required', reason: '达到审批门槛' };
  }
  return { action: 'allowed' };
}

/** Aggregate stats to a flat leaderboard by tool. */
export function flattenStats(
  stats: Record<string, Record<string, number>>,
): { tool: string; executed: number; blocked: number; approval_required: number }[] {
  const tools = new Set<string>();
  Object.values(stats).forEach((m) => Object.keys(m).forEach((t) => tools.add(t)));
  return [...tools].map((tool) => ({
    tool,
    executed: stats.executed?.[tool] ?? 0,
    blocked: stats.blocked?.[tool] ?? 0,
    approval_required: stats.approval_required?.[tool] ?? 0,
  })).sort((a, b) => (b.blocked + b.approval_required) - (a.blocked + a.approval_required));
}
