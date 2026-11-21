/**
 * Training-as-a-Service (TaaS) types — SkyMaster v2.3 E6
 */

export interface TrainingDataset {
  id: string;
  orgId?: string;
  ownerId?: string;
  name: string;
  description?: string;
  datasetType: string;
  fileFormat: string;
  storageUri: string;
  sizeBytes?: number;
  numSamples?: number;
  schemaValidation: 'pending' | 'passed' | 'failed';
  schemaErrors?: Record<string, any>;
  createdAt: string;
}

export interface CreateDatasetRequest {
  name: string;
  description?: string;
  datasetType: string;
  fileFormat: string;
  sizeBytes?: number;
  numSamples?: number;
}

export interface GPUNode {
  id: string;
  name: string;
  gpuModel: string;
  totalVramBytes: number;
  usedVramBytes: number;
  enabled: boolean;
  lastHeartbeatAt?: string;
}

export interface FineTuneJob {
  id: string;
  orgId?: string;
  ownerId?: string;
  name: string;
  description?: string;
  baseModelId?: string;
  baseModelUri?: string;
  datasetId: string;
  numEpochs: number;
  learningRate: number;
  batchSize: number;
  gradientAccumulationSteps: number;
  loraRank?: number;
  maxSeqLength?: number;
  state: string;
  scheduledNodeId?: string;
  startedAt?: string;
  finishedAt?: string;
  errorMessage?: string;
  outputModelUri?: string;
  publishedToMarketplace: boolean;
  marketplaceModelId?: string;
  gpuHoursUsed?: number;
  costCents?: number;
  createdAt: string;
}

export interface CreateFineTuneRequest {
  name: string;
  description?: string;
  baseModelId?: string;
  baseModelUri?: string;
  datasetId: string;
  numEpochs: number;
  learningRate: number;
  batchSize: number;
  gradientAccumulationSteps: number;
  loraRank?: number;
  maxSeqLength?: number;
  outputModelName?: string;
}

export interface FineTuneMetric {
  id: string;
  jobId: string;
  step: number;
  epoch?: number;
  loss?: number;
  accuracy?: number;
  otherMetrics?: Record<string, any>;
  timestamp: string;
}
