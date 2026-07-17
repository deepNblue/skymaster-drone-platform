/**
 * F4.2 · Copilot prompt template admin.
 * URL: /dashboard/copilot/prompts
 */
'use client';
import {
  Alert, Badge, Button, Card, Col, Descriptions, Empty, Form, Input,
  List, Modal, Radio, Row, Segmented, Space, Switch, Tabs, Tag,
  Typography, message,
} from 'antd';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import { useCallback, useEffect, useMemo, useState } from 'react';

import {
  DiffResult, PERSONAS, Persona, PromptTemplate,
  activateVersion, assessPromptRisk, classifyDiffLine,
  createTemplate, diffVersions, listTemplates, personaLabel, rollback,
} from '@/lib/copilot_prompt_templates';

dayjs.extend(relativeTime);

const { Text, Title, Paragraph } = Typography;
const { TextArea } = Input;

export default function PromptAdminPage() {
  const [persona, setPersona] = useState<Persona>('operator');
  const [items, setItems] = useState<PromptTemplate[]>([]);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [diffModal, setDiffModal] = useState<{
    open: boolean; from: number; to: number; diff?: DiffResult;
  }>({ open: false, from: 0, to: 0 });
  const [form] = Form.useForm<{
    name: string; system_prompt: string;
    notes?: string; activate?: boolean;
  }>();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await listTemplates({ persona });
      setItems(rows);
    } catch (e: any) {
      message.error(`加载失败: ${e?.message ?? e}`);
    } finally {
      setLoading(false);
    }
  }, [persona]);

  useEffect(() => { void load(); }, [load]);

  const active = useMemo(
    () => items.find((x) => x.is_active),
    [items],
  );

  const submitNew = useCallback(async () => {
    const v = await form.validateFields();
    setCreating(true);
    try {
      await createTemplate({
        persona,
        name: v.name,
        system_prompt: v.system_prompt,
        notes: v.notes,
        activate: !!v.activate,
      });
      message.success('新版本已创建');
      form.resetFields();
      await load();
    } catch (e: any) {
      message.error(`失败: ${e?.message ?? e}`);
    } finally {
      setCreating(false);
    }
  }, [form, persona, load]);

  const doActivate = useCallback(async (version: number) => {
    try {
      await activateVersion(persona, version);
      message.success(`v${version} 已激活`);
      await load();
    } catch (e: any) {
      message.error(`失败: ${e?.message ?? e}`);
    }
  }, [persona, load]);

  const doRollback = useCallback(async () => {
    try {
      const r = await rollback(persona);
      message.success(`已回退至 v${r.version}`);
      await load();
    } catch (e: any) {
      message.error(`失败: ${e?.message ?? e}`);
    }
  }, [persona, load]);

  const openDiff = useCallback(
    async (from: number, to: number) => {
      try {
        const d = await diffVersions(persona, from, to);
        setDiffModal({ open: true, from, to, diff: d });
      } catch (e: any) {
        message.error(`失败: ${e?.message ?? e}`);
      }
    }, [persona],
  );

  const promptText = Form.useWatch('system_prompt', form) ?? '';
  const risk = useMemo(
    () => assessPromptRisk(promptText),
    [promptText],
  );

  return (
    <div style={{ padding: 16 }}>
      <Title level={4}>🧠 Copilot Prompt 版本管理</Title>
      <Alert
        type="info" showIcon closable
        style={{ marginBottom: 12 }}
        message="每个 persona 保留完整版本链, 同时只有一个 active
          版本. 支持一键激活 / 回退到上一版, 上线出问题秒回滚."
      />

      <Segmented<Persona>
        value={persona}
        onChange={(v) => setPersona(v as Persona)}
        options={PERSONAS.map((p) => ({
          label: personaLabel(p), value: p,
        }))}
        style={{ marginBottom: 12 }}
      />

      <Row gutter={12}>
        <Col xs={24} lg={10}>
          <Card size="small" title="✏️ 新建版本">
            <Form form={form} layout="vertical">
              <Form.Item
                name="name" label="版本名"
                rules={[{ required: true, max: 128 }]}
              >
                <Input placeholder="e.g. 客服话术 v3" />
              </Form.Item>
              <Form.Item
                name="system_prompt" label="System Prompt"
                rules={[{ required: true, max: 16000 }]}
              >
                <TextArea
                  rows={10}
                  placeholder="你是一名友善的..."
                />
              </Form.Item>
              {risk.level !== 'ok' && (
                <Alert
                  type={risk.level === 'high' ? 'error' : 'warning'}
                  message={risk.level === 'high'
                    ? '⚠️ 检测到高风险内容'
                    : '⚠️ 需要关注'}
                  description={risk.reasons.join('; ')}
                  showIcon style={{ marginBottom: 12 }}
                />
              )}
              <Form.Item name="notes" label="备注 (选填)">
                <TextArea rows={2} maxLength={4000} />
              </Form.Item>
              <Form.Item name="activate" valuePropName="checked">
                <Switch />
                <Text style={{ marginLeft: 8 }}>
                  创建后立即激活
                </Text>
              </Form.Item>
              <Button
                type="primary" loading={creating}
                onClick={submitNew}
                disabled={risk.level === 'high'}
              >
                创建版本
              </Button>
            </Form>
          </Card>
        </Col>

        <Col xs={24} lg={14}>
          <Card
            size="small"
            title={
              <Space>
                <span>版本列表</span>
                {active && (
                  <Tag color="green">当前 v{active.version}</Tag>
                )}
                <Badge count={items.length} showZero
                  color="#1677ff" />
              </Space>
            }
            extra={
              <Button
                onClick={doRollback}
                disabled={items.length < 2}
              >
                ↩ 回退上一版
              </Button>
            }
          >
            {items.length === 0 ? (
              <Empty description="尚无版本" />
            ) : (
              <List<PromptTemplate>
                loading={loading}
                dataSource={items}
                renderItem={(t) => (
                  <List.Item
                    style={{
                      background: t.is_active
                        ? '#f6ffed' : 'transparent',
                      padding: '10px 12px',
                    }}
                    actions={[
                      !t.is_active && (
                        <Button
                          key="a" size="small" type="link"
                          onClick={() => void doActivate(t.version)}
                        >
                          激活
                        </Button>
                      ),
                      active && !t.is_active && (
                        <Button
                          key="d" size="small" type="link"
                          onClick={() => void openDiff(
                            t.version, active.version,
                          )}
                        >
                          对比 vs 当前
                        </Button>
                      ),
                    ].filter(Boolean) as React.ReactNode[]}
                  >
                    <List.Item.Meta
                      title={
                        <Space size={6}>
                          <Tag color={t.is_active ? 'green' : 'blue'}>
                            v{t.version}
                          </Tag>
                          <Text strong={t.is_active}>{t.name}</Text>
                          {t.is_active && (
                            <Tag color="green">Active</Tag>
                          )}
                        </Space>
                      }
                      description={
                        <Space direction="vertical" size={2}>
                          <Paragraph
                            style={{ margin: 0, fontSize: 12 }}
                            ellipsis={{ rows: 2 }}
                            type="secondary"
                          >
                            {t.system_prompt}
                          </Paragraph>
                          {t.notes && (
                            <Text
                              type="secondary"
                              style={{ fontSize: 12 }}
                              italic
                            >
                              📝 {t.notes}
                            </Text>
                          )}
                          <Text
                            type="secondary"
                            style={{ fontSize: 11 }}
                          >
                            {t.created_at
                              ? dayjs(t.created_at).fromNow()
                              : ''}
                          </Text>
                        </Space>
                      }
                    />
                  </List.Item>
                )}
              />
            )}
          </Card>
        </Col>
      </Row>

      <Modal
        open={diffModal.open}
        onCancel={() => setDiffModal(
          { open: false, from: 0, to: 0 },
        )}
        onOk={() => setDiffModal(
          { open: false, from: 0, to: 0 },
        )}
        width={800}
        title={`Diff v${diffModal.from} → v${diffModal.to}`}
      >
        {diffModal.diff?.changed ? (
          <pre style={{
            maxHeight: 500, overflow: 'auto',
            fontSize: 12, lineHeight: '18px',
            background: '#fafafa', padding: 12,
          }}>
            {diffModal.diff.diff.split('\n').map((line, i) => {
              const kind = classifyDiffLine(line);
              const bg =
                kind === 'add' ? '#eaffea' :
                  kind === 'del' ? '#ffecec' :
                    kind === 'hunk' ? '#f0f0ff' : 'transparent';
              return (
                <div
                  key={i}
                  style={{
                    background: bg,
                    padding: '0 4px',
                    fontFamily: 'monospace',
                  }}
                >{line || ' '}</div>
              );
            })}
          </pre>
        ) : (
          <Empty description="两版内容一致" />
        )}
      </Modal>
    </div>
  );
}
