/**
 * E3.3 · Vision Detection alert rule client.
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

export type AlertAction = 'log' | 'feishu' | 'sms';
export const ALERT_ACTIONS: AlertAction[] = ['log', 'feishu', 'sms'];
export const ALERT_ACTION_LABEL: Record<AlertAction, string> = {
  log: '日志',
  feishu: '飞书通知',
  sms: '短信',
};

export interface AlertRule {
  id: string;
  name: string;
  label: string;
  min_member_count: number;
  min_peak_confidence: number;
  action: AlertAction;
  cooldown_seconds: number;
  enabled: boolean;
  last_fired_at: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface AlertFire {
  rule_id: string;
  rule_name: string;
  action: AlertAction;
  label: string;
  member_count: number;
  peak_confidence: number;
  centroid_lat: number;
  centroid_lng: number;
  first_seen_at: string | null;
  last_seen_at: string | null;
}

export interface EvaluateResult {
  evaluated_at: number;
  total_clusters: number;
  fires: AlertFire[];
  fire_count: number;
}

export function listAlertRules(
  opts?: { enabled_only?: boolean },
): Promise<AlertRule[]> {
  const qs = opts?.enabled_only ? '?enabled_only=true' : '';
  return _do<AlertRule[]>(`/vision/alerts${qs}`);
}

export function createAlertRule(
  payload: {
    name: string; label: string;
    min_member_count?: number; min_peak_confidence?: number;
    action?: AlertAction; cooldown_seconds?: number;
    notes?: string | null;
  },
): Promise<AlertRule> {
  return _do<AlertRule>('/vision/alerts', {
    method: 'POST', body: JSON.stringify(payload),
  });
}

export function updateAlertRule(
  id: string, patch: Partial<AlertRule>,
): Promise<AlertRule> {
  return _do<AlertRule>(`/vision/alerts/${encodeURIComponent(id)}`, {
    method: 'PATCH', body: JSON.stringify(patch),
  });
}

export function deleteAlertRule(id: string): Promise<void> {
  return _do<void>(`/vision/alerts/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  });
}

export function evaluateAlerts(
  since_seconds = 3600,
): Promise<EvaluateResult> {
  return _do<EvaluateResult>(
    `/vision/alerts/evaluate?since_seconds=${since_seconds}`,
    { method: 'POST' },
  );
}

// Pure helpers ----------------------------------------------------

/** Human-readable summary of thresholds for a rule row. */
export function ruleSummary(r: AlertRule): string {
  const parts: string[] = [];
  parts.push(
    r.label === '*' ? '任意类别' : `类别=${r.label}`,
  );
  parts.push(`成员≥${r.min_member_count}`);
  if (r.min_peak_confidence > 0)
    parts.push(`置信度≥${r.min_peak_confidence.toFixed(2)}`);
  if (r.cooldown_seconds > 0)
    parts.push(`冷却${r.cooldown_seconds}s`);
  return parts.join(' · ');
}

/** How long since a rule last fired (in Chinese). */
export function lastFiredAgo(r: AlertRule, now = new Date()): string {
  if (!r.last_fired_at) return '未触发';
  const then = new Date(r.last_fired_at).getTime();
  const delta = Math.max(0, (now.getTime() - then) / 1000);
  if (delta < 60) return `${Math.floor(delta)}秒前`;
  if (delta < 3600) return `${Math.floor(delta / 60)}分钟前`;
  if (delta < 86_400) return `${Math.floor(delta / 3600)}小时前`;
  return `${Math.floor(delta / 86_400)}天前`;
}
