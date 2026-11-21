// SSE client for SkyMaster Copilot v2 (T4.0 Function Calling loop).
//
// Wraps:
//   POST /api/v1/copilot/sessions
//   POST /api/v1/copilot/v2/sessions/{sid}/messages
//   POST /api/v1/copilot/v2/approvals/{aid}/decide
//   GET  /api/v1/copilot/v2/approvals/pending
//
// Event contract (matches backend Emitter):
//   status              — { stage, ...kv }
//   text                — { text }
//   tool                — { event: 'start'|'end'|'error', name, ... }
//   approval_required   — { tool, arguments, approval_id }
//   error               — { stage, error }
//   done                — { stopped_reason, tool_calls[], pending_approvals[] }

const baseURL =
  process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';

export type CopilotV2EventType =
  | 'status'
  | 'text'
  | 'tool'
  | 'approval_required'
  | 'error'
  | 'done';

export interface CopilotV2Event {
  type: CopilotV2EventType;
  data: any;
}

function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const headers: Record<string, string> = { ...extra };
  if (typeof window !== 'undefined') {
    const token = localStorage.getItem('access_token');
    if (token) headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

export interface CreateSessionResponse {
  session_id: string;
}

export async function createSession(): Promise<CreateSessionResponse> {
  const res = await fetch(`${baseURL}/api/v1/copilot/sessions`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({}),
  });
  if (!res.ok) throw new Error(`createSession failed: ${res.status}`);
  return res.json();
}

/**
 * Send a prompt to a session using the v2 Function Calling loop.
 * Streams SSE events until the server closes the connection.
 */
export async function sendV2Message(
  sessionId: string,
  prompt: string,
  onEvent: (evt: CopilotV2Event) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(
    `${baseURL}/api/v1/copilot/v2/sessions/${sessionId}/messages`,
    {
      method: 'POST',
      headers: authHeaders({
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
      }),
      body: JSON.stringify({ prompt }),
      signal,
    },
  );
  if (!res.ok || !res.body) {
    throw new Error(`sendV2Message failed: ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let sep: number;
    while ((sep = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      const evt = parseFrame(frame);
      if (evt) onEvent(evt);
    }
  }
  if (buffer.trim().length > 0) {
    const evt = parseFrame(buffer);
    if (evt) onEvent(evt);
  }
}

function parseFrame(frame: string): CopilotV2Event | null {
  let type: string | null = null;
  const dataLines: string[] = [];
  for (const raw of frame.split('\n')) {
    const line = raw.replace(/\r$/, '');
    if (!line || line.startsWith(':')) continue;
    if (line.startsWith('event:')) {
      type = line.slice(6).trim();
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).replace(/^ /, ''));
    }
  }
  if (!type && dataLines.length === 0) return null;
  const raw = dataLines.join('\n');
  let data: any = raw;
  if (raw) {
    try {
      data = JSON.parse(raw);
    } catch {
      /* keep as string */
    }
  }
  return { type: (type || 'text') as CopilotV2EventType, data };
}

// ---------------------------------------------------------------------------
// Approval APIs (T4.1)
// ---------------------------------------------------------------------------

export type V2Decision = 'approved' | 'rejected' | 'modified';

export interface V2ApprovalDecideBody {
  decision: V2Decision;
  modifications?: Record<string, any>;
  comment?: string;
}

export interface V2ApprovalDecideResponse {
  approval_id: string;
  trace_id: string;
  decision: V2Decision;
  tool: string;
  arguments: Record<string, any>;
  result: Record<string, any>;
  is_error: boolean;
}

export async function decideV2Approval(
  approvalId: string,
  body: V2ApprovalDecideBody,
): Promise<V2ApprovalDecideResponse> {
  const res = await fetch(
    `${baseURL}/api/v1/copilot/v2/approvals/${approvalId}/decide`,
    {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body),
    },
  );
  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new Error(`decideV2Approval failed: ${res.status} ${detail}`);
  }
  return res.json();
}

export interface V2PendingApproval {
  approval_id: string;
  trace_id: string;
  session_id: string | null;
  org_id: string | null;
  tool: string | null;
  arguments: Record<string, any> | null;
  prompt: string | null;
  created_at: string | null;
}

export async function listV2PendingApprovals(
  limit = 50,
): Promise<V2PendingApproval[]> {
  const res = await fetch(
    `${baseURL}/api/v1/copilot/v2/approvals/pending?limit=${limit}`,
    { headers: authHeaders() },
  );
  if (!res.ok) throw new Error(`listV2PendingApprovals failed: ${res.status}`);
  return res.json();
}
