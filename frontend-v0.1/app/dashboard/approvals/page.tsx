'use client';

import React, { useEffect, useState } from 'react';
import {
  Card, Table, Button, Tag, Space, Typography, Modal, Form, Input,
  InputNumber, DatePicker, Select, message, Alert, Descriptions, Timeline,
  Popconfirm, Divider, List,
} from 'antd';
import {
  PlusOutlined, SendOutlined, CheckCircleOutlined, CloseCircleOutlined,
  RocketOutlined, ClockCircleOutlined, StopOutlined, ReloadOutlined,
  SafetyCertificateOutlined, FilePdfOutlined, QrcodeOutlined,
  RobotOutlined, ThunderboltOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import {
  listApprovals, getApproval, createApproval, submitApproval,
  previewRouting, decideAuthority, cancelApproval, markApprovalFlown,
  preflightCheck, type FlightApproval, type PreflightResult,
  batchSubmitApprovals, secondApproveApproval,
  attachSignature, listSignatures, sha256Hex,
  approvalCertificatePdfUrl, verifyApproval,
  dispatchRpa, pollRpaJob,
  type ApprovalSignature, type RPAJobOut,
} from '@/lib/api';

const { Title, Text } = Typography;
const { RangePicker } = DatePicker;

const STATUS_COLOR: Record<string, string> = {
  draft: 'default',
  submitted: 'processing',
  pending_second_approval: 'warning',
  in_review: 'processing',
  approved: 'success',
  rejected: 'error',
  flown: 'purple',
  archived: 'default',
  cancelled: 'default',
};

const STATUS_LABEL: Record<string, string> = {
  draft: '草稿',
  submitted: '已提交',
  pending_second_approval: '待二次审核',
  in_review: '审批中',
  approved: '已批准',
  rejected: '已驳回',
  flown: '已飞行',
  archived: '归档',
  cancelled: '已取消',
};

const AUTHORITY_STATUS_COLOR: Record<string, string> = {
  pending: 'default',
  submitted: 'processing',
  accepted: 'blue',
  approving: 'processing',
  approved: 'success',
  rejected: 'error',
  skipped: 'default',
};

export default function ApprovalsPage() {
  const [rows, setRows] = useState<FlightApproval[]>([]);
  const [loading, setLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [detail, setDetail] = useState<FlightApproval | null>(null);
  const [selected, setSelected] = useState<React.Key[]>([]);
  const [batching, setBatching] = useState(false);
  const [signatures, setSignatures] = useState<ApprovalSignature[]>([]);
  const [signBusy, setSignBusy] = useState(false);
  const [preflight, setPreflight] = useState<PreflightResult | null>(null);
  const [form] = Form.useForm();

  const load = async () => {
    setLoading(true);
    try {
      setRows(await listApprovals());
    } catch (e: any) {
      message.error('加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const loadDetail = async (id: string) => {
    setDetailId(id);
    setPreflight(null);
    setDetail(await getApproval(id));
    try {
      setSignatures(await listSignatures(id));
    } catch {
      setSignatures([]);
    }
  };

  const onCreate = async (values: any) => {
    try {
      const [start, end] = values.time_window || [];
      const poly: number[][] = [];
      if (values.polygon_text) {
        try {
          const parsed = JSON.parse(values.polygon_text);
          if (Array.isArray(parsed)) poly.push(...parsed);
        } catch { /* ignore */ }
      }
      await createApproval({
        title: values.title,
        purpose: values.purpose,
        category: values.category,
        pilot_name: values.pilot_name,
        pilot_license: values.pilot_license,
        aircraft_reg: values.aircraft_reg,
        aircraft_model: values.aircraft_model,
        insurance_no: values.insurance_no,
        max_alt_m: values.max_alt_m,
        area_polygon: poly.length ? poly : undefined,
        start_ts: start ? start.toISOString() : undefined,
        end_ts: end ? end.toISOString() : undefined,
      });
      message.success('已创建草稿');
      setCreateOpen(false);
      form.resetFields();
      load();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '创建失败');
    }
  };

  const onSubmit = async (id: string) => {
    try {
      await submitApproval(id);
      message.success('已提交至相关主管部门');
      load();
      if (detailId === id) loadDetail(id);
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '提交失败');
    }
  };

  const onDecide = async (code: string, decision: 'approved' | 'rejected') => {
    if (!detailId) return;
    let reason: string | undefined;
    if (decision === 'rejected') {
      reason = window.prompt('驳回原因（会写入 timeline）：') || undefined;
    }
    try {
      await decideAuthority(detailId, code, decision,
        `DEMO-${code.toUpperCase()}-${Date.now()}`, reason);
      message.success(`${code} → ${decision}`);
      loadDetail(detailId);
      load();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '操作失败');
    }
  };

  const onCancel = async (id: string) => {
    try {
      await cancelApproval(id);
      message.success('已取消');
      load();
      if (detailId === id) loadDetail(id);
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '取消失败');
    }
  };

  const onMarkFlown = async (id: string) => {
    try {
      await markApprovalFlown(id);
      message.success('已标记为已飞行');
      load();
      if (detailId === id) loadDetail(id);
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '操作失败');
    }
  };

  const onPreflight = async () => {
    if (!detailId) return;
    try {
      const res = await preflightCheck(detailId, true, undefined);
      setPreflight(res);
    } catch (e: any) {
      message.error('预检失败');
    }
  };

  const columns = [
    { title: '标题', dataIndex: 'title', ellipsis: true },
    {
      title: '类别', dataIndex: 'category', width: 80,
      render: (c: string) => <Tag>{c}</Tag>,
    },
    {
      title: '状态', dataIndex: 'status', width: 100,
      render: (s: string) => (
        <Tag color={STATUS_COLOR[s] || 'default'}>{STATUS_LABEL[s] || s}</Tag>
      ),
    },
    { title: '飞手', dataIndex: 'pilot_name', width: 120, ellipsis: true },
    {
      title: '最大高度', dataIndex: 'max_alt_m', width: 100,
      render: (v: number) => (v != null ? `${v} m` : '—'),
    },
    {
      title: '主管数', dataIndex: 'authorities', width: 90,
      render: (a: any[]) => a?.length ?? 0,
    },
    {
      title: '创建时间', dataIndex: 'created_at', width: 160,
      render: (t: string) => dayjs(t).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '操作', width: 260,
      render: (_: any, r: FlightApproval) => (
        <Space>
          <Button size="small" onClick={() => loadDetail(r.id)}>详情</Button>
          {r.status === 'draft' && (
            <Popconfirm title="提交至相关主管部门？" onConfirm={() => onSubmit(r.id)}>
              <Button size="small" type="primary" icon={<SendOutlined />}>
                提交
              </Button>
            </Popconfirm>
          )}
          {r.status === 'approved' && (
            <Button size="small" onClick={() => onMarkFlown(r.id)}
              icon={<RocketOutlined />}>已飞</Button>
          )}
          {!['flown', 'archived', 'cancelled'].includes(r.status) && (
            <Popconfirm title="取消该报备？" onConfirm={() => onCancel(r.id)}>
              <Button size="small" danger icon={<StopOutlined />}>取消</Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <div>
            <Title level={3}>
              <SafetyCertificateOutlined /> 飞行报备（一站式多头审批）
            </Title>
            <Text type="secondary">
              一份报备 · 平台按空域/属地/机型自动拆分至民航局 UOM、属地公安、空管、市监等主管部门
            </Text>
          </div>
          <Space>
            <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
            <Button
              icon={<SendOutlined />}
              loading={batching}
              disabled={selected.length === 0}
              onClick={async () => {
                setBatching(true);
                try {
                  const res = await batchSubmitApprovals(
                    selected.map((s) => String(s)),
                  );
                  message.success(
                    `批量提交: ${res.submitted} 成功 / ${res.held_for_second_approval} 待二次审核 / ${res.failed} 失败`,
                  );
                  setSelected([]);
                  load();
                } catch (e: any) {
                  message.error(`批量提交失败: ${e?.response?.data?.detail ?? e.message}`);
                } finally {
                  setBatching(false);
                }
              }}
            >
              批量提交 {selected.length > 0 && `(${selected.length})`}
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
              新建报备
            </Button>
          </Space>
        </div>

        <Card>
          <Table
            rowKey="id"
            columns={columns as any}
            dataSource={rows}
            loading={loading}
            pagination={{ pageSize: 20 }}
            size="small"
            rowSelection={{
              selectedRowKeys: selected,
              onChange: setSelected,
              getCheckboxProps: (r: FlightApproval) => ({
                disabled: r.status !== 'draft',
              }),
            }}
          />
        </Card>
      </Space>

      {/* 新建 Modal */}
      <Modal
        title="🛰️ 新建飞行报备"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        footer={null}
        width={720}
        destroyOnClose
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="填一次表 → 平台自动路由至相关主管部门 → 状态汇总回执"
        />
        <Form
          form={form}
          layout="vertical"
          onFinish={onCreate}
          initialValues={{ category: 'routine' }}
        >
          <Form.Item label="任务标题" name="title" rules={[{ required: true }]}>
            <Input placeholder="如：南宁市良庆区输电线路巡检" />
          </Form.Item>
          <Space size="middle" style={{ width: '100%' }}>
            <Form.Item label="作业性质" name="purpose" style={{ flex: 1, minWidth: 200 }}>
              <Select
                placeholder="选择或输入"
                options={[
                  { label: '航拍', value: '航拍' },
                  { label: '巡检', value: '巡检' },
                  { label: '农业作业', value: '农业作业' },
                  { label: '警务', value: '警务' },
                  { label: '应急救援', value: '应急救援' },
                  { label: '测绘', value: '测绘' },
                  { label: '文旅表演', value: '文旅表演' },
                ]}
                allowClear
              />
            </Form.Item>
            <Form.Item label="类别" name="category" style={{ minWidth: 140 }}>
              <Select options={[
                { label: '常规', value: 'routine' },
                { label: '特殊', value: 'special' },
                { label: '应急', value: 'emergency' },
              ]} />
            </Form.Item>
          </Space>
          <Space size="middle" style={{ width: '100%' }}>
            <Form.Item label="飞手姓名" name="pilot_name" style={{ flex: 1, minWidth: 180 }}>
              <Input />
            </Form.Item>
            <Form.Item label="飞手执照号" name="pilot_license" style={{ flex: 1, minWidth: 180 }}>
              <Input placeholder="CAAC-UAS-2026-xxxx" />
            </Form.Item>
          </Space>
          <Space size="middle" style={{ width: '100%' }}>
            <Form.Item label="无人机注册号" name="aircraft_reg" style={{ flex: 1, minWidth: 180 }}>
              <Input placeholder="UAS-CN-xxxxx" />
            </Form.Item>
            <Form.Item label="机型" name="aircraft_model" style={{ flex: 1, minWidth: 180 }}>
              <Input placeholder="DJI Mavic 3E" />
            </Form.Item>
          </Space>
          <Space size="middle" style={{ width: '100%' }}>
            <Form.Item label="保险单号" name="insurance_no" style={{ flex: 1, minWidth: 180 }}>
              <Input />
            </Form.Item>
            <Form.Item label="最大高度 (m)" name="max_alt_m" style={{ minWidth: 140 }}>
              <InputNumber min={0} max={1000} style={{ width: '100%' }} />
            </Form.Item>
          </Space>
          <Form.Item label="飞行时间窗" name="time_window" rules={[{ required: true }]}>
            <RangePicker showTime style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            label="飞行区域多边形 (JSON, [[lng,lat],...])"
            name="polygon_text"
            tooltip="留空则不做地理路由；示例：[[108.30,22.70],[108.35,22.70],[108.35,22.75],[108.30,22.75]]"
          >
            <Input.TextArea rows={3} placeholder="[[108.30,22.70],[108.35,22.70],[108.35,22.75],[108.30,22.75]]" />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0 }}>
            <Space>
              <Button type="primary" htmlType="submit">保存草稿</Button>
              <Button onClick={() => setCreateOpen(false)}>取消</Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      {/* 详情 Drawer/Modal */}
      <Modal
        title={detail ? `📋 ${detail.title}` : '详情'}
        open={detailId !== null}
        onCancel={() => { setDetailId(null); setDetail(null); setPreflight(null); }}
        footer={null}
        width={860}
        destroyOnClose
      >
        {detail && (
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            <Descriptions bordered size="small" column={2}>
              <Descriptions.Item label="状态">
                <Tag color={STATUS_COLOR[detail.status]}>
                  {STATUS_LABEL[detail.status]}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="类别">{detail.category}</Descriptions.Item>
              <Descriptions.Item label="飞手">{detail.pilot_name || '—'}</Descriptions.Item>
              <Descriptions.Item label="执照号">{detail.pilot_license || '—'}</Descriptions.Item>
              <Descriptions.Item label="无人机注册号">{detail.aircraft_reg || '—'}</Descriptions.Item>
              <Descriptions.Item label="机型">{detail.aircraft_model || '—'}</Descriptions.Item>
              <Descriptions.Item label="保险">{detail.insurance_no || '—'}</Descriptions.Item>
              <Descriptions.Item label="最大高度">
                {detail.max_alt_m != null ? `${detail.max_alt_m} m` : '—'}
              </Descriptions.Item>
              <Descriptions.Item label="时间窗" span={2}>
                {detail.start_ts ? dayjs(detail.start_ts).format('YYYY-MM-DD HH:mm') : '—'}
                {' ~ '}
                {detail.end_ts ? dayjs(detail.end_ts).format('YYYY-MM-DD HH:mm') : '—'}
              </Descriptions.Item>
              {detail.requires_second_approval && (
                <Descriptions.Item label="二次审核" span={2}>
                  {detail.second_approved_at ? (
                    <Tag color="success">
                      已由 {detail.second_approver_id?.slice(0, 8) ?? '监督人'} 批准 ·{' '}
                      {dayjs(detail.second_approved_at).format('MM-DD HH:mm')}
                    </Tag>
                  ) : (
                    <Tag color="warning">等待监督人签署</Tag>
                  )}
                </Descriptions.Item>
              )}
              {detail.reject_reason && (
                <Descriptions.Item label="驳回原因" span={2}>
                  <Text type="danger">{detail.reject_reason}</Text>
                </Descriptions.Item>
              )}
            </Descriptions>

            {detail.status === 'pending_second_approval' && (
              <Card size="small" style={{ background: '#fffbe6' }}>
                <Space direction="vertical" style={{ width: '100%' }}>
                  <Text strong>⚠ 高风险报备 · 需监督人二次审核</Text>
                  <Space>
                    <Popconfirm
                      title="确认批准并向主管扇出？"
                      onConfirm={async () => {
                        try {
                          await secondApproveApproval(detail.id, 'approve');
                          message.success('已批准，主管路由已提交');
                          const d = await getApproval(detail.id);
                          setDetail(d);
                          load();
                        } catch (e: any) {
                          message.error(
                            `${e?.response?.status === 403 ? '仅监督人/管理员可操作' : e.message}`,
                          );
                        }
                      }}
                    >
                      <Button type="primary" icon={<CheckCircleOutlined />}>
                        批准二次审核
                      </Button>
                    </Popconfirm>
                    <Popconfirm
                      title="驳回并退回草稿？"
                      onConfirm={async () => {
                        try {
                          await secondApproveApproval(detail.id, 'reject');
                          message.success('已驳回，退回草稿');
                          const d = await getApproval(detail.id);
                          setDetail(d);
                          load();
                        } catch (e: any) {
                          message.error(e.message);
                        }
                      }}
                    >
                      <Button danger icon={<CloseCircleOutlined />}>
                        驳回
                      </Button>
                    </Popconfirm>
                  </Space>
                </Space>
              </Card>
            )}

            <Divider style={{ margin: 0 }}>各主管审批状态</Divider>
            <List
              size="small"
              dataSource={detail.authorities}
              locale={{ emptyText: '尚未提交，无主管路由' }}
              renderItem={(a) => {
                const rpaJobId = (a.extra as any)?.rpa_job_id as string | undefined;
                const isRpa = a.channel === 'rpa';
                const canDispatch = isRpa && !['approved', 'rejected', 'skipped', 'cancelled'].includes(a.status);
                return (
                <List.Item
                  actions={[
                    ...(detail.status === 'in_review' &&
                    !['approved', 'rejected', 'skipped'].includes(a.status)
                      ? [
                          <Button
                            key="approve"
                            size="small"
                            type="link"
                            icon={<CheckCircleOutlined />}
                            onClick={() => onDecide(a.authority_code, 'approved')}
                          >通过</Button>,
                          <Button
                            key="reject"
                            size="small"
                            type="link"
                            danger
                            icon={<CloseCircleOutlined />}
                            onClick={() => onDecide(a.authority_code, 'rejected')}
                          >驳回</Button>,
                        ]
                      : []),
                    ...(canDispatch
                      ? [
                          <Button
                            key="rpa"
                            size="small"
                            type="link"
                            icon={<RobotOutlined />}
                            onClick={async () => {
                              try {
                                const j = await dispatchRpa(detail.id, a.authority_code);
                                message.success(
                                  `RPA 派发 ${j.driver} · 状态=${j.status}${j.external_ref ? ' · ref=' + j.external_ref : ''}`,
                                );
                                await loadDetail(detail.id);
                              } catch (e: any) {
                                message.error('RPA 派发失败: ' + (e?.response?.data?.detail ?? e.message));
                              }
                            }}
                          >派发 RPA</Button>,
                          rpaJobId ? (
                            <Button
                              key="poll"
                              size="small"
                              type="link"
                              icon={<ThunderboltOutlined />}
                              onClick={async () => {
                                try {
                                  const j = await pollRpaJob(rpaJobId!);
                                  message.info(
                                    `job=${j.job_id.slice(0,10)}… 状态=${j.status} poll#${j.poll_count}`,
                                  );
                                  await loadDetail(detail.id);
                                } catch (e: any) {
                                  message.error('轮询失败: ' + (e?.response?.data?.detail ?? e.message));
                                }
                              }}
                            >轮询</Button>
                          ) : null,
                        ].filter(Boolean) as any[]
                      : []),
                  ]}
                >
                  <Space wrap>
                    <Tag>P{a.priority}</Tag>
                    <span>{a.authority_name}</span>
                    <Tag color={AUTHORITY_STATUS_COLOR[a.status] || 'default'}>
                      {a.status}
                    </Tag>
                    <Tag>{a.channel}</Tag>
                    {isRpa && rpaJobId && (
                      <Tag color="geekblue" icon={<RobotOutlined />}>
                        RPA job {rpaJobId.slice(0, 8)}…
                      </Tag>
                    )}
                    {a.external_ref && (
                      <Text type="secondary" style={{ fontSize: 12 }}>{a.external_ref}</Text>
                    )}
                    {a.reject_reason && (
                      <Text type="danger" style={{ fontSize: 12 }}>{a.reject_reason}</Text>
                    )}
                  </Space>
                </List.Item>
              );}}
            />

            <Divider style={{ margin: 0 }}>
              <SafetyCertificateOutlined /> 起飞前预检
            </Divider>
            <Space>
              <Button onClick={onPreflight} icon={<SafetyCertificateOutlined />}>
                运行预检（Remote ID 已开）
              </Button>
              {preflight && (
                preflight.blocking ? (
                  <Tag color="error" icon={<CloseCircleOutlined />}>
                    禁止起飞 · {preflight.fail_count} 项失败
                  </Tag>
                ) : (
                  <Tag color="success" icon={<CheckCircleOutlined />}>
                    允许起飞（警告 {preflight.warn_count}）
                  </Tag>
                )
              )}
            </Space>
            {preflight && (
              <List
                size="small"
                bordered
                dataSource={preflight.items}
                renderItem={(i) => (
                  <List.Item>
                    <Space>
                      {i.severity === 'pass' && <Tag color="success">✓</Tag>}
                      {i.severity === 'warn' && <Tag color="warning">!</Tag>}
                      {i.severity === 'fail' && <Tag color="error">✗</Tag>}
                      <b>{i.name}</b>
                      <Text type="secondary">{i.detail}</Text>
                    </Space>
                  </List.Item>
                )}
              />
            )}

            <Divider style={{ margin: 0 }}>
              <SafetyCertificateOutlined /> 电子签署
            </Divider>
            <Space direction="vertical" size="small" style={{ width: '100%' }}>
              <Space wrap>
                <Button
                  size="small"
                  icon={<FilePdfOutlined />}
                  onClick={() => {
                    window.open(approvalCertificatePdfUrl(detail.id), '_blank');
                  }}
                >
                  下载证书 PDF
                </Button>
                <Button
                  size="small"
                  icon={<QrcodeOutlined />}
                  onClick={async () => {
                    try {
                      const v = await verifyApproval(detail.id);
                      Modal.info({
                        title: '在线核验快照 (QR verify)',
                        width: 640,
                        content: (
                          <pre style={{
                            maxHeight: 400, overflow: 'auto',
                            fontSize: 12, background: '#fafafa', padding: 8,
                          }}>
                            {JSON.stringify(v, null, 2)}
                          </pre>
                        ),
                      });
                    } catch (e: any) {
                      message.error('核验失败: ' + (e?.message ?? e));
                    }
                  }}
                >
                  在线核验
                </Button>
                <Button
                  size="small"
                  icon={<SafetyCertificateOutlined />}
                  loading={signBusy}
                  onClick={async () => {
                    if (!detail) return;
                    setSignBusy(true);
                    try {
                      const payload = JSON.stringify({
                        id: detail.id,
                        title: detail.title,
                        status: detail.status,
                        polygon: detail.area_polygon,
                        max_alt_m: detail.max_alt_m,
                        start_ts: detail.start_ts,
                        end_ts: detail.end_ts,
                      });
                      const sha = await sha256Hex(payload);
                      await attachSignature(detail.id, sha, {
                        note: '当前详情视图快照',
                      });
                      message.success('签署成功');
                      setSignatures(await listSignatures(detail.id));
                    } catch (e: any) {
                      message.error(`签署失败: ${e.message}`);
                    } finally {
                      setSignBusy(false);
                    }
                  }}
                >
                  签署当前详情快照
                </Button>
                <Button
                  size="small"
                  onClick={async () => {
                    if (!detail) return;
                    setSignatures(await listSignatures(detail.id));
                  }}
                >
                  刷新签署记录
                </Button>
              </Space>
              {signatures.length === 0 ? (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  暂无签署记录
                </Text>
              ) : (
                <List
                  size="small"
                  dataSource={signatures}
                  renderItem={(s) => (
                    <List.Item>
                      <Space direction="vertical" size={0} style={{ width: '100%' }}>
                        <Space>
                          <Tag color="blue">{s.algorithm}</Tag>
                          <Text code style={{ fontSize: 11 }}>
                            {s.payload_sha256.slice(0, 16)}…
                          </Text>
                          {s.authority_code && (
                            <Tag>{s.authority_code}</Tag>
                          )}
                        </Space>
                        <Text type="secondary" style={{ fontSize: 11 }}>
                          {s.signer_role ?? 'user'} · {s.signer_user_id.slice(0, 8)}… ·{' '}
                          {dayjs(s.signed_at).format('YYYY-MM-DD HH:mm:ss')}
                          {s.note && ` · ${s.note}`}
                        </Text>
                      </Space>
                    </List.Item>
                  )}
                />
              )}
            </Space>

            <Divider style={{ margin: 0 }}>
              <ClockCircleOutlined /> 时间线
            </Divider>
            <Timeline
              items={(detail.timeline || []).map((e: any) => ({
                children: (
                  <div>
                    <div><b>{e.action}</b> · {e.actor}</div>
                    <div style={{ color: '#8b949e', fontSize: 12 }}>
                      {dayjs(e.ts).format('YYYY-MM-DD HH:mm:ss')}
                      {e.note && ` · ${e.note}`}
                    </div>
                  </div>
                ),
              }))}
            />
          </Space>
        )}
      </Modal>
    </div>
  );
}
