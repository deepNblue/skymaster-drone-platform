'use client';

import React, { useState, useEffect } from 'react';
import { Form, Input, Button, Card, message, Typography, Alert, Divider, Space } from 'antd';
import { UserOutlined, LockOutlined, SafetyOutlined, GoogleOutlined, GithubOutlined } from '@ant-design/icons';
import { useRouter } from 'next/navigation';
import { api, login } from '@/lib/api';
import { useAuthStore } from '@/lib/store';

const { Title, Text } = Typography;

export default function LoginPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [need2FA, setNeed2FA] = useState(false);
  const [creds, setCreds] = useState<{ email: string; password: string } | null>(null);
  const [ssoProviders, setSsoProviders] = useState<string[]>([]);
  const setToken = useAuthStore((s) => s.setToken);

  useEffect(() => {
    api
      .get('/api/v1/auth/sso/providers')
      .then((r) => setSsoProviders(r.data?.providers || []))
      .catch(() => {});
  }, []);

  const onFinish = async (values: {
    email: string;
    password: string;
    totp_code?: string;
  }) => {
    setLoading(true);
    try {
      const data = await login(
        values.email || creds?.email || '',
        values.password || creds?.password || '',
        values.totp_code,
      );
      const token = data.access_token;
      if (token) {
        setToken(token);
        message.success('登录成功');
        router.replace('/dashboard');
      } else {
        message.error('登录失败：未收到 access_token');
      }
    } catch (err: any) {
      // 428 Precondition Required — server signals "need TOTP"
      if (err?.response?.status === 428) {
        setNeed2FA(true);
        setCreds({ email: values.email, password: values.password });
        message.info('该账号已启用 2FA，请输入 6 位动态码');
        return;
      }
      message.error(err?.response?.data?.detail || err?.message || '登录失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'var(--sm-bg-primary)',
      }}
    >
      <Card
        style={{
          width: 420,
          background: 'var(--sm-bg-secondary)',
          border: '1px solid #30363d',
        }}
      >
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <Title level={3} style={{ color: 'var(--sm-text-primary)', margin: 0 }}>
            SkyMaster
          </Title>
          <Text type="secondary">无人机统一管控平台</Text>
        </div>
        {need2FA && (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message="请输入身份验证器 App 上显示的 6 位动态码（或救急备份码）"
          />
        )}
        <Form
          name="login"
          onFinish={onFinish}
          layout="vertical"
          autoComplete="off"
        >
          {!need2FA && (
            <>
              <Form.Item
                label="邮箱"
                name="email"
                rules={[
                  { required: true, message: '请输入邮箱' },
                  { type: 'email', message: '邮箱格式不正确' },
                ]}
              >
                <Input
                  prefix={<UserOutlined />}
                  placeholder="admin@skymaster.local"
                />
              </Form.Item>
              <Form.Item
                label="密码"
                name="password"
                rules={[{ required: true, message: '请输入密码' }]}
              >
                <Input.Password prefix={<LockOutlined />} placeholder="password" />
              </Form.Item>
            </>
          )}
          {need2FA && (
            <Form.Item
              label="动态验证码 / 备份码"
              name="totp_code"
              rules={[
                { required: true, message: '请输入验证码' },
                {
                  validator: (_, v) => {
                    if (!v) return Promise.resolve();
                    // Accept 6-digit TOTP or backup code with hyphen
                    if (/^\d{6}$/.test(v) || /^[A-Z0-9]{5}-[A-Z0-9]{5}$/.test(v)) {
                      return Promise.resolve();
                    }
                    return Promise.reject(new Error('6 位数字或 XXXXX-XXXXX 备份码'));
                  },
                },
              ]}
            >
              <Input
                prefix={<SafetyOutlined />}
                placeholder="123456 或 ABCDE-12345"
                maxLength={11}
                autoFocus
              />
            </Form.Item>
          )}
          <Form.Item>
            <Button type="primary" htmlType="submit" loading={loading} block>
              {need2FA ? '验 证' : '登 录'}
            </Button>
          </Form.Item>
          {!need2FA && (
            <div style={{ textAlign: 'right', marginTop: -12, marginBottom: 12 }}>
              <a
                href="/forgot-password"
                style={{ color: '#8b949e', fontSize: 13 }}
              >
                忘记密码？
              </a>
            </div>
          )}
          {need2FA && (
            <Button
              type="link"
              block
              onClick={() => {
                setNeed2FA(false);
                setCreds(null);
              }}
            >
              返回重新输入密码
            </Button>
          )}
        </Form>
        {!need2FA && ssoProviders.length > 0 && (
          <>
            <Divider plain style={{ color: '#8b949e' }}>或使用第三方登录</Divider>
            <Space direction="vertical" style={{ width: '100%' }}>
              {ssoProviders.includes('google') && (
                <Button
                  block
                  icon={<GoogleOutlined />}
                  onClick={() => {
                    window.location.href =
                      (process.env.NEXT_PUBLIC_API_BASE_URL || '') +
                      '/api/v1/auth/sso/google/authorize';
                  }}
                >
                  使用 Google 登录
                </Button>
              )}
              {ssoProviders.includes('github') && (
                <Button
                  block
                  icon={<GithubOutlined />}
                  onClick={() => {
                    window.location.href =
                      (process.env.NEXT_PUBLIC_API_BASE_URL || '') +
                      '/api/v1/auth/sso/github/authorize';
                  }}
                >
                  使用 GitHub 登录
                </Button>
              )}
            </Space>
          </>
        )}
      </Card>
    </div>
  );
}
