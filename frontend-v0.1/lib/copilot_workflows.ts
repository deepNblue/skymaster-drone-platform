// Copilot Workflow REST client · v2.1 E2.1 (T10.3 + T10.4 + T10.5)
//
// Wraps the seven backend endpoints:
//   Stateless:
//     POST /api/v1/copilot/workflows/validate
//     POST /api/v1/copilot/workflows/run
//   Persistence (org-scoped):
//     POST   /api/v1/copilot/workflows
//     GET    /api/v1/copilot/workflows
//     GET    /api/v1/copilot/workflows/{id}
//     PUT    /api/v1/copilot/workflows/{id}
//     DELETE /api/v1/copilot/workflows/{id}
//     POST   /api/v1/copilot/workflows/{id}/run

const baseURL =
  process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';

function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...extra,
  };
  if (typeof window !== 'undefined') {
    const token = localStorage.getItem('access_token');
    if (token) headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

// ============================================================ types =======

/**
 * A single step's outcome inside a WorkflowRun trace.
 * Mirrors backend `RunStepResponse`.
 */
export interface WorkflowRunStep {
  id: string;
  tool: string;
  status: 'ok' | 'failed' | 'skipped' | 'pending';
  resolved_args: Record<string, unknown>;
  result: Record<string, unknown> | null;
  error: string | null;
  duration_ms: number;
}

/** A full workflow run trace. Mirrors backend `RunResponse`. */
export interface WorkflowRun {
  workflow_name: string;
  status: 'ok' | 'failed';
  duration_ms: number;
  steps: WorkflowRunStep[];
  error: string | null;
}

/** /validate response — either ok=true with metadata, or error diagnostics. */
export interface WorkflowValidation {
  ok: boolean;
  name: string | null;
  steps: string[];
  tools_used: string[];
  /** Only set when ok=false. Kind of DSL error. */
  error_type: 'syntax' | 'semantic' | 'workflow' | null;
  error: string | null;
}

/** A persisted workflow row. Mirrors backend `WorkflowRecordResponse`. */
export interface WorkflowRecord {
  id: string;
  name: string;
  description: string;
  dsl_yaml: string;
  version: number;
  owner_user_id: string | null;
  created_at: string;
  updated_at: string;
}

// ==================================================== stateless helpers ===

export async function validateWorkflow(
  workflow_yaml: string,
  allowed_input_keys?: string[],
): Promise<WorkflowValidation> {
  const resp = await fetch(`${baseURL}/api/v1/copilot/workflows/validate`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({
      workflow_yaml,
      ...(allowed_input_keys ? { allowed_input_keys } : {}),
    }),
  });
  if (!resp.ok) {
    // 4xx here means the *envelope* was wrong (auth, both-sources, etc).
    // DSL errors return 200 with ok=false and detailed diagnostics.
    throw new Error(`validate: HTTP ${resp.status} ${await resp.text()}`);
  }
  return resp.json();
}

export async function runInlineWorkflow(
  workflow_yaml: string,
  inputs: Record<string, unknown> = {},
  allowed_input_keys?: string[],
): Promise<WorkflowRun> {
  const resp = await fetch(`${baseURL}/api/v1/copilot/workflows/run`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({
      workflow_yaml,
      inputs,
      ...(allowed_input_keys ? { allowed_input_keys } : {}),
    }),
  });
  // 4xx = authoring error (bad DSL / unknown tool) — surface to caller.
  // 2xx (including status=failed inside body) = runtime issue, still parsed.
  if (!resp.ok) {
    throw new Error(`run: HTTP ${resp.status} ${await resp.text()}`);
  }
  return resp.json();
}

// ===================================================== persistence CRUD ===

export async function listWorkflows(): Promise<WorkflowRecord[]> {
  const resp = await fetch(`${baseURL}/api/v1/copilot/workflows`, {
    headers: authHeaders(),
  });
  if (!resp.ok) {
    throw new Error(`list workflows: HTTP ${resp.status}`);
  }
  return resp.json();
}

export async function getWorkflow(id: string): Promise<WorkflowRecord> {
  const resp = await fetch(`${baseURL}/api/v1/copilot/workflows/${id}`, {
    headers: authHeaders(),
  });
  if (!resp.ok) {
    throw new Error(`get workflow ${id}: HTTP ${resp.status}`);
  }
  return resp.json();
}

export async function createWorkflow(payload: {
  name: string;
  description?: string;
  dsl_yaml: string;
}): Promise<WorkflowRecord> {
  const resp = await fetch(`${baseURL}/api/v1/copilot/workflows`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    const text = await resp.text();
    // 409 = duplicate name, 400 = DSL error — surface as-is.
    throw new Error(`create: HTTP ${resp.status} ${text}`);
  }
  return resp.json();
}

export async function updateWorkflow(
  id: string,
  payload: {
    /** REQUIRED — optimistic-lock version. Must match current row. */
    version: number;
    name?: string;
    description?: string;
    dsl_yaml?: string;
  },
): Promise<WorkflowRecord> {
  const resp = await fetch(`${baseURL}/api/v1/copilot/workflows/${id}`, {
    method: 'PUT',
    headers: authHeaders(),
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    const text = await resp.text();
    // 409 = stale version, 400 = DSL error, 404 = missing/cross-org.
    throw new Error(`update: HTTP ${resp.status} ${text}`);
  }
  return resp.json();
}

export async function deleteWorkflow(id: string): Promise<void> {
  const resp = await fetch(`${baseURL}/api/v1/copilot/workflows/${id}`, {
    method: 'DELETE',
    headers: authHeaders(),
  });
  // 204 No Content on success — do NOT try to parse JSON.
  if (!resp.ok && resp.status !== 204) {
    throw new Error(`delete: HTTP ${resp.status} ${await resp.text()}`);
  }
}

// ========================================================= run history ===

/** Row in the /history list. Trace omitted for payload economy. */
export interface WorkflowRunHistoryEntry {
  id: string;
  workflow_id: string | null;
  workflow_name: string;
  status: 'ok' | 'failed';
  duration_ms: number;
  error: string | null;
  started_at: string;
}

/** /history/{id} detail — carries the full RunResponse under `trace`. */
export interface WorkflowRunHistoryDetail extends WorkflowRunHistoryEntry {
  trace: WorkflowRun | Record<string, unknown>;
}

export async function listWorkflowRunHistory(opts: {
  limit?: number;
  workflow_id?: string;
} = {}): Promise<WorkflowRunHistoryEntry[]> {
  const params = new URLSearchParams();
  if (opts.limit) params.set('limit', String(opts.limit));
  if (opts.workflow_id) params.set('workflow_id', opts.workflow_id);
  const qs = params.toString();
  const url =
    `${baseURL}/api/v1/copilot/workflows/history${qs ? '?' + qs : ''}`;
  const resp = await fetch(url, { headers: authHeaders() });
  if (!resp.ok) {
    throw new Error(`history: HTTP ${resp.status}`);
  }
  return resp.json();
}

export async function getWorkflowRunHistoryDetail(
  runId: string,
): Promise<WorkflowRunHistoryDetail> {
  const resp = await fetch(
    `${baseURL}/api/v1/copilot/workflows/history/${runId}`,
    { headers: authHeaders() },
  );
  if (!resp.ok) {
    throw new Error(`history detail: HTTP ${resp.status}`);
  }
  return resp.json();
}

export async function runStoredWorkflow(
  id: string,
  inputs: Record<string, unknown> = {},
  allowed_input_keys?: string[],
): Promise<WorkflowRun> {
  const resp = await fetch(`${baseURL}/api/v1/copilot/workflows/${id}/run`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({
      inputs,
      ...(allowed_input_keys ? { allowed_input_keys } : {}),
    }),
  });
  if (!resp.ok) {
    throw new Error(`run stored: HTTP ${resp.status} ${await resp.text()}`);
  }
  return resp.json();
}
