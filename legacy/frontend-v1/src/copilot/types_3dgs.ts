// 3DGS Reality Studio 前端类型定义

export type SceneStatus =
  | 'draft'
  | 'ingesting'
  | 'ingested'
  | 'colmap'
  | 'colmap_done'
  | 'training'
  | 'ready'
  | 'failed'
  | 'archived';

export type SceneAssetKind =
  | 'source_image'
  | 'source_video'
  | 'colmap_sparse'
  | 'colmap_dense'
  | 'gsplat_ckpt'
  | 'gsplat_ply'
  | 'preview_thumb'
  | 'log';

export interface SceneAsset {
  id: string;
  kind: SceneAssetKind;
  filename: string;
  storage_path: string;
  size_bytes?: number;
  sha256_hex?: string;
  uploaded_by?: string;
  created_at: string;
}

export interface Scene {
  id: string;
  org_id: string;
  name: string;
  description?: string;
  status: SceneStatus;
  error_msg?: string;
  coord_system?: string;
  n_source_images: number;
  n_points?: number;
  n_gaussians?: number;
  psnr_train?: number;
  scene_kind: '3dgs' | '4dgs';
  n_frames?: number;
  psnr_temporal?: number;
  mission_id?: string;
  assets: SceneAsset[];
  created_at: string;
  updated_at: string;
}

export interface SceneCreateRequest {
  name: string;
  description?: string;
  coord_system?: string;
  mission_id?: string;
  scene_kind: '3dgs' | '4dgs';
}

export interface ProgressUpdate {
  scene_id: string;
  status: SceneStatus;
  progress_pct: number;
  message?: string;
  timestamp: string;
}
