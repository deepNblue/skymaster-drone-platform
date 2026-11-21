/**
 * Approval city template API client
 */
import { request } from '../utils/request';
import type { CityTemplate, ParseReceiptRequest } from './types';

/**
 * List enabled city templates, optionally filtered by province
 */
export async function listCityTemplates(province?: string): Promise<CityTemplate[]> {
  return request.get('/api/v1/approval-city/templates', { params: { province } });
}

/**
 * Get template for specific province + city
 */
export async function getCityTemplate(
  province: string,
  city: string
): Promise<CityTemplate> {
  return request.get(`/api/v1/approval-city/template-by-city/${encodeURIComponent(province)}/${encodeURIComponent(city)}`);
}

/**
 * Parse receipt email and update approval status
 */
export async function parseReceipt(req: ParseReceiptRequest): Promise<{
  parsed_status: string | null;
  template_used: string | null;
}> {
  return request.post('/api/v1/approval-city/parse-receipt', req);
}
