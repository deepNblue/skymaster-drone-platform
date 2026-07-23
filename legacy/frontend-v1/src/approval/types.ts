/**
 * Approval types with city template support — v2.3 E7
 */

export interface CityTemplate {
  id: string;
  province: string;
  city: string;
  cityAdcode?: string;
  enabled: boolean;
  requiredFields: string[];
  fieldLabels?: Record<string, string>;
  submissionChannel: 'email' | 'online-rpa' | 'paper';
  targetEmail?: string;
  emailSubjectTemplate?: string;
  emailBodyTemplate?: string;
  lastTestedAt?: string;
}

export interface GetCityTemplatesRequest {
  province?: string;
}

export interface ParseReceiptRequest {
  approvalId: string;
  source: 'email' | 'manual' | 'portal';
  subject?: string;
  body?: string;
}
