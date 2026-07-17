'use client';

/**
 * v2.1 D2.2 · Scene annotation panel — table + stats + reply thread.
 *
 * A viewer-agnostic 2D UI for managing annotations on a 3DGS/4DGS scene.
 * The actual 3D pick + draw interactions live in Reality Studio viewer;
 * this panel exposes CRUD + filtering + status tracking.
 *
 * Route: /dashboard/scenes/[sid]/annotations
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import {
  Alert, Badge, Button, Card, Col, Descriptions, Empty, Form, Input,
  InputNumber, List, Modal, Row, Select, Space, Statistic, Switch, Table,
  Tag, Tooltip, Typography, message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  CheckCircleOutlined, CommentOutlined, DeleteOutlined, EditOutlined,
  PlusOutlined, ReloadOutlined,
} from '@ant-design/icons';

import {
  Annotation, AnnotationReply, AnnotationStats, GEOM_KIND_LABEL,
  GeomKind, SEVERITY_COLOR, SEVERITY_LABEL, Severity,
  createAnnotation, createReply, deleteAnnotation, getAnnotationStats,
  listAnnotations, listReplies, updateAnnotation,
} from '@/lib/scene_annotation';

const { Title, Paragraph, Text } = Typography;

const SEVERITIES: Severity[] = [
  'info', 'low', 'medium', 'high', 'critical',
];
const GEOM_KINDS: GeomKind[] = ['point', 'line', 'polygon', 'volume'];

export default function SceneAnnotationsPage() {
  const params = useParams<{ sid: string }>();
  const router = useRouter();
  const sid = params.sid;

  const [rows, setRows] = useState<Annotation[]>([]);
  const [stats, setStats] = useState<AnnotationStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [layerFilter, setLayerFilter] = useState<string>('');
  const [sevFilter, setSevFilter] = useState<Severity | undefined>();
  const [onlyUnresolved, setOnlyUnresolved] = useState(false);
  const [frameIndex, setFrameIndex] = useState<number | undefined>();

  const [editing, setEditing] = useState<Annotation | null>(null);
  const [creating, setCreating] = useState(false);
  const [form] = Form.useForm();

  const [replyOpen, setReplyOpen] = useState<Annotation | null>(null);
  const [replies, setReplies] = useState<AnnotationReply[]>([]);
  const [replyBody, setReplyBody] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [ann, st] = await Promise.all([
        listAnnotations(sid, {
          layer: layerFilter || undefined,
          severity: sevFilter,
          only_unresolved: onlyUnresolved,
          frame_index: frameIndex,
        }),
        getAnnotationStats(sid),
      ]);
      setRows(ann);
      setStats(st);
    } catch (e: any) {
      message.error(`加载失败: ${e?.message ?? e}`);
    } finally {
      setLoading(false);
    }
  }, [sid, layerFilter, sevFilter, onlyUnresolved, frameIndex]);

  useEffect(() => { void load(); }, [load]);

  const layers = useMemo(() => {
    const s = new Set(rows.map(r => r.layer).filter(Boolean));
    return Array.from(s).sort();
  }, [rows]);

  const openCreate = () => {
    setEditing(null);
    setCreating(true);
    form.resetFields();
    form.setFieldsValue({
      geom_kind: 'point',
      color: '#22d3ee',
      severity: 'info',
      layer: 'default',
      geom_vertices_json: '[[0, 0, 0]]',
    });
  };

  const openEdit = (row: Annotation) => {
    setEditing(row);
    setCreating(false);
    form.setFieldsValue({
      label: row.label,
      description: row.description ?? '',
      color: row.color,
      severity: row.severity,
      layer: row.layer,
      resolved: row.resolved,
    });
  };

  const closeModal = () => {
    setEditing(null);
    setCreating(false);
    form.resetFields();
  };

  const onSubmit = useCallback(async () => {
    let vals: any;
    try { vals = await form.validateFields(); } catch { return; }
    try {
      if (editing) {
        await updateAnnotation(editing.id, {
          label: vals.label,
          description: vals.description || null,
          color: vals.color,
          severity: vals.severity,
          layer: vals.layer,
          resolved: vals.resolved,
        });
        message.success('已更新');
      } else {
        let verts: number[][];
        try {
          verts = JSON.parse(vals.geom_vertices_json);
        } catch {
          message.error('顶点必须是 JSON 数组, 如 [[0,0,0],[1,0,0]]');
          return;
        }
        await createAnnotation(sid, {
          geom_kind: vals.geom_kind,
          geom_vertices: verts,
          label: vals.label,
          description: vals.description || null,
          color: vals.color,
          severity: vals.severity,
          layer: vals.layer,
          frame_index: vals.frame_index ?? null,
        });
        message.success('已创建');
      }
      closeModal();
      await load();
    } catch (e: any) {
      message.error(`保存失败: ${e?.message ?? e}`);
    }
  }, [form, editing, sid, load]);

  const onDelete = useCallback(async (row: Annotation) => {
    Modal.confirm({
      title: `删除标注 ${row.label}?`,
      content: '此操作不可撤销, 相关讨论回复一并删除.',
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        try {
          await deleteAnnotation(row.id);
          message.success('已删除');
          await load();
        } catch (e: any) {
          message.error(`删除失败: ${e?.message ?? e}`);
        }
      },
    });
  }, [load]);

  const openReplies = useCallback(async (row: Annotation) => {
    setReplyOpen(row);
    setReplyBody('');
    try {
      setReplies(await listReplies(row.id));
    } catch (e: any) {
      message.error(`加载讨论失败: ${e?.message ?? e}`);
    }
  }, []);

  const submitReply = useCallback(async () => {
    if (!replyOpen || !replyBody.trim()) return;
    try {
      await createReply(replyOpen.id, replyBody.trim());
      setReplyBody('');
      setReplies(await listReplies(replyOpen.id));
      message.success('已回复');
    } catch (e: any) {
      message.error(`回复失败: ${e?.message ?? e}`);
    }
  }, [replyOpen, replyBody]);

  const cols: ColumnsType<Annotation> = [
    {
      title: '状态', dataIndex: 'resolved', width: 68,
      render: (v: boolean) => v
        ? <Tag icon={<CheckCircleOutlined />} color="success">已整改</Tag>
        : <Badge status="processing" text="待处理" />,
    },
    {
      title: '标注', width: 200,
      render: (_: any, r: Annotation) => (
        <Space direction="vertical" size={0}>
          <Text strong>{r.label}</Text>
          {r.description && (
            <Text type="secondary" style={{ fontSize: 11 }}
              ellipsis={{ tooltip: r.description }}>
              {r.description}
            </Text>
          )}
        </Space>
      ),
    },
    {
      title: '类型', dataIndex: 'geom_kind', width: 80,
      render: (v: GeomKind, r: Annotation) => (
        <Tag color={r.color}>
          {GEOM_KIND_LABEL[v]}·{r.geometry_summary.n_vertices}
        </Tag>
      ),
    },
    {
      title: '度量', width: 140,
      render: (_: any, r: Annotation) => {
        const s = r.geometry_summary;
        if (s.length_m != null) {
          return <Text style={{ fontSize: 12 }}>
            长度 {s.length_m.toFixed(2)} m
          </Text>;
        }
        if (s.area_m2 != null) {
          return <Text style={{ fontSize: 12 }}>
            面积 {s.area_m2.toFixed(2)} m²
          </Text>;
        }
        if (s.footprint_area_m2 != null) {
          return <Text style={{ fontSize: 12 }}>
            底面 {s.footprint_area_m2.toFixed(2)} m²
          </Text>;
        }
        return <Text type="secondary">—</Text>;
      },
    },
    {
      title: '严重度', dataIndex: 'severity', width: 80,
      render: (v: Severity) => (
        <Tag color={SEVERITY_COLOR[v]}>{SEVERITY_LABEL[v]}</Tag>
      ),
    },
    {
      title: '图层', dataIndex: 'layer', width: 90,
      render: (v: string) => <Tag>{v}</Tag>,
    },
    {
      title: '帧', dataIndex: 'frame_index', width: 60, align: 'right',
      render: (v: number | null) => v == null
        ? <Text type="secondary">静态</Text>
        : `#${v}`,
    },
    {
      title: '操作', width: 190, fixed: 'right',
      render: (_: any, r: Annotation) => (
        <Space size={4}>
          <Tooltip title="讨论">
            <Button size="small" icon={<CommentOutlined />}
              onClick={() => void openReplies(r)}
            />
          </Tooltip>
          <Tooltip title="编辑">
            <Button size="small" icon={<EditOutlined />}
              onClick={() => openEdit(r)}
            />
          </Tooltip>
          <Tooltip title="删除">
            <Button size="small" danger icon={<DeleteOutlined />}
              onClick={() => void onDelete(r)}
            />
          </Tooltip>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 16 }}>
      <Space style={{ marginBottom: 8 }}>
        <Button onClick={() => router.back()}>← 返回</Button>
        <Title level={4} style={{ margin: 0 }}>
          场景标注 · Scene Annotations
        </Title>
      </Space>
      <Paragraph type="secondary">
        场景 <Text code>{sid}</Text> 的标注列表。支持
        点/线/面/体四种几何类型，可关联 4DGS 帧编号或作为静态标注。
      </Paragraph>

      {stats && (
        <Card size="small" style={{ marginBottom: 12 }}>
          <Row gutter={16}>
            <Col span={4}>
              <Statistic title="总标注" value={stats.total} />
            </Col>
            <Col span={4}>
              <Statistic
                title="未整改"
                value={stats.unresolved}
                valueStyle={{
                  color: stats.unresolved > 0 ? '#cf1322' : '#3f8600',
                }}
              />
            </Col>
            {SEVERITIES.map((s) => (
              <Col span={3} key={s}>
                <Statistic
                  title={SEVERITY_LABEL[s]}
                  value={stats.by_severity[s]}
                />
              </Col>
            ))}
          </Row>
        </Card>
      )}

      <Space style={{ marginBottom: 8 }} wrap>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          新增标注
        </Button>
        <Button icon={<ReloadOutlined />} onClick={() => void load()}>
          刷新
        </Button>
        <Text type="secondary">图层:</Text>
        <Select
          allowClear placeholder="全部"
          style={{ width: 140 }}
          value={layerFilter || undefined}
          onChange={(v) => setLayerFilter(v ?? '')}
          options={layers.map(l => ({ value: l, label: l }))}
        />
        <Text type="secondary">严重度:</Text>
        <Select
          allowClear placeholder="全部"
          style={{ width: 100 }}
          value={sevFilter}
          onChange={setSevFilter}
          options={SEVERITIES.map(s => ({
            value: s, label: SEVERITY_LABEL[s],
          }))}
        />
        <Text type="secondary">帧#:</Text>
        <InputNumber
          min={0} style={{ width: 80 }}
          placeholder="all"
          value={frameIndex}
          onChange={(v) => setFrameIndex(v ?? undefined)}
        />
        <Text type="secondary">仅未整改</Text>
        <Switch checked={onlyUnresolved}
          onChange={setOnlyUnresolved} size="small" />
      </Space>

      <Card size="small" bodyStyle={{ padding: 4 }}>
        <Table<Annotation>
          rowKey="id"
          columns={cols}
          dataSource={rows}
          loading={loading}
          size="small"
          pagination={{ pageSize: 20, showSizeChanger: false }}
          scroll={{ x: 1000 }}
          locale={{ emptyText: <Empty description="暂无标注" /> }}
        />
      </Card>

      {/* Create / Edit Modal */}
      <Modal
        title={editing ? `编辑 · ${editing.label}` : '新增标注'}
        open={editing !== null || creating}
        onCancel={closeModal}
        onOk={onSubmit}
        okText="保存"
        cancelText="取消"
        width={640}
      >
        <Form form={form} layout="vertical">
          {!editing && (
            <>
              <Form.Item name="geom_kind" label="几何类型"
                rules={[{ required: true }]}>
                <Select
                  options={GEOM_KINDS.map(k => ({
                    value: k, label: `${GEOM_KIND_LABEL[k]} (${k})`,
                  }))}
                />
              </Form.Item>
              <Form.Item name="geom_vertices_json"
                label="顶点数组 (JSON, 本地 ENU 米制)"
                rules={[{ required: true }]}
                help='格式: [[x,y,z], [x,y,z], ...]'>
                <Input.TextArea rows={3}
                  placeholder='[[0,0,0], [3,4,0]]' />
              </Form.Item>
              <Form.Item name="frame_index"
                label="帧编号 (4DGS 场景, 留空=静态)">
                <InputNumber min={0} style={{ width: '100%' }} />
              </Form.Item>
            </>
          )}

          <Form.Item name="label" label="标签"
            rules={[{ required: true, min: 1, max: 200 }]}>
            <Input placeholder="缺陷点1 / 裂缝A / 淤积区" />
          </Form.Item>
          <Form.Item name="description" label="描述 (可选)">
            <Input.TextArea rows={2} />
          </Form.Item>

          <Space.Compact block>
            <Form.Item name="severity" label="严重度"
              rules={[{ required: true }]}
              style={{ flex: 1 }}>
              <Select options={SEVERITIES.map(s => ({
                value: s, label: SEVERITY_LABEL[s],
              }))} />
            </Form.Item>
            <Form.Item name="layer" label="图层"
              rules={[{ required: true }]}
              style={{ flex: 1, marginLeft: 8 }}>
              <Input placeholder="default / defect / sensor" />
            </Form.Item>
            <Form.Item name="color" label="颜色"
              style={{ flex: 1, marginLeft: 8 }}>
              <Input placeholder="#22d3ee" />
            </Form.Item>
          </Space.Compact>

          {editing && (
            <Form.Item name="resolved" label="已整改"
              valuePropName="checked">
              <Switch />
            </Form.Item>
          )}
        </Form>
      </Modal>

      {/* Reply thread Modal */}
      <Modal
        title={
          replyOpen
            ? <>讨论 · <Text style={{ marginLeft: 4 }}>{replyOpen.label}</Text></>
            : '讨论'
        }
        open={replyOpen !== null}
        onCancel={() => { setReplyOpen(null); setReplyBody(''); setReplies([]); }}
        footer={null}
        width={600}
      >
        {replyOpen && (
          <>
            <Descriptions size="small" bordered column={2}
              style={{ marginBottom: 12 }}>
              <Descriptions.Item label="类型">
                {GEOM_KIND_LABEL[replyOpen.geom_kind]}
              </Descriptions.Item>
              <Descriptions.Item label="严重度">
                <Tag color={SEVERITY_COLOR[replyOpen.severity]}>
                  {SEVERITY_LABEL[replyOpen.severity]}
                </Tag>
              </Descriptions.Item>
            </Descriptions>
            {replies.length === 0 ? (
              <Empty description="暂无讨论" style={{ marginBottom: 12 }} />
            ) : (
              <List
                size="small"
                bordered
                dataSource={replies}
                style={{ marginBottom: 12 }}
                renderItem={(r) => (
                  <List.Item>
                    <Space direction="vertical" size={0}
                      style={{ width: '100%' }}>
                      <Text style={{ fontSize: 11 }} type="secondary">
                        {new Date(r.created_at).toLocaleString('zh-CN')}
                      </Text>
                      <Text>{r.body}</Text>
                    </Space>
                  </List.Item>
                )}
              />
            )}
            <Space.Compact style={{ width: '100%' }}>
              <Input
                placeholder="补充说明 / 整改进展 / 现场核查结论"
                value={replyBody}
                onChange={(e) => setReplyBody(e.target.value)}
                onPressEnter={() => void submitReply()}
              />
              <Button type="primary"
                disabled={!replyBody.trim()}
                onClick={() => void submitReply()}
              >回复</Button>
            </Space.Compact>
          </>
        )}
      </Modal>
    </div>
  );
}
