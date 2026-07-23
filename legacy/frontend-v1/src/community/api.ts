/**
 * Community API client for SkyMaster
 */
import { request } from '../utils/request';
import type {
  CommunityPost,
  CommunityComment,
  CreatePostRequest,
  UpdatePostRequest,
  CreateCommentRequest,
  ReportPostRequest,
  PostListResponse,
} from './types';

/**
 * List community posts
 */
export async function listPosts(params: {
  page?: number;
  size?: number;
  tenantId?: string;
  tag?: string;
}): Promise<PostListResponse> {
  return request.get('/api/v1/community/posts', { params });
}

/**
 * Get a single post by ID
 */
export async function getPost(postId: string): Promise<CommunityPost> {
  return request.get(`/api/v1/community/posts/${postId}`);
}

/**
 * Create a new post
 */
export async function createPost(data: CreatePostRequest): Promise<CommunityPost> {
  return request.post('/api/v1/community/posts', data);
}

/**
 * Update an existing post
 */
export async function updatePost(
  postId: string,
  data: UpdatePostRequest
): Promise<CommunityPost> {
  return request.put(`/api/v1/community/posts/${postId}`, data);
}

/**
 * Delete a post
 */
export async function deletePost(postId: string): Promise<void> {
  return request.delete(`/api/v1/community/posts/${postId}`);
}

/**
 * Like a post
 */
export async function likePost(postId: string): Promise<{ likeCount: number }> {
  return request.post(`/api/v1/community/posts/${postId}/like`);
}

/**
 * Unlike a post
 */
export async function unlikePost(postId: string): Promise<{ likeCount: number }> {
  return request.delete(`/api/v1/community/posts/${postId}/like`);
}

/**
 * Add comment to post
 */
export async function addComment(
  postId: string,
  data: CreateCommentRequest
): Promise<CommunityComment> {
  return request.post(`/api/v1/community/posts/${postId}/comments`, data);
}

/**
 * List comments for post
 */
export async function listComments(postId: string): Promise<CommunityComment[]> {
  return request.get(`/api/v1/community/posts/${postId}/comments`);
}

/**
 * Report a post
 */
export async function submitReport(data: ReportPostRequest): Promise<{ reportId: string }> {
  return request.post('/api/v1/community/reports', data);
}
