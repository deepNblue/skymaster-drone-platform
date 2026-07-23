/**
 * Community module types for SkyMaster v2.2 E4
 */

export interface CommunityPost {
  id: string;
  tenantId?: string;
  authorId?: string;
  title: string;
  body: string;
  tags?: string[];
  moderationStatus: 'approved' | 'rejected' | 'pending';
  pinned: boolean;
  viewCount: number;
  likeCount: number;
  commentCount: number;
  createdAt: string;
  updatedAt: string;
}

export interface CommunityComment {
  id: string;
  postId: string;
  parentId?: string;
  authorId?: string;
  body: string;
  moderationStatus: 'approved' | 'rejected' | 'pending';
  likeCount: number;
  createdAt: string;
}

export interface CreatePostRequest {
  title: string;
  body: string;
  tags?: string[];
  tenantId?: string;
}

export interface UpdatePostRequest {
  title?: string;
  body?: string;
  tags?: string[];
}

export interface CreateCommentRequest {
  body: string;
  parentId?: string;
}

export interface ReportPostRequest {
  postId: string;
  reason: string;
  note?: string;
}

export interface PostListResponse {
  total: number;
  page: number;
  size: number;
  items: CommunityPost[];
}
