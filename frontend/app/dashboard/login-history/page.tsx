'use client';

import React, { useEffect, useState } from 'react';
import { Card, Table, Tag, Space, Alert, Typography, Empty } from 'antd';
import {
  CheckCircleTwoTone,
  CloseCircleTwoTone,
  LockOutlined,
  GlobalOutlined,
} from '@ant-design/icons';
import { getMyLoginHistory } from '@/lib/api';

const { Title, Text } = Typography;

interface LoginEvent {
  id: string;
  method: string;
  outcome: string;
  ip?: string;
  country?: string;
  user_agent?: string;
  created_at: string;
}

const outcomeColor: Record<string, string> = {
  success: 'green',
  invalid_password: 'red',
  invalid_email: 'red',
  invalid_totp: 'red',
  locked: 'volcano',
  rate_limit: 'orange',
  deactivated: 'default',
};

const outcomeLabel: Record<string, string> = {
  success: '✅ 成功',
  invalid_password: '❌ 密码错',
  invalid_email: '❌ 账号不存在',
  invalid_totp: '❌ 动态码错',
  locked: '🔒 账号锁定',
  rate_limit: '⏱ 频率限制',
  deactivated: '🚫 已停用',
};

export default function LoginHistoryPage() {
  const [rows, setRows] = useState<LoginEvent[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    getMyLoginHistory(50)
      .then(setRows)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const suspicious = rows.filter(
    (r) => r.outcome !== 'success' && r.method === 'password',
  ).length;

  const columns = [
    {
      title: '时间',
      dataIndex: 'created_at',
      render: (v: string) => new Date(v).toLocaleString('zh-CN'),
      width: 180,
    },
    {
      title: '方式',
      dataIndex: 'method',
      render: (m: string) => {
        const map: Record<string, string> = {
          password: '🔑 密码',
          totp: '🔢 2FA',
          'sso:google': '🅶 Google',
          'sso:github': '🐙 GitHub',
          refresh: '♻️ 刷新',
          logout: '🚪 登出',
        };
        return map[m] || m;
      },
      width: 110,
    },
    {
      title: '结果',
      dataIndex: 'outcome',
      render: (o: string) => (
        <Tag color={outcomeColor[o] || 'default'}>
          {outcomeLabel[o] || o}
        </Tag>
      ),
      width: 130,
    },
    {
      title: 'IP',
      dataIndex: 'ip',
      render: (v?: string) => v || '-',
      width: 140,
    },
    {
      title: '国家',
      dataIndex: 'country',
      render: (v?: string) =>
        v ? <Tag icon={<GlobalOutlined />}>{v}</Tag> : '-',
      width: 90,
    },
    {
      title: 'User-Agent',
      dataIndex: 'user_agent',
      ellipsis: true,
      render: (v?: string) => (v ? <Text type="secondary">{v}</Text> : '-'),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <div>
          <Title level={3}>
            <LockOutlined /> 登录历史
          </Title>
          <Text type="secondary">
            展示最近 50 次账号认证事件。发现异常请立即修改密码并开启 2FA。
          </Text>
        </div>

        {suspicious > 0 && (
          <Alert
            type="warning"
            showIcon
            message={`最近有 ${suspicious} 次登录失败尝试`}
            description="如非本人操作，建议立即修改密码并开启双因素认证 (2FA)。"
          />
        )}

        <Card>
          {rows.length === 0 && !loading ? (
            <Empty description="暂无登录记录" />
          ) : (
            <Table
              size="small"
              rowKey="id"
              loading={loading}
              columns={columns as any}
              dataSource={rows}
              pagination={{ pageSize: 20, showSizeChanger: false }}
            />
          )}
        </Card>
      </Space>
    </div>
  );
}
