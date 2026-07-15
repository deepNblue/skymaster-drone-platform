'use client';

/**
 * Model Marketplace UI — v2.0 §3.16.
 * Path: /dashboard/model-marketplace
 *
 * Left:  filterable listings grid.
 * Right: deployments installed by my org.
 * Top:   create-listing drawer (owners) + refresh.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  Card,
  Col,
  Row,
  Space,
  Tag,
  Typography,
  Button,
  Input,
  Select,
  Drawer,
  Form,
  message,
  Spin,
  Empty,
  Table,
  Tooltip,
} from 'antd';
import {
  AppstoreOutlined,
  CloudDownloadOutlined,
  DollarOutlined,
  PlusOutlined,
  ReloadOutlined,
  StarFilled,
  StarOutlined,
  ThunderboltOutlined,
  UserOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  createModelListing,
  favoriteListing,
  listModelListings,
  listMyDeployments,
  listMyFavorites,
  ModelDeployment,
  ModelListing,
  PriceModel,
  unfavoriteListing,
} from '@/lib/model_marketplace';

const { Title, Text, Paragraph } = Typography;

const PRICE_LABEL: Record<PriceModel, string> = {
  free: '免费',
  per_call: '按次',
  per_frame: '按帧',
  per_token: '按token',
  per_month: '按月',
};

const TASK_OPTIONS = [
  { value: 'detection', label: '目标检测' },
  { value: 'segmentation', label: '语义分割' },
  { value: 'classification', label: '分类' },
  { value: 'tracking', label: '目标跟踪' },
  { value: 'depth', label: '深度估计' },
  { value: 'llm', label: '大模型' },
];

const FRAMEWORK_OPTIONS = [
  { value: 'onnx', label: 'ONNX' },
  { value: 'tensorrt', label: 'TensorRT' },
  { value: 'pytorch', label: 'PyTorch' },
  { value: 'tflite', label: 'TFLite' },
  { value: 'openvino', label: 'OpenVINO' },
];

export default function ModelMarketplacePage() {
  const router = useRouter();
  const [listings, setListings] = useState<ModelListing[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [task, setTask] = useState<string | undefined>();
  const [framework, setFramework] = useState<string | undefined>();
  const [tag, setTag] = useState<string | undefined>();

  const [deployments, setDeployments] = useState<ModelDeployment[]>([]);
  const [depLoading, setDepLoading] = useState(true);
  // T5.10 — favorites filter toggle
  const [favOnly, setFavOnly] = useState(false);
  const [busyFav, setBusyFav] = useState<string | null>(null);

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [form] = Form.useForm();

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      if (favOnly) {
        // T5.10 — dedicated favorites endpoint
        const rows = await listMyFavorites();
        setListings(rows);
        setTotal(rows.length);
      } else {
        const res = await listModelListings({ task, framework, tag, limit: 60 });
        setListings(res.items);
        setTotal(res.total);
      }
    } catch (e: any) {
      message.error(`加载失败: ${e?.response?.data?.detail ?? e.message}`);
    } finally {
      setLoading(false);
    }
  }, [task, framework, tag, favOnly]);

  const reloadDeps = useCallback(async () => {
    setDepLoading(true);
    try {
      setDeployments(await listMyDeployments());
    } catch (e: any) {
      // Don't error-toast for 401/403 — user might not be in an org.
    } finally {
      setDepLoading(false);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  useEffect(() => {
    reloadDeps();
  }, [reloadDeps]);

  const submit = async () => {
    try {
      const v = await form.validateFields();
      setSubmitting(true);
      await createModelListing({
        ...v,
        tags: v.tags
          ? v.tags.split(',').map((s: string) => s.trim()).filter(Boolean)
          : [],
      });
      message.success('模型已上架');
      form.resetFields();
      setDrawerOpen(false);
      reload();
    } catch (e: any) {
      if (e?.errorFields) return;
      message.error(`上架失败: ${e?.response?.data?.detail ?? e.message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const depColumns: ColumnsType<ModelDeployment> = [
    {
      title: '模型ID', dataIndex: 'listing_id',
      render: (v) => <Text code>{v.slice(0, 8)}</Text>,
    },
    { title: '版本', dataIndex: 'version_id', render: (v: string) => v.slice(0, 8) },
    {
      title: '状态', dataIndex: 'status',
      render: (s) => <Tag color="success">{s}</Tag>,
    },
    { title: '日配额', dataIndex: 'quota_calls_per_day', render: (v) => v ?? '无限' },
    { title: '安装于', dataIndex: 'installed_at',
      render: (t) => new Date(t).toLocaleDateString('zh-CN') },
    {
      title: '操作', key: 'ops', width: 120,
      render: (_, row) => (
        <Button
          size="small"
          onClick={() =>
            router.push(
              `/dashboard/model-marketplace/deployments/${row.id}/usage`,
            )
          }
        >
          用量
        </Button>
      ),
    },
  ];

  return (
    <div style={{ padding: 16 }}>
      <div style={{
        display: 'flex', justifyContent: 'space-between',
        alignItems: 'center', marginBottom: 12,
      }}>
        <Space direction="vertical" size={0}>
          <Title level={4} style={{ margin: 0 }}>
            <AppstoreOutlined /> 模型商店
          </Title>
          <Text type="secondary">
            上架 / 安装视觉与决策模型，管理调用配额和版本审核。
          </Text>
        </Space>
        <Space>
          <Button
            icon={favOnly ? <StarFilled style={{ color: '#faad14' }} /> : <StarOutlined />}
            type={favOnly ? 'primary' : 'default'}
            onClick={() => setFavOnly((v) => !v)}
          >
            {favOnly ? '仅收藏' : '收藏'}
          </Button>
          <Button icon={<ReloadOutlined />} onClick={reload}>
            刷新
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setDrawerOpen(true)}
          >
            上架模型
          </Button>
        </Space>
      </div>

      <Row gutter={12}>
        <Col span={16}>
          <Card size="small">
            <Space wrap style={{ marginBottom: 12 }}>
              <Select
                allowClear placeholder="任务类型" style={{ width: 140 }}
                options={TASK_OPTIONS}
                value={task} onChange={setTask}
              />
              <Select
                allowClear placeholder="框架" style={{ width: 140 }}
                options={FRAMEWORK_OPTIONS}
                value={framework} onChange={setFramework}
              />
              <Input.Search
                placeholder="标签过滤，如: drone"
                style={{ width: 180 }}
                allowClear
                onSearch={(v) => setTag(v || undefined)}
              />
              <Text type="secondary" style={{ fontSize: 12 }}>共 {total} 项</Text>
            </Space>

            {loading ? (
              <div style={{ textAlign: 'center', padding: 40 }}>
                <Spin />
              </div>
            ) : listings.length === 0 ? (
              <Empty description="暂无模型" />
            ) : (
              <Row gutter={[12, 12]}>
                {listings.map((l) => (
                  <Col span={12} key={l.id}>
                    <Card
                      hoverable size="small"
                      style={{ height: '100%' }}
                      onClick={() =>
                        router.push(`/dashboard/model-marketplace/${l.id}`)
                      }
                      extra={
                        // T5.10 — star button. stopPropagation so clicking
                        // the star doesn't navigate to the detail page.
                        <Button
                          size="small"
                          type="text"
                          loading={busyFav === l.id}
                          icon={
                            l.favorited_by_me ? (
                              <StarFilled style={{ color: '#faad14' }} />
                            ) : (
                              <StarOutlined />
                            )
                          }
                          onClick={async (e) => {
                            e.stopPropagation();
                            setBusyFav(l.id);
                            try {
                              if (l.favorited_by_me) {
                                await unfavoriteListing(l.id);
                                message.success('已取消收藏');
                              } else {
                                await favoriteListing(l.id);
                                message.success('已收藏');
                              }
                              setListings((rows) =>
                                rows.map((r) =>
                                  r.id === l.id
                                    ? { ...r, favorited_by_me: !r.favorited_by_me }
                                    : r,
                                ),
                              );
                            } catch (err: any) {
                              message.error(
                                `操作失败: ${err?.response?.data?.detail ?? err.message}`,
                              );
                            } finally {
                              setBusyFav(null);
                            }
                          }}
                        />
                      }
                    >
                      <Space direction="vertical" size={4} style={{ width: '100%' }}>
                        <Space wrap>
                          {l.is_featured && (
                            <Tag icon={<StarFilled />} color="gold">推荐</Tag>
                          )}
                          <Tag color="blue">
                            {TASK_OPTIONS.find((t) => t.value === l.task)?.label ?? l.task}
                          </Tag>
                          <Tag>{l.framework}</Tag>
                          {l.visibility === 'private' && (
                            <Tag color="red">私有</Tag>
                          )}
                          {l.visibility === 'org' && (
                            <Tag color="purple">仅本组织</Tag>
                          )}
                        </Space>
                        <Text strong style={{ fontSize: 14 }}>
                          {l.name}
                        </Text>
                        <Text
                          type="secondary"
                          style={{ fontSize: 12 }}
                          ellipsis={{ tooltip: l.description ?? '' }}
                        >
                          {l.description ?? '（无描述）'}
                        </Text>
                        <Space size={8} style={{ fontSize: 11, color: '#888' }}>
                          <Tooltip title="计费模式">
                            <span>
                              <DollarOutlined /> {PRICE_LABEL[l.price_model]}
                              {l.price_unit && l.price_model !== 'free' && (
                                <span>
                                  {' '}({l.price_unit} {l.currency})
                                </span>
                              )}
                            </span>
                          </Tooltip>
                          <span>
                            <UserOutlined /> {l.owner_user_id?.slice(0, 6) ?? '—'}
                          </span>
                          {/* T5.9 — popularity signal from backend aggregate */}
                          {typeof l.deployment_count === 'number' && (
                            <Tooltip title="激活部署数（installed + active）">
                              <span>
                                🚀 {l.deployment_count}
                              </span>
                            </Tooltip>
                          )}
                          {typeof l.version_count === 'number' && l.version_count > 0 && (
                            <Tooltip title="模型版本数">
                              <span>
                                v{l.version_count}
                              </span>
                            </Tooltip>
                          )}
                          {/* T5.11 — star rating rollup */}
                          {typeof l.review_count === 'number' && l.review_count > 0 && (
                            <Tooltip title={`${l.review_count} 条评价`}>
                              <span>
                                ⭐ {l.average_rating?.toFixed(1)}
                              </span>
                            </Tooltip>
                          )}
                          {(l.tags ?? []).slice(0, 3).map((t) => (
                            <span key={t}>#{t}</span>
                          ))}
                        </Space>
                      </Space>
                    </Card>
                  </Col>
                ))}
              </Row>
            )}
          </Card>
        </Col>

        <Col span={8}>
          <Card
            size="small"
            title={
              <Space>
                <CloudDownloadOutlined />
                <span>我的部署</span>
              </Space>
            }
            extra={
              <Button size="small" onClick={reloadDeps}>刷新</Button>
            }
          >
            <Table<ModelDeployment>
              dataSource={deployments}
              columns={depColumns}
              rowKey="id"
              size="small"
              pagination={false}
              loading={depLoading}
              locale={{ emptyText: '尚未安装模型' }}
              onRow={(r) => ({
                onClick: () =>
                  router.push(`/dashboard/model-marketplace/${r.listing_id}`),
                style: { cursor: 'pointer' },
              })}
            />
          </Card>

          <Card size="small" style={{ marginTop: 12 }}>
            <Space direction="vertical" size={6}>
              <Text strong>
                <ThunderboltOutlined /> 小贴士
              </Text>
              <Text type="secondary" style={{ fontSize: 12 }}>
                · 上架后需管理员审核方可对外可见<br />
                · 私有模型只对上架者可见<br />
                · 安装后可在部署详情设置日调用配额
              </Text>
            </Space>
          </Card>
        </Col>
      </Row>

      <Drawer
        title="上架新模型"
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        width={520}
        extra={
          <Button type="primary" loading={submitting} onClick={submit}>
            提交
          </Button>
        }
      >
        <Form form={form} layout="vertical" initialValues={{
          visibility: 'public', price_model: 'free',
          license: 'proprietary', currency: 'CNY',
        }}>
          <Form.Item
            name="slug" label="Slug（唯一标识）"
            rules={[
              { required: true },
              { pattern: /^[a-z0-9\-]+$/, message: '只允许小写字母、数字、-' },
            ]}
          >
            <Input placeholder="yolov8-drone" />
          </Form.Item>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input placeholder="YOLOv8 无人机检测" maxLength={128} />
          </Form.Item>
          <Form.Item name="description" label="简介">
            <Input.TextArea rows={3} placeholder="简单说明模型的用途、输入输出与限制" />
          </Form.Item>
          <Form.Item name="task" label="任务类型" rules={[{ required: true }]}>
            <Select options={TASK_OPTIONS} placeholder="选择任务类型" />
          </Form.Item>
          <Form.Item name="framework" label="框架" rules={[{ required: true }]}>
            <Select options={FRAMEWORK_OPTIONS} placeholder="选择部署框架" />
          </Form.Item>
          <Form.Item name="tags" label="标签" help="逗号分隔">
            <Input placeholder="drone, detection" />
          </Form.Item>
          <Form.Item name="visibility" label="可见性">
            <Select options={[
              { value: 'public', label: '公开' },
              { value: 'org', label: '仅本组织' },
              { value: 'private', label: '仅本人' },
            ]} />
          </Form.Item>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="price_model" label="计费模式">
                <Select options={[
                  { value: 'free', label: '免费' },
                  { value: 'per_call', label: '按次' },
                  { value: 'per_frame', label: '按帧' },
                  { value: 'per_token', label: '按token' },
                  { value: 'per_month', label: '按月' },
                ]} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="price_unit" label="单价 (可选)">
                <Input placeholder="如 0.001" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="license" label="许可证">
            <Input placeholder="apache-2 / mit / proprietary…" maxLength={32} />
          </Form.Item>
        </Form>
      </Drawer>
    </div>
  );
}
