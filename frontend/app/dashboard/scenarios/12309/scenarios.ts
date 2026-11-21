import { api } from '@/lib/api';

export type ScenarioBlock<T = any> = {
  available: boolean;
  reason?: string;
  items: T[];
  count: number;
  window_minutes?: number;
};

export type ScenarioMeta = {
  id: string;
  name: string;
  short_name: string;
  description: string;
  owner: string;
  region: {
    name: string;
    bbox: number[];
    center: { lat: number; lng: number };
    alt_limit_m: number;
    note?: string;
  };
  kpis: { key: string; label: string; unit: string }[];
  config_loaded: boolean;
};

export type ScenarioOverview = {
  meta: ScenarioMeta;
  routes: ScenarioBlock<{
    id: string; name: string; description: string;
    waypoints: { lat: number; lng: number; alt: number }[];
  }>;
  fleet: ScenarioBlock<{
    id: string; sn: string; label: string; model: string;
    protocol: string; status: string;
    dji_device_sn?: string; dji_gateway_sn?: string;
  }>;
  missions: ScenarioBlock<{
    task_id: string; flight_id: string; drone_sn: string;
    state: string; progress: number; idx: number;
    waypoint_count: number; breakpoint?: number;
    kmz_filename?: string; updated_at?: string;
  }>;
  alerts: ScenarioBlock<{
    id: string; label: string; confidence: number;
    severity: string; severity_label: string; status: string;
    open: boolean; lat?: number; lng?: number;
    drone_id?: string; mission_id?: string; created_at?: string;
  }>;
  approvals: ScenarioBlock<{
    id: string; title: string; category: string;
    status: string; status_label: string; open: boolean;
    max_alt_m?: number; start_ts?: string; end_ts?: string;
    created_at?: string;
  }>;
  streams: ScenarioBlock<{
    drone_id: string; name: string; active: boolean;
    hls_url?: string; rtsp_url?: string;
  }>;
  evidence: ScenarioBlock<{
    id: string; name: string; status: string; scene_kind: string;
    n_source_images: number; n_gaussians: number;
    psnr_train?: number; asset_count: number; created_at?: string;
  }>;
  kpi: Record<string, number>;
  timeline: {
    kind: string; at: string; title?: string;
    status?: string; id?: string;
  }[];
  generated_at: string;
};

export async function listScenarios() {
  const { data } = await api.get('/api/v1/scenarios');
  return data as { items: { id: string; name: string; short_name: string }[]; count: number };
}

export async function getScenario12309(): Promise<ScenarioOverview> {
  const { data } = await api.get('/api/v1/scenarios/12309/overview');
  return data as ScenarioOverview;
}
