'use client';

import React, { useEffect, useRef, useState } from 'react';
import {
  Card, Space, Typography, Input, Button, Tag, List, message, Empty,
  Layout, Menu, Modal, Select,
} from 'antd';
import {
  RobotOutlined, SendOutlined, PlusOutlined, ThunderboltOutlined,
} from '@ant-design/icons';
import {
  copilotDryRun, createCopilotSession, listCopilotSessions,
  listCopilotTurns, createCopilotTurn,
  type CopilotSession, type CopilotTurn,
} from '@/lib/api';

const { Title, Text, Paragraph } = Typography;
const { Sider, Content } = Layout;

const INTENT_COLORS: Record<string, string> = {
  takeoff: 'green', land: 'blue', return_home: 'purple',
  hover: 'cyan', goto_waypoint: 'geekblue',
  start_recording: 'gold', stop_recording: 'orange',
  vision_query: 'magenta', generate_report: 'volcano',
  help: 'default', status: 'default', unknown: 'error', noop: 'default',
};

export default function CopilotPage() {
  const [sessions, setSessions] = useState<CopilotSession[]>([]);
  const [activeSid, setActiveSid] = useState<string | null>(null);
  const [turns, setTurns] = useState<CopilotTurn[]>([]);
  const [text, setText] = useState('');
  const [preview, setPreview] = useState<any>(null);
  const [sending, setSending] = useState(false);
  const [newOpen, setNewOpen] = useState(false);
  const [newForm, setNewForm] = useState({ title: '', persona: 'operator' });
  const bottomRef = useRef<HTMLDivElement>(null);

  const loadSessions = async () => {
    try {
      const s = await listCopilotSessions();
      setSessions(s);
      if (!activeSid && s.length) setActiveSid(s[0].id);
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '加载失败');
    }
  };
  const loadTurns = async (sid: string) => {
    try {
      const t = await listCopilotTurns(sid);
      setTurns(t);
      setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' }), 50);
    } catch (e: any) {
      message.error('加载对话失败');
    }
  };

  useEffect(() => { loadSessions(); }, []);
  useEffect(() => { if (activeSid) loadTurns(activeSid); }, [activeSid]);

  // Debounced dry-run preview as user types.
  useEffect(() => {
    if (!text.trim()) { setPreview(null); return; }
    const t = setTimeout(async () => {
      try {
        const p = await copilotDryRun(text);
        setPreview(p);
      } catch { /* ignore */ }
    }, 250);
    return () => clearTimeout(t);
  }, [text]);

  const onNewSession = async () => {
    try {
      const s = await createCopilotSession({
        title: newForm.title || `会话-${new Date().toLocaleTimeString()}`,
        persona: newForm.persona,
      });
      setNewOpen(false);
      setNewForm({ title: '', persona: 'operator' });
      loadSessions();
      setActiveSid(s.id);
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '创建失败');
    }
  };

  const onSend = async () => {
    if (!activeSid || !text.trim()) return;
    setSending(true);
    try {
      await createCopilotTurn(activeSid, { text });
      setText('');
      setPreview(null);
      await loadTurns(activeSid);
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '发送失败');
    } finally {
      setSending(false);
    }
  };

  return (
    <Layout style={{ height: 'calc(100vh - 64px)', background: '#fff' }}>
      <Sider width={260} style={{ background: '#fafafa', padding: 12 }}>
        <Button
          type="primary" block icon={<PlusOutlined />}
          onClick={() => setNewOpen(true)}
          style={{ marginBottom: 12 }}
        >
          新建会话
        </Button>
        {sessions.length === 0 ? (
          <Empty description="尚无会话" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <Menu
            mode="inline"
            selectedKeys={activeSid ? [activeSid] : []}
            onClick={({ key }) => setActiveSid(String(key))}
            items={sessions.map(s => ({
              key: s.id,
              label: (
                <div>
                  <div style={{ fontSize: 13, lineHeight: '18px' }}>{s.title}</div>
                  <div style={{ fontSize: 11, color: '#888' }}>
                    <Tag color="blue">{s.persona}</Tag>
                    {new Date(s.created_at).toLocaleDateString()}
                  </div>
                </div>
              ),
            }))}
          />
        )}
      </Sider>

      <Content style={{ padding: 16, display: 'flex', flexDirection: 'column' }}>
        <div style={{ marginBottom: 8 }}>
          <Title level={4} style={{ margin: 0 }}>
            <RobotOutlined /> Copilot Agent · 自然语言操控
          </Title>
          <Text type="secondary">
            规则-first 意图解析 · 亚毫秒级 · 支持起飞/降落/返航/悬停/前往航点/视觉查询/报告
          </Text>
        </div>

        <div style={{
          flex: 1, overflowY: 'auto', padding: 12,
          background: '#f5f5f5', borderRadius: 6,
        }}>
          {turns.length === 0 ? (
            <Empty description={
              activeSid ? "发送第一条指令 · 试试 '起飞' 或 '去 30.5,104.06'" : "请先选择或新建会话"
            } />
          ) : (
            <List
              dataSource={turns}
              renderItem={t => (
                <List.Item style={{ border: 'none', padding: '4px 0' }}>
                  <div style={{ width: '100%' }}>
                    <div style={{ textAlign: 'right', marginBottom: 4 }}>
                      <span style={{
                        background: '#1677ff', color: 'white',
                        padding: '6px 12px', borderRadius: 8,
                        display: 'inline-block', maxWidth: '75%',
                      }}>{t.user_text}</span>
                    </div>
                    <div>
                      <span style={{
                        background: 'white', padding: '6px 12px',
                        borderRadius: 8, display: 'inline-block', maxWidth: '75%',
                        border: '1px solid #d9d9d9',
                      }}>
                        <Tag color={INTENT_COLORS[t.intent || 'unknown']}>
                          {t.intent}
                        </Tag>
                        <span>{t.reply_text}</span>
                        {t.latency_ms != null && (
                          <span style={{ color: '#888', fontSize: 11, marginLeft: 8 }}>
                            {t.latency_ms}ms
                          </span>
                        )}
                        {t.tool_call && (
                          <div style={{ marginTop: 4, fontSize: 11, color: '#666' }}>
                            <ThunderboltOutlined /> {t.tool_call.tool}
                            {t.tool_call.args && Object.keys(t.tool_call.args).length > 0 && (
                              <> · {JSON.stringify(t.tool_call.args)}</>
                            )}
                          </div>
                        )}
                      </span>
                    </div>
                  </div>
                </List.Item>
              )}
            />
          )}
          <div ref={bottomRef} />
        </div>

        {preview && preview.intent !== 'noop' && (
          <div style={{
            padding: 8, background: '#fffbe6',
            border: '1px solid #ffe58f', borderRadius: 4,
            fontSize: 12, marginTop: 8,
          }}>
            <ThunderboltOutlined /> 意图预览：
            <Tag color={INTENT_COLORS[preview.intent] || 'default'}>{preview.intent}</Tag>
            置信度 {(preview.confidence * 100).toFixed(0)}%
            {preview.tool_call && (
              <> · 将调用 <Text code>{preview.tool_call.tool}</Text></>
            )}
          </div>
        )}

        <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
          <Input.TextArea
            placeholder={activeSid ? "起飞 / 降落 / 返航 / 去 30.5,104.06 / 看到 person 吗" : "请先新建会话"}
            value={text}
            onChange={e => setText(e.target.value)}
            onPressEnter={e => {
              if (!e.shiftKey) { e.preventDefault(); onSend(); }
            }}
            disabled={!activeSid}
            autoSize={{ minRows: 1, maxRows: 4 }}
          />
          <Button
            type="primary" icon={<SendOutlined />}
            loading={sending} onClick={onSend}
            disabled={!activeSid || !text.trim()}
          >发送</Button>
        </div>
      </Content>

      <Modal
        title="🤖 新建 Copilot 会话"
        open={newOpen}
        onOk={onNewSession}
        onCancel={() => setNewOpen(false)}
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <div>
            <Text>标题：</Text>
            <Input
              value={newForm.title}
              onChange={e => setNewForm({ ...newForm, title: e.target.value })}
              placeholder="留空自动生成"
            />
          </div>
          <div>
            <Text>Persona：</Text>
            <Select
              style={{ width: '100%' }}
              value={newForm.persona}
              onChange={v => setNewForm({ ...newForm, persona: v })}
              options={[
                { value: 'operator', label: 'Operator · 自然语言操控' },
                { value: 'analyst', label: 'Analyst · 报告/查询' },
                { value: 'instructor', label: 'Instructor · 任务规划' },
              ]}
            />
          </div>
        </Space>
      </Modal>
    </Layout>
  );
}
