'use client';

import React, { useEffect, useState } from 'react';
import {
  Card, List, Button, Tag, Space, Typography, Popconfirm, message, Empty,
  Divider, Alert, Modal, Form, Input,
} from 'antd';
import {
  DesktopOutlined, MobileOutlined, LaptopOutlined, GlobalOutlined,
  DeleteOutlined, LockOutlined, ExclamationCircleOutlined,
} from '@ant-design/icons';
import {
  listMySessions, revokeSession, revokeOtherSessions, changePasswordV2 as changePassword,
} from '@/lib/api';

const { Title, Text } = Typography;

function deviceIcon(label?: string) {
  if (!label) return <DesktopOutlined />;
  const l = label.toLowerCase();
  if (l.includes('iphone') || l.includes('android') || l.includes('ipad')) {
    return <MobileOutlined />;
  }
  if (l.includes('mac') || l.includes('windows') || l.includes('linux')) {
    return <LaptopOutlined />;
  }
  return <DesktopOutlined />;
}

export default function SessionsPage() {
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [pwOpen, setPwOpen] = useState(false);
  const [pwLoading, setPwLoading] = useState(false);
  const [form] = Form.useForm();

  const load = async () => {
    setLoading(true);
    try {
      setRows(await listMySessions());
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const onRevoke = async (id: string) => {
    try {
      await revokeSession(id);
      message.success('设备已登出');
      load();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '操作失败');
    }
  };

  const onRevokeOthers = async () => {
    try {
      const res = await revokeOtherSessions();
      message.success(`已登出其他 ${res.revoked_count} 个设备`);
      load();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '操作失败');
    }
  };

  const onChangePw = async (values: any) => {
    if (values.new_password !== values.confirm) {
      message.error('两次输入不一致');
      return;
    }
    setPwLoading(true);
    try {
      const res = await changePassword(values.current, values.new_password);
      message.success(res.message || '密码已修改');
      setPwOpen(false);
      form.resetFields();
      load();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '修改失败');
    } finally {
      setPwLoading(false);
    }
  };

  const others = rows.filter((r) => !r.is_current).length;

  return (
    <div style={{ padding: 24 }}>
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <div>
          <Title level={3}>
            <DesktopOutlined /> 设备与安全
          </Title>
          <Text type="secondary">
            管理当前登录的所有设备，发现可疑设备可一键登出。
          </Text>
        </div>

        {others > 0 && (
          <Alert
            type="info"
            showIcon
            message={`您有 ${others} 台其他设备正在登录`}
            description={`如非本人操作，可点击"登出其他设备"或修改密码。`}
            action={
              <Space>
                <Popconfirm
                  title="登出所有其他设备？"
                  description="您当前的登录会话将保留"
                  onConfirm={onRevokeOthers}
                >
                  <Button danger size="small">登出其他设备</Button>
                </Popconfirm>
              </Space>
            }
          />
        )}

        <Card
          title="活跃会话"
          extra={
            <Button
              type="primary"
              icon={<LockOutlined />}
              onClick={() => setPwOpen(true)}
            >
              修改密码
            </Button>
          }
        >
          {rows.length === 0 && !loading ? (
            <Empty description="暂无活跃会话" />
          ) : (
            <List
              loading={loading}
              itemLayout="horizontal"
              dataSource={rows}
              renderItem={(r: any) => (
                <List.Item
                  actions={[
                    r.is_current ? (
                      <Tag color="green" key="current">当前设备</Tag>
                    ) : (
                      <Popconfirm
                        title="登出该设备？"
                        onConfirm={() => onRevoke(r.id)}
                        key="revoke"
                      >
                        <Button danger size="small" icon={<DeleteOutlined />}>
                          登出
                        </Button>
                      </Popconfirm>
                    ),
                  ]}
                >
                  <List.Item.Meta
                    avatar={
                      <span style={{ fontSize: 24 }}>
                        {deviceIcon(r.device_label)}
                      </span>
                    }
                    title={
                      <Space>
                        <span>{r.device_label || '未知设备'}</span>
                        {r.country && (
                          <Tag icon={<GlobalOutlined />}>{r.country}</Tag>
                        )}
                        {r.is_current && <Tag color="green">当前</Tag>}
                      </Space>
                    }
                    description={
                      <div style={{ color: '#8b949e', fontSize: 12 }}>
                        <div>IP: {r.ip || '未知'}</div>
                        <div>
                          最近活动: {new Date(r.last_seen_at).toLocaleString('zh-CN')}
                        </div>
                        {r.user_agent && (
                          <div style={{ marginTop: 4 }}>
                            <Text type="secondary" ellipsis style={{ maxWidth: 500 }}>
                              {r.user_agent}
                            </Text>
                          </div>
                        )}
                      </div>
                    }
                  />
                </List.Item>
              )}
            />
          )}
        </Card>
      </Space>

      <Modal
        title="🔒 修改密码"
        open={pwOpen}
        onCancel={() => setPwOpen(false)}
        footer={null}
        destroyOnClose
      >
        <Alert
          type="warning"
          showIcon
          icon={<ExclamationCircleOutlined />}
          style={{ marginBottom: 16 }}
          message="修改密码后，除当前设备外的所有登录会话都会被强制登出"
        />
        <Form form={form} layout="vertical" onFinish={onChangePw}>
          <Form.Item
            label="当前密码"
            name="current"
            rules={[{ required: true, message: '请输入当前密码' }]}
          >
            <Input.Password autoComplete="current-password" />
          </Form.Item>
          <Form.Item
            label="新密码"
            name="new_password"
            rules={[
              { required: true, message: '请输入新密码' },
              { min: 12, message: '至少 12 位' },
            ]}
          >
            <Input.Password autoComplete="new-password" placeholder="至少 12 位强密码" />
          </Form.Item>
          <Form.Item
            label="确认新密码"
            name="confirm"
            dependencies={['new_password']}
            rules={[
              { required: true, message: '请再次输入' },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue('new_password') === value) {
                    return Promise.resolve();
                  }
                  return Promise.reject(new Error('两次输入不一致'));
                },
              }),
            ]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0 }}>
            <Button type="primary" htmlType="submit" block loading={pwLoading}>
              确认修改
            </Button>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
