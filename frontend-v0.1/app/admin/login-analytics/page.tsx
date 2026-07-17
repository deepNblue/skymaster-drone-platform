'use client';

import React, { useEffect, useState } from 'react';
import {
  Card, Table, Tag, Space, Typography, Row, Col, Statistic, Select, Input, Button,
} from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { getLoginStats, listLoginEvents } from '@/lib/api';

const { Title, Text } = Typography;

const outcomeColor: Record<string, string> = {
  success: 'green',
  invalid_password: 'red',
  invalid_email: 'red',
  invalid_totp: 'red',
  locked: 'volcano',
  rate_limit: 'orange',
  deactivated: 'default',
};

export default function LoginAnalyticsPage() {
  const [rows, setRows] = useState<any[]>([]);
  const [stats, setStats] = useState<any>({ total: 0, success: 0, failed: 0, by_outcome: {} });
  const [loading, setLoading] = useState(false);
  const [hours, setHours] = useState(24);
  const [outcome, setOutcome] = useState<string | undefined>(undefined);
  const [emailFilter, setEmailFilter] = useState('');

  const reload = async () => {
    setLoading(true);
    try {
      const [s, r] = await Promise.all([
        getLoginStats(hours),
        listLoginEvents({
          since_hours: hours,
          outcome,
          email: emailFilter || undefined,
          limit: 200,
        }),
      ]);
      setStats(s);
      setRows(r);
    } catch (e) {
      // noop — surfaced by axios interceptor
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hours, outcome]);

  const columns = [
    {
      title: '时间',
      dataIndex: 'created_at',
      render: (v: string) => new Date(v).toLocaleString('zh-CN'),
      width: 180,
    },
    { title: '邮箱', dataIndex: 'email', ellipsis: true },
    { title: '方式', dataIndex: 'method', width: 120 },
    {
      title: '结果',
      dataIndex: 'outcome',
      render: (o: string) => <Tag color={outcomeColor[o] || 'default'}>{o}</Tag>,
      width: 140,
    },
    { title: 'IP', dataIndex: 'ip', width: 140 },
    { title: '国家', dataIndex: 'country', width: 80 },
  ];

  const failRate = stats.total > 0
    ? Math.round((stats.failed / stats.total) * 100)
    : 0;

  return (
    <div style={{ padding: 24 }}>
      <Title level={3}>登录分析（管理员）</Title>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card>
            <Statistic title={`过去 ${hours} 小时 · 总登录尝试`} value={stats.total} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="成功"
              value={stats.success}
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="失败"
              value={stats.failed}
              valueStyle={{ color: '#ff4d4f' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="失败率"
              value={failRate}
              suffix="%"
              valueStyle={{ color: failRate > 30 ? '#ff4d4f' : '#faad14' }}
            />
          </Card>
        </Col>
      </Row>

      <Card
        title="事件流"
        extra={
          <Space>
            <Select
              value={hours}
              onChange={setHours}
              options={[
                { label: '1 小时', value: 1 },
                { label: '24 小时', value: 24 },
                { label: '7 天', value: 168 },
                { label: '30 天', value: 720 },
              ]}
              style={{ width: 100 }}
            />
            <Select
              placeholder="全部结果"
              allowClear
              value={outcome}
              onChange={setOutcome}
              options={Object.keys(outcomeColor).map((k) => ({ label: k, value: k }))}
              style={{ width: 160 }}
            />
            <Input.Search
              placeholder="按邮箱过滤"
              value={emailFilter}
              onChange={(e) => setEmailFilter(e.target.value)}
              onSearch={reload}
              style={{ width: 200 }}
              allowClear
            />
            <Button icon={<ReloadOutlined />} onClick={reload}>刷新</Button>
          </Space>
        }
      >
        <Table
          size="small"
          rowKey="id"
          loading={loading}
          columns={columns as any}
          dataSource={rows}
          pagination={{ pageSize: 30 }}
        />
      </Card>
    </div>
  );
}
