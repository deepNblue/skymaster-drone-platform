/**
 * TaaS Fine-tune Job Detail page with loss chart — SkyMaster v2.3 E6
 */
import React, { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Card,
  Button,
  Space,
  Tag,
  Descriptions,
  Badge,
  message,
  Alert,
  Divider,
  Statistic,
  LineChart,
} from 'antd';
import {
  ArrowLeftOutlined,
  CloudUploadOutlined,
  StopOutlined,
} from '@ant-design/icons';
import * as api from './api';
import type { FineTuneJob, FineTuneMetric } from './types';

const { Line } = LineChart;

const STATE_COLOR: Record<string, any> = {
  draft: 'default',
  queued: 'processing',
  scheduled: 'processing',
  running: 'processing',
  completed: 'success',
  failed: 'error',
  canceled: 'default',
};

const STATE_LABEL: Record<string, string> = {
  draft: '草稿',
  queued: '排队中',
  scheduled: '已调度',
  running: '训练中',
  completed: '已完成',
  failed: '失败',
  canceled: '已取消',
};

export const JobDetail: React.FC = () => {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const [job, setJob] = useState<FineTuneJob | null>(null);
  const [metrics, setMetrics] = useState<FineTuneMetric[]>([]);
  const [loading, setLoading] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [canceling, setCanceling] = useState(false);
  const intervalRef = useRef<number | null>(null);

  const fetchJob = async () => {
    if (!jobId) return;
    setLoading(true);
    try {
      const data = await api.getJob(jobId);
      setJob(data);
    } catch (e) {
      message.error('加载任务失败');
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const fetchMetrics = async () => {
    if (!jobId) return;
    try {
      const data = await api.getJobMetrics(jobId);
      setMetrics(data);
    } catch (e) {
      console.error('Failed to fetch metrics', e);
    }
  };

  useEffect(() => {
    if (jobId) {
      fetchJob();
      fetchMetrics();
    }
    // Poll for updates if running
    if (job?.state === 'running' || job?.state === 'queued') {
      intervalRef.current = window.setInterval(() => {
        fetchJob();
        fetchMetrics();
      }, 5000);
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  const handleCancel = async () => {
    if (!jobId || !job) return;
    setCanceling(true);
    try {
      await api.cancelJob(jobId);
      message.success('已取消');
      fetchJob();
    } catch (e) {
      message.error('取消失败');
      console.error(e);
    } finally {
      setCanceling(false);
    }
  };

  const handlePublish = async () => {
    if (!jobId || !job) return;
    setPublishing(true);
    try {
      const res = await api.publishJobToMarketplace(jobId);
      message.success('发布成功到模型市场');
      fetchJob();
      if (res.model_id) {
        navigate(`/model-marketplace/${res.model_id}`);
      }
    } catch (e) {
      message.error('发布失败');
      console.error(e);
    } finally {
      setPublishing(false);
    }
  };

  const chartData = metrics.filter(m => m.loss != null).map(m => ({
    step: m.step,
    loss: Number(m.loss?.toFixed(4)),
    epoch: m.epoch ?? 0,
  }));

  const formatCost = (cents?: number) => {
    if (cents == null) return '-';
    return `¥${(cents / 100).toFixed(2)}`;
  };

  if (!job) {
    return (
      <div style={{ padding: 24 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/taas')}>
          返回列表
        </Button>
        <div style={{ marginTop: 24 }}>{loading ? '加载中...' : '任务不存在'}</div>
      </div>
    );
  }

  return (
    <div style={{ padding: 16, maxWidth: 1000, margin: '0 auto' }}>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/taas')}>
          返回列表
        </Button>
      </Space>

      <Card>
        <Space direction="vertical" style={{ width: '100%' }} size="large">
          <Space>
            <h1>{job.name}</h1>
            <Badge status={STATE_COLOR[job.state]} text={STATE_LABEL[job.state]} />
          </Space>

          {job.errorMessage && (
            <Alert
              message="训练出错"
              description={job.errorMessage}
              type="error"
              showIcon
            />
          )}

          <Descriptions bordered column={{ xs: 1, sm: 2 }}>
            <Descriptions.Item label="基础模型">{job.baseModelId ?? job.baseModelUri ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="数据集">{job.datasetId}</Descriptions.Item>
            <Descriptions.Item label="训练轮次">{job.numEpochs}</Descriptions.Item>
            <Descriptions.Item label="Batch Size">{job.batchSize}</Descriptions.Item>
            <Descriptions.Item label="学习率">{job.learningRate.toExponential(3)}</Descriptions.Item>
            <Descriptions.Item label="LoRA Rank">{job.loraRank ?? '全参数'}</Descriptions.Item>
            <Descriptions.Item label="已发布到市场">
              {job.publishedToMarketplace ? '是' : '否'}
            </Descriptions.Item>
            <Descriptions.Item label="费用">{formatCost(job.costCents)}</Descriptions.Item>
            <Descriptions.Item label="创建时间">{new Date(job.createdAt).toLocaleString()}</Descriptions.Item>
            <Descriptions.Item label="完成时间">
              {job.finishedAt ? new Date(job.finishedAt).toLocaleString() : '-'}
            </Descriptions.Item>
          </Descriptions>

          <Space>
            {['queued', 'scheduled', 'running'].includes(job.state) && (
              <Button
                danger
                icon={<StopOutlined />}
                onClick={handleCancel}
                loading={canceling}
              >
                取消任务
              </Button>
            )}
            {job.state === 'completed' && !job.publishedToMarketplace && (
              <Button
                type="primary"
                icon={<CloudUploadOutlined />}
                onClick={handlePublish}
                loading={publishing}
              >
                发布到模型市场
              </Button>
            )}
          </Space>
        </Space>
      </Card>

      {chartData.length > 0 && (
        <>
          <Divider />
          <Card title="损失曲线">
            <Line
              data={chartData}
              xField="step"
              yField="loss"
              smooth
              color="#1890ff"
              height={300}
            />
          </Card>
        </>
      )}

      {job.state === 'completed' && metrics.length === 0 && (
        <>
          <Divider />
          <Alert
            message="无指标记录"
            description="训练已完成但未保存指标数据"
            type="info"
          />
        </>
      )}
    </div>
  );
};
