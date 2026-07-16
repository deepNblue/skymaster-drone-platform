/**
 * T11.3 · Community playbook API client.
 *
 * Backend endpoints (see backend-v0.1/app/api/v1/community_playbooks.py):
 *
 *   POST   /community-playbooks              submit (201 pending)
 *   GET    /community-playbooks              list (approved + own if flag)
 *   GET    /community-playbooks/{slug}       fetch one
 *   DELETE /community-playbooks/{slug}       soft delete (author|admin)
 *   POST   /community-playbooks/{slug}/moderate  admin only
 *   POST   /community-playbooks/{slug}/install   fork into caller's org
 */
const baseURL =
  process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8080';

function authHeaders(): HeadersInit {
  if (typeof window === 'undefined') return {};
  const t = window.localStorage.getItem('access_token');
  return t ? { Authorization: `Bearer ${t}` } : {};
}

export interface CommunityPlaybook {
  slug: string;
  name: string;
  description: string;
  dsl_yaml: string;
  sample_inputs: Record<string, unknown>;
  tags: string[];
  status: 'pending' | 'approved' | 'rejected';
  rejected_reason: string | null;
  install_count: number;
  author_user_id: string;
  org_id: string;
  created_at: string;
  updated_at: string;
}

export interface SubmitPlaybookPayload {
  slug: string;
  name: string;
  description?: string;
  dsl_yaml: string;
  sample_inputs?: Record<string, unknown>;
  tags?: string[];
}

export interface InstallResult {
  workflow_id: string;
  workflow_name: string;
}

export async function submitCommunityPlaybook(
  payload: SubmitPlaybookPayload,
): Promise<CommunityPlaybook> {
  const resp = await fetch(`${baseURL}/api/v1/community-playbooks`, {
    method: 'POST',
    headers: { ...authHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify({
      slug: payload.slug,
      name: payload.name,
      description: payload.description ?? '',
      dsl_yaml: payload.dsl_yaml,
      sample_inputs: payload.sample_inputs ?? {},
      tags: payload.tags ?? [],
    }),
  });
  if (!resp.ok) {
    const detail = await resp.text();
    throw new Error(`submit: HTTP ${resp.status} — ${detail}`);
  }
  return resp.json();
}

export async function listCommunityPlaybooks(opts: {
  status?: 'pending' | 'approved' | 'rejected';
  include_own?: boolean;
  limit?: number;
} = {}): Promise<CommunityPlaybook[]> {
  const params = new URLSearchParams();
  if (opts.status) params.set('status', opts.status);
  if (opts.include_own) params.set('include_own', 'true');
  if (opts.limit != null) params.set('limit', String(opts.limit));
  const qs = params.toString();
  const url = `${baseURL}/api/v1/community-playbooks${qs ? '?' + qs : ''}`;
  const resp = await fetch(url, { headers: authHeaders() });
  if (!resp.ok) {
    throw new Error(`list: HTTP ${resp.status}`);
  }
  return resp.json();
}

export async function getCommunityPlaybook(
  slug: string,
): Promise<CommunityPlaybook> {
  const resp = await fetch(
    `${baseURL}/api/v1/community-playbooks/${encodeURIComponent(slug)}`,
    { headers: authHeaders() },
  );
  if (!resp.ok) {
    throw new Error(`get: HTTP ${resp.status}`);
  }
  return resp.json();
}

export async function deleteCommunityPlaybook(slug: string): Promise<void> {
  const resp = await fetch(
    `${baseURL}/api/v1/community-playbooks/${encodeURIComponent(slug)}`,
    { method: 'DELETE', headers: authHeaders() },
  );
  if (!resp.ok && resp.status !== 204) {
    const detail = await resp.text();
    throw new Error(`delete: HTTP ${resp.status} — ${detail}`);
  }
}

export async function moderateCommunityPlaybook(
  slug: string,
  approve: boolean,
  reason?: string,
): Promise<CommunityPlaybook> {
  const resp = await fetch(
    `${baseURL}/api/v1/community-playbooks/${encodeURIComponent(slug)}/moderate`,
    {
      method: 'POST',
      headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ approve, reason: reason ?? null }),
    },
  );
  if (!resp.ok) {
    const detail = await resp.text();
    throw new Error(`moderate: HTTP ${resp.status} — ${detail}`);
  }
  return resp.json();
}

export async function installCommunityPlaybook(
  slug: string,
): Promise<InstallResult> {
  const resp = await fetch(
    `${baseURL}/api/v1/community-playbooks/${encodeURIComponent(slug)}/install`,
    { method: 'POST', headers: authHeaders() },
  );
  if (!resp.ok) {
    const detail = await resp.text();
    throw new Error(`install: HTTP ${resp.status} — ${detail}`);
  }
  return resp.json();
}
