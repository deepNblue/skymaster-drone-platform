/**
 * Model Marketplace types for SkyMaster v2.2 E5
 */

export interface ModelListing {
  id: string;
  authorId?: string;
  orgId?: string;
  name: string;
  description: string;
  category: string;
  licenseType: 'free' | 'one-time' | 'subscription';
  priceCents?: number;
  revenueSplitAuthor: number;
  tags?: string[];
  averageRating?: number;
  reviewCount: number;
  downloadCount: number;
  purchaseCount: number;
  published: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface ModelReview {
  id: string;
  modelId: string;
  userId?: string;
  rating: number;
  comment?: string;
  createdAt: string;
}

export interface CreateModelRequest {
  name: string;
  description: string;
  category: string;
  licenseType: 'free' | 'one-time' | 'subscription';
  priceCents?: number;
  tags?: string[];
  published: boolean;
}

export interface UpdateModelRequest {
  name?: string;
  description?: string;
  category?: string;
  priceCents?: number;
  tags?: string[];
  published?: boolean;
}

export interface CreateReviewRequest {
  rating: number;
  comment?: string;
}

export interface ModelListResponse {
  total: number;
  page: number;
  size: number;
  items: ModelListing[];
}

export interface PurchaseOut {
  id: string;
  modelId: string;
  buyerId: string;
  amountCents: number;
  status: string;
  createdAt: string;
}
