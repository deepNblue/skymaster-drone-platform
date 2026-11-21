'use client';

import React, { useState } from 'react';
import {
  Card, Space, Typography, Button, Form, Input, DatePicker, Select,
  Alert, Result, Table, Tag, Descriptions, Divider, message,
} from 'antd';
import {
  DownloadOutlined, FileTextOutlined, SafetyOutlined,
  EyeOutlined, ThunderboltOutlined,
} from '@ant-design/icons';
import dayjs, { Dayjs } from 'dayjs';
import {
  auditPreview, auditIntegrity, auditExportUrl,
  type AuditRow, type AuditIntegrity, type AuditExportFilter,
} from '@/lib/api';

const { Title, Text, Paragraph } = Typography;

interface FormValues {
  range?: [Dayjs, Dayjs];
  actor_role?: string;
  action?: string;
  actor_id?: string;
  limit?: number;
}

function _toFilter(v: FormValues): AuditExportFilter {
  const f: AuditExportFilter = {};
  if (v.range?.[0]) f.ts_from = v.range[0].toISOString();
  if (v.range?.[1]) f.ts_to = v.range[1].toISOString();
  if (v.actor_role) f.actor_role = v.actor_role;
  if (v.action) f.action = v.action;
  if (v.actor_id) f.actor_id = v.actor_id;
  if (v.limit) f.limit = v.limit;
  return f;
}

export default function AuditExportPage() {
  const [form] = Form.useForm<FormValues>();
  const [preview, setPreview] = useState<AuditRow[] | null>(null);
  const [integrity, setIntegrity] = useState<AuditIntegrity | null>(null);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [loadingIntegrity, setLoadingIntegrity] = useState(false);

  const handlePreview = async () => {
    setLoadingPreview(true);
    try {
      const f = _toFilter(form.getFieldsValue());
      const r = await auditPreview({ ...f, limit: Math.min(f.limit ?? 20, 200) });
      setPreview(r.sample);
      if (r.sample.length === 0) message.info('过滤条件下无匹配行');
    } catch (e: any) {
      message.error(`预览失败：${e?.response?.data?.detail ?? e?.message ?? e}`);
    } finally {
      setLoadingPreview(false);
    }
  };

  const handleIntegrity = async () => {
    setLoadingIntegrity(true);
    try {
      const f = _toFilter(form.getFieldsValue());
      const r = await auditIntegrity(f);
      setIntegrity(r);
    } catch (e: any) {
      message.error(`完整性校验失败：${e?.response?.data?.detail ?? e?.message ?? e}`);
    } finally {
      setLoadingIntegrity(false);
    }
  };

  const handleDownload = (fmt: 'csv' | 'gbft') => {
    const f = _toFilter(form.getFieldsValue());
    const url = auditExportUrl(fmt, f);
    window.open(url, '_blank');
  };

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 80 },
    { title: 'ts', dataIndex: 'ts', width: 200,
      render: (v: string | null) => v ? dayjs(v).format('YYYY-MM-DD HH:mm:ss') : '—' },
    { title: 'actor_role', dataIndex: 'actor_role', width: 140,
      render: (v: string | null) => v ? <Tag>{v}</Tag> : '—' },
    { title: 'action', dataIndex: 'action', width: 200 },
    { title: 'resource', dataIndex: 'resource', ellipsis: true },
    { title: 'sig', dataIndex: 'sig_hex', width: 80,
      render: (v: string | null) => v ? <Tag color="green">✓</Tag> : <Tag>无</Tag> },
    { title: 'chain', dataIndex: 'curr_hash', width: 100,
      render: (v: string | null) => v ? <Text code style={{ fontSize: 10 }}>{v.slice(0, 8)}…</Text> : '—' },
  ];

  return (
    <div style={{ padding: 24, maxWidth: 1400 }}>
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>
            <FileTextOutlined /> 审计日志导出（等保三级）
          </Title>
          <Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
            审计员用于批量导出审计日志。支持 CSV（通用）与 GBFT（GB/T 20945 国标交换格式）。
            所有导出操作本身会被记录到 audit_logs 的 <code>audit.export</code> 行中。
          </Paragraph>
        </div>

        {/* 过滤条件 */}
        <Card title="🔎 过滤条件">
          <Form form={form} layout="inline" size="middle">
            <Form.Item name="range" label="时间范围">
              <DatePicker.RangePicker
                showTime
                style={{ width: 380 }}
                placeholder={['起始（含）', '结束（不含）']}
              />
            </Form.Item>
            <Form.Item name="actor_role" label="角色">
              <Select
                allowClear
                style={{ width: 160 }}
                placeholder="全部"
                options={[
                  { value: 'admin', label: 'admin' },
                  { value: 'system_officer', label: 'system_officer' },
                  { value: 'security_officer', label: 'security_officer' },
                  { value: 'audit_officer', label: 'audit_officer' },
                  { value: 'user', label: 'user' },
                ]}
              />
            </Form.Item>
            <Form.Item name="action" label="Action">
              <Input allowClear placeholder="例如 audit.export" style={{ width: 200 }} />
            </Form.Item>
            <Form.Item name="limit" label="上限" initialValue={1000}>
              <Input type="number" style={{ width: 100 }} min={1} max={500000} />
            </Form.Item>
          </Form>

          <Divider style={{ margin: '16px 0' }} />

          <Space wrap>
            <Button
              icon={<EyeOutlined />}
              onClick={handlePreview}
              loading={loadingPreview}
            >
              预览前 20 条
            </Button>
            <Button
              icon={<SafetyOutlined />}
              onClick={handleIntegrity}
              loading={loadingIntegrity}
            >
              校验哈希链完整性
            </Button>
            <Button
              type="primary"
              icon={<DownloadOutlined />}
              onClick={() => handleDownload('csv')}
            >
              下载 CSV
            </Button>
            <Button
              type="primary"
              icon={<ThunderboltOutlined />}
              onClick={() => handleDownload('gbft')}
            >
              下载 GBFT (JSONL)
            </Button>
          </Space>
        </Card>

        {/* 完整性报告 */}
        {integrity && (
          <Card title="🛡 哈希链 + 抗抵赖完整性">
            <Result
              status={integrity.hash_chain_ok ? 'success' : 'error'}
              title={integrity.hash_chain_ok ? '哈希链完整' : '哈希链断裂'}
              subTitle={
                integrity.hash_chain_ok
                  ? `共 ${integrity.total} 行审计记录 · 签名 ${integrity.signed_count} / 未签名 ${integrity.unsigned_count}`
                  : `在 audit_log.id=${integrity.hash_chain_break_at} 处 prev_hash 与上一行 curr_hash 不匹配`
              }
            />
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label="记录总数">{integrity.total}</Descriptions.Item>
              <Descriptions.Item label="链完整性">
                {integrity.hash_chain_ok ? (
                  <Tag color="green">✓ 通过</Tag>
                ) : (
                  <Tag color="red">✗ 断裂 @{integrity.hash_chain_break_at}</Tag>
                )}
              </Descriptions.Item>
              <Descriptions.Item label="SM2 已签名">
                <Tag color="blue">{integrity.signed_count}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="未签名（老数据）">
                <Tag>{integrity.unsigned_count}</Tag>
              </Descriptions.Item>
            </Descriptions>
            {!integrity.hash_chain_ok && (
              <Alert
                style={{ marginTop: 12 }}
                type="error"
                showIcon
                message="哈希链断裂说明存在被篡改的记录"
                description="立即冻结相关时间段的审计数据，交由安全员配合 SM2 逐行离线验证，锁定被篡改的时间点。"
              />
            )}
          </Card>
        )}

        {/* 预览表 */}
        {preview && (
          <Card title={`👁 预览（前 ${preview.length} 条）`}>
            <Table
              size="small"
              rowKey="id"
              dataSource={preview}
              columns={columns}
              pagination={false}
              scroll={{ x: 900 }}
            />
          </Card>
        )}
      </Space>
    </div>
  );
}
