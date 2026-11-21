/**
 * E2.3 · Copilot 长期记忆 API 客户端.
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
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
  return res.json();
}

export type MemoryKind = 'preference' | 'fact' | 'task_history' | 'insight';
export type MemoryScope = 'user' | 'org';

export interface Memory {
  id: string;
  org_id: string;
  user_id: string | null;
  kind: MemoryKind;
  scope: MemoryScope;
  key: string | null;
  content: string;
  tags: string[] | null;
  meta: Record<string, unknown> | null;
  ttl_days: number | null;
  weight: number;
  hit_count: number;
  created_at: string | null;
  last_hit_at: string | null;
  source_trace_id: string | null;
}

export interface MemoryHit {
  memory: Memory;
  score: number;
  reason: string;
}

export interface MemoryCreate {
  kind: MemoryKind;
  content: string;
  scope?: MemoryScope;
  key?: string;
  tags?: string[];
  meta?: Record<string, unknown>;
  ttl_days?: number;
  weight?: number;
}

// -- API --------------------------------------------------------

export function createMemory(body: MemoryCreate): Promise<Memory> {
  return _do<Memory>('/copilot/memory', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function searchMemory(opts?: {
  q?: string;
  kind?: MemoryKind[];
  tag?: string[];
  top_k?: number;
}): Promise<MemoryHit[]> {
  const p = new URLSearchParams();
  if (opts?.q) p.set('q', opts.q);
  (opts?.kind ?? []).forEach((k) => p.append('kind', k));
  (opts?.tag ?? []).forEach((t) => p.append('tag', t));
  if (opts?.top_k != null) p.set('top_k', String(opts.top_k));
  const qs = p.toString();
  return _do<MemoryHit[]>(`/copilot/memory/search${qs ? '?' + qs : ''}`);
}

export function memoryStats(): Promise<Record<string, number>> {
  return _do<Record<string, number>>('/copilot/memory/stats');
}

export function deleteMemory(id: string): Promise<{ deleted: boolean }> {
  return _do<{ deleted: boolean }>(`/copilot/memory/${id}`, { method: 'DELETE' });
}

// -- Pure helpers -----------------------------------------------

/** Chinese label for memory kind. */
export function kindLabel(k: MemoryKind): string {
  return {
    preference: '偏好',
    fact: '事实',
    task_history: '任务历史',
    insight: '洞察',
  }[k];
}

/** UI tag color for memory kind. */
export function kindColor(k: MemoryKind): string {
  return {
    preference: 'blue',
    fact: 'green',
    task_history: 'purple',
    insight: 'geekblue',
  }[k];
}

/**
 * Compute the retained days remaining for a TTL memory, or null if
 * ttl_days is 0/null (kept forever).
 */
export function daysRemaining(mem: Memory): number | null {
  if (!mem.ttl_days || !mem.created_at) return null;
  const created = new Date(mem.created_at).getTime();
  const elapsed = (Date.now() - created) / 86400000;
  return Math.max(0, Math.floor(mem.ttl_days - elapsed));
}

/** Snippet the content so long memories don't blow up the row height. */
export function snippet(text: string, maxLen = 100): string {
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen - 1) + '…';
}
