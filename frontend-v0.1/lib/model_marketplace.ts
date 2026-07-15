/**
 * Model Marketplace v2.0 §3.16 — API client.
 */
import { api } from './api';

export type Visibility = 'public' | 'org' | 'private';
export type ReviewStatus = 'pending' | 'approved' | 'rejected' | 'withdrawn';
export type PriceModel = 'free' | 'per_call' | 'per_frame' | 'per_token' | 'per_month';

export interface ModelListing {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  task: string;
  framework: string;
  tags: string[] | null;
  visibility: Visibility;
  owner_org_id: string | null;
  owner_user_id: string | null;
  license: string;
  price_model: PriceModel;
  price_unit: string | null;
  currency: string;
  is_featured: boolean;
  created_at: string;
  updated_at: string;
  // T5.9 — aggregate counts populated by the API layer.
  deployment_count?: number;
  version_count?: number;
  // T5.10 — favorite state
  favorited_by_me?: boolean;
  // T5.11 — review rollup
  average_rating?: number;
  review_count?: number;
}

export interface ModelVersion {
  id: string;
  listing_id: string;
  version: string;
  artifact_uri: string;
  artifact_sha256: string;
  size_bytes: number | null;
  inputs_schema: Record<string, unknown> | null;
  outputs_schema: Record<string, unknown> | null;
  hardware: string[] | null;
  benchmark: Record<string, unknown> | null;
  review_status: ReviewStatus;
  review_note: string | null;
  reviewer_id: string | null;
  reviewed_at: string | null;
  created_at: string;
}

export interface ModelDeployment {
  id: string;
  org_id: string;
  listing_id: string;
  version_id: string;
  status: string;
  endpoint_url: string | null;
  quota_calls_per_day: number | null;
  installed_by: string | null;
  installed_at: string;
  updated_at: string;
}

export interface UsageSummary {
  deployment_id: string;
  since_days: number;
  total_units: number;
  by_outcome: Record<string, number>;
}

export interface UsageDailyPoint {
  day: string; // YYYY-MM-DD UTC
  total_units: number;
  by_outcome: Record<string, number>;
}

export interface UsageDailySeries {
  deployment_id: string;
  since_days: number;
  quota_calls_per_day: number | null;
  points: UsageDailyPoint[];
}

export interface ListingPage {
  total: number;
  items: ModelListing[];
}

// ---------------------------------------------------------------------------

const BASE = '/api/v1/model-marketplace';

export async function listModelListings(params: {
  task?: string;
  framework?: string;
  tag?: string;
  // T5.12 — search + sort
  q?: string;
  sort?: 'featured' | 'newest' | 'popular' | 'top_rated';
  limit?: number;
  offset?: number;
} = {}): Promise<ListingPage> {
  const { data } = await api.get(`${BASE}/listings`, { params });
  return data as ListingPage;
}

export async function getModelListing(lid: string): Promise<ModelListing> {
  const { data } = await api.get(`${BASE}/listings/${lid}`);
  return data as ModelListing;
}

export async function createModelListing(body: Partial<ModelListing>): Promise<ModelListing> {
  const { data } = await api.post(`${BASE}/listings`, body);
  return data as ModelListing;
}

export async function listModelVersions(lid: string): Promise<ModelVersion[]> {
  const { data } = await api.get(`${BASE}/listings/${lid}/versions`);
  return data as ModelVersion[];
}

export async function createModelVersion(
  lid: string,
  body: Partial<ModelVersion>,
): Promise<ModelVersion> {
  const { data } = await api.post(`${BASE}/listings/${lid}/versions`, body);
  return data as ModelVersion;
}

export async function reviewModelVersion(
  vid: string,
  action: 'approve' | 'reject' | 'withdraw',
  note?: string,
): Promise<ModelVersion> {
  const { data } = await api.post(`${BASE}/versions/${vid}/review`, {
    action,
    note,
  });
  return data as ModelVersion;
}

export async function installModelVersion(
  vid: string,
  body: { endpoint_url?: string; quota_calls_per_day?: number } = {},
): Promise<ModelDeployment> {
  const { data } = await api.post(`${BASE}/versions/${vid}/install`, body);
  return data as ModelDeployment;
}

export async function listMyDeployments(): Promise<ModelDeployment[]> {
  const { data } = await api.get(`${BASE}/deployments`);
  return data as ModelDeployment[];
}

export async function getUsageSummary(
  did: string,
  since_days = 7,
): Promise<UsageSummary> {
  const { data } = await api.get(`${BASE}/deployments/${did}/usage-summary`, {
    params: { since_days },
  });
  return data as UsageSummary;
}

export async function getUsageDaily(
  did: string,
  since_days = 30,
): Promise<UsageDailySeries> {
  const { data } = await api.get(`${BASE}/deployments/${did}/usage-daily`, {
    params: { since_days },
  });
  return data as UsageDailySeries;
}

// ---------------------------------------------------------------------------
// T5.10 — Favorites (bookmarks)
// ---------------------------------------------------------------------------
export async function favoriteListing(lid: string): Promise<void> {
  await api.post(`${BASE}/listings/${lid}/favorite`);
}

export async function unfavoriteListing(lid: string): Promise<void> {
  await api.delete(`${BASE}/listings/${lid}/favorite`);
}

export async function listMyFavorites(): Promise<ModelListing[]> {
  const { data } = await api.get(`${BASE}/favorites`);
  return data as ModelListing[];
}

// ---------------------------------------------------------------------------
// T5.13 — filter facets
// ---------------------------------------------------------------------------
export interface MarketplaceFacets {
  tasks: Record<string, number>;
  frameworks: Record<string, number>;
  tags: Record<string, number>;
  total: number;
}

export async function getMarketplaceFacets(): Promise<MarketplaceFacets> {
  const { data } = await api.get(`${BASE}/facets`);
  return data as MarketplaceFacets;
}

// ---------------------------------------------------------------------------
// T5.11 — Reviews
// ---------------------------------------------------------------------------
export interface Review {
  id: string;
  listing_id: string;
  user_id: string;
  rating: number;
  comment: string | null;
  created_at: string;
}

export interface ReviewAggregate {
  average_rating: number;
  review_count: number;
  rating_histogram: Record<string, number>;
}

export async function submitReview(
  lid: string, rating: number, comment?: string,
): Promise<Review> {
  const { data } = await api.post(
    `${BASE}/listings/${lid}/reviews`, { rating, comment },
  );
  return data as Review;
}

export async function listReviews(
  lid: string, limit = 50,
): Promise<Review[]> {
  const { data } = await api.get(
    `${BASE}/listings/${lid}/reviews`, { params: { limit } },
  );
  return data as Review[];
}

export async function getReviewAggregate(
  lid: string,
): Promise<ReviewAggregate> {
  const { data } = await api.get(
    `${BASE}/listings/${lid}/reviews/aggregate`,
  );
  return data as ReviewAggregate;
}

export async function deleteMyReview(lid: string): Promise<void> {
  await api.delete(`${BASE}/listings/${lid}/reviews/mine`);
}
