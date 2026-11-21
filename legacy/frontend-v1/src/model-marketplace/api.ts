/**
 * Model Marketplace API client
 */
import { request } from '../utils/request';
import type {
  ModelListing,
  ModelReview,
  CreateModelRequest,
  UpdateModelRequest,
  CreateReviewRequest,
  ModelListResponse,
  PurchaseOut,
} from './types';

/**
 * List public published models
 */
export async function listModels(params: {
  page?: number;
  size?: number;
  category?: string;
  tag?: string;
  search?: string;
  authorId?: string;
}): Promise<ModelListResponse> {
  return request.get('/api/v1/model-marketplace/models', { params });
}

/**
 * Get a single model by ID
 */
export async function getModel(modelId: string): Promise<ModelListing> {
  return request.get(`/api/v1/model-marketplace/models/${modelId}`);
}

/**
 * Create a new model listing
 */
export async function createModel(data: CreateModelRequest): Promise<ModelListing> {
  return request.post('/api/v1/model-marketplace/models', data);
}

/**
 * Update an existing model
 */
export async function updateModel(
  modelId: string,
  data: UpdateModelRequest
): Promise<ModelListing> {
  return request.put(`/api/v1/model-marketplace/models/${modelId}`, data);
}

/**
 * Delete a model
 */
export async function deleteModel(modelId: string): Promise<void> {
  return request.delete(`/api/v1/model-marketplace/models/${modelId}`);
}

/**
 * List models authored by current user (including drafts)
 */
export async function listMyModels(): Promise<ModelListing[]> {
  return request.get('/api/v1/model-marketplace/my');
}

/**
 * Purchase a model
 */
export async function purchaseModel(modelId: string): Promise<PurchaseOut> {
  return request.post(`/api/v1/model-marketplace/models/${modelId}/purchase`, {});
}

/**
 * List reviews for a model
 */
export async function listReviews(modelId: string): Promise<ModelReview[]> {
  return request.get(`/api/v1/model-marketplace/models/${modelId}/reviews`);
}

/**
 * Create or update review
 */
export async function createReview(
  modelId: string,
  data: CreateReviewRequest
): Promise<ModelReview> {
  return request.post(`/api/v1/model-marketplace/models/${modelId}/reviews`, data);
}
