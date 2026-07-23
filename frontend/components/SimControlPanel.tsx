'use client';

import React, { useEffect, useState } from 'react';
import { Card, Button, Select, InputNumber, Tag, Space, message, Modal } from 'antd';
import { RocketOutlined, HomeOutlined, PauseOutlined, PushpinOutlined } from '@ant-design/icons';

interface SimDrone { sysid: number; command_port: number }
interface SimState { mode: string; armed: boolean; mission_progress: string; mission_completed?: boolean; mission_completed_at?: number | null }

// Backend on the same host, port 8000.
const API = (typeof window !== 'undefined' &&
  process.env.NEXT_PUBLIC_API_BASE_URL) ||
  (typeof window !== 'undefined' ? `${window.location.protocol}//${window.location.hostname}:8000/api/v1` : 'http://localhost:8000/api/v1');

async function api<T = any>(method: string, path: string, body?: any): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export default function SimControlPanel({ selectedDroneId }: { selectedDroneId?: string }) {
  const [drones, setDrones] = useState<SimDrone[]>([]);
  const [sysid, setSysid] = useState<number>(1);
  const [state, setState] = useState<SimState | null>(null);
  const [busy, setBusy] = useState(false);
  const [gotoLat, setGotoLat] = useState<number>(39.910);
  const [gotoLng, setGotoLng] = useState<number>(116.420);
  const [gotoAlt, setGotoAlt] = useState<number>(120);

  useEffect(() => {
    api<{ drones: SimDrone[] }>('GET', '/sim/drones')
      .then((r) => {
        setDrones(r.drones || []);
        if (r.drones?.length) setSysid(r.drones[0].sysid);
      })
      .catch(() => {/* silent — dev-only */});
  }, []);

  useEffect(() => {
    if (selectedDroneId) {
      const n = Number(selectedDroneId);
      if (Number.isFinite(n)) setSysid(n);
    }
  }, [selectedDroneId]);

  // Poll state every 1.5s
  useEffect(() => {
    if (!sysid) return;
    let alive = true;
    let lastCompletedAt: number | null = null;
    const tick = async () => {
      try {
        const s = await api<SimState>('GET', `/sim/drones/${sysid}/state`);
        if (!alive) return;
        // Detect the moment mission_completed flips true (rising edge).
        if (s.mission_completed && s.mission_completed_at && s.mission_completed_at !== lastCompletedAt) {
          lastCompletedAt = s.mission_completed_at;
          message.success(`✅ 无人机 ${sysid} 任务完成 (${s.mission_progress})`);
        }
        setState(s);
      } catch {/* ignore */}
    };
    tick();
    const id = setInterval(tick, 1500);
    return () => { alive = false; clearInterval(id); };
  }, [sysid]);

  const run = async (label: string, fn: () => Promise<any>) => {
    setBusy(true);
    try {
      const r = await fn();
      message.success(`${label} → ${JSON.stringify(r).slice(0, 80)}`);
    } catch (e: any) {
      message.error(`${label} failed: ${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  const goto = () => run('GOTO', () => api('POST', `/sim/drones/${sysid}/goto`, {
    lat: gotoLat, lng: gotoLng, alt: gotoAlt,
  }));
  const rtl = () => run('RTL', () => api('POST', `/sim/drones/${sysid}/rtl`));
  const hover = () => run('HOVER', () => api('POST', `/sim/drones/${sysid}/mode`, { mode: 'hover' }));
  const circle = () => run('CIRCLE', () => api('POST', `/sim/drones/${sysid}/mode`, { mode: 'circle' }));

  const dispatchMission = () => {
    Modal.confirm({
      title: '派发演示任务',
      content: `将向 sysid=${sysid} 上传 3 个航点（北京奥体附近）并进入 mission 模式`,
      okText: '派发',
      cancelText: '取消',
      onOk: async () => {
        await run('MISSION', () => api('POST', `/sim/drones/${sysid}/mission`, {
          waypoints: [
            { lat: 39.905, lng: 116.405, alt: 80 },
            { lat: 39.908, lng: 116.412, alt: 110 },
            { lat: 39.914, lng: 116.418, alt: 140 },
          ],
        }));
      },
    });
  };

  if (drones.length === 0) return null;

  return (
    <Card
      title={<span style={{ color: '#e6edf3' }}>🎮 仿真控制</span>}
      size="small"
      style={{
        position: 'absolute',
        top: 16,
        left: 16,
        width: 300,
        background: 'rgba(13, 17, 23, 0.92)',
        border: '1px solid #21262d',
        zIndex: 10,
      }}
      headStyle={{ color: '#e6edf3', borderBottom: '1px solid #21262d' }}
      bodyStyle={{ color: '#e6edf3', padding: 12 }}
    >
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <div>
          <div style={{ color: '#8b949e', fontSize: 12, marginBottom: 4 }}>目标无人机</div>
          <Select
            value={sysid}
            onChange={setSysid}
            style={{ width: '100%' }}
            options={drones.map((d) => ({
              label: `sysid=${d.sysid} (:${d.command_port})`,
              value: d.sysid,
            }))}
          />
        </div>

        {state && (
          <div style={{ background: '#0d1117', padding: 8, borderRadius: 4, fontSize: 12 }}>
            <Space size="small" wrap>
              <Tag color={state.armed ? 'green' : 'red'}>{state.armed ? 'ARMED' : 'DISARMED'}</Tag>
              <Tag color="blue">{state.mode}</Tag>
              <Tag color={state.mission_completed ? 'green' : 'purple'}>
                mission {state.mission_progress}
                {state.mission_completed && ' ✅'}
              </Tag>
            </Space>
          </div>
        )}

        <div>
          <div style={{ color: '#8b949e', fontSize: 12, marginBottom: 4 }}>GOTO 目标</div>
          <Space.Compact style={{ width: '100%' }}>
            <InputNumber
              value={gotoLat}
              onChange={(v) => setGotoLat(v || 0)}
              step={0.001}
              precision={4}
              style={{ width: '33%' }}
              placeholder="lat"
            />
            <InputNumber
              value={gotoLng}
              onChange={(v) => setGotoLng(v || 0)}
              step={0.001}
              precision={4}
              style={{ width: '33%' }}
              placeholder="lng"
            />
            <InputNumber
              value={gotoAlt}
              onChange={(v) => setGotoAlt(v || 0)}
              step={10}
              style={{ width: '34%' }}
              placeholder="alt(m)"
            />
          </Space.Compact>
          <Button
            icon={<PushpinOutlined />}
            block
            style={{ marginTop: 6 }}
            loading={busy}
            onClick={goto}
          >
            飞到此点
          </Button>
        </div>

        <Space wrap>
          <Button icon={<RocketOutlined />} loading={busy} onClick={dispatchMission}>
            派发任务
          </Button>
          <Button icon={<HomeOutlined />} loading={busy} onClick={rtl}>
            RTL
          </Button>
          <Button icon={<PauseOutlined />} loading={busy} onClick={hover}>
            悬停
          </Button>
          <Button loading={busy} onClick={circle}>
            画圆
          </Button>
        </Space>
      </Space>
    </Card>
  );
}
