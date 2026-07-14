import axios, { AxiosInstance, AxiosRequestConfig } from 'axios';

const baseURL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';
export const apiBaseURL = baseURL;

export const api: AxiosInstance = axios.create({
  baseURL,
  timeout: 15000,
});

// ---- LocalStorage helpers -------------------------------------------------
const _get = (k: string): string | null =>
  typeof window !== 'undefined' ? localStorage.getItem(k) : null;
const _set = (k: string, v: string | null) => {
  if (typeof window === 'undefined') return;
  if (v == null) localStorage.removeItem(k);
  else localStorage.setItem(k, v);
};

// ---- Request auth header --------------------------------------------------
api.interceptors.request.use((config) => {
  const token = _get('access_token');
  if (token) {
    config.headers = config.headers || {};
    (config.headers as any).Authorization = `Bearer ${token}`;
  }
  return config;
});

// ---- 401 → refresh once, else redirect ------------------------------------
let _refreshInflight: Promise<string | null> | null = null;

async function _tryRefresh(): Promise<string | null> {
  if (_refreshInflight) return _refreshInflight;
  const refresh = _get('refresh_token');
  if (!refresh) return null;
  _refreshInflight = (async () => {
    try {
      const resp = await axios.post(
        `${baseURL}/api/v1/auth/refresh`,
        { refresh_token: refresh },
        { timeout: 8000 },
      );
      const { access_token, refresh_token: newRefresh } = resp.data;
      _set('access_token', access_token);
      if (newRefresh) _set('refresh_token', newRefresh);
      return access_token;
    } catch {
      _set('access_token', null);
      _set('refresh_token', null);
      return null;
    } finally {
      _refreshInflight = null;
    }
  })();
  return _refreshInflight;
}

api.interceptors.response.use(
  (res) => res,
  async (err) => {
    const original = err?.config as AxiosRequestConfig & { _retried?: boolean };
    // Don't retry /auth/refresh itself, avoid infinite loop
    const isRefreshCall = original?.url?.includes('/auth/refresh');
    if (
      err?.response?.status === 401 &&
      typeof window !== 'undefined' &&
      original &&
      !original._retried &&
      !isRefreshCall
    ) {
      original._retried = true;
      const newToken = await _tryRefresh();
      if (newToken) {
        original.headers = original.headers || {};
        (original.headers as any).Authorization = `Bearer ${newToken}`;
        return api.request(original);
      }
      // Fallthrough to redirect
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login';
      }
    }
    return Promise.reject(err);
  },
);

export async function logout() {
  const refresh =
    typeof window !== 'undefined' ? localStorage.getItem('refresh_token') : null;
  if (refresh) {
    try {
      await api.post('/api/v1/auth/logout', { refresh_token: refresh });
    } catch {
      // best-effort — server may already be down or token invalid
    }
  }
  _set('access_token', null);
  _set('refresh_token', null);
}

export async function login(email: string, password: string, totpCode?: string) {
  const { data } = await api.post('/api/v1/auth/login', {
    email,
    password,
    totp_code: totpCode,
  });
  // Persist refresh token for future auto-refresh
  if (typeof window !== 'undefined' && data?.refresh_token) {
    _set('refresh_token', data.refresh_token);
  }
  return data;
}

// ---- Vision AI + Copilot (v2.0 R20 Track B) -----------------------------
export interface VisionDetectionOut {
  id: string;
  label: string;
  confidence: number;
  bbox: number[] | null;
  lat: number | null;
  lng: number | null;
  alt_m: number | null;
  drone_id: string | null;
  mission_id: string | null;
  stream_key: string | null;
  model_tag: string | null;
  runtime: string | null;
  status: string;
  frame_idx: number | null;
  frame_ts: string | null;
  created_at: string;
}

export async function getVisionRuntimes() {
  const { data } = await api.get('/api/v1/vision/runtimes');
  return data as { available: string[]; active: string; persist_threshold: number };
}
export async function visionInfer(body: {
  image_b64?: string; hint?: string; frame_idx?: number;
  drone_id?: string; mission_id?: string; stream_key?: string;
  lat?: number; lng?: number; alt_m?: number; persist?: boolean;
}) {
  const { data } = await api.post('/api/v1/vision/infer', body);
  return data as {
    runtime: string; model_tag: string; latency_ms: number;
    detections: any[]; persisted: string[];
  };
}
export async function listDetections(params: {
  label?: string; drone_id?: string; mission_id?: string;
  status?: string; since_minutes?: number; limit?: number;
} = {}) {
  const { data } = await api.get('/api/v1/vision/detections', { params });
  return data as VisionDetectionOut[];
}
export async function ackDetection(id: string, status: string) {
  const { data } = await api.post(
    `/api/v1/vision/detections/${id}/ack`, null,
    { params: { status } },
  );
  return data as VisionDetectionOut;
}

export interface CopilotSession {
  id: string; title: string; persona: string; created_at: string;
}
export interface CopilotTurn {
  id: string; turn_idx: number; user_text: string;
  intent: string | null; args: any; reply_text: string | null;
  tool_call: any; tool_result: any; status: string;
  latency_ms: number | null; created_at: string;
}
export async function copilotDryRun(text: string, drone_id?: string) {
  const { data } = await api.post('/api/v1/copilot/dry-run', { text, drone_id });
  return data as {
    intent: string; args: any; confidence: number;
    reply: string; tool_call: any;
  };
}
export async function createCopilotSession(body: {
  title?: string; persona?: string; system_prompt?: string;
}) {
  const { data } = await api.post('/api/v1/copilot/sessions', body);
  return data as CopilotSession;
}
export async function listCopilotSessions() {
  const { data } = await api.get('/api/v1/copilot/sessions');
  return data as CopilotSession[];
}
export async function listCopilotTurns(sid: string) {
  const { data } = await api.get(`/api/v1/copilot/sessions/${sid}/turns`);
  return data as CopilotTurn[];
}
export async function createCopilotTurn(
  sid: string, body: { text: string; drone_id?: string; execute?: boolean },
) {
  const { data } = await api.post(`/api/v1/copilot/sessions/${sid}/turns`, body);
  return data as CopilotTurn;
}

// ---- Three-Officer SoD (v2.0 R19) ---------------------------------------
export interface OfficerUser {
  id: string;
  email: string;
  role: string;
  officer_role: string | null;
  is_active: boolean;
}

export async function listOfficers() {
  const { data } = await api.get('/api/v1/admin/officers');
  return data as OfficerUser[];
}
export async function grantOfficer(user_id: string, officer_role: string) {
  const { data } = await api.post('/api/v1/admin/officers/grant', {
    user_id, officer_role,
  });
  return data as OfficerUser;
}
export async function revokeOfficer(user_id: string) {
  const { data } = await api.post('/api/v1/admin/officers/revoke', { user_id });
  return data as OfficerUser;
}
export async function getOfficerMatrix() {
  const { data } = await api.get('/api/v1/admin/officers/matrix');
  return data as { officers: string[]; matrix: Record<string, string[]> };
}

// ---- SM2 Signature (v2.0 R20 · 抗抵赖) ----------------------------------
export interface Sm2Status {
  enabled: boolean;
  active_key_id: string | null;
  known_key_ids: string[];
}
export interface Sm2VerifyIn {
  record_id: string;
  curr_hash: string;
  ts: string;
  signature_hex: string;
  key_id: string;
}
export interface Sm2VerifyOut {
  ok: boolean;
  key_id: string;
  known_key: boolean;
}
export interface Sm2PublicKey {
  key_id: string;
  public_hex: string;
  curve: string;
}
export interface Sm2AuditSig {
  id: number;
  action: string;
  resource: string | null;
  curr_hash: string | null;
  sig_hex: string | null;
  sig_key_id: string | null;
  ts: string | null;
}

// R21 · Rotation + HSM ------------------------------------------------------
export interface Sm2KeyInfo {
  key_id: string;
  has_private: boolean;
  active: boolean;
  created_at: number | null;
  age_days: number | null;
  lifetime_days: number;
  rotation_due: boolean;
}
export interface Sm2Rotation {
  active_key_id: string | null;
  any_rotation_due: boolean;
  keys: Sm2KeyInfo[];
}
export interface HsmBackend {
  name: string;
  priority: number;
  available: boolean;
}
export interface HsmStatus {
  backends: HsmBackend[];
  active_backend: string;
}

export async function sm2Rotation() {
  const { data } = await api.get('/api/v1/crypto/sm2/rotation');
  return data as Sm2Rotation;
}
export async function sm2Hsm() {
  const { data } = await api.get('/api/v1/crypto/sm2/hsm');
  return data as HsmStatus;
}

// R22 · Audit export -------------------------------------------------------
export interface AuditRow {
  id: number;
  ts: string | null;
  actor_id: string | null;
  actor_role: string | null;
  action: string;
  resource: string | null;
  diff: unknown;
  ip: string | null;
  ua: string | null;
  prev_hash: string | null;
  curr_hash: string | null;
  sig_hex: string | null;
  sig_key_id: string | null;
}
export interface AuditPreview {
  total: number;
  sample: AuditRow[];
}
export interface AuditIntegrity {
  total: number;
  hash_chain_ok: boolean;
  hash_chain_break_at: number | null;
  signed_count: number;
  unsigned_count: number;
}
export interface AuditExportFilter {
  ts_from?: string;
  ts_to?: string;
  actor_role?: string;
  action?: string;
  actor_id?: string;
  limit?: number;
}

function _qs(f: AuditExportFilter): string {
  const p = new URLSearchParams();
  Object.entries(f).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') p.set(k, String(v));
  });
  const s = p.toString();
  return s ? `?${s}` : '';
}

export async function auditPreview(f: AuditExportFilter = {}) {
  const { data } = await api.get(`/api/v1/audit/export/preview${_qs(f)}`);
  return data as AuditPreview;
}
export async function auditIntegrity(f: AuditExportFilter = {}) {
  const { data } = await api.get(`/api/v1/audit/integrity${_qs(f)}`);
  return data as AuditIntegrity;
}
export function auditExportUrl(fmt: 'csv' | 'gbft', f: AuditExportFilter = {}): string {
  // Returns a full URL for <a href="..."> download. Cookie auth is
  // already set via api.defaults.withCredentials.
  const base = api.defaults.baseURL ?? '';
  return `${base}/api/v1/audit/export/${fmt}${_qs(f)}`;
}

// R23 · CIIO 自评 ---------------------------------------------------------
export type CiioStatus = 'pass' | 'fail' | 'partial' | 'unknown' | 'na';

export interface CiioCheck {
  code: string;
  category: string;
  title: string;
  obligation_zh: string;
  status: CiioStatus;
  evidence: string;
  references: string[];
}

export interface CiioReport {
  generated_at: string;
  total: number;
  counts: Record<CiioStatus, number>;
  coverage_pct: number;
  checks: CiioCheck[];
}

export async function ciioStatus() {
  const { data } = await api.get('/api/v1/ciio/status');
  return data as CiioReport;
}

export function ciioReportMdUrl(): string {
  const base = api.defaults.baseURL ?? '';
  return `${base}/api/v1/ciio/report.md`;
}

// R24 / v2.1 T1 · 3DGS Reality Studio -------------------------------------
export type SceneStatus =
  | 'draft' | 'ingesting' | 'ingested'
  | 'colmap' | 'colmap_done'
  | 'training' | 'ready'
  | 'failed' | 'archived';

export interface SceneAsset {
  id: string;
  kind: string;
  filename: string;
  size_bytes: number | null;
  sha256_hex: string | null;
}

export interface Scene {
  id: string;
  name: string;
  description: string | null;
  status: SceneStatus;
  error_msg: string | null;
  coord_system: string | null;
  n_source_images: number;
  n_points: number | null;
  n_gaussians: number | null;
  psnr_train: number | null;
  mission_id: string | null;
  assets: SceneAsset[];
}

export interface ScenesList {
  total: number;
  scenes: Scene[];
}

export interface SceneCreate {
  name: string;
  description?: string;
  coord_system?: string;
  mission_id?: string;
}

export async function listScenes(status?: SceneStatus) {
  const qs = status ? `?status=${status}` : '';
  const { data } = await api.get(`/api/v1/scenes${qs}`);
  return data as ScenesList;
}

export async function getScene(id: string) {
  const { data } = await api.get(`/api/v1/scenes/${id}`);
  return data as Scene;
}

export async function createScene(body: SceneCreate) {
  const { data } = await api.post('/api/v1/scenes', body);
  return data as Scene;
}

export async function sceneAction(
  id: string,
  action: 'ingest' | 'colmap' | 'train' | 'reset' | 'archive',
) {
  const { data } = await api.post(`/api/v1/scenes/${id}/${action}`);
  return data as Scene;
}

// v2.1 T1.1 · Scene chunked upload ----------------------------------------
export interface UploadRef {
  upload_id: string;
  filename: string;
  kind: string;
  sha256_hex: string;
  size_bytes: number;
  total_chunks: number;
  received_chunks: number[];
}

export interface UploadComplete {
  asset_id: string;
  sha256_hex: string;
  size_bytes: number;
  filename: string;
  dedup: boolean;
}

const CHUNK_SIZE = 4 * 1024 * 1024; // 4 MiB per chunk

/** Compute SHA-256 of a File as lowercase hex via Web Crypto. */
export async function sha256File(file: File): Promise<string> {
  const buf = await file.arrayBuffer();
  const hash = await crypto.subtle.digest('SHA-256', buf);
  return Array.from(new Uint8Array(hash))
    .map(b => b.toString(16).padStart(2, '0'))
    .join('');
}

export async function uploadStart(
  sceneId: string,
  body: {
    filename: string;
    kind: string;
    sha256_hex: string;
    size_bytes: number;
    total_chunks: number;
  },
): Promise<UploadRef> {
  const { data } = await api.post(`/api/v1/scenes/${sceneId}/uploads`, body);
  return data as UploadRef;
}

export async function uploadStatus(sceneId: string, uploadId: string): Promise<UploadRef> {
  const { data } = await api.get(`/api/v1/scenes/${sceneId}/uploads/${uploadId}`);
  return data as UploadRef;
}

export async function uploadChunk(
  sceneId: string,
  uploadId: string,
  chunkIdx: number,
  chunk: Blob,
): Promise<void> {
  await api.put(
    `/api/v1/scenes/${sceneId}/uploads/${uploadId}/chunks/${chunkIdx}`,
    chunk,
    { headers: { 'Content-Type': 'application/octet-stream' } },
  );
}

export async function uploadComplete(sceneId: string, uploadId: string): Promise<UploadComplete> {
  const { data } = await api.post(`/api/v1/scenes/${sceneId}/uploads/${uploadId}/complete`);
  return data as UploadComplete;
}

export async function uploadAbort(sceneId: string, uploadId: string): Promise<void> {
  await api.delete(`/api/v1/scenes/${sceneId}/uploads/${uploadId}`);
}

// v2.1 T1.3 · Scene artifacts (trained .ply/.splat download) --------------
export interface Artifact {
  id: string;
  kind: string;
  filename: string;
  size_bytes: number | null;
  sha256_hex: string | null;
  download_url: string;
}

export interface ArtifactList {
  scene_id: string;
  total: number;
  artifacts: Artifact[];
}

export interface ArtifactManifest {
  scene_id: string;
  scene_name: string;
  status: SceneStatus;
  n_gaussians: number | null;
  psnr_train: number | null;
  generated_at: string | null;
  artifacts: Artifact[];
}

export async function listArtifacts(sceneId: string): Promise<ArtifactList> {
  const { data } = await api.get(`/api/v1/scenes/${sceneId}/artifacts`);
  return data as ArtifactList;
}

export async function artifactManifest(sceneId: string): Promise<ArtifactManifest> {
  const { data } = await api.get(`/api/v1/scenes/${sceneId}/artifacts/manifest.json`);
  return data as ArtifactManifest;
}

export function artifactDownloadUrl(sceneId: string, assetId: string): string {
  const base = api.defaults.baseURL ?? '';
  return `${base}/api/v1/scenes/${sceneId}/assets/${assetId}/download`;
}

/**
 * High-level uploader: computes SHA-256, starts upload, streams chunks
 * (skipping any already-received chunks for resumability), completes.
 *
 * onProgress reports 0..1.
 */
export async function uploadFile(
  sceneId: string,
  file: File,
  kind: string = 'source_image',
  onProgress?: (pct: number) => void,
): Promise<UploadComplete> {
  const sha = await sha256File(file);
  const totalChunks = Math.max(1, Math.ceil(file.size / CHUNK_SIZE));
  const ref = await uploadStart(sceneId, {
    filename: file.name,
    kind,
    sha256_hex: sha,
    size_bytes: file.size,
    total_chunks: totalChunks,
  });

  const done = new Set<number>(ref.received_chunks);
  for (let i = 0; i < totalChunks; i++) {
    if (done.has(i)) continue;
    const start = i * CHUNK_SIZE;
    const end = Math.min(start + CHUNK_SIZE, file.size);
    await uploadChunk(sceneId, ref.upload_id, i, file.slice(start, end));
    done.add(i);
    if (onProgress) onProgress(done.size / totalChunks);
  }
  const result = await uploadComplete(sceneId, ref.upload_id);
  if (onProgress) onProgress(1);
  return result;
}

export async function sm2Status() {
  const { data } = await api.get('/api/v1/crypto/sm2/status');
  return data as Sm2Status;
}
export async function sm2PublicKey(key_id: string) {
  const { data } = await api.get(`/api/v1/crypto/sm2/public/${encodeURIComponent(key_id)}`);
  return data as Sm2PublicKey;
}
export async function sm2Verify(body: Sm2VerifyIn) {
  const { data } = await api.post('/api/v1/crypto/sm2/verify', body);
  return data as Sm2VerifyOut;
}
export async function sm2GenerateKeypair() {
  const { data } = await api.post('/api/v1/crypto/sm2/generate-keypair', {});
  return data as { private_hex: string; public_hex: string; curve: string };
}
export async function sm2AuditSig(audit_id: number) {
  const { data } = await api.get(`/api/v1/crypto/sm2/audit/${audit_id}`);
  return data as Sm2AuditSig;
}
export async function dualSign(action: string, cosigner_id: string) {
  const { data } = await api.post('/api/v1/admin/officers/dual-sign', {
    action, cosigner_id,
  });
  return data;
}

// ---- Compliance (v2.0 R18 国密) -----------------------------------------
export interface ComplianceStatus {
  enabled: boolean;
  mode: 'off' | 'hash' | 'full';
  modules: string[];
  algo: { hash: string | null; cipher: string | null };
}

export async function getComplianceStatus() {
  const { data } = await api.get('/api/v1/admin/compliance/status');
  return data as ComplianceStatus;
}

export async function toggleCompliance(
  body: { enabled?: boolean; mode?: 'off' | 'hash' | 'full'; modules?: string[] },
) {
  const { data } = await api.post('/api/v1/admin/compliance/toggle', body);
  return data as { ok: boolean; before: ComplianceStatus; after: ComplianceStatus };
}

export async function verifyAuditChain(limit = 500) {
  const { data } = await api.post(
    `/api/v1/admin/compliance/verify-audit-chain?limit=${limit}`,
  );
  return data as { checked: number; ok: boolean; broken_at: any };
}

// ---- Flight Approvals (v2.0 Track A R17) ---------------------------------
export interface Authority {
  code: string;
  name: string;
  channel: string;
  priority: number;
  scope?: string;
  reason?: string;
}

export interface ApprovalAuthorityRow {
  id: string;
  authority_code: string;
  authority_name: string;
  channel: string;
  status: string;
  external_ref?: string;
  submitted_at?: string;
  responded_at?: string;
  reject_reason?: string;
  priority: number;
  /** T7.5 — free-form JSON dict populated by RPA bridge etc.
   *  Known keys: rpa_job_id, driver. */
  extra?: Record<string, unknown> | null;
}

export interface FlightApproval {
  id: string;
  title: string;
  purpose?: string;
  category: string;
  status: string;
  pilot_name?: string;
  pilot_license?: string;
  aircraft_reg?: string;
  aircraft_model?: string;
  insurance_no?: string;
  area_polygon?: number[][];
  max_alt_m?: number;
  min_alt_m?: number;
  start_ts?: string;
  end_ts?: string;
  reject_reason?: string;
  timeline?: any[];
  created_at: string;
  updated_at: string;
  authorities: ApprovalAuthorityRow[];
  requires_second_approval?: boolean;
  second_approver_id?: string | null;
  second_approved_at?: string | null;
}

export async function listAuthorityCatalog() {
  const { data } = await api.get('/api/v1/approvals/authorities/catalog');
  return data.authorities as Authority[];
}

export async function listApprovals(status?: string) {
  const { data } = await api.get('/api/v1/approvals', {
    params: status ? { status } : {},
  });
  return data as FlightApproval[];
}

export async function getApproval(id: string) {
  const { data } = await api.get(`/api/v1/approvals/${id}`);
  return data as FlightApproval;
}

export async function createApproval(body: Partial<FlightApproval> & { title: string }) {
  const { data } = await api.post('/api/v1/approvals', body);
  return data as FlightApproval;
}

export async function updateApproval(id: string, body: Partial<FlightApproval>) {
  const { data } = await api.patch(`/api/v1/approvals/${id}`, body);
  return data as FlightApproval;
}

export async function previewRouting(id: string, weight?: number) {
  const { data } = await api.post(
    `/api/v1/approvals/${id}/route`,
    null,
    { params: weight != null ? { aircraft_weight_kg: weight } : {} },
  );
  return data.authorities as Authority[];
}

export async function submitApproval(id: string, weight?: number) {
  const { data } = await api.post(
    `/api/v1/approvals/${id}/submit`,
    null,
    { params: weight != null ? { aircraft_weight_kg: weight } : {} },
  );
  return data as FlightApproval;
}

export async function decideAuthority(
  id: string, code: string, decision: string, externalRef?: string, reason?: string,
) {
  const { data } = await api.post(
    `/api/v1/approvals/${id}/authorities/${code}/decide`,
    { decision, external_ref: externalRef, reason },
  );
  return data as FlightApproval;
}

export async function cancelApproval(id: string) {
  const { data } = await api.post(`/api/v1/approvals/${id}/cancel`);
  return data as FlightApproval;
}

export async function markApprovalFlown(id: string) {
  const { data } = await api.post(`/api/v1/approvals/${id}/mark-flown`);
  return data as FlightApproval;
}

// T7.0 v2.0 enhancements ----------------------------------------------------
export interface ApprovalSignature {
  id: string;
  approval_id: string;
  authority_code?: string | null;
  signer_user_id: string;
  signer_role?: string | null;
  payload_sha256: string;
  algorithm: string;
  note?: string | null;
  signed_at: string;
}

export interface BatchSubmitResult {
  approval_id: string;
  ok: boolean;
  status?: string;
  error?: string;
}

export interface BatchSubmitResponse {
  submitted: number;
  held_for_second_approval: number;
  failed: number;
  results: BatchSubmitResult[];
}

export async function secondApproveApproval(
  id: string,
  decision: 'approve' | 'reject',
  note?: string,
  weight?: number,
) {
  const { data } = await api.post(
    `/api/v1/approvals/${id}/second-approval`,
    { decision, note },
    { params: weight != null ? { aircraft_weight_kg: weight } : {} },
  );
  return data as FlightApproval;
}

export async function batchSubmitApprovals(
  approvalIds: string[],
  weight?: number,
) {
  const { data } = await api.post(
    '/api/v1/approvals/batch-submit',
    { approval_ids: approvalIds, aircraft_weight_kg: weight },
  );
  return data as {
    submitted: number;
    held_for_second_approval: number;
    failed: number;
    results: { approval_id: string; ok: boolean; status?: string; error?: string }[];
  };
}

/** T7.13 — batch second-approval decision. */
export async function batchSecondApproveApprovals(
  approvalIds: string[],
  decision: 'approve' | 'reject',
  note?: string,
  weight?: number,
) {
  const { data } = await api.post(
    '/api/v1/approvals/batch-second-approval',
    {
      approval_ids: approvalIds,
      decision,
      note,
      aircraft_weight_kg: weight,
    },
  );
  return data as {
    approved: number;
    rejected: number;
    failed: number;
    results: { approval_id: string; ok: boolean; status?: string; error?: string }[];
  };
}

export async function attachSignature(
  id: string,
  payloadSha256: string,
  opts: { authorityCode?: string; note?: string; algorithm?: string } = {},
) {
  const { data } = await api.post(
    `/api/v1/approvals/${id}/signatures`,
    {
      payload_sha256: payloadSha256,
      authority_code: opts.authorityCode,
      algorithm: opts.algorithm ?? 'sha256',
      note: opts.note,
    },
  );
  return data as ApprovalSignature;
}

export async function listSignatures(id: string) {
  const { data } = await api.get(`/api/v1/approvals/${id}/signatures`);
  return data as ApprovalSignature[];
}

/** T7.5 — RPA bridge integration. */
export interface RPAJobOut {
  job_id: string;
  approval_id: string;
  authority_code: string;
  driver: string;
  status: string;               // queued|submitted|approving|approved|rejected|cancelled|error
  external_ref: string | null;
  reject_reason: string | null;
  poll_count: number;
  created_at: number;
  updated_at: number;
}

/** POST /approvals/{id}/rpa-dispatch — idempotent per (approval, authority). */
export async function dispatchRpa(
  approvalId: string,
  authorityCode: string,
): Promise<RPAJobOut> {
  const { data } = await api.post(
    `/api/v1/approvals/${approvalId}/rpa-dispatch`,
    { authority_code: authorityCode },
  );
  return data as RPAJobOut;
}

/** GET /approvals/rpa-jobs/{jobId} — polls the bridge; may advance status. */
export async function pollRpaJob(jobId: string): Promise<RPAJobOut> {
  const { data } = await api.get(`/api/v1/approvals/rpa-jobs/${jobId}`);
  return data as RPAJobOut;
}

/** T7.3 — Absolute URL for the approval certificate PDF endpoint. */
export function approvalCertificatePdfUrl(id: string): string {
  return `${baseURL}/api/v1/approvals/${id}/certificate.pdf`;
}

/** T7.7 — Absolute URL for the UOM reports CSV export. */
export function uomReportsCsvUrl(opts?: {
  operator_id?: string;
  status?: string;
}): string {
  const qs = new URLSearchParams();
  if (opts?.operator_id) qs.set('operator_id', opts.operator_id);
  if (opts?.status) qs.set('status', opts.status);
  const q = qs.toString();
  return `${baseURL}/api/v1/uom/reports.csv${q ? '?' + q : ''}`;
}

/** T7.9 — Absolute URL for the flat approvals CSV export. */
export function approvalsBatchCsvUrl(opts?: {
  status?: string;
  limit?: number;
  created_from?: string;
  created_to?: string;
}): string {
  const qs = new URLSearchParams();
  if (opts?.status) qs.set('status', opts.status);
  if (opts?.limit) qs.set('limit', String(opts.limit));
  if (opts?.created_from) qs.set('created_from', opts.created_from);
  if (opts?.created_to) qs.set('created_to', opts.created_to);
  const q = qs.toString();
  return `${baseURL}/api/v1/approvals/export.csv${q ? '?' + q : ''}`;
}

/** T7.9 — Absolute URL for the approval certificates ZIP export. */
export function approvalsCertificatesZipUrl(opts?: {
  status?: string;
  limit?: number;
  created_from?: string;
  created_to?: string;
}): string {
  const qs = new URLSearchParams();
  if (opts?.status) qs.set('status', opts.status);
  if (opts?.limit) qs.set('limit', String(opts.limit));
  if (opts?.created_from) qs.set('created_from', opts.created_from);
  if (opts?.created_to) qs.set('created_to', opts.created_to);
  const q = qs.toString();
  return `${baseURL}/api/v1/approvals/export/certificates.zip${q ? '?' + q : ''}`;
}

/** T7.4 — Public verify snapshot (what the QR on the PDF points to). */
export async function verifyApproval(id: string) {
  const { data } = await api.get(`/api/v1/approvals/${id}/verify`);
  return data as {
    approval_id: string;
    status: string;
    aircraft_reg: string | null;
    start_ts: string | null;
    end_ts: string | null;
    authorities: {
      code: string;
      channel: string;
      status: string;
      external_ref: string | null;
    }[];
    signatures: {
      signer_role: string | null;
      payload_sha256: string;
      algorithm: string;
      signed_at: string | null;
    }[];
  };
}

/** Compute SHA-256 of a UTF-8 string in the browser via SubtleCrypto. */
export async function sha256Hex(text: string): Promise<string> {
  const enc = new TextEncoder().encode(text);
  const buf = await crypto.subtle.digest('SHA-256', enc);
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

export interface PreflightItem {
  key: string; name: string; severity: 'pass' | 'warn' | 'fail'; detail: string;
}
export interface PreflightResult {
  ok: boolean; blocking: boolean; fail_count: number; warn_count: number;
  items: PreflightItem[];
}
export async function preflightCheck(
  id: string, remoteIdBroadcast?: boolean, intendedMaxAltM?: number,
) {
  const { data } = await api.post(
    `/api/v1/approvals/${id}/preflight-check`,
    {
      remote_id_broadcast: remoteIdBroadcast,
      intended_max_alt_m: intendedMaxAltM,
    },
  );
  return data as PreflightResult;
}

// ---- Session management ---------------------------------------------------
export async function listMySessions() {
  const { data } = await api.get('/api/v1/auth/sessions');
  return data as Array<{
    id: string;
    jti: string;
    ip?: string;
    country?: string;
    user_agent?: string;
    device_label?: string;
    created_at: string;
    last_seen_at: string;
    is_current: boolean;
  }>;
}

export async function revokeSession(sessionId: string) {
  const { data } = await api.delete(`/api/v1/auth/sessions/${sessionId}`);
  return data;
}

export async function revokeOtherSessions() {
  const { data } = await api.post('/api/v1/auth/sessions/revoke-others');
  return data;
}

export async function changePasswordV2(current: string, next: string) {
  const { data } = await api.post('/api/v1/auth/change-password', {
    current_password: current,
    new_password: next,
  });
  return data;
}

// ---- Login history / auth events -----------------------------------------
export async function getMyLoginHistory(limit = 20) {
  const { data } = await api.get('/api/v1/auth/login-events/me', {
    params: { limit },
  });
  return data as Array<{
    id: string;
    method: string;
    outcome: string;
    ip?: string;
    country?: string;
    user_agent?: string;
    created_at: string;
  }>;
}

export async function getLoginStats(sinceHours = 24) {
  const { data } = await api.get('/api/v1/auth/login-events/stats', {
    params: { since_hours: sinceHours },
  });
  return data as {
    total: number;
    success: number;
    failed: number;
    by_outcome: Record<string, number>;
  };
}

export async function listLoginEvents(params: {
  outcome?: string;
  email?: string;
  ip?: string;
  since_hours?: number;
  limit?: number;
}) {
  const { data } = await api.get('/api/v1/auth/login-events', { params });
  return data;
}

// ---- 2FA / TOTP -----------------------------------------------------------
export async function get2FAStatus(): Promise<{ enabled: boolean }> {
  const { data } = await api.get('/api/v1/auth/2fa/status');
  return data;
}

export async function setup2FA(): Promise<{
  secret: string;
  provisioning_uri: string;
  backup_codes: string[];
}> {
  const { data } = await api.post('/api/v1/auth/2fa/setup');
  return data;
}

export async function verify2FA(code: string): Promise<{ ok: boolean }> {
  const { data } = await api.post('/api/v1/auth/2fa/verify', { code });
  return data;
}

export async function disable2FA(code: string): Promise<{ ok: boolean }> {
  const { data } = await api.post('/api/v1/auth/2fa/disable', { code });
  return data;
}

export async function changePassword(oldPw: string, newPw: string) {
  const { data } = await api.post('/api/v1/auth/password', {
    old_password: oldPw,
    new_password: newPw,
  });
  return data;
}

export async function getMe() {
  const { data } = await api.get('/api/v1/auth/me');
  return data;
}

export async function getDrones() {
  const { data } = await api.get('/api/v1/drones');
  return data;
}

export async function createDrone(payload: { sn: string; model: string; protocol: string }) {
  const { data } = await api.post('/api/v1/drones', payload);
  return data;
}

export async function getMissions(params?: { status?: string }) {
  const { data } = await api.get('/api/v1/missions', { params });
  return data;
}

export async function createMission(payload: Record<string, unknown>) {
  const { data } = await api.post('/api/v1/missions', payload);
  return data;
}

export async function getMission(id: string) {
  const { data } = await api.get(`/api/v1/missions/${id}`);
  return data;
}

export async function validateMission(id: string) {
  const { data } = await api.post(`/api/v1/missions/${id}/validate`);
  return data;
}

export async function dispatchMission(id: string) {
  const { data } = await api.post(`/api/v1/missions/${id}/dispatch`);
  return data;
}

export async function abortMission(id: string) {
  const { data } = await api.post(`/api/v1/missions/${id}/abort`);
  return data;
}

export async function getMissionLogs(id: string, limit = 100) {
  const { data } = await api.get(`/api/v1/missions/${id}/logs`, { params: { limit } });
  return data;
}

export async function getStreams() {
  const { data } = await api.get('/api/v1/streams');
  return data;
}

export async function getStream(id: string) {
  const { data } = await api.get(`/api/v1/streams/${id}`);
  return data;
}

export async function getApprovals(params?: { status?: string }) {
  const { data } = await api.get('/api/v1/approvals', { params });
  return data;
}

export async function listPendingApprovals(limit = 50) {
  const { data } = await api.get('/api/v1/copilot/approvals/pending', {
    params: { limit },
  });
  return data as Array<{
    trace_id: string;
    session_id: string | null;
    org_id: string | null;
    org_name: string | null;
    intent: string | null;
    prompt: string;
    started_at: string | null;
    status: string;
  }>;
}

export async function bulkApproveTraces(
  traceIds: string[],
  decision: 'approved' | 'rejected' | 'modified',
  comment?: string,
) {
  const { data } = await api.post('/api/v1/copilot/approvals/bulk', {
    trace_ids: traceIds,
    decision,
    comment,
  });
  return data as {
    requested: number;
    processed: number;
    approved_ids: string[];
    skipped: Array<{ trace_id: string; reason: string }>;
  };
}

export async function approveTrace(
  traceId: string,
  decision: 'approved' | 'rejected' | 'modified',
  comment?: string
) {
  const { data } = await api.post(
    `/api/v1/copilot/traces/${traceId}/approve`,
    { decision, comment }
  );
  return data;
}

// ---- T5.6 Copilot trace inspector -----------------------------------------
export interface CopilotTraceStep {
  idx: number;
  tool: string;
  args: Record<string, unknown> | null;
  result: Record<string, unknown> | null;
  duration_ms: number | null;
  error: string | null;
  ts: string | null;
}

export interface CopilotTrace {
  id: string;
  session_id: string | null;
  prompt: string | null;
  intent: string | null;
  confidence: number | null;
  status: string | null;
  started_at: string | null;
  ended_at: string | null;
  output: Record<string, unknown> | null;
  steps: CopilotTraceStep[] | null;
}

export async function listSessionTraces(sessionId: string): Promise<CopilotTrace[]> {
  const { data } = await api.get(
    `/api/v1/copilot/sessions/${sessionId}/traces`,
  );
  return data as CopilotTrace[];
}

export async function getTrace(traceId: string): Promise<CopilotTrace> {
  const { data } = await api.get(`/api/v1/copilot/traces/${traceId}`);
  return data as CopilotTrace;
}

// ---- Admin API (v1.0 multi-tenant) ----------------------------------------
export async function listOrganizations() {
  const { data } = await api.get('/api/v1/admin/organizations');
  return data;
}

export async function createOrganization(name: string) {
  const { data } = await api.post('/api/v1/admin/organizations', { name });
  return data;
}

export async function updateOrganization(orgId: string, name: string) {
  const { data } = await api.patch(`/api/v1/admin/organizations/${orgId}`, {
    name,
  });
  return data;
}

export async function deleteOrganization(orgId: string) {
  const { data } = await api.delete(`/api/v1/admin/organizations/${orgId}`);
  return data;
}

export async function listUsers(params?: {
  org_id?: string;
  q?: string;
  role?: string;
  is_active?: boolean;
}) {
  const { data } = await api.get('/api/v1/admin/users', { params });
  return data;
}

export async function createUser(payload: {
  email: string;
  password: string;
  role: string;
  org_id?: string | null;
}) {
  const { data } = await api.post('/api/v1/admin/users', payload);
  return data;
}

export async function patchUser(
  userId: string,
  patch: { role?: string; org_id?: string; is_active?: boolean }
) {
  const { data } = await api.patch(`/api/v1/admin/users/${userId}`, patch);
  return data;
}

export async function deactivateUser(userId: string) {
  const { data } = await api.delete(`/api/v1/admin/users/${userId}`);
  return data;
}

// ============================================================================
// v2.1 T2.0 · Scene Marketplace
// ============================================================================

export interface SceneListing {
  id: string;
  scene_id: string;
  org_id: string;
  slug: string;
  title: string;
  description: string | null;
  tags: string[] | null;
  visibility: 'public' | 'org_only' | 'unlisted';
  status: 'active' | 'archived' | 'removed';
  license: string;
  price_cents: number;
  category: string | null;
  is_featured: boolean;
  featured_note: string | null;
  n_gaussians: number | null;
  n_points: number | null;
  clone_count: number;
  view_count: number;
}

export interface SceneListingPage {
  total: number;
  items: SceneListing[];
  limit: number;
  offset: number;
}

export interface PublishListingBody {
  scene_id: string;
  title: string;
  description?: string;
  tags?: string[];
  license?: string;
  price_cents?: number;
  visibility?: 'public' | 'org_only' | 'unlisted';
  slug?: string;
  cover_asset_id?: string;
}

export async function publishSceneListing(body: PublishListingBody): Promise<SceneListing> {
  const { data } = await api.post('/api/v1/marketplace/scenes', body);
  return data;
}

export async function browseSceneListings(params: {
  q?: string;
  tags?: string;             // comma-separated
  min_gaussians?: number;
  license?: string;
  org_id?: string;
  limit?: number;
  offset?: number;
} = {}): Promise<SceneListingPage> {
  const { data } = await api.get('/api/v1/marketplace/scenes', { params });
  return data;
}

export async function cloneSceneListing(listingId: string): Promise<{
  scene_id: string;
  listing_id: string;
  cloned_by_org_id: string;
}> {
  const { data } = await api.post(`/api/v1/marketplace/scenes/${listingId}/clone`);
  return data;
}

export async function reviewSceneListing(
  listingId: string,
  body: { rating: number; comment?: string },
) {
  const { data } = await api.post(
    `/api/v1/marketplace/scenes/${listingId}/reviews`, body,
  );
  return data;
}

export async function sceneListingRating(listingId: string): Promise<{
  count: number;
  average: number | null;
}> {
  const { data } = await api.get(`/api/v1/marketplace/scenes/${listingId}/rating`);
  return data;
}

// ============================================================================
// v2.1 T2.1 · Discovery + moderation
// ============================================================================

export const SCENE_CATEGORIES = [
  'tourism', 'engineering', 'emergency', 'agriculture', 'urban', 'industrial', 'other',
] as const;
export type SceneCategory = typeof SCENE_CATEGORIES[number];

export const SCENE_CATEGORY_LABELS: Record<SceneCategory, string> = {
  tourism: '旅游',
  engineering: '工程',
  emergency: '应急',
  agriculture: '农业',
  urban: '城市',
  industrial: '工业',
  other: '其他',
};

export async function browseSceneListingsExtended(params: {
  q?: string;
  tags?: string;
  min_gaussians?: number;
  license?: string;
  category?: SceneCategory;
  featured_only?: boolean;
  sort?: 'recent' | 'popular' | 'featured';
  org_id?: string;
  limit?: number;
  offset?: number;
} = {}): Promise<SceneListingPage> {
  const { data } = await api.get('/api/v1/marketplace/scenes', { params });
  return data;
}

export async function fetchCategoryCounts(): Promise<{ category: SceneCategory; count: number }[]> {
  const { data } = await api.get('/api/v1/marketplace/scenes/discovery/categories');
  return data;
}

export async function fetchTrendingListings(limit = 10, days = 7): Promise<SceneListing[]> {
  const { data } = await api.get('/api/v1/marketplace/scenes/discovery/trending', {
    params: { limit, days },
  });
  return data;
}

export async function featureSceneListing(
  listingId: string, featured: boolean, note?: string,
): Promise<SceneListing> {
  const { data } = await api.post(
    `/api/v1/marketplace/scenes/${listingId}/feature`,
    { featured, note },
  );
  return data;
}

export async function moderateSceneListing(
  listingId: string, new_status: 'active' | 'archived' | 'removed', reason?: string,
): Promise<SceneListing> {
  const { data } = await api.post(
    `/api/v1/marketplace/scenes/${listingId}/moderate`,
    { new_status, reason },
  );
  return data;
}

// ============================================================================
// v2.1 T2.2 · Moderation reports + appeals
// ============================================================================

export const REPORT_CATEGORIES = [
  'copyright', 'privacy', 'sensitive_area', 'illegal', 'spam', 'other',
] as const;
export type ReportCategory = typeof REPORT_CATEGORIES[number];

export const REPORT_CATEGORY_LABELS: Record<ReportCategory, string> = {
  copyright: '版权侵权',
  privacy: '隐私（人脸/车牌/住宅）',
  sensitive_area: '敏感区域（军事/边境/核电）',
  illegal: '违法内容',
  spam: '垃圾/低质量',
  other: '其他',
};

export interface Report {
  id: string;
  listing_id: string;
  reporter_user_id: string | null;
  category: ReportCategory;
  details: string | null;
  status: 'open' | 'reviewing' | 'accepted' | 'rejected' | 'duplicate';
  resolution_note: string | null;
}

export interface Appeal {
  id: string;
  listing_id: string;
  appeal_seq: number;
  appellant_user_id: string | null;
  original_status: string;
  appeal_message: string;
  status: 'pending' | 'accepted' | 'rejected' | 'withdrawn';
  resolution_note: string | null;
}

export async function fileReport(
  listingId: string, body: { category: ReportCategory; details?: string },
): Promise<{ report: Report; auto_hidden: boolean }> {
  const { data } = await api.post(
    `/api/v1/marketplace/scenes/${listingId}/reports`, body,
  );
  return data;
}

export async function listReports(params: {
  status?: string;
  listing_id?: string;
  category?: string;
  limit?: number;
  offset?: number;
} = {}): Promise<{ total: number; items: Report[]; limit: number; offset: number }> {
  const { data } = await api.get('/api/v1/marketplace/scenes/reports', { params });
  return data;
}

export async function reportSummary(listingId: string): Promise<{
  total: number;
  by_status: Record<string, number>;
  by_category: Record<string, number>;
}> {
  const { data } = await api.get(
    `/api/v1/marketplace/scenes/${listingId}/reports/summary`,
  );
  return data;
}

export async function resolveReport(
  reportId: string, body: { new_status: string; note?: string; take_down_reason?: string },
): Promise<Report> {
  const { data } = await api.post(
    `/api/v1/marketplace/scenes/reports/${reportId}/resolve`, body,
  );
  return data;
}

export async function fileAppeal(
  listingId: string, appeal_message: string,
): Promise<Appeal> {
  const { data } = await api.post(
    `/api/v1/marketplace/scenes/${listingId}/appeals`,
    { appeal_message },
  );
  return data;
}

export async function listAppeals(params: {
  status?: string;
  listing_id?: string;
  limit?: number;
  offset?: number;
} = {}): Promise<{ total: number; items: Appeal[]; limit: number; offset: number }> {
  const { data } = await api.get('/api/v1/marketplace/scenes/appeals', { params });
  return data;
}

export async function resolveAppeal(
  appealId: string, accept: boolean, note?: string,
): Promise<Appeal> {
  const { data } = await api.post(
    `/api/v1/marketplace/scenes/appeals/${appealId}/resolve`,
    { accept, note },
  );
  return data;
}

export async function withdrawAppeal(appealId: string): Promise<Appeal> {
  const { data } = await api.post(
    `/api/v1/marketplace/scenes/appeals/${appealId}/withdraw`,
  );
  return data;
}
