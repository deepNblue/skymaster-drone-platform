'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { ConfigProvider, theme as antdTheme, Button, Select, Tag, message, Tooltip } from 'antd';
import {
  RocketOutlined,
  SafetyCertificateOutlined,
  WarningOutlined,
  ReloadOutlined,
  VideoCameraOutlined,
  ArrowUpOutlined,
} from '@ant-design/icons';
import { api } from '@/lib/api';

// DJI 摇杆控制面板：双虚拟摇杆 → DRC 实时指令 → 后端 DJICloudConnector
// 左杆：油门(上下) / 偏航(左右)；右杆：俯仰(上下) / 横滚(左右)

const DARK_BG = '#0b1220';
const PANEL_BG = '#111a2c';
const PANEL_BORDER = '#1c2942';
const ACCENT = '#2b7fff';
const GREEN = '#52c41a';
const AMBER = '#faad14';
const RED = '#ff4d4f';

type Axes = { throttle: number; yaw: number; pitch: number; roll: number };
const NEUTRAL: Axes = { throttle: 0, yaw: 0, pitch: 0, roll: 0 };

type DrcAck = {
  seq: number;
  axes: Axes;
  state: string;
  latency_ms: number | null;
  at: number;
};
type DrcPending = {
  seq: number;
  axes: Axes;
  age_ms: number;
  timed_out: boolean;
};
type DjiStatus = {
  available: boolean;
  mode: string;
  gateway_sn: string;
  connected: boolean;
  aircraft: string[];
  last_drc: Record<string, Axes>;
  drc_link?: {
    seq: number;
    last_ack: Record<string, DrcAck>;
    pending: Record<string, DrcPending>;
    ack_timeout_ms: number;
  };
  states: Record<string, string>;
  reconnect_attempt: number;
};

// ---- 单个摇杆组件 ----------------------------------------------------------
function Joystick({
  x, y, onMove, onRelease, label, xLabel, yLabel, color = ACCENT,
}: {
  x: number; y: number;
  onMove: (x: number, y: number) => void;
  onRelease: () => void;
  label: string; xLabel: string; yLabel: string; color?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);

  const update = useCallback((clientX: number, clientY: number) => {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const cx = r.left + r.width / 2;
    const cy = r.top + r.height / 2;
    const radius = r.width / 2 - 14;
    let dx = (clientX - cx) / radius;
    let dy = (clientY - cy) / radius;
    const mag = Math.hypot(dx, dy);
    if (mag > 1) { dx /= mag; dy /= mag; }
    onMove(Math.round(dx * 1000) / 1000, Math.round(-dy * 1000) / 1000);
  }, [onMove]);

  useEffect(() => {
    const move = (e: PointerEvent) => { if (dragging.current) update(e.clientX, e.clientY); };
    const up = () => { if (dragging.current) { dragging.current = false; onRelease(); } };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
    window.addEventListener('pointercancel', up);
    return () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      window.removeEventListener('pointercancel', up);
    };
  }, [update, onRelease]);

  return (
    <div style={{ textAlign: 'center', userSelect: 'none' }}>
      <div style={{ color: '#9fb3d1', fontSize: 12, marginBottom: 8, letterSpacing: 1 }}>{label}</div>
      <div
        ref={ref}
        onPointerDown={(e) => {
          dragging.current = true;
          (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
          update(e.clientX, e.clientY);
        }}
        style={{
          position: 'relative', width: 180, height: 180, borderRadius: '50%',
          margin: '0 auto', cursor: 'grab', touchAction: 'none',
          background: 'radial-gradient(circle, #162442 0%, #0d1628 70%)',
          border: `2px solid ${PANEL_BORDER}`,
          boxShadow: 'inset 0 0 30px rgba(0,0,0,.5)',
        }}
      >
        {/* 十字准线 */}
        <div style={{ position: 'absolute', left: '50%', top: 10, bottom: 10, width: 1, background: '#22314d' }} />
        <div style={{ position: 'absolute', top: '50%', left: 10, right: 10, height: 1, background: '#22314d' }} />
        <div style={{ position: 'absolute', inset: 24, borderRadius: '50%', border: '1px dashed #1e2c46' }} />
        {/* 摇杆帽 */}
        <div
          style={{
            position: 'absolute', left: '50%', top: '50%', width: 52, height: 52,
            borderRadius: '50%',
            background: `radial-gradient(circle at 35% 30%, ${color}, #0d1b33)`,
            border: '2px solid rgba(255,255,255,.25)',
            boxShadow: '0 4px 14px rgba(0,0,0,.6)',
            transform: `translate(calc(-50% + ${x * 62}px), calc(-50% + ${-y * 62}px))`,
            transition: dragging.current ? 'none' : 'transform .12s ease-out',
          }}
        />
      </div>
      <div style={{ marginTop: 10, fontFamily: 'monospace', fontSize: 12, color: '#7f96b8' }}>
        {xLabel} <b style={{ color }}>{x.toFixed(2)}</b> &nbsp;|&nbsp; {yLabel} <b style={{ color }}>{y.toFixed(2)}</b>
      </div>
    </div>
  );
}

export default function DjiControlPage() {
  const [status, setStatus] = useState<DjiStatus | null>(null);
  const [selected, setSelected] = useState<string>('');
  const [axes, setAxes] = useState<Axes>(NEUTRAL);
  const [sending, setSending] = useState(false);
  const [err, setErr] = useState<string>('');

  const fetchStatus = useCallback(async () => {
    try {
      const { data } = await api.get('/api/v1/dji/status');
      setStatus(data);
      setErr('');
      if (!selected && data.aircraft?.length) setSelected(data.aircraft[0]);
    } catch (e: any) {
      setErr(e?.response?.data?.detail || '无法连接 DJI 控制服务');
    }
  }, [selected]);

  // 有待确认指令时加快轮询，让回执状态及时刷新
  const hasPending = !!(
    status?.drc_link?.pending && Object.keys(status.drc_link.pending).length
  );

  useEffect(() => { fetchStatus(); }, [fetchStatus]);

  useEffect(() => {
    const t = setInterval(fetchStatus, hasPending ? 500 : 4000);
    return () => clearInterval(t);
  }, [fetchStatus, hasPending]);

  // 当前四轴：左杆 = 油门(throttle)/偏航(yaw)，右杆 = 俯仰(pitch)/横滚(roll)
  // 用 ref 保存最新值，避免高频发送闭包读到旧值
  const axesRef = useRef<Axes>(NEUTRAL);
  const selectedRef = useRef<string>('');
  useEffect(() => { axesRef.current = axes; }, [axes]);
  useEffect(() => { selectedRef.current = selected; }, [selected]);
  const timerRef = useRef<number | null>(null);

  const sendDrc = useCallback(async (a: Axes) => {
    const sn = selectedRef.current;
    if (!sn || sending) return;
    setSending(true);
    try {
      await api.post('/api/v1/dji/drc', { drone_sn: sn, ...a });
    } catch (e: any) {
      setErr(e?.response?.data?.detail || 'DRC 指令发送失败');
    } finally {
      setSending(false);
    }
  }, [sending]);

  // 摇杆移动：更新 UI + 启动 100ms 周期发送
  const startSending = useCallback(() => {
    if (timerRef.current != null) return;
    timerRef.current = window.setInterval(() => sendDrc(axesRef.current), 100);
  }, [sendDrc]);
  const stopSending = useCallback(() => {
    if (timerRef.current != null) { clearInterval(timerRef.current); timerRef.current = null; }
  }, []);
  useEffect(() => () => stopSending(), [stopSending]);

  const onLeft = useCallback((x: number, y: number) => {
    setAxes((a) => ({ ...a, yaw: x, throttle: y }));
    startSending();
  }, [startSending]);
  const onRight = useCallback((x: number, y: number) => {
    setAxes((a) => ({ ...a, roll: x, pitch: y }));
    startSending();
  }, [startSending]);
  const onRelease = useCallback(() => {
    stopSending();
    setAxes(NEUTRAL);
    sendDrc(NEUTRAL); // 松手回中
    setTimeout(fetchStatus, 300);
  }, [stopSending, sendDrc, fetchStatus]);

  const doAction = async (action: string) => {
    if (!selected) return;
    try {
      await api.post('/api/v1/dji/action', { action, drone_sn: selected });
      message.success(`已下发：${action}`);
      setTimeout(fetchStatus, 300);
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '指令失败');
    }
  };

  const lastDrc = selected && status?.last_drc?.[selected] ? status.last_drc[selected] : null;
  const drcAck = selected ? status?.drc_link?.last_ack?.[selected] || null : null;
  const drcPending = selected ? status?.drc_link?.pending?.[selected] || null : null;
  const aircraft = status?.aircraft || [];

  return (
    <ConfigProvider theme={{ algorithm: antdTheme.darkAlgorithm, token: { colorPrimary: ACCENT } }}>
      <div style={{ minHeight: '100vh', background: DARK_BG, color: '#e6eefb', padding: 24 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
          <RocketOutlined style={{ fontSize: 24, color: ACCENT }} />
          <div>
            <h1 style={{ margin: 0, fontSize: 22 }}>DJI 摇杆控制面板</h1>
            <div style={{ color: '#7f96b8', fontSize: 12, marginTop: 2 }}>
              虚拟遥控器 · DRC 实时指令 · {status?.mode || '--'} 模式
            </div>
          </div>
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
            {status?.available ? (
              <Tag color={status.connected || status.mode === 'mock' ? 'green' : 'orange'}>
                {status.mode === 'mock' ? 'MOCK 仿真' : status.connected ? 'MQTT 已连接' : '重连中'}
              </Tag>
            ) : <Tag color="red">服务不可用</Tag>}
            <Tooltip title="刷新状态"><Button icon={<ReloadOutlined />} onClick={fetchStatus} size="small" /></Tooltip>
          </div>
        </div>

        {/* 安全警告 */}
        <div style={{
          background: 'linear-gradient(90deg, rgba(250,173,20,.14), transparent)',
          border: `1px solid ${AMBER}`, borderRadius: 8, padding: '10px 16px',
          marginBottom: 20, color: '#ffd591', fontSize: 13, display: 'flex', gap: 10, alignItems: 'center',
        }}>
          <WarningOutlined style={{ fontSize: 18 }} />
          <span>
            <b>安全提示：</b>当前 DRC 指令直接控制飞行器。真机模式下油门/俯仰/横滚会驱动电机——
            务必先在模拟器或安全空域验证轴方向与量程。Mock 模式仅更新仿真状态。
          </span>
        </div>

        {err && (
          <div style={{ background: 'rgba(255,77,79,.12)', border: `1px solid ${RED}`,
            borderRadius: 8, padding: '8px 16px', marginBottom: 16, color: '#ffa39e' }}>{err}</div>
        )}

        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 420px) 1fr', gap: 20 }}>
          {/* 左：摇杆区 */}
          <div style={{ background: PANEL_BG, border: `1px solid ${PANEL_BORDER}`, borderRadius: 12, padding: 20 }}>
            <div style={{ fontSize: 13, color: '#9fb3d1', marginBottom: 14 }}>
              飞行器选择 &nbsp;
              <Select
                value={selected || undefined}
                onChange={setSelected}
                placeholder="选择无人机"
                style={{ width: 220 }}
                options={aircraft.map((sn) => ({ value: sn, label: sn }))}
              />
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-around', gap: 16 }}>
              <Joystick
                label="左杆 · 油门/偏航" xLabel="YAW" yLabel="THR"
                x={axes.yaw} y={axes.throttle} onMove={onLeft} onRelease={onRelease} color={ACCENT}
              />
              <Joystick
                label="右杆 · 俯仰/横滚" xLabel="ROL" yLabel="PIT"
                x={axes.roll} y={axes.pitch} onMove={onRight} onRelease={onRelease} color="#36cfc9"
              />
            </div>
            <div style={{ textAlign: 'center', color: '#5f759a', fontSize: 11, marginTop: 16 }}>
              拖动摇杆持续下发（100ms），松开自动回中
            </div>
          </div>

          {/* 右：状态与指令区 */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
            <div style={{ background: PANEL_BG, border: `1px solid ${PANEL_BORDER}`, borderRadius: 12, padding: 20 }}>
              <h3 style={{ margin: '0 0 16px', fontSize: 15 }}>
                <SafetyCertificateOutlined style={{ color: GREEN, marginRight: 8 }} />实时轴值 / DRC
              </h3>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
                {([['THR', axes.throttle, ACCENT], ['YAW', axes.yaw, ACCENT],
                   ['PIT', axes.pitch, '#36cfc9'], ['ROL', axes.roll, '#36cfc9']] as const).map(([k, v, c]) => (
                  <div key={k} style={{ background: '#0d1628', borderRadius: 8, padding: 12, textAlign: 'center' }}>
                    <div style={{ color: '#7f96b8', fontSize: 11 }}>{k}</div>
                    <div style={{ fontFamily: 'monospace', fontSize: 20, color: c, marginTop: 4 }}>{v.toFixed(2)}</div>
                    <div style={{ height: 4, background: '#1c2942', borderRadius: 2, marginTop: 8, overflow: 'hidden' }}>
                      <div style={{ height: '100%', width: `${Math.abs(v) * 100}%`, background: c,
                        marginLeft: v < 0 ? `${50 - Math.abs(v) * 50}%` : '50%' }} />
                    </div>
                  </div>
                ))}
              </div>
              {lastDrc && (
                <div style={{ marginTop: 14, color: '#7f96b8', fontSize: 12, fontFamily: 'monospace' }}>
                  后端回显 DRC：THR {lastDrc.throttle?.toFixed(2)} / YAW {lastDrc.yaw?.toFixed(2)} /
                  PIT {lastDrc.pitch?.toFixed(2)} / ROL {lastDrc.roll?.toFixed(2)}
                </div>
              )}
              <div style={{
                marginTop: 12, paddingTop: 12, borderTop: `1px solid ${PANEL_BORDER}`,
                display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
              }}>
                <span style={{ color: '#9fb3d1', fontSize: 12 }}>指令回执</span>
                {drcPending ? (
                  <Tag color={drcPending.timed_out ? 'red' : 'processing'}>
                    等待回执 · seq {drcPending.seq} · {drcPending.age_ms.toFixed(0)}ms
                  </Tag>
                ) : drcAck ? (
                  <>
                    <Tag color={drcAck.state === 'acked' ? 'green' : 'red'}>
                      {drcAck.state === 'acked' ? '已回执' : drcAck.state === 'timeout' ? '回执超时' : '发送失败'}
                      {` · seq ${drcAck.seq}`}
                      {drcAck.latency_ms != null && ` · ${drcAck.latency_ms.toFixed(0)}ms`}
                    </Tag>
                    <span style={{ color: '#5f759a', fontSize: 11, fontFamily: 'monospace' }}>
                      执行轴 THR {drcAck.axes?.throttle?.toFixed(2)} / YAW {drcAck.axes?.yaw?.toFixed(2)} /
                      PIT {drcAck.axes?.pitch?.toFixed(2)} / ROL {drcAck.axes?.roll?.toFixed(2)}
                    </span>
                  </>
                ) : (
                  <Tag>暂无回执</Tag>
                )}
              </div>
            </div>

            <div style={{ background: PANEL_BG, border: `1px solid ${PANEL_BORDER}`, borderRadius: 12, padding: 20 }}>
              <h3 style={{ margin: '0 0 16px', fontSize: 15 }}>快捷指令</h3>
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                <Button icon={<ArrowUpOutlined />} onClick={() => doAction('return_home')} disabled={!selected}>
                  一键返航
                </Button>
                <Button onClick={() => doAction('hover')} disabled={!selected}>悬停（回中）</Button>
                <Button icon={<VideoCameraOutlined />}
                  onClick={() => doAction('live_start')} disabled={!selected}>开始直播推流</Button>
              </div>
              <div style={{ marginTop: 14, color: '#5f759a', fontSize: 12 }}>
                连接器：{status?.gateway_sn || '--'} · 飞机 {aircraft.length} 台 ·
                重连次数 {status?.reconnect_attempt ?? 0}
              </div>
            </div>
          </div>
        </div>
      </div>
    </ConfigProvider>
  );
}
