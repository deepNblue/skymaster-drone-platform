'use client';

import React, { useEffect, useState } from 'react';
import {
  Card, Table, Tag, Space, Typography, Button, Modal, Select, message,
  Alert, Descriptions, Popconfirm,
} from 'antd';
import {
  SafetyOutlined, UserAddOutlined, DeleteOutlined, TeamOutlined,
} from '@ant-design/icons';
import {
  listOfficers, grantOfficer, revokeOfficer, getOfficerMatrix,
  type OfficerUser,
} from '@/lib/api';

const { Title, Text, Paragraph } = Typography;

const OFFICER_LABELS: Record<string, { label: string; color: string; desc: string }> = {
  system_officer: {
    label: '系统员', color: 'blue',
    desc: '配置/部署/备份，不涉及授权与审计',
  },
  security_officer: {
    label: '安全员', color: 'gold',
    desc: '授权/密钥/合规策略，唯一可指派其他三员',
  },
  audit_officer: {
    label: '审计员', color: 'purple',
    desc: '只读日志/生成报表，无系统写权限',
  },
};

export default function OfficersPage() {
  const [officers, setOfficers] = useState<OfficerUser[]>([]);
  const [matrix, setMatrix] = useState<Record<string, string[]> | null>(null);
  const [grantOpen, setGrantOpen] = useState(false);
  const [grantForm, setGrantForm] = useState<{ user_id: string; officer_role: string }>({
    user_id: '', officer_role: 'audit_officer',
  });
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [os, m] = await Promise.all([
        listOfficers(),
        getOfficerMatrix(),
      ]);
      setOfficers(os);
      setMatrix(m.matrix);
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '需要安全员/审计员/管理员身份');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  const onGrant = async () => {
    if (!grantForm.user_id) { message.warning('请输入 user_id'); return; }
    try {
      await grantOfficer(grantForm.user_id, grantForm.officer_role);
      message.success('已授权');
      setGrantOpen(false);
      load();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '授权失败');
    }
  };

  const onRevoke = async (id: string) => {
    try {
      await revokeOfficer(id);
      message.success('已撤销');
      load();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '撤销失败');
    }
  };

  const columns = [
    { title: '邮箱', dataIndex: 'email', ellipsis: true },
    {
      title: '业务角色', dataIndex: 'role', width: 100,
      render: (r: string) => <Tag>{r}</Tag>,
    },
    {
      title: '三员身份', dataIndex: 'officer_role', width: 160,
      render: (o: string) => {
        const l = OFFICER_LABELS[o];
        return l ? <Tag color={l.color}>{l.label}</Tag> : '—';
      },
    },
    {
      title: '启用', dataIndex: 'is_active', width: 70,
      render: (a: boolean) => a ? '✅' : '❌',
    },
    {
      title: '操作', width: 100,
      render: (_: any, r: OfficerUser) => (
        <Popconfirm title="撤销该用户的三员身份？" onConfirm={() => onRevoke(r.id)}>
          <Button size="small" danger icon={<DeleteOutlined />}>撤销</Button>
        </Popconfirm>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <div>
            <Title level={3}>
              <TeamOutlined /> 三员分立 · 等保 2.0 三级
            </Title>
            <Text type="secondary">
              系统员 / 安全员 / 审计员 三权分置 · 违反 SoD 的操作在 API 层直接 403
            </Text>
          </div>
          <Button
            type="primary"
            icon={<UserAddOutlined />}
            onClick={() => setGrantOpen(true)}
          >
            指派三员身份
          </Button>
        </div>

        <Alert
          type="info"
          showIcon
          message="铁律：admin 账号不得兼任三员 · 安全员唯一可授权其他三员 · 高危操作要求双人协签"
        />

        <Card size="small">
          <Space wrap size="middle">
            {Object.entries(OFFICER_LABELS).map(([k, v]) => (
              <Descriptions key={k} bordered size="small" column={1}
                style={{ minWidth: 260 }}
                title={<Tag color={v.color}>{v.label}</Tag>}
              >
                <Descriptions.Item label="职责">{v.desc}</Descriptions.Item>
              </Descriptions>
            ))}
          </Space>
        </Card>

        <Card title="当前三员分布">
          <Table
            rowKey="id"
            columns={columns as any}
            dataSource={officers}
            loading={loading}
            pagination={false}
            size="small"
            locale={{ emptyText: '尚未指派任何三员身份（bootstrap grace period）' }}
          />
        </Card>

        {matrix && (
          <Card title="权限矩阵">
            <Table
              size="small"
              pagination={false}
              dataSource={Object.entries(matrix).map(([k, v]) => ({
                key: k, action: k, roles: v.join(', '),
              }))}
              columns={[
                { title: '操作', dataIndex: 'action', width: 240 },
                { title: '允许角色', dataIndex: 'roles' },
              ]}
            />
          </Card>
        )}
      </Space>

      <Modal
        title="🎖️ 指派三员身份"
        open={grantOpen}
        onOk={onGrant}
        onCancel={() => setGrantOpen(false)}
        destroyOnClose
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Alert
            type="warning"
            showIcon
            message="只有安全员可指派 · admin 不可兼任 · 不可给自己授权"
          />
          <div>
            <Text>目标 user_id：</Text>
            <input
              style={{
                width: '100%', padding: 6, marginTop: 4,
                border: '1px solid #d9d9d9', borderRadius: 4,
              }}
              placeholder="UUID"
              value={grantForm.user_id}
              onChange={(e) => setGrantForm(f => ({ ...f, user_id: e.target.value }))}
            />
          </div>
          <div>
            <Text>身份：</Text>
            <Select
              style={{ width: '100%', marginTop: 4 }}
              value={grantForm.officer_role}
              onChange={(v) => setGrantForm(f => ({ ...f, officer_role: v }))}
              options={Object.entries(OFFICER_LABELS).map(([k, v]) => ({
                value: k, label: `${v.label} — ${v.desc}`,
              }))}
            />
          </div>
        </Space>
      </Modal>
    </div>
  );
}
