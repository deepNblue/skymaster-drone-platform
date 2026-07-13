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
