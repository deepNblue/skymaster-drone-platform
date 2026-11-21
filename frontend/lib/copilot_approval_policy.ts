/**
 * E2.5 · 双签/多签审批策略 API 客户端.
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
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
  return res.json();
}

export type RiskLevel = 'low' | 'medium' | 'high' | 'critical';

export interface ApprovalPolicy {
  org_id: string;
  dual_sign_tools: string[] | null;
  dual_sign_min_risk: RiskLevel | null;
  required_roles: string[] | null;
  bypass_roles: string[] | null;
}

export interface ApprovalSignoff {
  id: string;
  signer_id: string;
  signer_role: string | null;
  decision: 'approve' | 'reject';
  comment: string | null;
  created_at: string | null;
}

export interface ApprovalStatus {
  approval_id: string;
  needs_signs: number;
  done_signs: number;
  required_roles: string[];
  reason: string;
  final_decision: 'approve' | 'reject' | null;
  signoffs: ApprovalSignoff[];
}

export function getPolicy(): Promise<ApprovalPolicy | null> {
  return _do<ApprovalPolicy | null>('/copilot/approval-policy/me');
}

export function upsertPolicy(
  body: Omit<ApprovalPolicy, 'org_id'>,
): Promise<ApprovalPolicy> {
  return _do<ApprovalPolicy>('/copilot/approval-policy/me', {
    method: 'PUT',
    body: JSON.stringify(body),
  });
}

export function signApproval(
  approvalId: string,
  body: {
    decision: 'approve' | 'reject';
    comment?: string;
    tool_name: string;
    risk_level?: RiskLevel;
  },
): Promise<{ final_decision: string | null; needs_signs: number; done_signs: number }> {
  return _do(
    `/copilot/approval-policy/approvals/${approvalId}/sign`,
    { method: 'POST', body: JSON.stringify(body) },
  );
}

export function approvalStatus(
  approvalId: string,
  toolName: string,
  riskLevel?: RiskLevel,
): Promise<ApprovalStatus> {
  const p = new URLSearchParams({ tool_name: toolName });
  if (riskLevel) p.set('risk_level', riskLevel);
  return _do<ApprovalStatus>(
    `/copilot/approval-policy/approvals/${approvalId}/status?${p}`,
  );
}

// -- Pure helpers -----------------------------------------------

export function riskColor(r: RiskLevel | null): string {
  if (!r) return 'default';
  return { low: 'green', medium: 'blue', high: 'orange', critical: 'red' }[r];
}

export function progressPct(status: ApprovalStatus): number {
  if (!status.needs_signs) return 0;
  return Math.round((status.done_signs / status.needs_signs) * 100);
}

export function finalBadge(
  final: string | null,
): { text: string; color: string } {
  if (final === 'approve') return { text: '已批准', color: 'green' };
  if (final === 'reject') return { text: '已拒绝', color: 'red' };
  return { text: '待签', color: 'gold' };
}
