'use client';

import React, { useEffect, useState } from 'react';
import {
  Card, Table, Tag, Space, Typography, Button, Descriptions,
  Modal, message, Alert, Empty, Divider, Input, Result,
} from 'antd';
import {
  SafetyCertificateOutlined, KeyOutlined, CheckCircleOutlined,
  CloseCircleOutlined, ReloadOutlined, InfoCircleOutlined,
} from '@ant-design/icons';
import {
  sm2Status, sm2PublicKey, sm2Verify, sm2AuditSig,
  sm2Rotation, sm2Hsm,
  type Sm2Status, type Sm2PublicKey, type Sm2AuditSig,
  type Sm2Rotation, type HsmStatus,
} from '@/lib/api';

const { Title, Text, Paragraph } = Typography;

export default function CryptoSm2Page() {
  const [status, setStatus] = useState<Sm2Status | null>(null);
  const [pubkey, setPubkey] = useState<Sm2PublicKey | null>(null);
  const [loadingStatus, setLoadingStatus] = useState(false);
  const [selectedKid, setSelectedKid] = useState<string | null>(null);

  // R21 · rotation + HSM
  const [rotation, setRotation] = useState<Sm2Rotation | null>(null);
  const [hsm, setHsm] = useState<HsmStatus | null>(null);

  // 抗抵赖验证器
  const [auditId, setAuditId] = useState('');
  const [sigRow, setSigRow] = useState<Sm2AuditSig | null>(null);
  const [verifyResult, setVerifyResult] = useState<{ ok: boolean; note: string } | null>(null);
  const [verifying, setVerifying] = useState(false);

  const loadStatus = async () => {
    setLoadingStatus(true);
    try {
      const [s, r, h] = await Promise.all([sm2Status(), sm2Rotation(), sm2Hsm()]);
      setStatus(s);
      setRotation(r);
      setHsm(h);
      if (s.active_key_id && !selectedKid) {
        setSelectedKid(s.active_key_id);
      }
    } catch (e: any) {
      message.error(`加载 SM2 状态失败：${e?.message ?? e}`);
    } finally {
      setLoadingStatus(false);
    }
  };

  const loadPubKey = async (kid: string) => {
    try {
      const p = await sm2PublicKey(kid);
      setPubkey(p);
    } catch (e: any) {
      message.error(`加载公钥失败：${e?.message ?? e}`);
    }
  };

  useEffect(() => { loadStatus(); }, []);
  useEffect(() => { if (selectedKid) loadPubKey(selectedKid); }, [selectedKid]);

  const handleVerifyAudit = async () => {
    if (!auditId.trim()) {
      message.warning('请输入审计日志 ID');
      return;
    }
    setVerifying(true);
    setSigRow(null);
    setVerifyResult(null);
    try {
      const id = parseInt(auditId, 10);
      if (isNaN(id)) {
        message.error('审计 ID 必须是数字');
        return;
      }
      const row = await sm2AuditSig(id);
      setSigRow(row);

      if (!row.sig_hex || !row.sig_key_id || !row.curr_hash || !row.ts) {
        setVerifyResult({ ok: false, note: '该审计行未被 SM2 签名（可能签名开关关闭时写入）' });
        return;
      }
      const r = await sm2Verify({
        record_id: String(row.id),
        curr_hash: row.curr_hash,
        ts: row.ts,
        signature_hex: row.sig_hex,
        key_id: row.sig_key_id,
      });
      if (r.ok) {
        setVerifyResult({ ok: true, note: `SM2 签名验证通过 · key_id=${r.key_id}` });
      } else {
        setVerifyResult({
          ok: false,
          note: r.known_key
            ? '⚠️ 签名验证失败 · 该行可能被篡改'
            : `⚠️ 未知 key_id=${r.key_id} · 无法验证（密钥已轮换或丢失？）`,
        });
      }
    } catch (e: any) {
      message.error(`验证失败：${e?.response?.data?.detail ?? e?.message ?? e}`);
    } finally {
      setVerifying(false);
    }
  };

  return (
    <div style={{ padding: 24, maxWidth: 1200 }}>
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>
            <SafetyCertificateOutlined /> SM2 抗抵赖签名
          </Title>
          <Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
            国密 SM2 数字签名 · 在 R18 审计哈希链之上叠加抗抵赖层。第三方可用平台公钥离线验证任一审计行未被篡改。
          </Paragraph>
        </div>

        {/* 状态卡 */}
        <Card
          title={<><InfoCircleOutlined /> 签名服务状态</>}
          extra={
            <Button
              icon={<ReloadOutlined />}
              onClick={loadStatus}
              loading={loadingStatus}
            >
              刷新
            </Button>
          }
        >
          {status ? (
            <Descriptions column={2} size="small">
              <Descriptions.Item label="签名开关">
                {status.enabled ? (
                  <Tag color="green" icon={<CheckCircleOutlined />}>已启用</Tag>
                ) : (
                  <Tag color="default" icon={<CloseCircleOutlined />}>未启用（soft-fail）</Tag>
                )}
              </Descriptions.Item>
              <Descriptions.Item label="活动密钥 ID">
                {status.active_key_id ? (
                  <Tag color="blue">{status.active_key_id}</Tag>
                ) : (
                  <Text type="secondary">—</Text>
                )}
              </Descriptions.Item>
              <Descriptions.Item label="已注册密钥 ID" span={2}>
                <Space wrap>
                  {status.known_key_ids.length ? status.known_key_ids.map(kid => (
                    <Tag
                      key={kid}
                      color={kid === selectedKid ? 'processing' : 'default'}
                      style={{ cursor: 'pointer' }}
                      onClick={() => setSelectedKid(kid)}
                    >
                      {kid}
                    </Tag>
                  )) : <Text type="secondary">无</Text>}
                </Space>
              </Descriptions.Item>
            </Descriptions>
          ) : loadingStatus ? (
            <Text type="secondary">加载中...</Text>
          ) : (
            <Empty />
          )}
          {status && !status.enabled && (
            <Alert
              style={{ marginTop: 16 }}
              type="info"
              showIcon
              message="Soft-fail 模式"
              description={
                <>
                  未配置 <code>SM2_PRIVATE_KEY_HEX</code> / <code>SM2_PUBLIC_KEY_HEX</code>{' '}
                  环境变量时，签名模块保持关闭状态且不阻塞审计写入。生产环境应配置密钥启用签名。
                </>
              }
            />
          )}
        </Card>

        {/* 公钥导出 */}
        <Card
          title={<><KeyOutlined /> 公钥导出（可分发给第三方验证方）</>}
        >
          {pubkey ? (
            <Descriptions column={1} size="small">
              <Descriptions.Item label="Key ID">
                <Tag color="blue">{pubkey.key_id}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="曲线">
                <Tag>{pubkey.curve}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="公钥 (未压缩 hex, 128 字符)">
                <Paragraph
                  copyable={{ text: pubkey.public_hex }}
                  code
                  style={{ margin: 0, wordBreak: 'break-all' }}
                >
                  {pubkey.public_hex}
                </Paragraph>
              </Descriptions.Item>
            </Descriptions>
          ) : (
            <Empty description="点击上方 key_id 查看公钥" />
          )}
        </Card>

        {/* R21 · Rotation & HSM */}
        <Card title={<>🔄 密钥轮换 · 等保三级 90 天要求</>}>
          {rotation ? (
            <>
              {rotation.any_rotation_due && (
                <Alert
                  style={{ marginBottom: 12 }}
                  type="warning"
                  showIcon
                  message="有密钥超过生命周期"
                  description="至少一个密钥的 age_days 已超过 lifetime_days，请生成新密钥并将旧 key_id 加入 SM2_RETIRED_KEY_IDS。"
                />
              )}
              <Table
                size="small"
                rowKey="key_id"
                pagination={false}
                dataSource={rotation.keys}
                columns={[
                  {
                    title: 'Key ID',
                    dataIndex: 'key_id',
                    render: (v: string) => (
                      <Tag color={v === rotation.active_key_id ? 'processing' : 'default'}>
                        {v}
                        {v === rotation.active_key_id ? ' · 当前签名' : ''}
                      </Tag>
                    ),
                  },
                  {
                    title: '状态',
                    dataIndex: 'active',
                    render: (a: boolean) =>
                      a ? <Tag color="green">激活</Tag> : <Tag color="default">仅验证</Tag>,
                  },
                  {
                    title: '含私钥',
                    dataIndex: 'has_private',
                    render: (v: boolean) => (v ? <Tag color="blue">是</Tag> : <Tag>否</Tag>),
                  },
                  {
                    title: '已使用',
                    dataIndex: 'age_days',
                    render: (d: number | null) =>
                      d == null ? <Text type="secondary">未知</Text> : `${d.toFixed(1)} 天`,
                  },
                  {
                    title: '生命周期',
                    dataIndex: 'lifetime_days',
                    render: (d: number) => `${d.toFixed(0)} 天`,
                  },
                  {
                    title: '轮换到期',
                    dataIndex: 'rotation_due',
                    render: (v: boolean) =>
                      v ? <Tag color="red">✗ 已到期</Tag> : <Tag color="green">✓ 正常</Tag>,
                  },
                ]}
              />
            </>
          ) : (
            <Empty />
          )}
        </Card>

        <Card title={<>🛡 签名后端 · HSM 集成</>}>
          {hsm ? (
            <>
              <Descriptions column={1} size="small" style={{ marginBottom: 12 }}>
                <Descriptions.Item label="当前活动后端">
                  <Tag color="blue">{hsm.active_backend}</Tag>
                </Descriptions.Item>
              </Descriptions>
              <Table
                size="small"
                rowKey="name"
                pagination={false}
                dataSource={hsm.backends}
                columns={[
                  {
                    title: '后端',
                    dataIndex: 'name',
                    render: (v: string) => (
                      <Tag color={v === hsm.active_backend ? 'processing' : 'default'}>{v}</Tag>
                    ),
                  },
                  { title: '优先级', dataIndex: 'priority' },
                  {
                    title: '可用',
                    dataIndex: 'available',
                    render: (v: boolean) =>
                      v ? <Tag color="green">✓</Tag> : <Tag color="default">✗</Tag>,
                  },
                ]}
              />
              <Alert
                style={{ marginTop: 12 }}
                type="info"
                showIcon
                message="HSM 接入预留"
                description="pkcs11 后端为占位，生产环境接入 深信服/三未信安/得安/Thales 国密硬件后，在 SM2_HSM_ENABLED=1 且 PyKCS11 驱动就位时自动优先。当前 env-hex 后端保持工作以确保不停机迁移。"
              />
            </>
          ) : (
            <Empty />
          )}
        </Card>

        {/* 抗抵赖验证器 */}
        <Card
          title={<>🔎 抗抵赖验证器 · 对审计行做离线签名核验</>}
        >
          <Paragraph type="secondary">
            输入任意审计日志 ID，平台会取出该行的 <code>curr_hash</code> + <code>signature</code>，
            用当前公钥离线验证。若签名合法则证明该行自被记录起未被任何人篡改。
          </Paragraph>
          <Space.Compact style={{ width: '100%', maxWidth: 400 }}>
            <Input
              placeholder="审计日志 ID (例如 12345)"
              value={auditId}
              onChange={(e) => setAuditId(e.target.value)}
              onPressEnter={handleVerifyAudit}
            />
            <Button
              type="primary"
              onClick={handleVerifyAudit}
              loading={verifying}
            >
              验证
            </Button>
          </Space.Compact>

          {sigRow && (
            <div style={{ marginTop: 16 }}>
              <Divider style={{ margin: '12px 0' }} orientation="left" plain>
                审计行 #{sigRow.id}
              </Divider>
              <Descriptions column={1} size="small" bordered>
                <Descriptions.Item label="Action">{sigRow.action}</Descriptions.Item>
                <Descriptions.Item label="Resource">{sigRow.resource ?? '—'}</Descriptions.Item>
                <Descriptions.Item label="Timestamp">{sigRow.ts ?? '—'}</Descriptions.Item>
                <Descriptions.Item label="curr_hash">
                  <Text code style={{ wordBreak: 'break-all' }}>{sigRow.curr_hash ?? '—'}</Text>
                </Descriptions.Item>
                <Descriptions.Item label="SM2 sig_hex">
                  {sigRow.sig_hex ? (
                    <Text code style={{ wordBreak: 'break-all' }}>{sigRow.sig_hex}</Text>
                  ) : (
                    <Tag color="default">未签名</Tag>
                  )}
                </Descriptions.Item>
                <Descriptions.Item label="sig_key_id">
                  {sigRow.sig_key_id ? <Tag color="blue">{sigRow.sig_key_id}</Tag> : '—'}
                </Descriptions.Item>
              </Descriptions>
            </div>
          )}

          {verifyResult && (
            <Result
              style={{ paddingTop: 24 }}
              status={verifyResult.ok ? 'success' : 'warning'}
              title={verifyResult.ok ? '签名验证通过' : '签名验证失败'}
              subTitle={verifyResult.note}
            />
          )}
        </Card>
      </Space>
    </div>
  );
}
