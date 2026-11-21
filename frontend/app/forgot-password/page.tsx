'use client';

import React, { useState } from 'react';
import { Form, Input, Button, Card, Typography, message, Alert } from 'antd';
import { MailOutlined, ArrowLeftOutlined } from '@ant-design/icons';
import Link from 'next/link';
import { api } from '@/lib/api';

const { Title, Text } = Typography;

export default function ForgotPasswordPage() {
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);

  const onFinish = async (values: { email: string }) => {
    setLoading(true);
    try {
      await api.post('/api/v1/auth/forgot-password', values);
      setSent(true);
    } catch (e: any) {
      // Anti-enumeration — still show success even on server error
      // to avoid leaking email registration status. Log only.
      console.warn(e);
      setSent(true);
    } finally {
      setLoading(false);
    }
  };

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
      <Card style={{ width: 440 }}>
        <Title level={3} style={{ textAlign: 'center' }}>
          🔑 找回密码
        </Title>
        {sent ? (
          <Alert
            type="success"
            showIcon
            message="邮件已发送"
            description={
              <span>
                如果该邮箱已注册，我们已发送重置链接。链接 30 分钟内有效，请检查收件箱（也留意垃圾邮件）。
                <br />
                <Link href="/login">
                  <ArrowLeftOutlined /> 返回登录
                </Link>
              </span>
            }
          />
        ) : (
          <>
            <Text type="secondary">
              输入您注册时使用的邮箱地址，我们会发送重置链接。
            </Text>
            <Form
              layout="vertical"
              onFinish={onFinish}
              style={{ marginTop: 20 }}
            >
              <Form.Item
                label="邮箱"
                name="email"
                rules={[
                  { required: true, message: '请输入邮箱' },
                  { type: 'email', message: '邮箱格式不正确' },
                ]}
              >
                <Input prefix={<MailOutlined />} placeholder="your@email.com" autoFocus />
              </Form.Item>
              <Form.Item>
                <Button type="primary" htmlType="submit" block loading={loading}>
                  发送重置链接
                </Button>
              </Form.Item>
              <Form.Item style={{ marginBottom: 0 }}>
                <Link href="/login">
                  <Button type="link" block>
                    <ArrowLeftOutlined /> 返回登录
                  </Button>
                </Link>
              </Form.Item>
            </Form>
          </>
        )}
      </Card>
    </div>
  );
}
