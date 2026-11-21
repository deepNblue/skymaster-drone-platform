'use client';

import React, { useEffect, useState } from 'react';
import { Table, Tag, Button, Space, Select, Typography, message } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { getMissions } from '@/lib/api';

const { Title } = Typography;

interface Mission {
  id: string;
  name: string;
  drone_id?: string;
  drone_sn?: string;
  template?: string;
  status: string;
  created_at?: string;
}

const statusColor: Record<string, string> = {
  draft: 'default',
  pending: 'gold',
  running: 'blue',
  completed: 'green',
  failed: 'red',
  cancelled: 'default',
};

export default function MissionsPage() {
  const [data, setData] = useState<Mission[]>([]);
  const [loading, setLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string | undefined>();

  const fetchData = async () => {
    setLoading(true);
    try {
      const list = await getMissions({ status: statusFilter });
      setData(Array.isArray(list) ? list : list?.items || []);
    } catch (err: any) {
      message.error(err?.message || '加载任务列表失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [statusFilter]);

  const columns = [
    { title: '任务名', dataIndex: 'name', key: 'name' },
    { title: '设备', dataIndex: 'drone_sn', key: 'drone_sn', render: (v?: string) => v || '-' },
    { title: '模板', dataIndex: 'template', key: 'template', render: (v?: string) => v || '-' },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (s: string) => <Tag color={statusColor[s] || 'default'}>{s}</Tag>,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (t?: string) => (t ? dayjs(t).format('YYYY-MM-DD HH:mm:ss') : '-'),
    },
    {
      title: '操作',
      key: 'actions',
      render: () => (
        <Space>
          <Button size="small">详情</Button>
          <Button size="small" type="primary">下发</Button>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={3} style={{ color: 'var(--sm-text-primary)', margin: 0 }}>
          任务
        </Title>
        <Space>
          <Select
            allowClear
            placeholder="按状态筛选"
            style={{ width: 160 }}
            value={statusFilter}
            onChange={setStatusFilter}
            options={[
              { value: 'draft', label: '草稿' },
              { value: 'pending', label: '待审批' },
              { value: 'running', label: '执行中' },
              { value: 'completed', label: '已完成' },
              { value: 'failed', label: '失败' },
              { value: 'cancelled', label: '已取消' },
            ]}
          />
          <Button type="primary" icon={<PlusOutlined />}>
            新建任务
          </Button>
        </Space>
      </div>

      <Table
        rowKey="id"
        columns={columns}
        dataSource={data}
        loading={loading}
        pagination={{ pageSize: 20 }}
      />
    </div>
  );
}
