'use client';

/**
 * CopilotV2Drawer — T4.2 前端消费 v2 Function Calling loop 的 SSE 流。
 *
 * 相比 v1 的 CopilotDrawer：
 *   - 使用 sendV2Message → /copilot/v2/sessions/{sid}/messages
 *   - 处理 status / text / tool / approval_required / error / done 事件
 *   - 敏感工具触发 approval_required 后，就地弹出批准/驳回/修改 UI
 *   - 批准/驳回后调用 decideV2Approval，并把结果 append 到对话
 */
import React, { useEffect, useRef, useState } from 'react';
import {
  Drawer,
  Input,
  Button,
  Alert,
  Space,
  Typography,
  Tag,
  Card,
  message as antdMessage,
  Popconfirm,
} from 'antd';
import {
  RobotOutlined,
  SendOutlined,
  UserOutlined,
  ToolOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  EditOutlined,
} from '@ant-design/icons';
import {
  createSession,
  sendV2Message,
  decideV2Approval,
  CopilotV2Event,
} from '@/lib/copilot_v2';
import VisionToolResult from './VisionToolResult';

const { Text, Paragraph } = Typography;

export interface ToolStep {
  id: string;
  name: string;
  event: 'start' | 'end' | 'error';
  args?: any;
  result?: any;
}

export interface PendingApproval {
  approval_id: string;
  tool: string;
  arguments: Record<string, any>;
  resolved?: 'approved' | 'rejected' | 'modified';
  result?: any;
  is_error?: boolean;
}

export interface V2Message {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  status?: string;
  steps?: ToolStep[];
  approvals?: PendingApproval[];
  streaming?: boolean;
  error?: string;
  stoppedReason?: string;
}

export interface CopilotV2DrawerProps {
  open: boolean;
  onClose: () => void;
}

const HEADER_GRADIENT = 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)';

export default function CopilotV2Drawer({ open, onClose }: CopilotV2DrawerProps) {
  const [messages, setMessages] = useState<V2Message[]>([
    {
      id: 'welcome',
      role: 'assistant',
      text: '您好，我是 SkyMaster Copilot v2。可以帮您查询无人机 / 空域 / 气象，规划、下发或中止飞行任务。敏感操作会先向您确认。',
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

  useEffect(
    () => () => {
      abortRef.current?.abort();
    },
    [],
  );

  const patch = (id: string, p: Partial<V2Message>) =>
    setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, ...p } : m)));

  const addStep = (id: string, step: ToolStep) =>
    setMessages((prev) =>
      prev.map((m) => {
        if (m.id !== id) return m;
        // If this step already exists by name+start, mark its end/error instead of duplicating
        const existing = (m.steps || []).find(
          (s) => s.name === step.name && s.event === 'start',
        );
        if (existing && step.event !== 'start') {
          return {
            ...m,
            steps: (m.steps || []).map((s) =>
              s === existing ? { ...s, event: step.event, result: step.result } : s,
            ),
          };
        }
        return { ...m, steps: [...(m.steps || []), step] };
      }),
    );

  const addApproval = (id: string, ap: PendingApproval) =>
    setMessages((prev) =>
      prev.map((m) =>
        m.id === id
          ? { ...m, approvals: [...(m.approvals || []), ap] }
          : m,
      ),
    );

  const patchApproval = (
    msgId: string,
    approvalId: string,
    p: Partial<PendingApproval>,
  ) =>
    setMessages((prev) =>
      prev.map((m) =>
        m.id === msgId
          ? {
              ...m,
              approvals: (m.approvals || []).map((a) =>
                a.approval_id === approvalId ? { ...a, ...p } : a,
              ),
            }
          : m,
      ),
    );

  const handleEvent = (asstId: string, evt: CopilotV2Event) => {
    switch (evt.type) {
      case 'status':
        patch(asstId, { status: evt.data?.stage });
        break;
      case 'text': {
        const chunk = typeof evt.data === 'string' ? evt.data : evt.data?.text ?? '';
        if (chunk) {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === asstId ? { ...m, text: (m.text || '') + chunk } : m,
            ),
          );
        }
        break;
      }
      case 'tool': {
        addStep(asstId, {
          id: `${evt.data?.name}-${Date.now()}-${Math.random()}`,
          name: evt.data?.name || 'tool',
          event: (evt.data?.event as any) || 'start',
          args: evt.data?.arguments,
          result: evt.data?.result,
        });
        break;
      }
      case 'approval_required': {
        addApproval(asstId, {
          approval_id: evt.data?.approval_id,
          tool: evt.data?.tool,
          arguments: evt.data?.arguments || {},
        });
        break;
      }
      case 'error': {
        const msg =
          typeof evt.data === 'string'
            ? evt.data
            : evt.data?.error || evt.data?.message || '后端错误';
        patch(asstId, { error: msg, streaming: false });
        break;
      }
      case 'done': {
        patch(asstId, {
          streaming: false,
          stoppedReason: evt.data?.stopped_reason,
        });
        break;
      }
    }
  };

  const handleSend = async (rawText: string) => {
    const text = rawText.trim();
    if (!text || sending) return;

    const userMsg: V2Message = { id: `u-${Date.now()}`, role: 'user', text };
    const asstId = `a-${Date.now()}`;
    const asstMsg: V2Message = {
      id: asstId,
      role: 'assistant',
      text: '',
      streaming: true,
      status: 'llm_call',
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

      await sendV2Message(
        sessionIdRef.current!,
        text,
        (evt) => handleEvent(asstId, evt),
        ctrl.signal,
      );
      patch(asstId, { streaming: false });
    } catch (err: any) {
      const msg =
        err?.name === 'AbortError'
          ? '请求已取消'
          : err?.message || '与 Copilot v2 通信失败';
      patch(asstId, { streaming: false, error: msg });
      antdMessage.error(msg);
    } finally {
      setSending(false);
    }
  };

  const handleApprovalDecision = async (
    msgId: string,
    approval: PendingApproval,
    decision: 'approved' | 'rejected' | 'modified',
    modifications?: Record<string, any>,
    comment?: string,
  ) => {
    try {
      const res = await decideV2Approval(approval.approval_id, {
        decision,
        modifications,
        comment,
      });
      patchApproval(msgId, approval.approval_id, {
        resolved: decision,
        result: res.result,
        is_error: res.is_error,
      });
      antdMessage.success(
        decision === 'approved'
          ? '已批准并执行'
          : decision === 'rejected'
            ? '已驳回'
            : '已按修改后参数执行',
      );
    } catch (e: any) {
      antdMessage.error(e?.message || '审批操作失败');
    }
  };

  return (
    <Drawer
      title={null}
      width={520}
      placement="right"
      open={open}
      onClose={onClose}
      closable={false}
      styles={{
        header: { display: 'none' },
        body: {
          padding: 0,
          display: 'flex',
          flexDirection: 'column',
          height: '100%',
        },
      }}
    >
      {/* Header */}
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
          <RobotOutlined style={{ fontSize: 24 }} />
          <div>
            <div style={{ fontSize: 16, fontWeight: 600 }}>SkyMaster Copilot v2</div>
            <Text style={{ color: 'rgba(255,255,255,0.85)', fontSize: 12 }}>
              Function Calling · 敏感操作审批
            </Text>
          </div>
        </Space>
        <Button type="text" style={{ color: '#fff' }} onClick={onClose}>
          关闭
        </Button>
      </div>

      {/* Message list */}
      <div
        ref={listRef}
        style={{
          flex: 1,
          overflow: 'auto',
          padding: 16,
          background: 'var(--sm-bg, #0d1117)',
        }}
      >
        {messages.map((m) => (
          <MessageBubble
            key={m.id}
            msg={m}
            onDecide={(ap, dec, mods, cmt) =>
              handleApprovalDecision(m.id, ap, dec, mods, cmt)
            }
          />
        ))}
      </div>

      {/* Composer */}
      <div style={{ padding: 12, borderTop: '1px solid var(--sm-border, #30363d)' }}>
        <Space.Compact style={{ width: '100%' }}>
          <Input
            placeholder="试试：'查一下 D1 状态' 或 '为 D1 创建一条到 X 点的巡逻任务'"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onPressEnter={() => handleSend(input)}
            disabled={sending}
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
      </div>
    </Drawer>
  );
}

// ---------------------------------------------------------------------------
// Bubble
// ---------------------------------------------------------------------------

interface BubbleProps {
  msg: V2Message;
  onDecide: (
    ap: PendingApproval,
    decision: 'approved' | 'rejected' | 'modified',
    modifications?: Record<string, any>,
    comment?: string,
  ) => void;
}

function MessageBubble({ msg, onDecide }: BubbleProps) {
  const isUser = msg.role === 'user';
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: isUser ? 'flex-end' : 'flex-start',
        marginBottom: 12,
      }}
    >
      <div style={{ maxWidth: '85%' }}>
        {!isUser && (
          <Space size={4} style={{ marginBottom: 4 }}>
            <RobotOutlined style={{ color: '#764ba2' }} />
            <Text type="secondary" style={{ fontSize: 11 }}>
              Copilot
            </Text>
            {msg.status && msg.streaming && (
              <Tag color="processing" style={{ fontSize: 10, margin: 0 }}>
                {msg.status}
              </Tag>
            )}
          </Space>
        )}
        <div
          style={{
            background: isUser ? '#1677ff' : 'var(--sm-panel, #161b22)',
            color: isUser ? '#fff' : 'inherit',
            padding: '10px 14px',
            borderRadius: 12,
            border: isUser ? undefined : '1px solid var(--sm-border, #30363d)',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
          }}
        >
          {msg.text || (msg.streaming ? '…' : '')}
          {msg.streaming && <span style={{ opacity: 0.6 }}>▍</span>}
        </div>

        {/* Tool steps */}
        {msg.steps && msg.steps.length > 0 && (
          <div style={{ marginTop: 6 }}>
            {msg.steps.map((s) => {
              const vision =
                s.event === 'end' && s.result
                  ? (s.name === 'list_detections' ||
                      s.name === 'detection_stats')
                  : false;
              return (
                <div key={s.id} style={{ fontSize: 12, opacity: 0.85 }}>
                  <div>
                    <ToolOutlined style={{ marginRight: 4 }} />
                    <Tag
                      color={
                        s.event === 'error'
                          ? 'red'
                          : s.event === 'end'
                            ? 'green'
                            : 'blue'
                      }
                      style={{ fontSize: 11 }}
                    >
                      {s.name}
                    </Tag>
                    {!vision && s.result && (
                      <Text
                        type="secondary"
                        style={{ fontSize: 11 }}
                        code
                        ellipsis={{ tooltip: JSON.stringify(s.result) }}
                      >
                        {JSON.stringify(s.result).slice(0, 60)}
                      </Text>
                    )}
                  </div>
                  {vision && (
                    <VisionToolResult name={s.name} result={s.result} />
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* Pending approvals */}
        {msg.approvals && msg.approvals.length > 0 && (
          <div style={{ marginTop: 8 }}>
            {msg.approvals.map((ap) => (
              <ApprovalCard
                key={ap.approval_id}
                approval={ap}
                onDecide={onDecide}
              />
            ))}
          </div>
        )}

        {/* Errors */}
        {msg.error && (
          <Alert
            type="error"
            message={msg.error}
            style={{ marginTop: 6 }}
            showIcon
          />
        )}

        {/* Stopped reason */}
        {msg.stoppedReason &&
          msg.stoppedReason !== 'end' &&
          msg.stoppedReason !== 'approval_required' && (
            <Tag color="orange" style={{ marginTop: 6 }}>
              stopped: {msg.stoppedReason}
            </Tag>
          )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Approval card — inline UI for sensitive tool decision
// ---------------------------------------------------------------------------

interface ApprovalCardProps {
  approval: PendingApproval;
  onDecide: BubbleProps['onDecide'];
}

function ApprovalCard({ approval, onDecide }: ApprovalCardProps) {
  const [modifyOpen, setModifyOpen] = useState(false);
  const [modifiedArgs, setModifiedArgs] = useState<string>(() =>
    JSON.stringify(approval.arguments, null, 2),
  );
  const [comment, setComment] = useState('');

  if (approval.resolved) {
    return (
      <Card size="small" style={{ marginTop: 6 }} bordered>
        <Space>
          <Tag
            color={
              approval.resolved === 'rejected'
                ? 'red'
                : approval.is_error
                  ? 'orange'
                  : 'green'
            }
            icon={
              approval.resolved === 'rejected' ? (
                <CloseCircleOutlined />
              ) : (
                <CheckCircleOutlined />
              )
            }
          >
            {approval.tool} · {approval.resolved}
          </Tag>
          {approval.result && (
            <Text
              type="secondary"
              style={{ fontSize: 11 }}
              code
              ellipsis={{ tooltip: JSON.stringify(approval.result) }}
            >
              {JSON.stringify(approval.result).slice(0, 80)}
            </Text>
          )}
        </Space>
      </Card>
    );
  }

  return (
    <Card
      size="small"
      style={{ marginTop: 6, borderColor: '#faad14' }}
      title={
        <Space>
          <Tag color="warning">敏感操作待批准</Tag>
          <Text strong>{approval.tool}</Text>
        </Space>
      }
    >
      <pre
        style={{
          background: 'rgba(0,0,0,0.15)',
          padding: 8,
          borderRadius: 6,
          fontSize: 11,
          margin: 0,
          maxHeight: 160,
          overflow: 'auto',
        }}
      >
        {JSON.stringify(approval.arguments, null, 2)}
      </pre>

      {modifyOpen && (
        <>
          <Text type="secondary" style={{ fontSize: 11, display: 'block', marginTop: 8 }}>
            修改参数（合并到原参数上，JSON）
          </Text>
          <Input.TextArea
            rows={5}
            value={modifiedArgs}
            onChange={(e) => setModifiedArgs(e.target.value)}
            style={{ fontFamily: 'monospace', fontSize: 12, marginTop: 4 }}
          />
        </>
      )}

      <Space style={{ marginTop: 10 }}>
        <Popconfirm
          title="确认按当前参数执行？"
          onConfirm={() => onDecide(approval, 'approved')}
          okText="批准"
          cancelText="取消"
        >
          <Button size="small" type="primary" icon={<CheckCircleOutlined />}>
            批准
          </Button>
        </Popconfirm>
        <Button
          size="small"
          icon={<EditOutlined />}
          onClick={() => {
            if (!modifyOpen) {
              setModifyOpen(true);
              return;
            }
            try {
              const parsed = JSON.parse(modifiedArgs);
              onDecide(approval, 'modified', parsed);
            } catch {
              antdMessage.error('修改后的参数不是合法 JSON');
            }
          }}
        >
          {modifyOpen ? '按修改执行' : '修改'}
        </Button>
        <Popconfirm
          title="驳回该敏感操作？"
          description={
            <Input
              placeholder="备注（可选）"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              size="small"
            />
          }
          onConfirm={() => onDecide(approval, 'rejected', undefined, comment)}
          okText="驳回"
          okButtonProps={{ danger: true }}
          cancelText="取消"
        >
          <Button size="small" danger icon={<CloseCircleOutlined />}>
            驳回
          </Button>
        </Popconfirm>
      </Space>
    </Card>
  );
}
