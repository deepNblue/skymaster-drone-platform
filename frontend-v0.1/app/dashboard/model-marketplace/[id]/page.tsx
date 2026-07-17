'use client';

/**
 * Model listing detail — versions + install action.
 * Path: /dashboard/model-marketplace/[id]
 */
import React, { useCallback, useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import {
  Card, Space, Tag, Typography, Button, Table, Modal, Form, Input,
  InputNumber, message, Spin, Divider, Alert, Empty,
} from 'antd';
import {
  ArrowLeftOutlined, CheckOutlined, CloseOutlined, CloudDownloadOutlined,
  PlusOutlined, StarFilled,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  createModelVersion, getModelListing, installModelVersion,
  listModelVersions, listSimilarListings,
  ModelListing, ModelVersion, reviewModelVersion,
} from '@/lib/model_marketplace';
import { getMe } from '@/lib/api';

const { Title, Text, Paragraph } = Typography;

const STATUS_TAG = {
  approved: { color: 'success', label: '已通过' },
  pending: { color: 'processing', label: '待审' },
  rejected: { color: 'error', label: '已拒绝' },
  withdrawn: { color: 'default', label: '已撤回' },
} as const;

export default function ModelListingDetailPage() {
  const params = useParams();
  const router = useRouter();
  const lid = params?.id as string;

  const [listing, setListing] = useState<ModelListing | null>(null);
  const [versions, setVersions] = useState<ModelVersion[]>([]);
  // T5.14 — 'people also viewed' recommendations
  const [similar, setSimilar] = useState<ModelListing[]>([]);
  const [loading, setLoading] = useState(true);
  const [me, setMe] = useState<any | null>(null);

  const [pushOpen, setPushOpen] = useState(false);
  const [pushForm] = Form.useForm();
  const [pushing, setPushing] = useState(false);

  const [installTarget, setInstallTarget] = useState<ModelVersion | null>(null);
  const [installQuota, setInstallQuota] = useState<number | undefined>();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [l, vs, u] = await Promise.all([
        getModelListing(lid),
        listModelVersions(lid),
        getMe().catch(() => null),
      ]);
      setListing(l);
      setVersions(vs);
      setMe(u);
      // T5.14 — best-effort; a slow /similar shouldn't block the page
      listSimilarListings(lid, 6).then(setSimilar).catch(() => setSimilar([]));
    } catch (e: any) {
      message.error(`加载失败: ${e?.response?.data?.detail ?? e.message}`);
    } finally {
      setLoading(false);
    }
  }, [lid]);

  useEffect(() => {
    if (lid) load();
  }, [lid, load]);

  const isOwner = !!(
    me && listing &&
    (me.id === listing.owner_user_id ||
      (me.org_id && listing.owner_org_id === me.org_id))
  );
  const isAdmin = me?.role === 'admin';

  const push = async () => {
    try {
      const v = await pushForm.validateFields();
      setPushing(true);
      await createModelVersion(lid, {
        version: v.version,
        artifact_uri: v.artifact_uri,
        artifact_sha256: v.artifact_sha256,
        size_bytes: v.size_bytes ?? null,
        hardware: v.hardware
          ? v.hardware.split(',').map((s: string) => s.trim()).filter(Boolean)
          : [],
      });
      message.success('版本已提交，等待审核');
      pushForm.resetFields();
      setPushOpen(false);
      load();
    } catch (e: any) {
      if (e?.errorFields) return;
      message.error(`提交失败: ${e?.response?.data?.detail ?? e.message}`);
    } finally {
      setPushing(false);
    }
  };

  const review = async (v: ModelVersion, action: 'approve' | 'reject') => {
    try {
      await reviewModelVersion(v.id, action);
      message.success(action === 'approve' ? '已通过' : '已拒绝');
      load();
    } catch (e: any) {
      message.error(`操作失败: ${e?.response?.data?.detail ?? e.message}`);
    }
  };

  const doInstall = async () => {
    if (!installTarget) return;
    try {
      await installModelVersion(installTarget.id, {
        quota_calls_per_day: installQuota,
      });
      message.success('已安装到本组织');
      setInstallTarget(null);
      setInstallQuota(undefined);
      load();
    } catch (e: any) {
      message.error(`安装失败: ${e?.response?.data?.detail ?? e.message}`);
    }
  };

  if (loading) {
    return (
      <div style={{ padding: 40, textAlign: 'center' }}>
        <Spin />
      </div>
    );
  }
  if (!listing) {
    return (
      <div style={{ padding: 40, textAlign: 'center' }}>
        <Text type="secondary">模型不存在或无权访问</Text>
        <br />
        <Button
          type="link"
          onClick={() => router.push('/dashboard/model-marketplace')}
        >
          返回商店
        </Button>
      </div>
    );
  }

  const columns: ColumnsType<ModelVersion> = [
    {
      title: '版本', dataIndex: 'version',
      render: (v) => <Text strong>{v}</Text>,
    },
    {
      title: '状态', dataIndex: 'review_status',
      render: (s: keyof typeof STATUS_TAG) => (
        <Tag color={STATUS_TAG[s].color}>{STATUS_TAG[s].label}</Tag>
      ),
    },
    {
      title: '大小',
      dataIndex: 'size_bytes',
      render: (b) =>
        b ? `${(b / 1024 / 1024).toFixed(1)} MB` : '—',
    },
    {
      title: '硬件要求',
      dataIndex: 'hardware',
      render: (hw: string[] | null) =>
        (hw ?? []).map((h) => (
          <Tag key={h} style={{ marginBottom: 2 }}>{h}</Tag>
        )),
    },
    {
      title: '提交时间',
      dataIndex: 'created_at',
      render: (t) => new Date(t).toLocaleString('zh-CN'),
    },
    {
      title: '操作',
      key: 'act',
      render: (_, v) => (
        <Space size={4}>
          {v.review_status === 'approved' && (
            <Button
              size="small"
              type="primary"
              icon={<CloudDownloadOutlined />}
              onClick={() => setInstallTarget(v)}
            >
              安装
            </Button>
          )}
          {isAdmin && v.review_status === 'pending' && (
            <>
              <Button size="small" icon={<CheckOutlined />}
                onClick={() => review(v, 'approve')}>通过</Button>
              <Button size="small" danger icon={<CloseOutlined />}
                onClick={() => review(v, 'reject')}>拒绝</Button>
            </>
          )}
          {(isOwner || isAdmin) && v.review_status !== 'approved' && (
            <Button
              size="small" icon={<CloudDownloadOutlined />}
              onClick={() => setInstallTarget(v)}
            >
              内部安装
            </Button>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 16, maxWidth: 1100, margin: '0 auto' }}>
      <Button
        type="link"
        icon={<ArrowLeftOutlined />}
        style={{ paddingLeft: 0, marginBottom: 8 }}
        onClick={() => router.push('/dashboard/model-marketplace')}
      >
        返回商店
      </Button>

      <Card>
        <Space wrap style={{ marginBottom: 8 }}>
          {listing.is_featured && <Tag icon={<StarFilled />} color="gold">推荐</Tag>}
          <Tag color="blue">{listing.task}</Tag>
          <Tag>{listing.framework}</Tag>
          {listing.visibility === 'private' && <Tag color="red">私有</Tag>}
          {listing.visibility === 'org' && <Tag color="purple">仅本组织</Tag>}
          {(listing.tags ?? []).map((t) => (
            <Tag key={t}>#{t}</Tag>
          ))}
        </Space>
        <Title level={3} style={{ marginBottom: 4 }}>{listing.name}</Title>
        <Text type="secondary" style={{ fontSize: 12 }}>
          slug: <Text code>{listing.slug}</Text> · 许可证: {listing.license} ·
          {' '}计费: {listing.price_model}
          {listing.price_unit && listing.price_model !== 'free' &&
            <> ({listing.price_unit} {listing.currency})</>}
        </Text>
        {listing.description && (
          <Paragraph style={{ marginTop: 12, whiteSpace: 'pre-wrap' }}>
            {listing.description}
          </Paragraph>
        )}

        <Divider />

        <Space style={{ marginBottom: 12 }}>
          {(isOwner || isAdmin) && (
            <Button
              type="primary" icon={<PlusOutlined />}
              onClick={() => setPushOpen(true)}
            >
              发布新版本
            </Button>
          )}
        </Space>

        {versions.length === 0 ? (
          <Empty description="还没有版本" />
        ) : (
          <Table<ModelVersion>
            dataSource={versions}
            columns={columns}
            rowKey="id"
            size="small"
            pagination={false}
          />
        )}
      </Card>

      {/* T5.14 — 'people also viewed' section */}
      {similar.length > 0 && (
        <Card
          size="small"
          title="🔗 相似模型"
          style={{ marginTop: 16 }}
          extra={
            <Text type="secondary" style={{ fontSize: 12 }}>
              基于任务、框架和标签相似度推荐
            </Text>
          }
        >
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
            gap: 12,
          }}>
            {similar.map((s) => (
              <Card
                key={s.id}
                size="small"
                hoverable
                onClick={() => window.location.assign(
                  `/dashboard/model-marketplace/${s.id}`,
                )}
                style={{ cursor: 'pointer' }}
              >
                <div style={{ fontWeight: 500, marginBottom: 4 }}>
                  {s.name}
                </div>
                <div style={{ fontSize: 12, color: '#8c8c8c', marginBottom: 6 }}>
                  {s.task} · {s.framework}
                </div>
                <Space size="small">
                  {typeof s.deployment_count === 'number' && s.deployment_count > 0 && (
                    <span style={{ fontSize: 12 }}>🚀 {s.deployment_count}</span>
                  )}
                  {typeof s.review_count === 'number' && s.review_count > 0 && (
                    <span style={{ fontSize: 12 }}>
                      ⭐ {s.average_rating?.toFixed(1)}
                    </span>
                  )}
                </Space>
              </Card>
            ))}
          </div>
        </Card>
      )}

      <Modal
        open={pushOpen}
        title="发布新版本"
        okText="提交审核"
        cancelText="取消"
        confirmLoading={pushing}
        onOk={push}
        onCancel={() => setPushOpen(false)}
      >
        <Form form={pushForm} layout="vertical">
          <Form.Item name="version" label="版本号"
            rules={[{ required: true }]}>
            <Input placeholder="1.0.0" maxLength={32} />
          </Form.Item>
          <Form.Item name="artifact_uri" label="制品 URI"
            rules={[{ required: true }]}>
            <Input placeholder="s3://bucket/path/model.onnx" />
          </Form.Item>
          <Form.Item name="artifact_sha256" label="SHA256"
            rules={[
              { required: true },
              { len: 64, message: '必须是 64 位 hex' },
            ]}>
            <Input placeholder="a1b2c3…（64 位）" />
          </Form.Item>
          <Form.Item name="size_bytes" label="大小 (字节)">
            <InputNumber
              style={{ width: '100%' }}
              placeholder="可选，如 12345678"
            />
          </Form.Item>
          <Form.Item name="hardware" label="硬件要求"
            help="逗号分隔，如: cuda>=11.8, vram>=8gb">
            <Input placeholder="cuda>=11.8, vram>=8gb" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        open={!!installTarget}
        title={`安装 ${listing.name} @ ${installTarget?.version ?? ''}`}
        okText="确认安装"
        onOk={doInstall}
        onCancel={() => setInstallTarget(null)}
      >
        {installTarget?.review_status !== 'approved' && (
          <Alert
            type="warning" showIcon style={{ marginBottom: 12 }}
            message="该版本尚未通过审核，将以内部测试身份安装（仅上架者/管理员可用）"
          />
        )}
        <Text type="secondary">
          设置日调用配额（可选，超额将返回 429）
        </Text>
        <InputNumber
          style={{ width: '100%', marginTop: 8 }}
          placeholder="留空表示无限"
          min={1}
          value={installQuota}
          onChange={(v) => setInstallQuota(v ?? undefined)}
        />
      </Modal>
    </div>
  );
}
