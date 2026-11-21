'use client';

import React, { useEffect, useState } from 'react';
import {
  Card, Space, Typography, Button, Table, Tag, Modal, Form, Input,
  message, Descriptions, Steps, Alert, Empty, Popconfirm,
} from 'antd';
import {
  PlusOutlined, ReloadOutlined, ThunderboltOutlined,
  RollbackOutlined, InboxOutlined, RocketOutlined,
} from '@ant-design/icons';
import Link from 'next/link';
import {
  listScenes, createScene, sceneAction,
  type Scene, type SceneStatus, type SceneCreate,
} from '@/lib/api';

const { Title, Text, Paragraph } = Typography;

const STATUS_COLOR: Record<SceneStatus, string> = {
  draft: 'default',
  ingesting: 'processing',
  ingested: 'cyan',
  colmap: 'processing',
  colmap_done: 'cyan',
  training: 'processing',
  ready: 'green',
  failed: 'red',
  archived: 'default',
};

const STATUS_LABEL: Record<SceneStatus, string> = {
  draft: '草稿',
  ingesting: '上传中',
  ingested: '待处理',
  colmap: 'COLMAP 中',
  colmap_done: 'COLMAP 完成',
  training: '训练中',
  ready: '就绪',
  failed: '失败',
  archived: '已归档',
};

const PIPELINE_STEPS: SceneStatus[] = [
  'draft', 'ingested', 'colmap_done', 'ready',
];

function _stepIndex(status: SceneStatus): number {
  if (status === 'failed') return -1;
  if (status === 'archived') return PIPELINE_STEPS.length;
  if (status === 'ingesting') return 0;
  if (status === 'colmap') return 1;
  if (status === 'training') return 2;
  return PIPELINE_STEPS.indexOf(status);
}

export default function ScenesPage() {
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [form] = Form.useForm<SceneCreate>();
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const r = await listScenes();
      setScenes(r.scenes);
    } catch (e: any) {
      message.error(`加载场景列表失败：${e?.response?.data?.detail ?? e?.message ?? e}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const handleCreate = async () => {
    try {
      const values = await form.validateFields();
      const scene = await createScene(values);
      message.success(`场景 ${scene.name} 已创建`);
      setModalOpen(false);
      form.resetFields();
      load();
    } catch (e: any) {
      if (e?.errorFields) return;
      message.error(`创建失败：${e?.response?.data?.detail ?? e?.message ?? e}`);
    }
  };

  const doAction = async (
    id: string,
    action: 'ingest' | 'colmap' | 'train' | 'reset' | 'archive',
  ) => {
    setBusyId(id);
    try {
      await sceneAction(id, action);
      message.success(`${action} 已执行`);
      load();
    } catch (e: any) {
      message.error(`${action} 失败：${e?.response?.data?.detail ?? e?.message ?? e}`);
    } finally {
      setBusyId(null);
    }
  };

  const columns = [
    {
      title: '名称', dataIndex: 'name', width: 220,
      render: (v: string, row: Scene) => (
        <Link href={`/dashboard/scenes/${row.id}`}>
          <Text strong>{v}</Text>
          {row.description && (
            <div><Text type="secondary" style={{ fontSize: 12 }}>{row.description}</Text></div>
          )}
        </Link>
      ),
    },
    {
      title: '状态', dataIndex: 'status', width: 130,
      render: (s: SceneStatus) => <Tag color={STATUS_COLOR[s]}>{STATUS_LABEL[s]}</Tag>,
    },
    {
      title: '源图数', dataIndex: 'n_source_images', width: 100,
    },
    {
      title: '点数', dataIndex: 'n_points', width: 110,
      render: (v: number | null) => v == null ? '—' : v.toLocaleString(),
    },
    {
      title: 'Gaussians', dataIndex: 'n_gaussians', width: 130,
      render: (v: number | null) => v == null ? '—' : v.toLocaleString(),
    },
    {
      title: 'PSNR', dataIndex: 'psnr_train', width: 90,
      render: (v: number | null) => v == null ? '—' : `${v.toFixed(1)} dB`,
    },
    {
      title: '操作', key: 'ops', width: 320,
      render: (_: unknown, row: Scene) => {
        const busy = busyId === row.id;
        const buttons: React.ReactNode[] = [];
        if (row.status === 'draft') {
          buttons.push(
            <Button key="ingest" size="small" icon={<InboxOutlined />}
                    loading={busy}
                    onClick={() => doAction(row.id, 'ingest')}>
              开始摄入
            </Button>,
          );
        }
        if (row.status === 'ingested') {
          buttons.push(
            <Button key="colmap" size="small" type="primary"
                    icon={<ThunderboltOutlined />}
                    loading={busy}
                    onClick={() => doAction(row.id, 'colmap')}>
              运行 COLMAP
            </Button>,
          );
        }
        if (row.status === 'colmap_done') {
          buttons.push(
            <Button key="train" size="small" type="primary"
                    icon={<RocketOutlined />}
                    loading={busy}
                    onClick={() => doAction(row.id, 'train')}>
              训练 3DGS
            </Button>,
          );
        }
        if (row.status === 'failed') {
          buttons.push(
            <Button key="reset" size="small" icon={<RollbackOutlined />}
                    loading={busy}
                    onClick={() => doAction(row.id, 'reset')}>
              重置
            </Button>,
          );
        }
        if (row.status !== 'archived') {
          buttons.push(
            <Popconfirm key="archive"
                        title="归档后不可再运行流水线，确认？"
                        onConfirm={() => doAction(row.id, 'archive')}>
              <Button size="small" danger>归档</Button>
            </Popconfirm>,
          );
        }
        return <Space wrap>{buttons}</Space>;
      },
    },
  ];

  return (
    <div style={{ padding: 24, maxWidth: 1400 }}>
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>
            <ThunderboltOutlined /> 3DGS Reality Studio · 场景管理
          </Title>
          <Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
            将无人机采集的图像/视频通过 COLMAP 结构还原 → Gaussian Splatting 训练，
            输出可导出的 <code>.ply</code>/<code>.splat</code> 三维模型。政务/测绘/应急客户核心能力。
          </Paragraph>
        </div>

        <Card
          extra={
            <Space>
              <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>
                刷新
              </Button>
              <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>
                新建场景
              </Button>
            </Space>
          }
          title={<>📦 场景列表（{scenes.length}）</>}
        >
          {scenes.length === 0 ? (
            <Empty description="暂无场景 · 点击右上『新建场景』开始" />
          ) : (
            <Table
              rowKey="id"
              size="small"
              dataSource={scenes}
              columns={columns}
              pagination={false}
              expandable={{
                expandedRowRender: (row) => (
                  <Space direction="vertical" style={{ width: '100%' }}>
                    <Steps
                      size="small"
                      status={row.status === 'failed' ? 'error' : undefined}
                      current={_stepIndex(row.status)}
                      items={[
                        { title: '草稿' },
                        { title: '摄入完成' },
                        { title: 'COLMAP 完成' },
                        { title: '3DGS 就绪' },
                      ]}
                    />
                    {row.error_msg && (
                      <Alert type="error" showIcon message="流水线错误"
                             description={row.error_msg} />
                    )}
                    <Descriptions column={4} size="small" bordered>
                      <Descriptions.Item label="坐标系">
                        {row.coord_system || '—'}
                      </Descriptions.Item>
                      <Descriptions.Item label="源图数">
                        {row.n_source_images}
                      </Descriptions.Item>
                      <Descriptions.Item label="资源数">
                        {row.assets.length}
                      </Descriptions.Item>
                      <Descriptions.Item label="ID">
                        <Text code style={{ fontSize: 10 }}>{row.id.slice(0, 8)}</Text>
                      </Descriptions.Item>
                    </Descriptions>
                  </Space>
                ),
              }}
            />
          )}
        </Card>
      </Space>

      <Modal
        title="新建 3DGS 场景"
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={handleCreate}
        okText="创建"
        cancelText="取消"
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="name"
            label="场景名称"
            rules={[{ required: true, min: 1, max: 120 }]}
          >
            <Input placeholder="例：xxx 校园西区" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea placeholder="用途 / 采集范围 / 备注" rows={3} />
          </Form.Item>
          <Form.Item name="coord_system" label="坐标系">
            <Input placeholder="WGS84 / local ENU / 相对坐标" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
