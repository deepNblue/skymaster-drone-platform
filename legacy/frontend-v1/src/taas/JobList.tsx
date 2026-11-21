/**
 * TaaS Fine-tune Job List page — SkyMaster v2.3 E6
 */
import React, { useState, useEffect } from 'react';
import {
  Card,
  Button,
  Space,
  Tag,
  Table,
  Modal,
  Form,
  Select,
  InputNumber,
  message,
  Popconfirm,
  Badge,
  Typography,
} from 'antd';
import {
  PlusOutlined,
  EyeOutlined,
  StopOutlined,
  CloudUploadOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import * as api from './api';
import type { FineTuneJob, CreateFineTuneRequest } from './types';

const { Text } = Typography;

const DATASET_TYPE_OPTIONS = [
  { label: '分类', value: 'classification' },
  { label: '目标检测', value: 'object-detection' },
  { label: '大语言模型', value: 'text-lm' },
  { label: '扩散模型', value: 'diffusion' },
];

const STATE_COLOR: Record<string, string> = {
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

export const JobList: React.FC = () => {
  const navigate = useNavigate();
  const [jobs, setJobs] = useState<FineTuneJob[]>([]);
  const [loading, setLoading] = useState(false);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [datasets, setDatasets] = useState<{ label: string; value: string }[]>([]);
  const [form] = Form.useForm<CreateFineTuneRequest>();

  const fetchJobs = async () => {
    setLoading(true);
    try {
      const data = await api.listMyJobs();
      setJobs(data);
    } catch (e) {
      message.error('加载任务列表失败');
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const fetchMyDatasets = async () => {
    try {
      const data = await api.listMyDatasets();
      const passed = data.filter(d => d.schemaValidation === 'passed');
      setDatasets(passed.map(d => ({ label: d.name, value: d.id })));
    } catch (e) {
      console.error('Failed to load datasets', e);
    }
  };

  useEffect(() => {
    fetchJobs();
    fetchMyDatasets();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleOpenCreate = () => {
    form.resetFields();
    form.setFieldsValue({
      num_epochs: 3,
      learning_rate: 5e-5,
      batch_size: 8,
      gradient_accumulation_steps: 1,
      lora_rank: 8,
    });
    setCreateModalOpen(true);
  };

  const handleCreate = async () => {
    try {
      const values = await form.validateFields();
      await api.createFineTuneJob(values);
      message.success('创建成功，已加入训练队列');
      setCreateModalOpen(false);
      fetchJobs();
    } catch (e) {
      message.error('创建失败');
      console.error(e);
    }
  };

  const handleCancel = async (id: string) => {
    try {
      await api.cancelJob(id);
      message.success('已取消');
      fetchJobs();
    } catch (e) {
      message.error('取消失败');
      console.error(e);
    }
  };

  const handlePublish = async (id: string) => {
    try {
      const res = await api.publishJobToMarketplace(id);
      message.success('发布成功到模型市场');
      fetchJobs();
      if (res.model_id) {
        navigate(`/model-marketplace/${res.model_id}`);
      }
    } catch (e) {
      message.error('发布失败');
      console.error(e);
    }
  };

  const formatVram = (bytes?: number) => {
    if (!bytes) return '-';
    const gb = bytes / (1024 ** 3);
    return `${gb.toFixed(1)} GB`;
  };

  const columns = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      render: (text: string, record: FineTuneJob) => (
        <Space>
          <Text strong>{text}</Text>
          {record.loraRank && <Tag color="blue">LoRA r={record.loraRank}</Tag>}
        </Space>
      ),
    },
    {
      title: '状态',
      dataIndex: 'state',
      key: 'state',
      render: (state: string) => (
        <Badge status={STATE_COLOR[state] as any} text={STATE_LABEL[state]} />
      ),
    },
    {
      title: 'Epochs',
      dataIndex: 'numEpochs',
      key: 'numEpochs',
      width: 80,
    },
    {
      title: 'LR',
      dataIndex: 'learningRate',
      key: 'learningRate',
      width: 100,
      render: (lr: number) => lr.toExponential(2),
    },
    {
      title: '已发布',
      dataIndex: 'publishedToMarketplace',
      key: 'publishedToMarketplace',
      render: (v: boolean) => v ? '是' : '否',
      width: 80,
    },
    {
      title: '费用',
      dataIndex: 'costCents',
      key: 'costCents',
      width: 80,
      render: (c?: number) => c ? `¥${(c / 100).toFixed(2)}` : '-',
    },
    {
      title: '操作',
      key: 'actions',
      width: 220,
      render: (_: any, record: FineTuneJob) => (
        <Space size="small">
          <Button
            size="small"
            icon={<EyeOutlined />}
            onClick={() => navigate(`/taas/jobs/${record.id}`)}
          >
            详情
          </Button>
          {['queued', 'scheduled', 'running'].includes(record.state) && (
            <Popconfirm
              title="确定取消此训练任务吗？"
              onConfirm={() => handleCancel(record.id)}
            >
              <Button size="small" danger icon={<StopOutlined />}>
                取消
              </Button>
            </Popconfirm>
          )}
          {record.state === 'completed' && !record.publishedToMarketplace && (
            <Button
              size="small"
              type="primary"
              icon={<CloudUploadOutlined />}
              onClick={() => handlePublish(record.id)}
            >
              发布
            </Button>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 16, maxWidth: 1200, margin: '0 auto' }}>
      <Space style={{ marginBottom: 16 }} direction="vertical" style={{ width: '100%' }}>
        <Space>
          <h1>一键微调训练</h1>
        </Space>
        <Space style={{ justifyContent: 'flex-end' }}>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={handleOpenCreate}
          >
            新建微调任务
          </Button>
        </Space>
      </Space>

      <Card>
        <Table
          loading={loading}
          dataSource={jobs}
          columns={columns}
          rowKey="id"
          pagination={{ pageSize: 10 }}
        />
      </Card>

      <Modal
        title="新建微调任务"
        open={createModalOpen}
        onCancel={() => setCreateModalOpen(false)}
        onOk={handleCreate}
        okText="创建并排队"
        width={600}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="name"
            label="任务名称"
            rules={[{ required: true, min: 3, max: 128 }]}
          >
            <Input placeholder="YOLOv8 电力线缺陷检测微调" />
          </Form.Item>
          <Form.Item
            name="datasetId"
            label="训练数据集"
            rules={[{ required: true }]}
          >
            <Select placeholder="选择已验证通过的数据集">
              {datasets.map(d => (
                <Select.Option key={d.value} value={d.value}>
                  {d.label}
                </Select.Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item
            name="baseModelId"
            label="基础模型（来自模型市场）"
          >
            <Select placeholder="可选，选择市场已有模型作为起点">
              {/* populated async in future */}
            </Select>
          </Form.Item>
          <Space direction="horizontal" size="large">
            <Form.Item
              name="num_epochs"
              label="训练轮次"
              rules={[{ required: true }]}
            >
              <InputNumber min={1} max={100} />
            </Form.Item>
            <Form.Item
              name="batch_size"
              label="Batch Size"
              rules={[{ required: true }]}
            >
              <InputNumber min={1} max={128} />
            </Form.Item>
            <Form.Item
              name="lora_rank"
              label="LoRA Rank"
              help="留空为全参数微调"
            >
              <InputNumber min={1} max={64} placeholder="8" />
            </Form.Item>
          </Space>
          <Form.Item
            name="learning_rate"
            label="学习率"
            rules={[{ required: true }]}
          >
            <InputNumber
              min={1e-7}
              max={1e-2}
              step={1e-5}
              precision={7}
            />
          </Form.Item>
          <Form.Item
            name="output_model_name"
            label="输出模型名称"
            help="发布到模型市场时显示"
          >
            <Input placeholder="我的模型" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};
