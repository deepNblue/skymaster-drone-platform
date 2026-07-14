/**
 * Community v2.0 §3.18 API client helpers.
 *
 * Uses the axios instance from api.ts so tokens + refresh logic apply.
 */
import { api } from './api';

export type ModerationStatus = 'pending' | 'approved' | 'rejected' | 'archived';

export interface CommunityPost {
  id: string;
  tenant_id: string | null;
  author_id: string | null;
  title: string;
  body: string;
  tags: string[] | null;
  moderation_status: ModerationStatus;
  moderation_reason: string | null;
  pinned: boolean;
  view_count: number;
  like_count: number;
  comment_count: number;
  created_at: string;
  updated_at: string;
}

export interface CommunityComment {
  id: string;
  post_id: string;
  parent_id: string | null;
  author_id: string | null;
  body: string;
  moderation_status: ModerationStatus;
  like_count: number;
  created_at: string;
}

export interface PostList {
  total: number;
  items: CommunityPost[];
}

// ---------------------------------------------------------------------------

export async function listCommunityPosts(params: {
  limit?: number;
  offset?: number;
  include_pending?: boolean;
  tag?: string;
} = {}): Promise<PostList> {
  const { data } = await api.get('/api/v1/community/posts', { params });
  return data as PostList;
}

export async function getCommunityPost(pid: string): Promise<CommunityPost> {
  const { data } = await api.get(`/api/v1/community/posts/${pid}`);
  return data as CommunityPost;
}

export async function createCommunityPost(body: {
  title: string;
  body: string;
  tags?: string[];
}): Promise<CommunityPost> {
  const { data } = await api.post('/api/v1/community/posts', body);
  return data as CommunityPost;
}

export async function listCommunityComments(
  pid: string,
): Promise<CommunityComment[]> {
  const { data } = await api.get(`/api/v1/community/posts/${pid}/comments`);
  return data as CommunityComment[];
}

export async function createCommunityComment(
  pid: string,
  body: string,
  parent_id?: string,
): Promise<CommunityComment> {
  const { data } = await api.post(
    `/api/v1/community/posts/${pid}/comments`,
    { body, parent_id },
  );
  return data as CommunityComment;
}

export async function likeCommunityPost(pid: string): Promise<CommunityPost> {
  const { data } = await api.post(`/api/v1/community/posts/${pid}/like`);
  return data as CommunityPost;
}

// --- Admin ------------------------------------------------------------------

export async function fetchModerationQueue(params: {
  limit?: number;
  offset?: number;
} = {}): Promise<PostList> {
  const { data } = await api.get('/api/v1/community/moderation/queue', {
    params,
  });
  return data as PostList;
}

export async function moderateCommunityPost(
  pid: string,
  action: 'approve' | 'reject' | 'archive',
  reason?: string,
): Promise<CommunityPost> {
  const { data } = await api.post(
    `/api/v1/community/posts/${pid}/moderate`,
    { action, reason },
  );
  return data as CommunityPost;
}

// ---- T6.5 Reporting ------------------------------------------------------

export const REPORT_REASONS = [
  { value: 'spam', label: '垃圾/广告' },
  { value: 'harassment', label: '骚扰/攻击' },
  { value: 'misinformation', label: '虚假信息' },
  { value: 'illegal', label: '违法违规' },
  { value: 'porn', label: '色情' },
  { value: 'violence', label: '暴力' },
  { value: 'off_topic', label: '偏离主题' },
  { value: 'other', label: '其他' },
] as const;

export type ReportReason = typeof REPORT_REASONS[number]['value'];

export interface ReportOut {
  id: string;
  post_id: string;
  reporter_id: string | null;
  reason: string;
  note: string | null;
  status: 'open' | 'resolved' | 'dismissed';
  resolved_by: string | null;
  resolved_at: string | null;
  created_at: string;
}

export async function reportPost(
  pid: string,
  body: { reason: ReportReason; note?: string },
): Promise<ReportOut> {
  const { data } = await api.post(
    `/api/v1/community/posts/${pid}/report`,
    body,
  );
  return data as ReportOut;
}

export async function listOpenReports(): Promise<{
  total: number;
  items: ReportOut[];
}> {
  const { data } = await api.get('/api/v1/community/moderation/reports');
  return data;
}

export async function resolveReport(
  rid: string,
  action: 'resolve' | 'dismiss',
  note?: string,
): Promise<ReportOut> {
  const { data } = await api.post(
    `/api/v1/community/moderation/reports/${rid}/resolve`,
    { action, note },
  );
  return data as ReportOut;
}

/** T6.12 — reporter reputation for moderation UI. */
export interface ReporterReputation {
  reporter_id: string;
  resolved: number;
  dismissed: number;
  open: number;
  weight: number;
  label: 'trusted' | 'neutral' | 'suspect';
}

export async function getReporterReputation(
  reporterId: string,
): Promise<ReporterReputation> {
  const { data } = await api.get(
    `/api/v1/community/moderation/reporters/${reporterId}/reputation`,
  );
  return data as ReporterReputation;
}

/** T6.8 — admin dashboard summary. */
export interface ModerationStats {
  open_reports: number;
  pending_posts: number;
  auto_hidden_posts: number;
  auto_hide_threshold: number;
}

export async function fetchModerationStats(): Promise<ModerationStats> {
  const { data } = await api.get('/api/v1/community/moderation/stats');
  return data as ModerationStats;
}
