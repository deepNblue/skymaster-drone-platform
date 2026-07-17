'use client';

import React, { useState } from 'react';
import { Card, Button, Space, Tag, Modal, InputNumber, List, message } from 'antd';
import { DeleteOutlined, SendOutlined, ClearOutlined, EditOutlined, StopOutlined } from '@ant-design/icons';

export interface EditorWaypoint {
  lat: number;
  lng: number;
  alt: number;
}

interface Props {
  sysid: number;
  waypoints: EditorWaypoint[];
  onChange: (wps: EditorWaypoint[]) => void;
  onToggleDrawing: (drawing: boolean) => void;
  drawing: boolean;
  defaultAlt: number;
  onDefaultAltChange: (v: number) => void;
  apiBase: string;
}

/**
 * Right-side panel that turns map clicks into a mission and POSTs it
 * to /api/v1/sim/drones/{sysid}/mission.
 */
export default function MissionEditorPanel({
  sysid,
  waypoints,
  onChange,
  onToggleDrawing,
  drawing,
  defaultAlt,
  onDefaultAltChange,
  apiBase,
}: Props) {
  const [busy, setBusy] = useState(false);

  const removeAt = (i: number) => onChange(waypoints.filter((_, k) => k !== i));

  const updateAlt = (i: number, alt: number) =>
    onChange(waypoints.map((w, k) => (k === i ? { ...w, alt } : w)));

  const dispatch = async () => {
    if (waypoints.length === 0) {
      message.warning('先在地图上点几个航点');
      return;
    }
    setBusy(true);
    try {
      const res = await fetch(`${apiBase}/sim/drones/${sysid}/mission`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ waypoints }),
      });
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      await res.json();
      message.success(`任务派发成功 · ${waypoints.length} 航点`);
      onToggleDrawing(false);
    } catch (e: any) {
      message.error(`派发失败: ${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  const clear = () =>
    Modal.confirm({ title: '清空所有航点？', onOk: () => onChange([]) });

  return (
    <Card
      title={
        <span style={{ color: '#e6edf3' }}>
          ✏️ 任务编辑器 · sysid={sysid}
        </span>
      }
      size="small"
      style={{
        position: 'absolute',
        top: 16,
        right: 16,
        width: 340,
        maxHeight: 'calc(100vh - 200px)',
        background: 'rgba(13, 17, 23, 0.92)',
        border: '1px solid #21262d',
        zIndex: 10,
        display: 'flex',
        flexDirection: 'column',
      }}
      headStyle={{ color: '#e6edf3', borderBottom: '1px solid #21262d' }}
      bodyStyle={{ color: '#e6edf3', padding: 12, overflow: 'auto' }}
    >
      <Space direction="vertical" size="small" style={{ width: '100%' }}>
        <Space wrap>
          <Button
            type={drawing ? 'primary' : 'default'}
            icon={drawing ? <StopOutlined /> : <EditOutlined />}
            danger={drawing}
            onClick={() => onToggleDrawing(!drawing)}
          >
            {drawing ? '停止绘制' : '开始绘制'}
          </Button>
          <span style={{ fontSize: 12, color: '#8b949e' }}>默认高度</span>
          <InputNumber
            size="small"
            value={defaultAlt}
            onChange={(v) => onDefaultAltChange(v || 100)}
            min={10}
            max={500}
            style={{ width: 70 }}
          />
          <span style={{ fontSize: 12, color: '#8b949e' }}>m</span>
        </Space>

        {drawing && (
          <Tag color="orange" style={{ margin: 0 }}>
            🖱 在地图上点击 → 添加航点（{waypoints.length} 个）
          </Tag>
        )}

        {waypoints.length > 0 ? (
          <List
            size="small"
            dataSource={waypoints}
            style={{ background: '#0d1117', borderRadius: 4 }}
            renderItem={(w, i) => (
              <List.Item
                style={{ padding: '4px 8px', borderBottom: '1px solid #21262d' }}
                actions={[
                  <Button
                    key="del"
                    size="small"
                    danger
                    type="text"
                    icon={<DeleteOutlined />}
                    onClick={() => removeAt(i)}
                  />,
                ]}
              >
                <div style={{ fontSize: 12, color: '#e6edf3', flex: 1 }}>
                  <Tag color="cyan" style={{ margin: 0, marginRight: 6 }}>
                    #{i + 1}
                  </Tag>
                  {w.lat.toFixed(5)}, {w.lng.toFixed(5)}
                  <InputNumber
                    size="small"
                    value={w.alt}
                    onChange={(v) => updateAlt(i, v || 100)}
                    style={{ width: 70, marginLeft: 8 }}
                    min={10}
                    max={500}
                  />
                </div>
              </List.Item>
            )}
          />
        ) : (
          <div style={{ color: '#8b949e', fontSize: 12, textAlign: 'center', padding: 12 }}>
            尚无航点。点「开始绘制」后在地图上点击。
          </div>
        )}

        {waypoints.length > 0 && (
          <Space style={{ marginTop: 4 }}>
            <Button
              type="primary"
              icon={<SendOutlined />}
              loading={busy}
              onClick={dispatch}
            >
              派发 ({waypoints.length})
            </Button>
            <Button icon={<ClearOutlined />} onClick={clear} danger>
              清空
            </Button>
          </Space>
        )}

        <div style={{ fontSize: 11, color: '#6e7681', marginTop: 4 }}>
          Tip: 新点自动取"默认高度"；可单独修改
        </div>
      </Space>
    </Card>
  );
}
