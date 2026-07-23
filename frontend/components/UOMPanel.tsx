'use client';

import React, { useEffect, useState } from 'react';
import { Button, Space, Tag, Modal, Form, Input, InputNumber, DatePicker, message, Table, Popconfirm } from 'antd';
import { SafetyCertificateOutlined, PlusOutlined, DownloadOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { api, uomReportsCsvUrl } from '@/lib/api';

interface FlightReport {
  id: string;
  operator_id: string;
  pilot_name: string;
  aircraft_reg: string;
  purpose: string;
  area_polygon: number[][];
  max_alt_m: number;
  start_ts: number;
  end_ts: number;
  status: 'draft' | 'pending' | 'approved' | 'rejected' | 'cancelled' | 'expired';
  submitted_at?: number;
  reviewed_at?: number;
  reviewer?: string;
  approval_code?: string;
  reject_reason?: string;
}

const STATUS_COLOR: Record<string, string> = {
  pending: 'orange',
  approved: 'green',
  rejected: 'red',
  cancelled: 'default',
  expired: 'default',
  draft: 'blue',
};

/**
 * Compliance panel — v2.0 Module ①.
 * Small floating drawer on the live map that lists flight-reports and
 * lets the operator submit / approve / reject.
 */
export default function UOMPanel({ defaultArea }: { defaultArea?: number[][] }) {
  const [open, setOpen] = useState(false);
  const [reports, setReports] = useState<FlightReport[]>([]);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [form] = Form.useForm();

  const load = async () => {
    setLoading(true);
    try {
      const r = await api.get<{ reports: FlightReport[] }>('/uom/reports');
      setReports(r.data.reports);
    } catch (e: any) {
      message.error(`加载失败: ${e?.message || e}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!open) return;
    load();
    const id = setInterval(load, 3000); // catch auto-approver
    return () => clearInterval(id);
  }, [open]);

  const submit = async () => {
    const v = await form.validateFields();
    setCreating(true);
    try {
      const [start, end] = v.window;
      await api.post('/uom/reports', {
        operator_id: v.operator_id,
        pilot_name: v.pilot_name,
        aircraft_reg: v.aircraft_reg,
        purpose: v.purpose,
        area_polygon: defaultArea && defaultArea.length >= 3
          ? defaultArea
          : [
              [116.30, 39.90],
              [116.50, 39.90],
              [116.50, 40.00],
              [116.30, 40.00],
            ],
        max_alt_m: v.max_alt_m,
        start_ts: start.unix(),
        end_ts: end.unix(),
      });
      message.success('已提交，等待审批');
      form.resetFields();
      await load();
    } catch (e: any) {
      message.error(`提交失败: ${e?.message || e}`);
    } finally {
      setCreating(false);
    }
  };

  const approve = async (id: string) => {
    await api.post(`/uom/reports/${id}/approve`, { reviewer: 'operator' });
    message.success('已批准');
    load();
  };
  const reject = async (id: string) => {
    await api.post(`/uom/reports/${id}/reject`, { reason: '手动驳回', reviewer: 'operator' });
    message.info('已驳回');
    load();
  };

  return (
    <>
      <Button
        icon={<SafetyCertificateOutlined />}
        onClick={() => setOpen(true)}
        style={{
          position: 'absolute',
          top: 16,
          right: 16,
          zIndex: 25,
          background: 'rgba(13,17,23,0.9)',
          border: '1px solid #21262d',
          color: '#e6edf3',
        }}
      >
        🛡 飞行报备
      </Button>

      <Modal
        title="🛡 飞行报备 (UOM) · v2.0 合规"
        open={open}
        onCancel={() => setOpen(false)}
        footer={null}
        width={860}
      >
        <div style={{ marginBottom: 16 }}>
          <Form form={form} layout="inline" style={{ flexWrap: 'wrap', gap: 8 }}>
            <Form.Item name="operator_id" rules={[{ required: true }]} initialValue="org-1">
              <Input placeholder="运营人ID" style={{ width: 100 }} />
            </Form.Item>
            <Form.Item name="pilot_name" rules={[{ required: true }]}>
              <Input placeholder="飞手姓名" style={{ width: 100 }} />
            </Form.Item>
            <Form.Item name="aircraft_reg" rules={[{ required: true }]}>
              <Input placeholder="机身注册号" style={{ width: 140 }} />
            </Form.Item>
            <Form.Item name="purpose" rules={[{ required: true }]} initialValue="航拍">
              <Input placeholder="作业性质" style={{ width: 100 }} />
            </Form.Item>
            <Form.Item name="max_alt_m" rules={[{ required: true }]} initialValue={120}>
              <InputNumber placeholder="限高(m)" min={1} max={500} style={{ width: 100 }} />
            </Form.Item>
            <Form.Item name="window" rules={[{ required: true }]} initialValue={[dayjs().add(1, 'minute'), dayjs().add(2, 'hour')]}>
              <DatePicker.RangePicker showTime style={{ width: 350 }} />
            </Form.Item>
            <Form.Item>
              <Button type="primary" icon={<PlusOutlined />} onClick={submit} loading={creating}>
                提交报备
              </Button>
            </Form.Item>
            <Form.Item>
              <Button
                icon={<DownloadOutlined />}
                onClick={() => {
                  const opId = form.getFieldValue('operator_id') as string | undefined;
                  window.open(uomReportsCsvUrl(opId ? { operator_id: opId } : {}), '_blank');
                }}
                title="导出当前 operator 的报备列表 CSV（Excel 兼容 UTF-8 BOM）"
              >
                导出 CSV
              </Button>
            </Form.Item>
          </Form>
        </div>

        <Table
          rowKey="id"
          loading={loading}
          dataSource={reports}
          size="small"
          pagination={{ pageSize: 5 }}
          columns={[
            { title: '飞手', dataIndex: 'pilot_name', width: 90 },
            { title: '机身', dataIndex: 'aircraft_reg', width: 130 },
            { title: '作业', dataIndex: 'purpose', width: 70 },
            { title: '限高', dataIndex: 'max_alt_m', width: 60, render: (v: number) => `${v}m` },
            {
              title: '时段',
              width: 180,
              render: (_, r) => `${dayjs.unix(r.start_ts).format('MM-DD HH:mm')} → ${dayjs.unix(r.end_ts).format('HH:mm')}`,
            },
            {
              title: '状态', dataIndex: 'status', width: 90,
              render: (s: string) => <Tag color={STATUS_COLOR[s] || 'default'}>{s}</Tag>,
            },
            {
              title: '审批号', dataIndex: 'approval_code', width: 200,
              render: (v?: string) => v ? <code style={{ fontSize: 11 }}>{v}</code> : '—',
            },
            {
              title: '操作',
              render: (_, r) => r.status === 'pending' ? (
                <Space>
                  <Popconfirm title="批准该报备？" onConfirm={() => approve(r.id)}>
                    <Button size="small" type="primary">批准</Button>
                  </Popconfirm>
                  <Popconfirm title="驳回该报备？" onConfirm={() => reject(r.id)}>
                    <Button size="small" danger>驳回</Button>
                  </Popconfirm>
                </Space>
              ) : '—',
            },
          ]}
        />
      </Modal>
    </>
  );
}
