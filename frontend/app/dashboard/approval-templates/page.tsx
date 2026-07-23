'use client';

/**
 * E2.5 · Approval Template dashboard page.
 *
 * Simple 2-column layout — list on the left, edit/apply on the right.
 * We deliberately keep the polygon picker out for now (Roadmap says
 * v2.1 will add MapDraw); polygons live as raw JSON here.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import {
  Button, Card, DatePicker, Empty, Form, Input, InputNumber, Modal,
  Popconfirm, Select, Space, Tag, Typography, message,
} from 'antd';
import {
  ArrowLeftOutlined, DeleteOutlined, EditOutlined, PlayCircleOutlined,
  PlusOutlined, ReloadOutlined,
} from '@ant-design/icons';
import dayjs, { Dayjs } from 'dayjs';

import {
  ApplyPayload, ApprovalCategory, ApprovalTemplate,
  applyApprovalTemplate, createApprovalTemplate, deleteApprovalTemplate,
  listApprovalTemplates, updateApprovalTemplate,
} from '@/lib/approval_templates';

const { Title, Text, Paragraph } = Typography;

const CATEGORY_LABELS: Record<ApprovalCategory, string> = {
  routine: '常规',
  high_altitude: '高空',
  night: '夜航',
  sensitive_area: '敏感区',
  emergency: '应急',
};

function CategoryTag({ c }: { c: ApprovalCategory }) {
  const color = ({
    routine: 'blue', high_altitude: 'purple', night: 'geekblue',
    sensitive_area: 'red', emergency: 'orange',
  } as const)[c];
  return <Tag color={color}>{CATEGORY_LABELS[c]}</Tag>;
}

export default function ApprovalTemplatesPage() {
  const [rows, setRows] = useState<ApprovalTemplate[]>([]);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<ApprovalTemplate | null>(null);

  // Editor modal.
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form] = Form.useForm();

  // Apply modal.
  const [applyOpen, setApplyOpen] = useState(false);
  const [applyForm] = Form.useForm();

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listApprovalTemplates();
      setRows(data);
      if (selected && !data.find((t) => t.id === selected.id)) {
        setSelected(null);
      }
    } catch (e: any) {
      message.error(`加载失败: ${e?.message ?? e}`);
    } finally {
      setLoading(false);
    }
  }, [selected]);

  useEffect(() => { void reload(); }, []); // eslint-disable-line

  const openCreate = () => {
    setEditingId(null);
    form.resetFields();
    form.setFieldsValue({ category: 'routine' });
    setEditorOpen(true);
  };

  const openEdit = (t: ApprovalTemplate) => {
    setEditingId(t.id);
    form.setFieldsValue({
      ...t,
      // Convert list fields to JSON string for the textarea.
      default_area_polygon: t.default_area_polygon
        ? JSON.stringify(t.default_area_polygon) : '',
      authorities_preset: JSON.stringify(t.authorities_preset, null, 2),
      checklist_json: JSON.stringify(t.checklist_json, null, 2),
    });
    setEditorOpen(true);
  };

  const submitEditor = useCallback(async () => {
    let vals: any;
    try { vals = await form.validateFields(); } catch { return; }

    // Parse the free-form JSON fields.
    let polygon: number[][] | null = null;
    if (vals.default_area_polygon?.trim()) {
      try { polygon = JSON.parse(vals.default_area_polygon); }
      catch (e: any) {
        message.error(`polygon JSON 解析失败: ${e?.message ?? e}`);
        return;
      }
    }
    let preset: any[] = [];
    if (vals.authorities_preset?.trim()) {
      try { preset = JSON.parse(vals.authorities_preset); }
      catch (e: any) {
        message.error(`authorities_preset JSON 解析失败: ${e?.message ?? e}`);
        return;
      }
    }
    let checklist: any[] = [];
    if (vals.checklist_json?.trim()) {
      try { checklist = JSON.parse(vals.checklist_json); }
      catch (e: any) {
        message.error(`checklist_json JSON 解析失败: ${e?.message ?? e}`);
        return;
      }
    }

    const payload = {
      name: vals.name,
      category: vals.category as ApprovalCategory,
      purpose: vals.purpose ?? null,
      pilot_name: vals.pilot_name ?? null,
      pilot_license: vals.pilot_license ?? null,
      aircraft_reg: vals.aircraft_reg ?? null,
      aircraft_model: vals.aircraft_model ?? null,
      insurance_no: vals.insurance_no ?? null,
      max_alt_m: vals.max_alt_m ?? null,
      min_alt_m: vals.min_alt_m ?? null,
      default_area_polygon: polygon,
      authorities_preset: preset,
      checklist_json: checklist,
    };

    try {
      if (editingId) {
        await updateApprovalTemplate(editingId, payload);
        message.success('已更新');
      } else {
        await createApprovalTemplate(payload);
        message.success('已创建');
      }
      setEditorOpen(false);
      await reload();
    } catch (e: any) {
      message.error(`保存失败: ${e?.message ?? e}`);
    }
  }, [editingId, form, reload]);

  const doDelete = useCallback(async (id: string) => {
    try {
      await deleteApprovalTemplate(id);
      message.success('已删除');
      setSelected(null);
      await reload();
    } catch (e: any) {
      message.error(`删除失败: ${e?.message ?? e}`);
    }
  }, [reload]);

  const openApply = (t: ApprovalTemplate) => {
    applyForm.resetFields();
    applyForm.setFieldsValue({
      title: `${t.name} · ${dayjs().format('YYYY-MM-DD')}`,
      range: [dayjs(), dayjs().add(2, 'hour')],
    });
    setApplyOpen(true);
  };

  const submitApply = useCallback(async () => {
    if (!selected) return;
    let vals: any;
    try { vals = await applyForm.validateFields(); } catch { return; }
    const [start, end] = vals.range as [Dayjs, Dayjs];
    let overrideP: number[][] | null = null;
    if (vals.area_polygon_override?.trim()) {
      try { overrideP = JSON.parse(vals.area_polygon_override); }
      catch (e: any) {
        message.error(`polygon override 解析失败: ${e?.message ?? e}`);
        return;
      }
    }
    const payload: ApplyPayload = {
      title: vals.title,
      start_ts: start.toISOString(),
      end_ts: end.toISOString(),
      area_polygon_override: overrideP,
      max_alt_m_override: vals.max_alt_m_override ?? null,
      min_alt_m_override: vals.min_alt_m_override ?? null,
    };
    try {
      const res = await applyApprovalTemplate(selected.id, payload);
      message.success(`已创建报备草稿 ${res.approval_id.slice(0, 8)}…`);
      setApplyOpen(false);
      await reload();
    } catch (e: any) {
      message.error(`创建失败: ${e?.message ?? e}`);
    }
  }, [selected, applyForm, reload]);

  return (
    <div style={{ padding: 16 }}>
      <div style={{ marginBottom: 12 }}>
        <Space>
          <Link href="/dashboard/approvals">
            <Button size="small" icon={<ArrowLeftOutlined />}>
              返回报备列表
            </Button>
          </Link>
          <Title level={4} style={{ margin: 0 }}>
            合规报备模板
          </Title>
        </Space>
        <Paragraph type="secondary" style={{ marginTop: 4 }}>
          存一次填多次 — 巡线/测绘/警务 常态化飞行的报备表单模板。
          一键 apply 生成 flight_approval 草稿, 走现有审批流。
        </Paragraph>
      </div>

      <Space
        style={{ marginBottom: 8, width: '100%', justifyContent: 'flex-end' }}
      >
        <Button size="small" icon={<ReloadOutlined />} onClick={() => void reload()}>
          刷新
        </Button>
        <Button type="primary" size="small" icon={<PlusOutlined />} onClick={openCreate}>
          新建模板
        </Button>
      </Space>

      <div style={{ display: 'flex', gap: 12 }}>
        <Card size="small" style={{ width: 360 }}
          bodyStyle={{ padding: 4, maxHeight: 620, overflowY: 'auto' }}>
          {rows.length === 0 && !loading ? (
            <Empty description="还没有模板" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          ) : rows.map((t) => (
            <div
              key={t.id}
              onClick={() => setSelected(t)}
              style={{
                padding: 8, borderRadius: 4, cursor: 'pointer',
                background: selected?.id === t.id
                  ? 'rgba(24, 144, 255, 0.08)' : 'transparent',
                borderLeft: selected?.id === t.id
                  ? '3px solid #1890ff' : '3px solid transparent',
                marginBottom: 2,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <Text strong>{t.name}</Text>
                <CategoryTag c={t.category} />
              </div>
              <div>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  <PlayCircleOutlined /> apply {t.apply_count} 次
                  {' · '}
                  {t.pilot_name ?? '未设置 pilot'}
                </Text>
              </div>
            </div>
          ))}
        </Card>

        <Card size="small" style={{ flex: 1 }}>
          {selected === null ? (
            <Empty description="从左侧选择一个模板" />
          ) : (
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <div>
                  <Title level={5} style={{ margin: 0 }}>
                    {selected.name} <CategoryTag c={selected.category} />
                  </Title>
                  <Text type="secondary">
                    apply {selected.apply_count} 次 · {selected.purpose ?? '(未填 purpose)'}
                  </Text>
                </div>
                <Space>
                  <Button
                    type="primary"
                    icon={<PlayCircleOutlined />}
                    onClick={() => openApply(selected)}
                  >
                    应用 · 新建报备草稿
                  </Button>
                  <Button icon={<EditOutlined />} onClick={() => openEdit(selected)}>
                    编辑
                  </Button>
                  <Popconfirm title="确认删除?" onConfirm={() => void doDelete(selected.id)}>
                    <Button danger icon={<DeleteOutlined />}>删除</Button>
                  </Popconfirm>
                </Space>
              </div>

              <div style={{ marginTop: 12 }}>
                <Title level={5}>飞行员/机身</Title>
                <ul style={{ marginTop: 4, paddingLeft: 20 }}>
                  <li>Pilot: {selected.pilot_name ?? '—'} / 执照: {selected.pilot_license ?? '—'}</li>
                  <li>机身: {selected.aircraft_reg ?? '—'} ({selected.aircraft_model ?? '—'})</li>
                  <li>保险: {selected.insurance_no ?? '—'}</li>
                  <li>飞行高度: {selected.min_alt_m ?? '—'} ~ {selected.max_alt_m ?? '—'} m</li>
                </ul>

                <Title level={5}>主管部门通道</Title>
                {selected.authorities_preset.length === 0 ? (
                  <Text type="secondary">(未预置)</Text>
                ) : (
                  <ul style={{ marginTop: 4, paddingLeft: 20 }}>
                    {selected.authorities_preset.map((a, i) => (
                      <li key={i}>
                        <Tag>{a.code}</Tag>
                        {a.name}
                        {a.channel ? <Tag color="cyan" style={{ marginLeft: 4 }}>{a.channel}</Tag> : null}
                        {a.priority != null && <Text type="secondary"> · 优先级 {a.priority}</Text>}
                      </li>
                    ))}
                  </ul>
                )}

                <Title level={5}>起飞前 Checklist</Title>
                {selected.checklist_json.length === 0 ? (
                  <Text type="secondary">(未设置)</Text>
                ) : (
                  <ul style={{ marginTop: 4, paddingLeft: 20 }}>
                    {selected.checklist_json.map((c) => (
                      <li key={c.id}>{c.text}</li>
                    ))}
                  </ul>
                )}

                {selected.default_area_polygon && (
                  <>
                    <Title level={5}>默认作业面 (polygon)</Title>
                    <pre style={{ background: '#f1f5f9', padding: 8, fontSize: 11 }}>
                      {JSON.stringify(selected.default_area_polygon)}
                    </pre>
                  </>
                )}
              </div>
            </div>
          )}
        </Card>
      </div>

      {/* Editor modal */}
      <Modal
        title={editingId ? '编辑模板' : '新建模板'}
        open={editorOpen}
        onCancel={() => setEditorOpen(false)}
        onOk={submitEditor}
        okText="保存"
        cancelText="取消"
        width={720}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="模板名" rules={[{ required: true, max: 120 }]}>
            <Input placeholder="巡线-乡道 / 测绘-A标段" />
          </Form.Item>
          <Form.Item name="category" label="分类" rules={[{ required: true }]}>
            <Select options={Object.entries(CATEGORY_LABELS).map(([v, l]) => ({ value: v, label: l }))} />
          </Form.Item>
          <Form.Item name="purpose" label="Purpose (作业目的)">
            <Input placeholder="农村配电线路巡检" />
          </Form.Item>

          <div style={{ display: 'flex', gap: 8 }}>
            <Form.Item name="pilot_name" label="Pilot 姓名" style={{ flex: 1 }}>
              <Input />
            </Form.Item>
            <Form.Item name="pilot_license" label="执照号" style={{ flex: 1 }}>
              <Input />
            </Form.Item>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <Form.Item name="aircraft_reg" label="机身编号" style={{ flex: 1 }}>
              <Input />
            </Form.Item>
            <Form.Item name="aircraft_model" label="型号" style={{ flex: 1 }}>
              <Input />
            </Form.Item>
            <Form.Item name="insurance_no" label="保险号" style={{ flex: 1 }}>
              <Input />
            </Form.Item>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <Form.Item name="min_alt_m" label="最低高度 (m)" style={{ flex: 1 }}>
              <InputNumber style={{ width: '100%' }} min={0} />
            </Form.Item>
            <Form.Item name="max_alt_m" label="最高高度 (m)" style={{ flex: 1 }}>
              <InputNumber style={{ width: '100%' }} min={0} />
            </Form.Item>
          </div>

          <Form.Item name="default_area_polygon" label="默认 polygon (JSON, 可选)">
            <Input.TextArea rows={2} placeholder='[[103.0, 30.5], [103.1, 30.5], [103.1, 30.6]]' />
          </Form.Item>
          <Form.Item name="authorities_preset" label="主管部门预置 (JSON)"
            help='格式: [{"code":"uom","name":"民航局 UOM","channel":"api","priority":1}]'>
            <Input.TextArea rows={4} />
          </Form.Item>
          <Form.Item name="checklist_json" label="Checklist (JSON)"
            help='格式: [{"id":"batt","text":"电池充满 ≥ 90%"}]'>
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>

      {/* Apply modal */}
      <Modal
        title="应用模板 · 新建报备草稿"
        open={applyOpen}
        onCancel={() => setApplyOpen(false)}
        onOk={submitApply}
        okText="创建草稿"
        cancelText="取消"
      >
        <Form form={applyForm} layout="vertical">
          <Form.Item name="title" label="报备标题" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="range" label="起止时间" rules={[{ required: true }]}>
            <DatePicker.RangePicker showTime style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="area_polygon_override" label="Polygon 覆盖 (JSON, 可选)">
            <Input.TextArea rows={2} placeholder="留空则用模板默认" />
          </Form.Item>
          <div style={{ display: 'flex', gap: 8 }}>
            <Form.Item name="min_alt_m_override" label="最低高度覆盖" style={{ flex: 1 }}>
              <InputNumber style={{ width: '100%' }} min={0} />
            </Form.Item>
            <Form.Item name="max_alt_m_override" label="最高高度覆盖" style={{ flex: 1 }}>
              <InputNumber style={{ width: '100%' }} min={0} />
            </Form.Item>
          </div>
        </Form>
      </Modal>
    </div>
  );
}
