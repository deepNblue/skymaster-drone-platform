'use client';

import React, { useState, Suspense } from 'react';
import { Form, Input, Button, Card, Typography, Result, Alert } from 'antd';
import { LockOutlined, CheckCircleTwoTone } from '@ant-design/icons';
import { useSearchParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { api } from '@/lib/api';

const { Title, Text } = Typography;

function ResetInner() {
  const params = useSearchParams();
  const router = useRouter();
  const token = params.get('token') || '';
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const onFinish = async (values: { new_password: string; confirm: string }) => {
    if (values.new_password !== values.confirm) {
      setErr('两次输入的密码不一致');
      return;
    }
    setErr(null);
    setLoading(true);
    try {
      await api.post('/api/v1/auth/reset-password', {
        token,
        new_password: values.new_password,
      });
      setDone(true);
      setTimeout(() => router.push('/login'), 2500);
    } catch (e: any) {
      setErr(e?.response?.data?.detail || '重置失败，链接可能已过期');
    } finally {
      setLoading(false);
    }
  };

  if (!token) {
    return (
      <Result
        status="error"
        title="缺少重置令牌"
        subTitle="请通过邮件中的链接访问此页面"
        extra={
          <Link href="/forgot-password">
            <Button type="primary">重新申请</Button>
          </Link>
        }
      />
    );
  }

  if (done) {
    return (
      <Result
        icon={<CheckCircleTwoTone twoToneColor="#52c41a" />}
        title="密码已重置"
        subTitle="正在跳转至登录页..."
      />
    );
  }

  return (
    <>
      <Title level={3} style={{ textAlign: 'center' }}>
        🔒 设置新密码
      </Title>
      <Text type="secondary">
        请设置一个新密码。至少 12 位，包含大小写字母、数字和特殊字符。
      </Text>
      {err && (
        <Alert
          type="error"
          showIcon
          message={err}
          style={{ marginTop: 12, marginBottom: 12 }}
        />
      )}
      <Form layout="vertical" onFinish={onFinish} style={{ marginTop: 20 }}>
        <Form.Item
          label="新密码"
          name="new_password"
          rules={[
            { required: true, message: '请输入新密码' },
            { min: 12, message: '至少 12 位' },
          ]}
          hasFeedback
        >
          <Input.Password prefix={<LockOutlined />} placeholder="至少 12 位强密码" />
        </Form.Item>
        <Form.Item
          label="确认新密码"
          name="confirm"
          dependencies={['new_password']}
          hasFeedback
          rules={[
            { required: true, message: '请再次输入密码' },
            ({ getFieldValue }) => ({
              validator(_, value) {
                if (!value || getFieldValue('new_password') === value) {
                  return Promise.resolve();
                }
                return Promise.reject(new Error('两次输入的密码不一致'));
              },
            }),
          ]}
        >
          <Input.Password prefix={<LockOutlined />} placeholder="重复输入" />
        </Form.Item>
        <Form.Item>
          <Button type="primary" htmlType="submit" block loading={loading}>
            重置密码
          </Button>
        </Form.Item>
      </Form>
    </>
  );
}

export default function ResetPasswordPage() {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        minHeight: '100vh',
        background: '#0d1117',
      }}
    >
      <Card style={{ width: 460 }}>
        <Suspense fallback={<div>Loading...</div>}>
          <ResetInner />
        </Suspense>
      </Card>
    </div>
  );
}
