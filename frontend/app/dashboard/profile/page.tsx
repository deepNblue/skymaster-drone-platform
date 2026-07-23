'use client';

/**
 * ProfilePage — v2.0 R10 "我的账户"
 *
 * 允许登录用户查看资料，修改密码。JWT refresh 已由 lib/api 层自动处理。
 */
import React, { useState, useEffect } from 'react';
import {
  Card, Descriptions, Form, Input, Button, message, Tag, Space, Alert,
  Divider, Typography, Modal, Steps, QRCode,
} from 'antd';
import {
  LockOutlined, UserOutlined, KeyOutlined, SafetyOutlined, CheckCircleOutlined,
} from '@ant-design/icons';
import { useAuthStore } from '@/lib/store';
import {
  changePassword, getMe,
  get2FAStatus, setup2FA, verify2FA, disable2FA,
} from '@/lib/api';

const { Title } = Typography;

const ROLE_COLOR: Record<string, string> = {
  admin: 'red',
  operator: 'blue',
  viewer: 'default',
};

export default function ProfilePage() {
  const user = useAuthStore((s) => s.user);
  const setUser = useAuthStore((s) => s.setUser);
  const [loading, setLoading] = useState(false);
  const [form] = Form.useForm();

  // 2FA state
  const [twoFAEnabled, setTwoFAEnabled] = useState(false);
  const [setupOpen, setSetupOpen] = useState(false);
  const [setupData, setSetupData] = useState<{
    secret: string;
    provisioning_uri: string;
    backup_codes: string[];
  } | null>(null);
  const [totpCode, setTotpCode] = useState('');
  const [disableCode, setDisableCode] = useState('');
  const [disableOpen, setDisableOpen] = useState(false);

  useEffect(() => {
    // Refresh profile from /auth/me on mount
    getMe()
      .then((u) => setUser(u))
      .catch(() => {});
    get2FAStatus()
      .then((s) => setTwoFAEnabled(!!s.enabled))
      .catch(() => {});
  }, [setUser]);

  const startSetup = async () => {
    try {
      const data = await setup2FA();
      setSetupData(data);
      setSetupOpen(true);
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '开启 2FA 失败');
    }
  };

  const confirmSetup = async () => {
    if (!/^\d{6}$/.test(totpCode)) {
      message.error('请输入 6 位数字动态码');
      return;
    }
    try {
      await verify2FA(totpCode);
      message.success('2FA 已成功开启');
      setSetupOpen(false);
      setTotpCode('');
      setSetupData(null);
      setTwoFAEnabled(true);
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '验证失败');
    }
  };

  const confirmDisable = async () => {
    if (!/^\d{6}$/.test(disableCode)) {
      message.error('请输入 6 位数字动态码');
      return;
    }
    try {
      await disable2FA(disableCode);
      message.success('2FA 已关闭');
      setDisableOpen(false);
      setDisableCode('');
      setTwoFAEnabled(false);
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '关闭失败');
    }
  };

  const onFinish = async (values: {
    old_password: string;
    new_password: string;
    confirm: string;
  }) => {
    if (values.new_password !== values.confirm) {
      message.error('两次输入的新密码不一致');
      return;
    }
    setLoading(true);
    try {
      await changePassword(values.old_password, values.new_password);
      message.success('密码修改成功，请下次登录使用新密码');
      form.resetFields();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '修改失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: 720, margin: '32px auto', padding: 16 }}>
      <Title level={3}>
        <Space>
          <UserOutlined />
          我的账户
        </Space>
      </Title>

      <Card style={{ marginBottom: 16 }}>
        <Descriptions title="个人资料" column={1} bordered size="small">
          <Descriptions.Item label="邮箱">
            {user?.email || '-'}
          </Descriptions.Item>
          <Descriptions.Item label="角色">
            <Tag color={ROLE_COLOR[user?.role || ''] || 'default'}>
              {user?.role || 'unknown'}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="组织 ID">
            <code style={{ fontSize: 12 }}>{user?.org_id || '-'}</code>
          </Descriptions.Item>
          <Descriptions.Item label="状态">
            {user?.is_active === false ? (
              <Tag color="red">已停用</Tag>
            ) : (
              <Tag color="green">正常</Tag>
            )}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card
        title={
          <Space>
            <KeyOutlined />
            修改密码
          </Space>
        }
      >
        <Alert
          type="info"
          showIcon
          message="密码策略：长度 ≥8 字符；至少包含小写/大写/数字/符号中的 3 种；不能是常见弱口令；不能包含邮箱前缀"
          style={{ marginBottom: 16 }}
        />
        <Form form={form} layout="vertical" onFinish={onFinish}>
          <Form.Item
            label="旧密码"
            name="old_password"
            rules={[{ required: true, message: '请输入旧密码' }]}
          >
            <Input.Password
              prefix={<LockOutlined />}
              placeholder="当前密码"
              autoComplete="current-password"
            />
          </Form.Item>
          <Form.Item
            label="新密码"
            name="new_password"
            rules={[
              { required: true, message: '请输入新密码' },
              { min: 8, message: '至少 8 位' },
              {
                validator: (_, v) => {
                  if (!v) return Promise.resolve();
                  const classes =
                    (/[a-z]/.test(v) ? 1 : 0) +
                    (/[A-Z]/.test(v) ? 1 : 0) +
                    (/[0-9]/.test(v) ? 1 : 0) +
                    (/[^A-Za-z0-9]/.test(v) ? 1 : 0);
                  return classes >= 3
                    ? Promise.resolve()
                    : Promise.reject(new Error('至少包含 3 类字符'));
                },
              },
            ]}
          >
            <Input.Password
              prefix={<LockOutlined />}
              placeholder="新密码 (≥8 位, 3 类字符)"
              autoComplete="new-password"
            />
          </Form.Item>
          <Form.Item
            label="确认新密码"
            name="confirm"
            dependencies={['new_password']}
            rules={[{ required: true, message: '请再次输入新密码' }]}
          >
            <Input.Password
              prefix={<LockOutlined />}
              placeholder="再次输入新密码"
              autoComplete="new-password"
            />
          </Form.Item>
          <Divider />
          <Space>
            <Button type="primary" htmlType="submit" loading={loading}>
              修改密码
            </Button>
            <Button onClick={() => form.resetFields()}>重置</Button>
          </Space>
        </Form>
      </Card>

      <Card
        title={
          <Space>
            <SafetyOutlined />
            双因素认证 (2FA / TOTP)
          </Space>
        }
        style={{ marginTop: 16 }}
        extra={
          twoFAEnabled ? (
            <Tag color="green" icon={<CheckCircleOutlined />}>已启用</Tag>
          ) : (
            <Tag color="default">未启用</Tag>
          )
        }
      >
        <Alert
          type={twoFAEnabled ? 'success' : 'warning'}
          showIcon
          message={
            twoFAEnabled
              ? '当前账号已启用两步验证，登录时需要额外输入动态验证码。'
              : '推荐启用两步验证，可显著降低账号被盗风险。'
          }
          style={{ marginBottom: 16 }}
        />
        {twoFAEnabled ? (
          <Button danger onClick={() => setDisableOpen(true)}>
            关闭 2FA
          </Button>
        ) : (
          <Button type="primary" onClick={startSetup}>
            开启 2FA
          </Button>
        )}
      </Card>

      {/* Setup 2FA modal */}
      <Modal
        title="开启 2FA"
        open={setupOpen}
        onCancel={() => {
          setSetupOpen(false);
          setSetupData(null);
          setTotpCode('');
        }}
        onOk={confirmSetup}
        okText="验证并启用"
        width={520}
      >
        {setupData && (
          <>
            <Steps
              size="small"
              current={1}
              items={[
                { title: '扫描二维码' },
                { title: '输入验证码' },
                { title: '保存备份码' },
              ]}
              style={{ marginBottom: 16 }}
            />
            <div style={{ textAlign: 'center', marginBottom: 16 }}>
              <QRCode value={setupData.provisioning_uri} size={180} />
              <div style={{ marginTop: 8, fontSize: 12, color: '#888' }}>
                或手动输入密钥: <code>{setupData.secret}</code>
              </div>
            </div>
            <Form.Item label="6 位动态码">
              <Input
                value={totpCode}
                onChange={(e) => setTotpCode(e.target.value)}
                maxLength={6}
                placeholder="123456"
                prefix={<SafetyOutlined />}
              />
            </Form.Item>
            <Alert
              type="warning"
              message="⚠️ 请妥善保存下列备份码，每个只能使用一次，用于手机丢失时救急"
              description={
                <div style={{ fontFamily: 'monospace', fontSize: 12 }}>
                  {setupData.backup_codes.map((c) => (
                    <div key={c}>{c}</div>
                  ))}
                </div>
              }
            />
          </>
        )}
      </Modal>

      {/* Disable 2FA modal */}
      <Modal
        title="关闭 2FA"
        open={disableOpen}
        onCancel={() => {
          setDisableOpen(false);
          setDisableCode('');
        }}
        onOk={confirmDisable}
        okText="确认关闭"
        okButtonProps={{ danger: true }}
      >
        <Alert
          type="warning"
          showIcon
          message="关闭 2FA 前需要再次验证您的身份"
          style={{ marginBottom: 12 }}
        />
        <Input
          value={disableCode}
          onChange={(e) => setDisableCode(e.target.value)}
          maxLength={6}
          placeholder="输入 6 位动态码"
          prefix={<SafetyOutlined />}
        />
      </Modal>
    </div>
  );
}
