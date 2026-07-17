/**
 * F4.2 · Copilot prompt template admin client.
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

export type Persona = 'operator' | 'analyst' | 'instructor';
export const PERSONAS: readonly Persona[] = [
  'operator', 'analyst', 'instructor',
];

export interface PromptTemplate {
  id: string;
  persona: Persona;
  version: number;
  name: string;
  system_prompt: string;
  notes: string | null;
  is_active: boolean;
  created_by: string | null;
  created_at: string | null;
}

export interface DiffResult {
  persona: Persona;
  from_version: number;
  to_version: number;
  diff: string;
  changed: boolean;
}

export interface TemplateIn {
  persona: Persona;
  name: string;
  system_prompt: string;
  notes?: string;
  activate?: boolean;
}

export function createTemplate(
  body: TemplateIn,
): Promise<PromptTemplate> {
  return _do<PromptTemplate>(
    `/copilot/prompt-templates`,
    { method: 'POST', body: JSON.stringify(body) },
  );
}

export function activateVersion(
  persona: Persona, version: number,
): Promise<PromptTemplate> {
  return _do(
    `/copilot/prompt-templates/${persona}` +
    `/versions/${version}/activate`,
    { method: 'POST' },
  );
}

export function rollback(persona: Persona): Promise<PromptTemplate> {
  return _do(
    `/copilot/prompt-templates/${persona}/rollback`,
    { method: 'POST' },
  );
}

export function listTemplates(opts?: {
  persona?: Persona; limit?: number; offset?: number;
}): Promise<PromptTemplate[]> {
  const p = new URLSearchParams();
  if (opts?.persona) p.set('persona', opts.persona);
  if (opts?.limit != null) p.set('limit', String(opts.limit));
  if (opts?.offset != null) p.set('offset', String(opts.offset));
  const qs = p.toString();
  return _do<PromptTemplate[]>(
    `/copilot/prompt-templates${qs ? '?' + qs : ''}`,
  );
}

export function getActive(
  persona: Persona,
): Promise<PromptTemplate> {
  return _do(`/copilot/prompt-templates/${persona}/active`);
}

export function getVersion(
  persona: Persona, version: number,
): Promise<PromptTemplate> {
  return _do(
    `/copilot/prompt-templates/${persona}/versions/${version}`,
  );
}

export function diffVersions(
  persona: Persona, from_version: number, to_version: number,
): Promise<DiffResult> {
  return _do(
    `/copilot/prompt-templates/${persona}` +
    `/diff/${from_version}/${to_version}`,
  );
}

// -- Pure helpers --------------------------------------------------

const PERSONA_LABELS: Record<Persona, string> = {
  operator: '🚁 飞控助手',
  analyst: '🔍 分析助手',
  instructor: '👨‍🏫 教练助手',
};

export function personaLabel(p: Persona): string {
  return PERSONA_LABELS[p] ?? p;
}

/**
 * Group templates by persona (map key = persona,
 * value = list sorted by version desc).
 */
export function groupByPersona(
  templates: PromptTemplate[],
): Map<Persona, PromptTemplate[]> {
  const map = new Map<Persona, PromptTemplate[]>();
  for (const t of templates) {
    const arr = map.get(t.persona) ?? [];
    arr.push(t);
    map.set(t.persona, arr);
  }
  for (const arr of map.values()) {
    arr.sort((a, b) => b.version - a.version);
  }
  return map;
}

/** Simple diff line categorization for coloring. */
export type DiffLineKind = 'add' | 'del' | 'hunk' | 'header' | 'ctx';

export function classifyDiffLine(line: string): DiffLineKind {
  if (line.startsWith('+++') || line.startsWith('---')) return 'header';
  if (line.startsWith('@@')) return 'hunk';
  if (line.startsWith('+')) return 'add';
  if (line.startsWith('-')) return 'del';
  return 'ctx';
}

/** Cheap prompt "risk" heuristic — trigger admin warning banner. */
export function assessPromptRisk(prompt: string): {
  level: 'ok' | 'warn' | 'high';
  reasons: string[];
} {
  const reasons: string[] = [];
  const banned = [
    /ignore (all|any|previous)/i,
    /disregard.+instructions/i,
    /jailbreak/i,
  ];
  for (const rx of banned) {
    if (rx.test(prompt)) reasons.push(`危险指令: ${rx.source}`);
  }
  if (prompt.length > 12000) reasons.push('prompt 过长 (>12k)');
  if (!/[\u4e00-\u9fff]/.test(prompt) && prompt.length < 50) {
    reasons.push('内容过短且无中文');
  }
  const level: 'ok' | 'warn' | 'high' =
    reasons.some((r) => r.includes('危险指令'))
      ? 'high'
      : reasons.length > 0 ? 'warn' : 'ok';
  return { level, reasons };
}
