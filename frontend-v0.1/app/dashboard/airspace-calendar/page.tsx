'use client';

/**
 * E2.5b · Airspace calendar dashboard page.
 *
 * Two responsibilities:
 *   1. list existing occupancy slots (uom / notam / local / manual)
 *   2. probe conflicts for a proposed (polygon, time, alt) window
 *
 * A proper 2D map picker lives on Roadmap v2.1 (MapDraw). For now the
 * polygon is edited as a JSON textarea — it's what UOM API and NOTAM
 * feeds hand us anyway.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import {
  Alert, Button, Card, DatePicker, Descriptions, Empty, Form, Input,
  InputNumber, Modal, Popconfirm, Select, Space, Table, Tag, Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  ArrowLeftOutlined, DeleteOutlined, PlusOutlined, RadarChartOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import dayjs, { Dayjs } from 'dayjs';

import {
  CalendarEntry,
  CalendarSource,
  ConflictSummary,
  checkAirspaceConflicts,
  createCalendarEntry,
  deleteCalendarEntry,
  listCalendarEntries,
} from '@/lib/airspace_calendar';

const { Title, Text, Paragraph } = Typography;

const SOURCE_COLOR: Record<CalendarSource, string> = {
  uom: 'red',
  notam: 'orange',
  local: 'blue',
  manual: 'purple',
};
const SOURCE_LABEL: Record<CalendarSource, string> = {
  uom: 'UOM',
  notam: 'NOTAM',
  local: '本平台',
  manual: '手工',
};

export default function AirspaceCalendarPage() {
  const [rows, setRows] = useState<CalendarEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [filterSrc, setFilterSrc] = useState<CalendarSource | undefined>();

  const [createOpen, setCreateOpen] = useState(false);
  const [createForm] = Form.useForm();

  const [probeOpen, setProbeOpen] = useState(false);
  const [probeForm] = Form.useForm();
  const [probeResult, setProbeResult] = useState<{
    count: number; conflicts: ConflictSummary[];
  } | null>(null);
  const [probing, setProbing] = useState(false);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listCalendarEntries({ source: filterSrc });
      setRows(data);
    } catch (e: any) {
      message.error(`加载失败: ${e?.message ?? e}`);
    } finally {
      setLoading(false);
    }
  }, [filterSrc]);

  useEffect(() => { void reload(); }, [reload]);

  const submitCreate = useCallback(async () => {
    let vals: any;
    try { vals = await createForm.validateFields(); } catch { return; }
    let polygon: number[][];
    try {
      polygon = JSON.parse(vals.geo_polygon);
      if (!Array.isArray(polygon) || polygon.length === 0) {
        throw new Error('polygon 不能为空');
      }
    } catch (e: any) {
      message.error(`polygon JSON 解析失败: ${e?.message ?? e}`);
      return;
    }
    const [start, end] = vals.range as [Dayjs, Dayjs];
    try {
      await createCalendarEntry({
        source: vals.source,
        title: vals.title,
        purpose: vals.purpose ?? null,
        external_ref: vals.external_ref ?? null,
        geo_polygon: polygon,
        start_ts: start.toISOString(),
        end_ts: end.toISOString(),
        min_alt_m: vals.min_alt_m ?? null,
        max_alt_m: vals.max_alt_m ?? null,
        priority: vals.priority ?? 10,
      });
      message.success('已录入');
      setCreateOpen(false);
      createForm.resetFields();
      await reload();
    } catch (e: any) {
      message.error(`录入失败: ${e?.message ?? e}`);
    }
  }, [createForm, reload]);

  const runProbe = useCallback(async () => {
    let vals: any;
    try { vals = await probeForm.validateFields(); } catch { return; }
    let polygon: number[][];
    try { polygon = JSON.parse(vals.geo_polygon); }
    catch (e: any) {
      message.error(`polygon JSON 解析失败: ${e?.message ?? e}`);
      return;
    }
    const [start, end] = vals.range as [Dayjs, Dayjs];
    setProbing(true);
    setProbeResult(null);
    try {
      const res = await checkAirspaceConflicts({
        geo_polygon: polygon,
        start_ts: start.toISOString(),
        end_ts: end.toISOString(),
        min_alt_m: vals.min_alt_m ?? null,
        max_alt_m: vals.max_alt_m ?? null,
      });
      setProbeResult(res);
    } catch (e: any) {
      message.error(`探测失败: ${e?.message ?? e}`);
    } finally {
      setProbing(false);
    }
  }, [probeForm]);

  const doDelete = useCallback(async (id: string) => {
    try {
      await deleteCalendarEntry(id);
      message.success('已删除');
      await reload();
    } catch (e: any) {
      message.error(`删除失败: ${e?.message ?? e}`);
    }
  }, [reload]);

  const cols: ColumnsType<CalendarEntry> = useMemo(() => ([
    {
      title: '来源', dataIndex: 'source', width: 90,
      render: (v: CalendarSource) => (
        <Tag color={SOURCE_COLOR[v]}>{SOURCE_LABEL[v]}</Tag>
      ),
    },
    { title: '标题', dataIndex: 'title', ellipsis: true },
    {
      title: '起止时间', width: 260,
      render: (_: any, r: CalendarEntry) => (
        <Text style={{ fontSize: 12 }}>
          {dayjs(r.start_ts).format('MM-DD HH:mm')} →
          {' '}{dayjs(r.end_ts).format('MM-DD HH:mm')}
        </Text>
      ),
    },
    {
      title: '高度', width: 120,
      render: (_: any, r: CalendarEntry) => (
        <Text style={{ fontSize: 12 }}>
          {r.min_alt_m ?? '—'} ~ {r.max_alt_m ?? '—'} m
        </Text>
      ),
    },
    {
      title: 'Bbox', width: 200,
      render: (_: any, r: CalendarEntry) => (
        <Text type="secondary" style={{ fontSize: 11 }}>
          ({r.bbox_min_lon.toFixed(3)}, {r.bbox_min_lat.toFixed(3)}) ~
          ({r.bbox_max_lon.toFixed(3)}, {r.bbox_max_lat.toFixed(3)})
        </Text>
      ),
    },
    { title: '外部编号', dataIndex: 'external_ref', width: 140,
      render: (v: string | null) => v ?? '—' },
    {
      title: '操作', width: 90, fixed: 'right',
      render: (_: any, r: CalendarEntry) => (
        <Popconfirm title="确认删除?" onConfirm={() => void doDelete(r.id)}>
          <Button size="small" danger icon={<DeleteOutlined />} />
        </Popconfirm>
      ),
    },
  ]), [doDelete]);

  return (
    <div style={{ padding: 16 }}>
      <Space style={{ marginBottom: 12 }}>
        <Link href="/dashboard/approvals">
          <Button size="small" icon={<ArrowLeftOutlined />}>
            返回报备列表
          </Button>
        </Link>
        <Title level={4} style={{ margin: 0 }}>空域占用日历</Title>
      </Space>
      <Paragraph type="secondary">
        UOM / NOTAM / 本平台报备 / 手工录入的空域占用汇总。
        提交报备前可以用「冲突探测」测试预期时窗与空域是否冲突，
        避免打 UOM API 前就发现问题。
      </Paragraph>

      <Space style={{ marginBottom: 8, width: '100%', justifyContent: 'space-between' }}>
        <Space>
          <Text type="secondary">来源过滤:</Text>
          <Select
            allowClear placeholder="全部"
            style={{ width: 120 }}
            value={filterSrc}
            onChange={setFilterSrc}
            options={(['uom', 'notam', 'local', 'manual'] as CalendarSource[]).map((s) => ({
              value: s, label: SOURCE_LABEL[s],
            }))}
          />
        </Space>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => void reload()}>刷新</Button>
          <Button icon={<RadarChartOutlined />} onClick={() => {
            probeForm.resetFields();
            probeForm.setFieldsValue({
              range: [dayjs(), dayjs().add(2, 'hour')],
            });
            setProbeResult(null);
            setProbeOpen(true);
          }}>
            冲突探测
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => {
            createForm.resetFields();
            createForm.setFieldsValue({
              source: 'local', priority: 10,
              range: [dayjs(), dayjs().add(2, 'hour')],
            });
            setCreateOpen(true);
          }}>
            录入占用
          </Button>
        </Space>
      </Space>

      <Card size="small" bodyStyle={{ padding: 4 }}>
        <Table<CalendarEntry>
          rowKey="id"
          columns={cols}
          dataSource={rows}
          loading={loading}
          size="small"
          pagination={{ pageSize: 20, showSizeChanger: false }}
          scroll={{ x: 1000 }}
          locale={{ emptyText: <Empty description="暂无空域占用条目" /> }}
        />
      </Card>

      {/* Create Modal */}
      <Modal
        title="录入空域占用"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={submitCreate}
        okText="保存"
        cancelText="取消"
        width={640}
      >
        <Form form={createForm} layout="vertical">
          <div style={{ display: 'flex', gap: 8 }}>
            <Form.Item name="source" label="来源" rules={[{ required: true }]} style={{ flex: 1 }}>
              <Select options={(['uom', 'notam', 'local', 'manual'] as CalendarSource[]).map((s) => ({
                value: s, label: SOURCE_LABEL[s],
              }))} />
            </Form.Item>
            <Form.Item name="external_ref" label="外部编号" style={{ flex: 1 }}>
              <Input placeholder="UOM-2026-000123 / NOTAM 号" />
            </Form.Item>
          </div>
          <Form.Item name="title" label="标题" rules={[{ required: true, max: 255 }]}>
            <Input />
          </Form.Item>
          <Form.Item name="purpose" label="用途">
            <Input />
          </Form.Item>
          <Form.Item name="range" label="起止时间" rules={[{ required: true }]}>
            <DatePicker.RangePicker showTime style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="geo_polygon" label="polygon (JSON)"
            rules={[{ required: true }]}
            help='格式: [[lon, lat], [lon, lat], ...]'>
            <Input.TextArea rows={3}
              placeholder='[[103.00, 30.50], [103.05, 30.50], [103.05, 30.55]]' />
          </Form.Item>
          <div style={{ display: 'flex', gap: 8 }}>
            <Form.Item name="min_alt_m" label="最低高度 m" style={{ flex: 1 }}>
              <InputNumber style={{ width: '100%' }} min={0} />
            </Form.Item>
            <Form.Item name="max_alt_m" label="最高高度 m" style={{ flex: 1 }}>
              <InputNumber style={{ width: '100%' }} min={0} />
            </Form.Item>
            <Form.Item name="priority" label="优先级" style={{ flex: 1 }}>
              <InputNumber style={{ width: '100%' }} min={0} />
            </Form.Item>
          </div>
        </Form>
      </Modal>

      {/* Probe Modal */}
      <Modal
        title="冲突探测（不落库）"
        open={probeOpen}
        onCancel={() => setProbeOpen(false)}
        footer={null}
        width={720}
      >
        <Form form={probeForm} layout="vertical">
          <Form.Item name="range" label="起止时间" rules={[{ required: true }]}>
            <DatePicker.RangePicker showTime style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="geo_polygon" label="polygon (JSON)"
            rules={[{ required: true }]}>
            <Input.TextArea rows={3}
              placeholder='[[103.00, 30.50], [103.05, 30.50], [103.05, 30.55]]' />
          </Form.Item>
          <div style={{ display: 'flex', gap: 8 }}>
            <Form.Item name="min_alt_m" label="最低高度 m" style={{ flex: 1 }}>
              <InputNumber style={{ width: '100%' }} min={0} />
            </Form.Item>
            <Form.Item name="max_alt_m" label="最高高度 m" style={{ flex: 1 }}>
              <InputNumber style={{ width: '100%' }} min={0} />
            </Form.Item>
          </div>
          <Space>
            <Button type="primary" onClick={runProbe} loading={probing}
              icon={<RadarChartOutlined />}>
              开始探测
            </Button>
            <Button onClick={() => setProbeOpen(false)}>关闭</Button>
          </Space>
        </Form>
        {probeResult && (
          <div style={{ marginTop: 12 }}>
            {probeResult.count === 0 ? (
              <Alert
                type="success" showIcon
                message="无冲突"
                description="该时间窗口下, 该空域没有已知的 UOM / NOTAM / 本地占用。"
              />
            ) : (
              <Alert
                type="warning" showIcon
                message={`发现 ${probeResult.count} 条冲突`}
                description={
                  <div style={{ marginTop: 6 }}>
                    {probeResult.conflicts.map((c) => (
                      <Descriptions key={c.id} size="small" bordered
                        column={2} style={{ marginBottom: 8 }}>
                        <Descriptions.Item label="来源">
                          <Tag color={SOURCE_COLOR[c.source as CalendarSource]}>
                            {SOURCE_LABEL[c.source as CalendarSource] ?? c.source}
                          </Tag>
                        </Descriptions.Item>
                        <Descriptions.Item label="标题">{c.title}</Descriptions.Item>
                        <Descriptions.Item label="起">
                          {dayjs(c.start_ts).format('MM-DD HH:mm')}
                        </Descriptions.Item>
                        <Descriptions.Item label="止">
                          {dayjs(c.end_ts).format('MM-DD HH:mm')}
                        </Descriptions.Item>
                        <Descriptions.Item label="高度">
                          {c.min_alt_m ?? '—'} ~ {c.max_alt_m ?? '—'} m
                        </Descriptions.Item>
                        <Descriptions.Item label="外部编号">
                          {c.external_ref ?? '—'}
                        </Descriptions.Item>
                      </Descriptions>
                    ))}
                  </div>
                }
              />
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}
