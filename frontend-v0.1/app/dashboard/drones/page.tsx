'use client';

import React, { useEffect, useState } from 'react';
import {
  Table,
  Tag,
  Button,
  Space,
  Modal,
  Form,
  Input,
  Select,
  message,
  Typography,
  Popconfirm,
} from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { getDrones, createDrone } from '@/lib/api';

const { Title } = Typography;

interface Drone {
  id: string;
  sn: string;
  model: string;
  protocol: string;
  status: string;
  last_seen?: string;
}

const statusColor: Record<string, string> = {
  online: 'green',
  offline: 'default',
  flying: 'blue',
  error: 'red',
};

export default function DronesPage() {
  const [data, setData] = useState<Drone[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [form] = Form.useForm();

  const fetchData = async () => {
    setLoading(true);
    try {
      const list = await getDrones();
      setData(Array.isArray(list) ? list : list?.items || []);
    } catch (err: any) {
      message.error(err?.message || '加载设备列表失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleCreate = async () => {
    try {
      const values = await form.validateFields();
      await createDrone(values);
      message.success('设备注册成功');
      setModalOpen(false);
      form.resetFields();
      fetchData();
    } catch (err: any) {
      if (err?.errorFields) return;
      message.error(err?.message || '注册失败');
    }
  };

  const columns = [
    { title: 'SN', dataIndex: 'sn', key: 'sn' },
    { title: '型号', dataIndex: 'model', key: 'model' },
    { title: '协议', dataIndex: 'protocol', key: 'protocol' },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (s: string) => <Tag color={statusColor[s] || 'default'}>{s}</Tag>,
    },
    {
      title: '最后在线',
      dataIndex: 'last_seen',
      key: 'last_seen',
      render: (t?: string) => (t ? dayjs(t).format('YYYY-MM-DD HH:mm:ss') : '-'),
    },
    {
      title: '操作',
      key: 'actions',
      render: (_: any, record: Drone) => (
        <Space>
          <Button size="small">查看</Button>
          <Button size="small" type="primary">连接</Button>
          <Popconfirm title="确认删除该设备?">
            <Button size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={3} style={{ color: 'var(--sm-text-primary)', margin: 0 }}>
          设备
        </Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>
          注册设备
        </Button>
      </div>

      <Table
        rowKey="id"
        columns={columns}
        dataSource={data}
        loading={loading}
        pagination={{ pageSize: 20 }}
      />

      <Modal
        title="注册设备"
        open={modalOpen}
        onOk={handleCreate}
        onCancel={() => setModalOpen(false)}
        okText="注册"
        cancelText="取消"
      >
        <Form form={form} layout="vertical">
          <Form.Item name="sn" label="SN 序列号" rules={[{ required: true }]}>
            <Input placeholder="例如 DJI-M300-001" />
          </Form.Item>
          <Form.Item name="model" label="型号" rules={[{ required: true }]}>
            <Input placeholder="例如 Matrice 300 RTK" />
          </Form.Item>
          <Form.Item name="protocol" label="协议" rules={[{ required: true }]} initialValue="mavlink">
            <Select
              options={[
                { value: 'mavlink', label: 'MAVLink' },
                { value: 'dji_psdk', label: 'DJI PSDK' },
                { value: 'custom', label: 'Custom' },
              ]}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
