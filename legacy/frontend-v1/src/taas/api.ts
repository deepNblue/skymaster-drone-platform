/**
 * Training-as-a-Service API client
 */
import { request } from '../utils/request';
import type {
  TrainingDataset,
  CreateDatasetRequest,
  GPUNode,
  FineTuneJob,
  CreateFineTuneRequest,
  FineTuneMetric,
} from './types';

/**
 * List my datasets
 */
export async function listMyDatasets(): Promise<TrainingDataset[]> {
  return request.get('/api/v1/taas/datasets');
}

/**
 * Create new dataset
 */
export async function createDataset(
  data: CreateDatasetRequest
): Promise<TrainingDataset> {
  return request.post('/api/v1/taas/datasets', data);
}

/**
 * Get dataset by ID
 */
export async function getDataset(id: string): Promise<TrainingDataset> {
  return request.get(`/api/v1/taas/datasets/${id}`);
}

/**
 * Delete dataset
 */
export async function deleteDataset(id: string): Promise<void> {
  return request.delete(`/api/v1/taas/datasets/${id}`);
}

/**
 * List enabled GPU nodes (admin only)
 */
export async function listGPUNodes(): Promise<GPUNode[]> {
  return request.get('/api/v1/taas/gpu-nodes');
}

/**
 * List my fine-tune jobs
 */
export async function listMyJobs(): Promise<FineTuneJob[]> {
  return request.get('/api/v1/taas/jobs');
}

/**
 * Create new fine-tune job
 */
export async function createFineTuneJob(
  data: CreateFineTuneRequest
): Promise<FineTuneJob> {
  return request.post('/api/v1/taas/jobs', data);
}

/**
 * Get job by ID
 */
export async function getJob(id: string): Promise<FineTuneJob> {
  return request.get(`/api/v1/taas/jobs/${id}`);
}

/**
 * Cancel queued/running job
 */
export async function cancelJob(id: string): Promise<{ status: string }> {
  return request.post(`/api/v1/taas/jobs/${id}/cancel`);
}

/**
 * Get all metrics for a job
 */
export async function getJobMetrics(id: string): Promise<FineTuneMetric[]> {
  return request.get(`/api/v1/taas/jobs/${id}/metrics`);
}

/**
 * Publish completed job to Model Marketplace
 */
export async function publishJobToMarketplace(
  id: string
): Promise<{ model_id: string | null }> {
  return request.post(`/api/v1/taas/jobs/${id}/publish`);
}
