// SSE client for SkyMaster Copilot backend.
// Wraps POST /api/v1/copilot/sessions and the streamed messages endpoint.

const baseURL =
  process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';

export type CopilotEventType =
  | 'intent'
  | 'step'
  | 'token'
  | 'approval_required'
  | 'done'
  | 'error';

export interface CopilotEvent {
  type: CopilotEventType;
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
 * Send a prompt to an existing session and stream SSE events.
 * Aborts when `signal` fires. Rejects on network / non-2xx.
 */
export async function sendMessage(
  sessionId: string,
  prompt: string,
  onEvent: (evt: CopilotEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(
    `${baseURL}/api/v1/copilot/sessions/${sessionId}/messages`,
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
    throw new Error(`sendMessage failed: ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  // SSE frames are separated by "\n\n"; each frame has "event: X\ndata: Y" lines.
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let sep;
    while ((sep = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      const evt = parseFrame(frame);
      if (evt) onEvent(evt);
    }
  }

  // Flush any trailing frame (server may omit final blank line).
  if (buffer.trim().length > 0) {
    const evt = parseFrame(buffer);
    if (evt) onEvent(evt);
  }
}

function parseFrame(frame: string): CopilotEvent | null {
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
      // keep as string (token events may be plain text)
    }
  }
  return { type: (type || 'token') as CopilotEventType, data };
}

export interface ApproveResponse {
  status: string;
  [k: string]: any;
}

export async function approveTrace(
  traceId: string,
  decision: 'approve' | 'reject',
  comment?: string,
): Promise<ApproveResponse> {
  const res = await fetch(
    `${baseURL}/api/v1/copilot/traces/${traceId}/approve`,
    {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ decision, comment: comment ?? '' }),
    },
  );
  if (!res.ok) throw new Error(`approveTrace failed: ${res.status}`);
  return res.json();
}

export async function getTrace(traceId: string): Promise<any> {
  const res = await fetch(`${baseURL}/api/v1/copilot/traces/${traceId}`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`getTrace failed: ${res.status}`);
  return res.json();
}
