/**
 * 无人机监控仪表盘 - 实时遥测数据显示
 * 包含姿态仪表、飞行数据、地图视图、视频流等
 */

import React, { useState, useEffect, useRef } from 'react';
import { Card, Row, Col, Progress, Tag, Button, Tabs, Select, Slider, Switch } from 'antd';
import {
  PlayCircleOutlined,
  PauseCircleOutlined,
  ThunderboltOutlined,
  EnvironmentOutlined,
  CompassOutlined,
  DashboardOutlined,
  VideoCameraOutlined,
  WarningOutlined,
  CheckCircleOutlined,
} from '@ant-design/icons';
import * as THREE from 'three';
import ReactECharts from 'echarts-for-react';

const { TabPane } = Tabs;
const { Option } = Select;

// 类型定义
interface TelemetryData {
  timestamp: string;
  position: {
    latitude: number;
    longitude: number;
    altitude: number;
    relative_altitude: number;
  };
  speed: {
    ground_speed: number;
    air_speed: number;
    vertical_speed: number;
  };
  attitude: {
    roll: number;
    pitch: number;
    yaw: number;
  };
  battery: {
    voltage: number;
    current: number;
    remaining: number;
  };
  signal: {
    rssi: number;
    snr: number;
  };
  gps: {
    satellites: number;
    fix: number;
  };
  status: {
    flight_mode: string;
    armed: boolean;
    system_status: number;
  };
}

interface MonitorProps {
  deviceId: string;
  websocketUrl?: string;
  videoStreamUrl?: string;
}

const Monitor: React.FC<MonitorProps> = ({
  deviceId,
  websocketUrl = 'ws://localhost:8000/ws',
  videoStreamUrl,
}) => {
  const [telemetry, setTelemetry] = useState<TelemetryData | null>(null);
  const [connected, setConnected] = useState(false);
  const [historyData, setHistoryData] = useState<{
    altitude: number[];
    speed: number[];
    battery: number[];
    timestamps: string[];
  }>({
    altitude: [],
    speed: [],
    battery: [],
    timestamps: [],
  });
  
  const websocketRef = useRef<WebSocket | null>(null);
  const attitudeCanvasRef = useRef<HTMLDivElement>(null);
  const attitudeSceneRef = useRef<THREE.Scene | null>(null);
  const attitudeCameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const attitudeRendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const droneModelRef = useRef<THREE.Group | null>(null);
  
  // WebSocket连接
  useEffect(() => {
    const ws = new WebSocket(websocketUrl);
    websocketRef.current = ws;
    
    ws.onopen = () => {
      console.log('WebSocket connected');
      setConnected(true);
      
      // 订阅遥测数据
      ws.send(JSON.stringify({
        type: 'subscribe_telemetry',
        device_id: deviceId,
      }));
    };
    
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      
      if (data.type === 'telemetry' && data.device_id === deviceId) {
        setTelemetry(data.data);
        
        // 更新历史数据
        setHistoryData(prev => {
          const maxPoints = 100;
          return {
            altitude: [...prev.altitude.slice(-maxPoints + 1), data.data.position.altitude],
            speed: [...prev.speed.slice(-maxPoints + 1), data.data.speed.ground_speed],
            battery: [...prev.battery.slice(-maxPoints + 1), data.data.battery.remaining],
            timestamps: [...prev.timestamps.slice(-maxPoints + 1), data.data.timestamp],
          };
        });
      }
    };
    
    ws.onerror = (error) => {
      console.error('WebSocket error:', error);
      setConnected(false);
    };
    
    ws.onclose = () => {
      console.log('WebSocket disconnected');
      setConnected(false);
    };
    
    return () => {
      ws.close();
    };
  }, [deviceId, websocketUrl]);
  
  // 初始化3D姿态显示
  useEffect(() => {
    if (!attitudeCanvasRef.current) return;
    
    // 创建场景
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x1a1a2e);
    attitudeSceneRef.current = scene;
    
    // 创建相机
    const camera = new THREE.PerspectiveCamera(
      60,
      attitudeCanvasRef.current.clientWidth / attitudeCanvasRef.current.clientHeight,
      0.1,
      1000
    );
    camera.position.z = 5;
    attitudeCameraRef.current = camera;
    
    // 创建渲染器
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(attitudeCanvasRef.current.clientWidth, attitudeCanvasRef.current.clientHeight);
    attitudeCanvasRef.current.appendChild(renderer.domElement);
    attitudeRendererRef.current = renderer;
    
    // 创建无人机模型（简化版）
    const droneGroup = new THREE.Group();
    
    // 机身
    const bodyGeometry = new THREE.BoxGeometry(0.5, 0.1, 0.5);
    const bodyMaterial = new THREE.MeshPhongMaterial({ color: 0x00ff00 });
    const body = new THREE.Mesh(bodyGeometry, bodyMaterial);
    droneGroup.add(body);
    
    // 机臂和螺旋桨
    const armPositions = [
      [0.3, 0, 0.3],
      [-0.3, 0, 0.3],
      [0.3, 0, -0.3],
      [-0.3, 0, -0.3],
    ];
    
    armPositions.forEach((pos) => {
      // 机臂
      const armGeometry = new THREE.BoxGeometry(0.4, 0.05, 0.05);
      const armMaterial = new THREE.MeshPhongMaterial({ color: 0x888888 });
      const arm = new THREE.Mesh(armGeometry, armMaterial);
      arm.position.set(pos[0] / 2, 0, pos[2] / 2);
      arm.rotation.y = Math.atan2(pos[0], pos[2]);
      droneGroup.add(arm);
      
      // 螺旋桨
      const propGeometry = new THREE.CylinderGeometry(0.15, 0.15, 0.02, 32);
      const propMaterial = new THREE.MeshPhongMaterial({ color: 0x0088ff });
      const prop = new THREE.Mesh(propGeometry, propMaterial);
      prop.position.set(pos[0], 0.05, pos[2]);
      droneGroup.add(prop);
    });
    
    droneModelRef.current = droneGroup;
    scene.add(droneGroup);
    
    // 添加光源
    const ambientLight = new THREE.AmbientLight(0x404040, 0.5);
    scene.add(ambientLight);
    
    const directionalLight = new THREE.DirectionalLight(0xffffff, 1);
    directionalLight.position.set(5, 5, 5);
    scene.add(directionalLight);
    
    // 添加坐标轴辅助
    const axesHelper = new THREE.AxesHelper(2);
    scene.add(axesHelper);
    
    // 动画循环
    const animate = () => {
      requestAnimationFrame(animate);
      renderer.render(scene, camera);
    };
    animate();
    
    // 窗口大小调整
    const handleResize = () => {
      if (!attitudeCanvasRef.current) return;
      
      camera.aspect = attitudeCanvasRef.current.clientWidth / attitudeCanvasRef.current.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(attitudeCanvasRef.current.clientWidth, attitudeCanvasRef.current.clientHeight);
    };
    
    window.addEventListener('resize', handleResize);
    
    return () => {
      window.removeEventListener('resize', handleResize);
      renderer.dispose();
      if (attitudeCanvasRef.current) {
        attitudeCanvasRef.current.removeChild(renderer.domElement);
      }
    };
  }, []);
  
  // 更新无人机姿态
  useEffect(() => {
    if (!droneModelRef.current || !telemetry) return;
    
    // 转换角度为弧度
    const roll = THREE.MathUtils.degToRad(telemetry.attitude.roll);
    const pitch = THREE.MathUtils.degToRad(telemetry.attitude.pitch);
    const yaw = THREE.MathUtils.degToRad(telemetry.attitude.yaw);
    
    // 应用旋转
    droneModelRef.current.rotation.set(pitch, yaw, -roll);
  }, [telemetry]);
  
  // 发送命令
  const sendCommand = (command: string, params?: any) => {
    if (!websocketRef.current || websocketRef.current.readyState !== WebSocket.OPEN) {
      console.error('WebSocket not connected');
      return;
    }
    
    websocketRef.current.send(JSON.stringify({
      type: 'command',
      device_id: deviceId,
      command,
      params,
    }));
  };
  
  // 获取飞行模式颜色
  const getFlightModeColor = (mode: string) => {
    const colorMap: Record<string, string> = {
      'MANUAL': 'default',
      'STABILIZED': 'blue',
      'ALTCTL': 'cyan',
      'POSCTL': 'green',
      'OFFBOARD': 'gold',
      'AUTO.MISSION': 'purple',
      'AUTO.RTL': 'orange',
      'AUTO.LAND': 'red',
    };
    return colorMap[mode] || 'default';
  };
  
  // 获取电池颜色
  const getBatteryColor = (remaining: number) => {
    if (remaining > 50) return '#52c41a';
    if (remaining > 20) return '#faad14';
    return '#f5222d';
  };
  
  // 获取GPS状态
  const getGPSStatus = (fix: number) => {
    if (fix >= 3) return { text: '3D Fix', color: 'success' };
    if (fix === 2) return { text: '2D Fix', color: 'warning' };
    return { text: 'No Fix', color: 'error' };
  };
  
  // 高度图表配置
  const altitudeChartOption = {
    title: { text: '高度变化', textStyle: { color: '#fff', fontSize: 14 } },
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: 'category',
      data: historyData.timestamps,
      show: false,
    },
    yAxis: {
      type: 'value',
      name: '高度 (m)',
      nameTextStyle: { color: '#fff' },
      axisLine: { lineStyle: { color: '#888' } },
      splitLine: { lineStyle: { color: '#333' } },
    },
    series: [{
      data: historyData.altitude,
      type: 'line',
      smooth: true,
      lineStyle: { color: '#00ff00', width: 2 },
      areaStyle: {
        color: {
          type: 'linear',
          x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: 'rgba(0, 255, 0, 0.5)' },
            { offset: 1, color: 'rgba(0, 255, 0, 0.1)' },
          ],
        },
      },
    }],
    backgroundColor: 'transparent',
  };
  
  // 速度图表配置
  const speedChartOption = {
    title: { text: '地速变化', textStyle: { color: '#fff', fontSize: 14 } },
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: 'category',
      data: historyData.timestamps,
      show: false,
    },
    yAxis: {
      type: 'value',
      name: '速度 (m/s)',
      nameTextStyle: { color: '#fff' },
      axisLine: { lineStyle: { color: '#888' } },
      splitLine: { lineStyle: { color: '#333' } },
    },
    series: [{
      data: historyData.speed,
      type: 'line',
      smooth: true,
      lineStyle: { color: '#0088ff', width: 2 },
      areaStyle: {
        color: {
          type: 'linear',
          x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: 'rgba(0, 136, 255, 0.5)' },
            { offset: 1, color: 'rgba(0, 136, 255, 0.1)' },
          ],
        },
      },
    }],
    backgroundColor: 'transparent',
  };
  
  if (!telemetry) {
    return (
      <div style={{ padding: '50px', textAlign: 'center', color: '#fff' }}>
        <p>等待遥测数据...</p>
        <p>设备ID: {deviceId}</p>
        <Tag color={connected ? 'success' : 'error'}>
          {connected ? '已连接' : '未连接'}
        </Tag>
      </div>
    );
  }
  
  return (
    <div className="drone-monitor" style={{ padding: '20px', backgroundColor: '#001529', minHeight: '100vh' }}>
      {/* 顶部状态栏 */}
      <Row gutter={[16, 16]} style={{ marginBottom: '20px' }}>
        <Col span={6}>
          <Card style={{ backgroundColor: '#002140', borderColor: '#0050b3' }}>
            <div style={{ color: '#fff' }}>
              <h3 style={{ margin: 0, color: '#fff' }}>设备ID</h3>
              <p style={{ margin: '10px 0 0', fontSize: '18px', fontWeight: 'bold' }}>{deviceId}</p>
            </div>
          </Card>
        </Col>
        
        <Col span={6}>
          <Card style={{ backgroundColor: '#002140', borderColor: '#0050b3' }}>
            <div style={{ color: '#fff' }}>
              <h3 style={{ margin: 0, color: '#fff' }}>飞行模式</h3>
              <Tag color={getFlightModeColor(telemetry.status.flight_mode)} style={{ marginTop: '10px' }}>
                {telemetry.status.flight_mode}
              </Tag>
            </div>
          </Card>
        </Col>
        
        <Col span={6}>
          <Card style={{ backgroundColor: '#002140', borderColor: '#0050b3' }}>
            <div style={{ color: '#fff' }}>
              <h3 style={{ margin: 0, color: '#fff' }}>状态</h3>
              <Tag color={telemetry.status.armed ? 'success' : 'default'} style={{ marginTop: '10px' }}>
                {telemetry.status.armed ? '已解锁' : '已上锁'}
              </Tag>
            </div>
          </Card>
        </Col>
        
        <Col span={6}>
          <Card style={{ backgroundColor: '#002140', borderColor: '#0050b3' }}>
            <div style={{ color: '#fff' }}>
              <h3 style={{ margin: 0, color: '#fff' }}>电池</h3>
              <Progress
                percent={telemetry.battery.remaining}
                strokeColor={getBatteryColor(telemetry.battery.remaining)}
                style={{ marginTop: '10px' }}
              />
              <p style={{ margin: '5px 0 0', fontSize: '12px' }}>
                {telemetry.battery.voltage.toFixed(1)}V | {telemetry.battery.current.toFixed(1)}A
              </p>
            </div>
          </Card>
        </Col>
      </Row>
      
      {/* 主要监控区域 */}
      <Row gutter={[16, 16]}>
        {/* 姿态仪表 */}
        <Col span={8}>
          <Card
            title={<span style={{ color: '#fff' }}><CompassOutlined /> 姿态仪表</span>}
            style={{ backgroundColor: '#002140', borderColor: '#0050b3' }}
            headStyle={{ borderBottom: '1px solid #0050b3' }}
          >
            <div ref={attitudeCanvasRef} style={{ width: '100%', height: '300px' }} />
            <Row gutter={[16, 16]} style={{ marginTop: '15px', color: '#fff' }}>
              <Col span={8}>
                <div>横滚 (Roll)</div>
                <div style={{ fontSize: '18px', fontWeight: 'bold' }}>
                  {telemetry.attitude.roll.toFixed(1)}°
                </div>
              </Col>
              <Col span={8}>
                <div>俯仰 (Pitch)</div>
                <div style={{ fontSize: '18px', fontWeight: 'bold' }}>
                  {telemetry.attitude.pitch.toFixed(1)}°
                </div>
              </Col>
              <Col span={8}>
                <div>偏航 (Yaw)</div>
                <div style={{ fontSize: '18px', fontWeight: 'bold' }}>
                  {telemetry.attitude.yaw.toFixed(1)}°
                </div>
              </Col>
            </Row>
          </Card>
        </Col>
        
        {/* 位置和速度 */}
        <Col span={8}>
          <Card
            title={<span style={{ color: '#fff' }}><EnvironmentOutlined /> 位置与速度</span>}
            style={{ backgroundColor: '#002140', borderColor: '#0050b3' }}
            headStyle={{ borderBottom: '1px solid #0050b3' }}
          >
            <div style={{ color: '#fff', marginBottom: '20px' }}>
              <h4 style={{ color: '#fff' }}>GPS位置</h4>
              <Row gutter={[16, 8]}>
                <Col span={12}>
                  <div>纬度: {telemetry.position.latitude.toFixed(6)}°</div>
                </Col>
                <Col span={12}>
                  <div>经度: {telemetry.position.longitude.toFixed(6)}°</div>
                </Col>
                <Col span={12}>
                  <div>海拔: {telemetry.position.altitude.toFixed(1)}m</div>
                </Col>
                <Col span={12}>
                  <div>相对高度: {telemetry.position.relative_altitude.toFixed(1)}m</div>
                </Col>
              </Row>
              <Tag color={getGPSStatus(telemetry.gps.fix).color} style={{ marginTop: '10px' }}>
                {getGPSStatus(telemetry.gps.fix).text} ({telemetry.gps.satellites}颗卫星)
              </Tag>
            </div>
            
            <div style={{ color: '#fff' }}>
              <h4 style={{ color: '#fff' }}>速度</h4>
              <Row gutter={[16, 8]}>
                <Col span={8}>
                  <div>地速</div>
                  <div style={{ fontSize: '18px', fontWeight: 'bold' }}>
                    {telemetry.speed.ground_speed.toFixed(1)} m/s
                  </div>
                </Col>
                <Col span={8}>
                  <div>空速</div>
                  <div style={{ fontSize: '18px', fontWeight: 'bold' }}>
                    {telemetry.speed.air_speed.toFixed(1)} m/s
                  </div>
                </Col>
                <Col span={8}>
                  <div>垂直速度</div>
                  <div style={{ fontSize: '18px', fontWeight: 'bold' }}>
                    {telemetry.speed.vertical_speed.toFixed(1)} m/s
                  </div>
                </Col>
              </Row>
            </div>
          </Card>
        </Col>
        
        {/* 控制面板 */}
        <Col span={8}>
          <Card
            title={<span style={{ color: '#fff' }}><DashboardOutlined /> 控制面板</span>}
            style={{ backgroundColor: '#002140', borderColor: '#0050b3' }}
            headStyle={{ borderBottom: '1px solid #0050b3' }}
          >
            <div style={{ color: '#fff' }}>
              <h4 style={{ color: '#fff', marginBottom: '15px' }}>飞行控制</h4>
              <Row gutter={[8, 8]}>
                <Col span={12}>
                  <Button
                    type="primary"
                    icon={<ThunderboltOutlined />}
                    onClick={() => sendCommand('arm')}
                    block
                    disabled={telemetry.status.armed}
                  >
                    解锁
                  </Button>
                </Col>
                <Col span={12}>
                  <Button
                    danger
                    icon={<PauseCircleOutlined />}
                    onClick={() => sendCommand('disarm')}
                    block
                    disabled={!telemetry.status.armed}
                  >
                    上锁
                  </Button>
                </Col>
                <Col span={12}>
                  <Button
                    type="default"
                    icon={<PlayCircleOutlined />}
                    onClick={() => sendCommand('takeoff', { altitude: 10 })}
                    block
                    disabled={!telemetry.status.armed}
                  >
                    起飞
                  </Button>
                </Col>
                <Col span={12}>
                  <Button
                    type="default"
                    danger
                    onClick={() => sendCommand('land')}
                    block
                  >
                    降落
                  </Button>
                </Col>
              </Row>
              
              <h4 style={{ color: '#fff', margin: '20px 0 15px' }}>飞行模式</h4>
              <Select
                value={telemetry.status.flight_mode}
                onChange={(mode) => sendCommand('set_mode', { mode })}
                style={{ width: '100%' }}
              >
                <Option value="STABILIZED">Stabilized</Option>
                <Option value="ALTCTL">Altitude Control</Option>
                <Option value="POSCTL">Position Control</Option>
                <Option value="OFFBOARD">Offboard</Option>
                <Option value="AUTO.MISSION">Auto Mission</Option>
                <Option value="AUTO.RTL">Return to Launch</Option>
                <Option value="AUTO.LAND">Auto Land</Option>
              </Select>
              
              <h4 style={{ color: '#fff', margin: '20px 0 15px' }}>信号强度</h4>
              <Row gutter={[16, 8]}>
                <Col span={12}>
                  <div>RSSI</div>
                  <Progress
                    percent={Math.min(100, Math.max(0, telemetry.signal.rssi + 100))}
                    strokeColor="#52c41a"
                  />
                </Col>
                <Col span={12}>
                  <div>SNR</div>
                  <div style={{ fontSize: '18px', fontWeight: 'bold' }}>
                    {telemetry.signal.snr.toFixed(1)} dB
                  </div>
                </Col>
              </Row>
            </div>
          </Card>
        </Col>
      </Row>
      
      {/* 图表区域 */}
      <Row gutter={[16, 16]} style={{ marginTop: '20px' }}>
        <Col span={12}>
          <Card style={{ backgroundColor: '#002140', borderColor: '#0050b3' }}>
            <ReactECharts option={altitudeChartOption} style={{ height: '250px' }} />
          </Card>
        </Col>
        <Col span={12}>
          <Card style={{ backgroundColor: '#002140', borderColor: '#0050b3' }}>
            <ReactECharts option={speedChartOption} style={{ height: '250px' }} />
          </Card>
        </Col>
      </Row>
    </div>
  );
};

export default Monitor;
