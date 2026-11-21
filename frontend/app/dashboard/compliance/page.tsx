'use client';

import React, { useEffect, useState } from 'react';
import {
  Card, Space, Typography, Switch, Radio, Checkbox, Button, Alert, Tag,
  Descriptions, message, Divider, Statistic,
} from 'antd';
import {
  SafetyCertificateOutlined, ThunderboltOutlined, LockOutlined,
  CheckCircleOutlined, WarningOutlined,
} from '@ant-design/icons';
import {
  getComplianceStatus, toggleCompliance, verifyAuditChain,
  type ComplianceStatus,
} from '@/lib/api';

const { Title, Text, Paragraph } = Typography;

const ALL_MODULES = ['audit_log', 'session', 'flight_approval', 'transcription'];

export default function CompliancePage() {
  const [status, setStatus] = useState<ComplianceStatus | null>(null);
  const [mode, setMode] = useState<'off' | 'hash' | 'full'>('off');
  const [modules, setModules] = useState<string[]>(['audit_log']);
  const [saving, setSaving] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [verifyResult, setVerifyResult] = useState<any>(null);

  const load = async () => {
    try {
      const s = await getComplianceStatus();
      setStatus(s);
      setMode(s.mode);
      setModules(s.modules.length ? s.modules : ['audit_log']);
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '仅管理员可访问');
    }
  };
  useEffect(() => { load(); }, []);

  const onSave = async () => {
    setSaving(true);
    try {
      const res = await toggleCompliance({
        enabled: mode !== 'off',
        mode,
        modules,
      });
      setStatus(res.after);
      message.success(`国密已切换为 ${res.after.mode}`);
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '切换失败');
    } finally {
      setSaving(false);
    }
  };

  const onQuickOff = async () => {
    setSaving(true);
    try {
      const res = await toggleCompliance({ enabled: false, mode: 'off' });
      setStatus(res.after);
      setMode('off');
      message.success('国密已关闭 · 恢复低延迟模式');
    } finally {
      setSaving(false);
    }
  };

  const onVerify = async () => {
    setVerifying(true);
    try {
      setVerifyResult(await verifyAuditChain(1000));
    } catch (e: any) {
      message.error('验证失败');
    } finally {
      setVerifying(false);
    }
  };

  return (
    <div style={{ padding: 24 }}>
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <div>
          <Title level={3}>
            <SafetyCertificateOutlined /> 国密合规 · 等保 2.0 三级
          </Title>
          <Text type="secondary">
            SM3 哈希链 + SM4 对称加密 · <b>默认关闭</b> · 低延迟场景（实时遥测/直播）可随时关闭
          </Text>
        </div>

        {status && (
          <Card size="small" bordered>
            <Space size="large">
              <Statistic
                title="当前状态"
                value={status.enabled ? '已启用' : '已关闭'}
                valueStyle={{
                  color: status.enabled ? '#3f8600' : '#8b949e',
                  fontSize: 20,
                }}
                prefix={status.enabled ? <LockOutlined /> : <ThunderboltOutlined />}
              />
              <Statistic
                title="模式"
                value={status.mode}
                valueStyle={{ fontSize: 20 }}
              />
              <Statistic
                title="保护模块"
                value={status.modules.length}
                valueStyle={{ fontSize: 20 }}
                suffix={`/ ${ALL_MODULES.length}`}
              />
              <Statistic
                title="哈希 / 加密"
                value={
                  (status.algo.hash || '—') + ' / ' + (status.algo.cipher || '—')
                }
                valueStyle={{ fontSize: 14 }}
              />
            </Space>
          </Card>
        )}

        <Card title="⚙️ 运行时开关">
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 16 }}
            message="开启 full 模式后，审计日志读写会引入 μs 级 SM3 + SM4 开销"
            description='遥测/实时流路径不受影响（默认不在保护模块列表内）。低延迟场景可点击"一键关闭"立即降级至 off。'
          />

          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            <div>
              <Text strong>加密模式</Text>
              <Radio.Group
                value={mode}
                onChange={(e) => setMode(e.target.value)}
                style={{ marginLeft: 16 }}
              >
                <Radio.Button value="off">
                  <ThunderboltOutlined /> off · 关闭（最快）
                </Radio.Button>
                <Radio.Button value="hash">
                  🔗 hash · 仅 SM3 哈希链
                </Radio.Button>
                <Radio.Button value="full">
                  🔒 full · SM3 + SM4 加密
                </Radio.Button>
              </Radio.Group>
            </div>

            <div>
              <Text strong>保护模块</Text>
              <Checkbox.Group
                value={modules}
                onChange={(v) => setModules(v as string[])}
                style={{ marginLeft: 16 }}
                disabled={mode === 'off'}
              >
                <Checkbox value="audit_log">审计日志</Checkbox>
                <Checkbox value="session">登录会话</Checkbox>
                <Checkbox value="flight_approval">飞行报备</Checkbox>
                <Checkbox value="transcription">会见转写</Checkbox>
              </Checkbox.Group>
            </div>

            <Space>
              <Button type="primary" loading={saving} onClick={onSave}>
                应用配置
              </Button>
              <Button
                danger
                icon={<ThunderboltOutlined />}
                loading={saving}
                onClick={onQuickOff}
                disabled={mode === 'off'}
              >
                ⚡ 一键关闭（低延迟模式）
              </Button>
            </Space>
          </Space>
        </Card>

        <Card title="🔍 审计链完整性验证">
          <Space direction="vertical" style={{ width: '100%' }}>
            <Paragraph type="secondary">
              读取近 1000 条审计日志，重新计算 SM3 哈希链，验证是否有断链或篡改。
            </Paragraph>
            <Button
              loading={verifying}
              icon={<CheckCircleOutlined />}
              onClick={onVerify}
            >
              开始验证
            </Button>
            {verifyResult && (
              <>
                <Divider style={{ margin: '12px 0' }} />
                <Descriptions bordered size="small" column={2}>
                  <Descriptions.Item label="已检查条数">
                    {verifyResult.checked}
                  </Descriptions.Item>
                  <Descriptions.Item label="链完整性">
                    {verifyResult.ok ? (
                      <Tag color="success" icon={<CheckCircleOutlined />}>
                        通过
                      </Tag>
                    ) : (
                      <Tag color="error" icon={<WarningOutlined />}>
                        存在断链
                      </Tag>
                    )}
                  </Descriptions.Item>
                  {verifyResult.broken_at && (
                    <Descriptions.Item label="断链位置" span={2}>
                      <pre style={{ margin: 0, fontSize: 12 }}>
                        {JSON.stringify(verifyResult.broken_at, null, 2)}
                      </pre>
                    </Descriptions.Item>
                  )}
                </Descriptions>
              </>
            )}
          </Space>
        </Card>
      </Space>
    </div>
  );
}
