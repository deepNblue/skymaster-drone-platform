'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ConfigProvider, theme as antdTheme, Button, Select, Tag, Progress,
  Tooltip, message, Table,
} from 'antd';
import {
  RocketOutlined, AimOutlined, CompassOutlined, ReloadOutlined,
  WarningOutlined, CheckCircleOutlined, ClockCircleOutlined,
  CloseCircleOutlined, PlayCircleOutlined, SaveOutlined,
  ExperimentOutlined,
} from '@ant-design/icons';
import { api } from '@/lib/api';

// DJI 校准页：飞行器传感器校准状态机 + 遥控器摇杆九步采集向导。
// 所有时长 / 死区 / 采集步骤均来自后端 config/dji_calibration.json。

const DARK_BG = '#0b1220';
const PANEL_BG = '#111a2c';
const PANEL_BORDER = '#1c2942';
const ACCENT = '#2b7fff';
const GREEN = '#52c41a';
const AMBER = '#faad14';
const RED = '#ff4d4f';
const CYAN = '#36cfc9';

type CalItem = {
  key: string;
  kind: 'sensor' | 'rc';
  label: string;
  duration_s: number;
  hint: string;
};
type CalState = {
  state: string;
  progress: number;
  message?: string;
  duration_s?: number;
  updated_at?: number;
};
type CalStep = { key: string; axis: string; edge: string; label: string };
type RCAxisCal = { min: number; center: number; max: number };
type RCCal = {
  axes: Record<string, RCAxisCal>;
  deadzone: number;
  updated_at: number;
};
type CalStatus = {
  items: CalItem[];
  sensors: Record<string, Record<string, CalState>>;
  rc: Record<string, RCCal> | RCCal | null;
  config: {
    sensor_calibration: Record<string, { label: string; duration_s: number; hint: string }>;
    rc_calibration: { deadzone: number; steps: CalStep[] };
    progress_tick_s?: number;
  };
};
type Stick = { x: number; y: number };
type LogEntry = { ts: string; text: string; level: 'info' | 'ok' | 'warn' | 'err' };

const CENTER: Stick = { x: 0, y: 0 };

// ---- 摇杆组件 ------------------------------------------------------------
function Joystick({
  stick, onMove, onRelease, label, xLabel, yLabel, color = ACCENT,
}: {
  stick: Stick;
  onMove: (x: number, y: number) => void;
  onRelease: () => void;
  label: string;
  xLabel: string;
  yLabel: string;
  color?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);

  const update = useCallback((clientX: number, clientY: number) => {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const radius = r.width / 2 - 14;
    let dx = (clientX - (r.left + r.width / 2)) / radius;
    let dy = (clientY - (r.top + r.height / 2)) / radius;
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
          position: 'relative', width: 156, height: 156, borderRadius: '50%',
          margin: '0 auto', cursor: 'grab', touchAction: 'none',
          background: 'radial-gradient(circle, #162442 0%, #0d1628 70%)',
          border: `2px solid ${PANEL_BORDER}`,
          boxShadow: 'inset 0 0 26px rgba(0,0,0,.5)',
        }}
      >
        <div style={{ position: 'absolute', left: '50%', top: 10, bottom: 10, width: 1, background: '#22314d' }} />
        <div style={{ position: 'absolute', top: '50%', left: 10, right: 10, height: 1, background: '#22314d' }} />
        <div style={{ position: 'absolute', inset: 20, borderRadius: '50%', border: '1px dashed #1e2c46' }} />
        <div
          style={{
            position: 'absolute', left: '50%', top: '50%', width: 46, height: 46,
            borderRadius: '50%',
            background: `radial-gradient(circle at 35% 30%, ${color}, #0d1b33)`,
            border: '2px solid rgba(255,255,255,.25)',
            boxShadow: '0 4px 12px rgba(0,0,0,.6)',
            transform: `translate(calc(-50% + ${stick.x * 54}px), calc(-50% + ${-stick.y * 54}px))`,
            transition: dragging.current ? 'none' : 'transform .12s ease-out',
          }}
        />
      </div>
      <div style={{ marginTop: 8, fontFamily: 'monospace', fontSize: 12, color: '#7f96b8' }}>
        {xLabel} <b style={{ color }}>{stick.x.toFixed(2)}</b> &nbsp;|&nbsp;
        {yLabel} <b style={{ color }}>{stick.y.toFixed(2)}</b>
      </div>
    </div>
  );
}

function stateTag(state?: string) {
  switch (state) {
    case 'success':
      return <Tag icon={<CheckCircleOutlined />} color="green">已完成</Tag>;
    case 'running':
      return <Tag icon={<ClockCircleOutlined />} color="processing">校准中</Tag>;
    case 'cancelled':
      return <Tag icon={<CloseCircleOutlined />} color="default">已取消</Tag>;
    case 'manual':
      return <Tag icon={<ExperimentOutlined />} color="blue">待采集</Tag>;
    default:
      return <Tag color="default">未校准</Tag>;
  }
}

export default function CalibrationPage() {
  const [status, setStatus] = useState<CalStatus | null>(null);
  const [selected, setSelected] = useState('');
  const [aircraft, setAircraft] = useState<string[]>([]);
  const [err, setErr] = useState('');
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [left, setLeft] = useState<Stick>(CENTER);
  const [right, setRight] = useState<Stick>(CENTER);
  const [stepIdx, setStepIdx] = useState(0);
  const [captured, setCaptured] = useState<Record<string, number>>({});
  const [saving, setSaving] = useState(false);

  const log = useCallback((text: string, level: LogEntry['level'] = 'info') => {
    setLogs((prev) => [{
      ts: new Date().toLocaleTimeString('zh-CN', { hour12: false }),
      text, level,
    }, ...prev].slice(0, 60));
  }, []);

  const fetchStatus = useCallback(async () => {
    try {
      const params = selected ? { params: { drone_sn: selected } } : undefined;
      const { data } = await api.get('/api/v1/dji/calibration/status', params);
      setStatus(data);
      setErr('');
    } catch (e: any) {
      setErr(e?.response?.data?.detail || '无法连接 DJI 校准服务');
    }
  }, [selected]);

  useEffect(() => {
    (async () => {
      try {
        const s = await api.get('/api/v1/dji/status');
        const list: string[] = s.data?.aircraft || [];
        setAircraft(list);
        if (list.length) setSelected((prev) => prev || list[0]);
      } catch { /* 校准接口自身可用即可 */ }
    })();
  }, []);

  useEffect(() => {
    fetchStatus();
    const t = setInterval(fetchStatus, 1500);
    return () => clearInterval(t);
  }, [fetchStatus]);

  const items = useMemo(() => status?.items || [], [status]);
  const sensorItems = useMemo(() => items.filter((i) => i.kind === 'sensor'), [items]);
  const steps = useMemo(
    () => status?.config?.rc_calibration?.steps || [],
    [status],
  );
  const step = steps[stepIdx];
  const states = (selected && status?.sensors?.[selected]) || {};
  const savedRc: RCCal | null = selected && status?.rc
    ? ((status.rc as Record<string, RCCal>)[selected] || null)
    : null;

  const startCal = async (key: string) => {
    if (!selected) return;
    try {
      await api.post('/api/v1/dji/calibration/start', { drone_sn: selected, item: key });
      log(`已下发 ${key} 校准指令`, 'info');
      message.success(`${key} 校准已启动`);
      setTimeout(fetchStatus, 300);
    } catch (e: any) {
      const detail = e?.response?.data?.detail || '指令失败';
      log(`${key} 启动失败：${detail}`, 'err');
      message.error(detail);
    }
  };

  const cancelCal = async (key: string) => {
    if (!selected) return;
    try {
      await api.post('/api/v1/dji/calibration/cancel', { drone_sn: selected, item: key });
      log(`已取消 ${key} 校准`, 'warn');
      setTimeout(fetchStatus, 300);
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '取消失败');
    }
  };

  const axisValue = (axis: string): number => {
    switch (axis) {
      case 'throttle': return left.y;
      case 'yaw': return left.x;
      case 'pitch': return right.y;
      case 'roll': return right.x;
      default: return 0;
    }
  };

  const targetOk = (s?: CalStep): boolean => {
    if (!s) return false;
    if (s.edge === 'center') {
      return Math.abs(left.x) + Math.abs(left.y) + Math.abs(right.x) + Math.abs(right.y) < 0.15;
    }
    const v = axisValue(s.axis);
    return s.edge === 'max' ? v > 0.7 : v < -0.7;
  };

  const capture = () => {
    if (!step || !targetOk(step)) return;
    const value = step.edge === 'center'
      ? (left.x + left.y + right.x + right.y) / 4
      : axisValue(step.axis);
    setCaptured((prev) => ({ ...prev, [step.key]: Math.round(value * 1000) / 1000 }));
    log(`采集 ${step.label} → ${value.toFixed(2)}`, 'ok');
    setStepIdx((i) => Math.min(steps.length - 1, i + 1));
  };

  const allCaptured = steps.length > 0 && steps.every((s) => captured[s.key] !== undefined);
  const buildAxes = (): Record<string, RCAxisCal> => ({
    throttle: { min: captured.throttle_min, center: captured.center, max: captured.throttle_max },
    yaw: { min: captured.yaw_left, center: captured.center, max: captured.yaw_right },
    pitch: { min: captured.pitch_min, center: captured.center, max: captured.pitch_max },
    roll: { min: captured.roll_left, center: captured.center, max: captured.roll_right },
  });

  const saveRc = async () => {
    if (!selected || !allCaptured) return;
    setSaving(true);
    try {
      const { data } = await api.post('/api/v1/dji/calibration/rc', {
        drone_sn: selected,
        axes: buildAxes(),
      });
      log(`摇杆校准已保存（死区 ${data.deadzone}）`, 'ok');
      message.success('摇杆校准参数已保存');
      setStepIdx(0);
      setCaptured({});
      fetchStatus();
    } catch (e: any) {
      const detail = e?.response?.data?.detail || '保存失败';
      log(`保存失败：${detail}`, 'err');
      message.error(detail);
    } finally {
      setSaving(false);
    }
  };

  const resetWizard = () => {
    setStepIdx(0);
    setCaptured({});
    setLeft(CENTER);
    setRight(CENTER);
    log('已重置摇杆采集向导', 'warn');
  };

  const mapped = (axis: string, raw: number): number => {
    const cal = savedRc?.axes?.[axis];
    if (!cal || cal.max <= cal.min) return raw;
    const center = cal.center || 0;
    const span = raw >= center ? cal.max - center : center - cal.min;
    if (span <= 0) return 0;
    const v = (raw - center) / span;
    const dz = savedRc?.deadzone ?? 0.05;
    return Math.abs(v) < dz ? 0 : Math.round(Math.max(-1, Math.min(1, v)) * 100) / 100;
  };

  const rcTableColumns = [
    { title: '轴', dataIndex: 'axis', key: 'axis' },
    { title: '最小', dataIndex: 'min', key: 'min' },
    { title: '中位', dataIndex: 'center', key: 'center' },
    { title: '最大', dataIndex: 'max', key: 'max' },
    { title: '原始 → 校准后', dataIndex: 'live', key: 'live' },
  ];
  const rcTableData = (['throttle', 'yaw', 'pitch', 'roll'] as const).map((axis) => {
    const raw = axisValue(axis);
    return {
      key: axis,
      axis: { throttle: '油门 THR', yaw: '偏航 YAW', pitch: '俯仰 PIT', roll: '横滚 ROL' }[axis],
      min: savedRc?.axes?.[axis]?.min?.toFixed(2) ?? '--',
      center: savedRc?.axes?.[axis]?.center?.toFixed(2) ?? '--',
      max: savedRc?.axes?.[axis]?.max?.toFixed(2) ?? '--',
      live: `${raw.toFixed(2)} → ${mapped(axis, raw).toFixed(2)}`,
    };
  });

  return (
    <ConfigProvider theme={{ algorithm: antdTheme.darkAlgorithm, token: { colorPrimary: ACCENT } }}>
      <div style={{ minHeight: '100vh', background: DARK_BG, color: '#e6eefb', padding: 24 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
          <CompassOutlined style={{ fontSize: 24, color: ACCENT }} />
          <div>
            <h1 style={{ margin: 0, fontSize: 22 }}>校准中心</h1>
            <div style={{ color: '#7f96b8', fontSize: 12, marginTop: 2 }}>
              传感器校准状态机 · 遥控器摇杆九点采集 · 参数独立持久化
            </div>
          </div>
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
            <Select
              value={selected || undefined}
              onChange={(v) => { setSelected(v); setStepIdx(0); setCaptured({}); }}
              placeholder="选择飞行器"
              style={{ width: 220 }}
              options={aircraft.map((sn) => ({ value: sn, label: sn }))}
              notFoundContent="未发现 DJI 飞行器（请检查 telemetry 栈）"
            />
            <Tooltip title="刷新状态">
              <Button icon={<ReloadOutlined />} onClick={fetchStatus} size="small" />
            </Tooltip>
          </div>
        </div>

        <div style={{
          background: 'linear-gradient(90deg, rgba(250,173,20,.14), transparent)',
          border: `1px solid ${AMBER}`, borderRadius: 8, padding: '10px 16px',
          marginBottom: 20, color: '#ffd591', fontSize: 13, display: 'flex', gap: 10, alignItems: 'center',
        }}>
          <WarningOutlined style={{ fontSize: 18 }} />
          <span>
            <b>安全提示：</b>校准前请确认飞行器已解锁桨叶保护、置于平稳地面且远离强磁源。
            真机校准会占用飞行器控制权——请勿在飞行中执行。
          </span>
        </div>

        {err && (
          <div style={{
            background: 'rgba(255,77,79,.12)', border: `1px solid ${RED}`,
            borderRadius: 8, padding: '8px 16px', marginBottom: 16, color: '#ffa39e',
          }}>{err}</div>
        )}

        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(340px, 1fr) minmax(420px, 1.2fr)', gap: 20 }}>
          {/* 左：传感器校准 */}
          <div style={{ background: PANEL_BG, border: `1px solid ${PANEL_BORDER}`, borderRadius: 12, padding: 20 }}>
            <h3 style={{ margin: '0 0 4px', fontSize: 15 }}>
              <RocketOutlined style={{ color: GREEN, marginRight: 8 }} />传感器校准
            </h3>
            <div style={{ color: '#5f759a', fontSize: 12, marginBottom: 16 }}>
              时长由后端配置文件定义 · 状态每 1.5s 轮询
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {sensorItems.map((item) => {
                const st = states[item.key];
                const running = st?.state === 'running';
                const pct = Math.round(st?.progress || 0);
                return (
                  <div key={item.key} style={{
                    background: '#0d1628', border: `1px solid ${PANEL_BORDER}`,
                    borderRadius: 10, padding: 14,
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <div style={{ fontSize: 14, fontWeight: 600, minWidth: 92 }}>{item.label}</div>
                      {stateTag(st?.state)}
                      <div style={{ marginLeft: 'auto', color: '#5f759a', fontSize: 11 }}>
                        {item.duration_s}s
                      </div>
                    </div>
                    <div style={{ color: '#7f96b8', fontSize: 12, margin: '8px 0' }}>{item.hint}</div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                      <div style={{ flex: 1 }}>
                        <Progress percent={pct} size="small" showInfo={false}
                          strokeColor={st?.state === 'success' ? GREEN : ACCENT} />
                      </div>
                      {running ? (
                        <Button size="small" danger onClick={() => cancelCal(item.key)}>取消</Button>
                      ) : (
                        <Button size="small" type="primary" icon={<PlayCircleOutlined />}
                          disabled={!selected} onClick={() => startCal(item.key)}>开始</Button>
                      )}
                    </div>
                    {st?.message && (
                      <div style={{ color: '#5f759a', fontSize: 11, marginTop: 6 }}>{st.message}</div>
                    )}
                  </div>
                );
              })}
              {sensorItems.length === 0 && (
                <div style={{ color: '#7f96b8', fontSize: 12 }}>连接器未挂载或未发现校准项</div>
              )}
            </div>

            {/* 已保存摇杆参数 */}
            <div style={{ marginTop: 20, borderTop: `1px solid ${PANEL_BORDER}`, paddingTop: 16 }}>
              <div style={{ display: 'flex', alignItems: 'center', marginBottom: 8 }}>
                <span style={{ fontSize: 14, fontWeight: 600 }}>已保存摇杆参数</span>
                <span style={{ marginLeft: 10 }}>
                  {savedRc ? <Tag color="green">已校准 · 死区 {savedRc.deadzone}</Tag> : <Tag>未校准</Tag>}
                </span>
              </div>
              <Table size="small" pagination={false} columns={rcTableColumns} dataSource={rcTableData} />
            </div>
          </div>

          {/* 右：摇杆采集向导 */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
            <div style={{ background: PANEL_BG, border: `1px solid ${PANEL_BORDER}`, borderRadius: 12, padding: 20 }}>
              <div style={{ display: 'flex', alignItems: 'center', marginBottom: 4 }}>
                <h3 style={{ margin: 0, fontSize: 15 }}>
                  <AimOutlined style={{ color: CYAN, marginRight: 8 }} />摇杆九点采集向导
                </h3>
                <div style={{ marginLeft: 'auto', color: '#7f96b8', fontSize: 12 }}>
                  {Math.min(stepIdx + 1, steps.length)} / {steps.length}
                </div>
              </div>
              <div style={{ color: '#5f759a', fontSize: 12, marginBottom: 14 }}>
                按提示推动对应摇杆到极限，点击「采集」记录端点；松开回中后采集中位
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-around', gap: 20 }}>
                <Joystick stick={left} color={ACCENT} label="左杆 · 油门/偏航"
                  xLabel="YAW" yLabel="THR"
                  onMove={(x, y) => setLeft({ x, y })}
                  onRelease={() => setLeft(CENTER)} />
                <Joystick stick={right} color={CYAN} label="右杆 · 俯仰/横滚"
                  xLabel="ROL" yLabel="PIT"
                  onMove={(x, y) => setRight({ x, y })}
                  onRelease={() => setRight(CENTER)} />
              </div>

              <div style={{
                background: '#0d1628', border: `1px solid ${PANEL_BORDER}`,
                borderRadius: 10, padding: 14, marginTop: 16,
              }}>
                <div style={{ color: '#9fb3d1', fontSize: 13, marginBottom: 8 }}>
                  当前步骤：<b style={{ color: CYAN }}>{step?.label || '已完成全部采集'}</b>
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 14 }}>
                  {steps.map((s, i) => (
                    <Tag key={s.key} color={
                      captured[s.key] !== undefined ? 'green' : i === stepIdx ? 'processing' : 'default'
                    } style={{ margin: 0, cursor: 'default' }}>
                      {i + 1}. {s.label.slice(0, 6)}
                    </Tag>
                  ))}
                </div>
                <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
                  <Tooltip title={
                    step && !targetOk(step)
                      ? (step.edge === 'center'
                        ? '请先松开双杆，使其回中'
                        : `请将${step.axis === 'throttle' || step.axis === 'yaw' ? '左' : '右'}杆推到${step.edge === 'max' ? '正向' : '反向'}极限（>|0.7|）`)
                      : ''
                  }>
                    <Button type="primary" icon={<CheckCircleOutlined />}
                      disabled={!step || !targetOk(step)} onClick={capture}>
                      采集当前位置
                    </Button>
                  </Tooltip>
                  <Button onClick={resetWizard}>重置向导</Button>
                  {allCaptured && (
                    <Button type="primary" ghost icon={<SaveOutlined />}
                      loading={saving} onClick={saveRc}>应用到飞行器</Button>
                  )}
                  {step && (
                    <span style={{ color: '#5f759a', fontSize: 12 }}>
                      当前值 {axisValue(step.axis).toFixed(2)} · 目标 {step.edge}
                    </span>
                  )}
                </div>
              </div>
            </div>

            {/* 日志 */}
            <div style={{ background: PANEL_BG, border: `1px solid ${PANEL_BORDER}`, borderRadius: 12, padding: 20 }}>
              <h3 style={{ margin: '0 0 12px', fontSize: 15 }}>操作日志</h3>
              <div style={{
                maxHeight: 180, overflowY: 'auto', fontFamily: 'monospace',
                fontSize: 12, lineHeight: '20px',
              }}>
                {logs.length === 0 && <div style={{ color: '#5f759a' }}>暂无操作记录</div>}
                {logs.map((l, i) => (
                  <div key={i} style={{ color: {
                    info: '#9fb3d1', ok: GREEN, warn: AMBER, err: '#ff7875',
                  }[l.level] }}>
                    <span style={{ color: '#5f759a', marginRight: 10 }}>{l.ts}</span>{l.text}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </ConfigProvider>
  );
}
