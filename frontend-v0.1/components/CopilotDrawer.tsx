'use client';

import React, { useEffect, useRef, useState } from 'react';
import {
  Drawer,
  Input,
  Button,
  Alert,
  Avatar,
  Space,
  Typography,
  Tag,
  message as antdMessage,
} from 'antd';
import {
  RobotOutlined,
  SendOutlined,
  UserOutlined,
  ToolOutlined,
} from '@ant-design/icons';
import {
  createSession,
  sendMessage as sendCopilotMessage,
  approveTrace,
  CopilotEvent,
} from '@/lib/copilot';

const { Text } = Typography;

export interface CopilotStep {
  id: string;
  tool: string;
  args?: any;
}

export interface CopilotMessage {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  intent?: string;
  steps?: CopilotStep[];
  traceId?: string;
  needsApproval?: boolean;
  approvalResolved?: 'approve' | 'reject';
  streaming?: boolean;
  error?: string;
}

export interface CopilotDrawerProps {
  open: boolean;
  onClose: () => void;
}

const HEADER_GRADIENT = 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)';

export default function CopilotDrawer({ open, onClose }: CopilotDrawerProps) {
  const [messages, setMessages] = useState<CopilotMessage[]>([
    {
      id: 'welcome',
      role: 'assistant',
      text: '您好，我是 SkyMaster Copilot。可以帮您规划任务、下发指令、查询设备状态。',
    },
  ]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const sessionIdRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messages]);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  const patchMessage = (id: string, patch: Partial<CopilotMessage>) => {
    setMessages((prev) =>
      prev.map((m) => (m.id === id ? { ...m, ...patch } : m)),
    );
  };

  const appendText = (id: string, chunk: string) => {
    setMessages((prev) =>
      prev.map((m) => (m.id === id ? { ...m, text: m.text + chunk } : m)),
    );
  };

  const addStep = (id: string, step: CopilotStep) => {
    setMessages((prev) =>
      prev.map((m) =>
        m.id === id ? { ...m, steps: [...(m.steps || []), step] } : m,
      ),
    );
  };

  const handleSend = async (rawText: string) => {
    const text = rawText.trim();
    if (!text || sending) return;

    const userMsg: CopilotMessage = {
      id: `u-${Date.now()}`,
      role: 'user',
      text,
    };
    const asstId = `a-${Date.now()}`;
    const asstMsg: CopilotMessage = {
      id: asstId,
      role: 'assistant',
      text: '',
      streaming: true,
    };
    setMessages((prev) => [...prev, userMsg, asstMsg]);
    setInput('');
    setSending(true);

    try {
      if (!sessionIdRef.current) {
        const { session_id } = await createSession();
        sessionIdRef.current = session_id;
      }

      abortRef.current?.abort();
      const ctrl = new AbortController();
      abortRef.current = ctrl;

      await sendCopilotMessage(
        sessionIdRef.current!,
        text,
        (evt: CopilotEvent) => handleEvent(asstId, evt),
        ctrl.signal,
      );
      patchMessage(asstId, { streaming: false });
    } catch (err: any) {
      const msg =
        err?.name === 'AbortError'
          ? '请求已取消'
          : err?.message || '与 Copilot 通信失败';
      patchMessage(asstId, { streaming: false, error: msg });
      antdMessage.error(msg);
    } finally {
      setSending(false);
    }
  };

  const handleEvent = (asstId: string, evt: CopilotEvent) => {
    switch (evt.type) {
      case 'intent': {
        const intent =
          typeof evt.data === 'string'
            ? evt.data
            : evt.data?.intent || JSON.stringify(evt.data);
        patchMessage(asstId, { intent });
        break;
      }
      case 'step': {
        const tool =
          evt.data?.tool || evt.data?.name || evt.data?.action || 'step';
        addStep(asstId, {
          id: evt.data?.id || `s-${Date.now()}-${Math.random()}`,
          tool,
          args: evt.data?.args ?? evt.data?.input,
        });
        break;
      }
      case 'token': {
        const chunk =
          typeof evt.data === 'string'
            ? evt.data
            : evt.data?.text ?? evt.data?.token ?? '';
        if (chunk) appendText(asstId, chunk);
        break;
      }
      case 'approval_required': {
        const traceId = evt.data?.trace_id || evt.data?.traceId;
        patchMessage(asstId, { needsApproval: true, traceId });
        break;
      }
      case 'done': {
        patchMessage(asstId, { streaming: false });
        break;
      }
      case 'error': {
        const msg =
          typeof evt.data === 'string'
            ? evt.data
            : evt.data?.message || '后端错误';
        patchMessage(asstId, { error: msg, streaming: false });
        break;
      }
    }
  };

  const handleApproval = async (
    msgId: string,
    traceId: string | undefined,
    decision: 'approve' | 'reject',
  ) => {
    if (!traceId) return;
    try {
      await approveTrace(traceId, decision);
      patchMessage(msgId, {
        needsApproval: false,
        approvalResolved: decision,
      });
      antdMessage.success(decision === 'approve' ? '已批准' : '已驳回');
    } catch (err: any) {
      antdMessage.error(err?.message || '审批失败');
    }
  };

  return (
    <Drawer
      title={null}
      width={480}
      placement="right"
      open={open}
      onClose={onClose}
      closable={false}
      headerStyle={{ display: 'none' }}
      bodyStyle={{
        padding: 0,
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
      }}
    >
      <div
        style={{
          background: HEADER_GRADIENT,
          color: '#fff',
          padding: '20px 24px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <Space>
          <RobotOutlined style={{ fontSize: 22 }} />
          <div>
            <div style={{ fontSize: 16, fontWeight: 600 }}>SkyMaster Copilot</div>
            <div style={{ fontSize: 12, opacity: 0.85 }}>
              AI 副驾 · 任务与指令助手
            </div>
          </div>
        </Space>
        <Button type="text" style={{ color: '#fff' }} onClick={onClose}>
          关闭
        </Button>
      </div>

      <div
        ref={listRef}
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: 16,
          background: '#0d1117',
        }}
      >
        {messages.map((m) => (
          <MessageBubble
            key={m.id}
            msg={m}
            onApprove={(d) => handleApproval(m.id, m.traceId, d)}
          />
        ))}
      </div>

      <div
        style={{
          borderTop: '1px solid #21262d',
          padding: 12,
          background: 'var(--sm-bg-secondary, #161b22)',
        }}
      >
        <Space.Compact style={{ width: '100%' }}>
          <Input.TextArea
            autoSize={{ minRows: 1, maxRows: 4 }}
            value={input}
            placeholder="向 Copilot 发送指令…"
            disabled={sending}
            onChange={(e) => setInput(e.target.value)}
            onPressEnter={(e) => {
              if (!e.shiftKey) {
                e.preventDefault();
                handleSend(input);
              }
            }}
          />
          <Button
            type="primary"
            icon={<SendOutlined />}
            loading={sending}
            onClick={() => handleSend(input)}
          >
            发送
          </Button>
        </Space.Compact>
        <Text type="secondary" style={{ fontSize: 12 }}>
          回车发送，Shift+Enter 换行。
        </Text>
      </div>
    </Drawer>
  );
}

function MessageBubble({
  msg,
  onApprove,
}: {
  msg: CopilotMessage;
  onApprove: (decision: 'approve' | 'reject') => void;
}) {
  const isUser = msg.role === 'user';
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: isUser ? 'row-reverse' : 'row',
        marginBottom: 12,
        gap: 8,
      }}
    >
      <Avatar
        size={32}
        icon={isUser ? <UserOutlined /> : <RobotOutlined />}
        style={{
          background: isUser
            ? '#1677ff'
            : 'linear-gradient(135deg,#667eea,#764ba2)',
          flexShrink: 0,
        }}
      />
      <div style={{ maxWidth: 360, display: 'flex', flexDirection: 'column', gap: 6 }}>
        {msg.intent && (
          <Tag color="default" style={{ alignSelf: isUser ? 'flex-end' : 'flex-start' }}>
            识别意图: {msg.intent}
          </Tag>
        )}
        {msg.steps?.map((s) => (
          <div
            key={s.id}
            style={{
              padding: '6px 10px',
              borderRadius: 6,
              background: '#161b22',
              border: '1px solid #30363d',
              fontSize: 12,
              color: '#c9d1d9',
            }}
          >
            <Space size={4}>
              <ToolOutlined style={{ color: '#a78bfa' }} />
              <b>{s.tool}</b>
            </Space>
            {s.args && (
              <div
                style={{
                  marginTop: 4,
                  fontFamily: 'monospace',
                  fontSize: 11,
                  color: '#8b949e',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-all',
                }}
              >
                {typeof s.args === 'string' ? s.args : JSON.stringify(s.args)}
              </div>
            )}
          </div>
        ))}
        {(msg.text || msg.streaming) && (
          <div
            style={{
              padding: '8px 12px',
              borderRadius: 8,
              background: isUser ? '#1677ff' : '#21262d',
              color: '#fff',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              fontSize: 14,
              lineHeight: 1.5,
            }}
          >
            {msg.text || (msg.streaming ? '…' : '')}
            {msg.streaming && msg.text ? '▍' : ''}
          </div>
        )}
        {msg.needsApproval && (
          <Alert
            type="warning"
            showIcon
            message="该操作需人工审批后才能下发"
            style={{ marginTop: 4 }}
            action={
              <Space>
                <Button size="small" type="primary" onClick={() => onApprove('approve')}>
                  批准
                </Button>
                <Button size="small" danger onClick={() => onApprove('reject')}>
                  驳回
                </Button>
              </Space>
            }
          />
        )}
        {msg.approvalResolved && (
          <Tag color={msg.approvalResolved === 'approve' ? 'green' : 'red'}>
            {msg.approvalResolved === 'approve' ? '已批准' : '已驳回'}
          </Tag>
        )}
        {msg.error && (
          <Alert type="error" showIcon message={msg.error} style={{ marginTop: 4 }} />
        )}
      </div>
    </div>
  );
}
