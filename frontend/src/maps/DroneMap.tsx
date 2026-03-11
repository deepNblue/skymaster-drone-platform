/**
 * 3D无人机地图组件 - 使用Cesium.js
 * 支持实时显示无人机位置、轨迹、航点规划
 */

import React, { useEffect, useRef, useState, useCallback } from 'react';
import * as Cesium from 'cesium';
import 'cesium/Build/Cesium/Widgets/widgets.css';

// 类型定义
interface Position {
  latitude: number;
  longitude: number;
  altitude: number;
}

interface DroneTelemetry {
  device_id: string;
  position: Position;
  attitude: {
    roll: number;
    pitch: number;
    yaw: number;
  };
  speed: {
    ground_speed: number;
    air_speed: number;
    vertical_speed: number;
  };
  battery: {
    voltage: number;
    current: number;
    remaining: number;
  };
  status: {
    flight_mode: string;
    armed: boolean;
    system_status: number;
  };
  timestamp: string;
}

interface Waypoint {
  waypoint_id: string;
  position: Position;
  waypoint_type: string;
  speed: number;
  hold_time: number;
  name: string;
}

interface DroneMapProps {
  websocketUrl?: string;
  onWaypointAdd?: (waypoint: Waypoint) => void;
  onWaypointSelect?: (waypoint_id: string) => void;
  onDroneSelect?: (device_id: string) => void;
}

// 无人机颜色映射
const DRONE_COLORS = {
  online: Cesium.Color.fromCssColorString('#00ff00'),
  flying: Cesium.Color.fromCssColorString('#0088ff'),
  warning: Cesium.Color.fromCssColorString('#ffaa00'),
  error: Cesium.Color.fromCssColorString('#ff0000'),
  offline: Cesium.Color.fromCssColorString('#888888'),
};

const DroneMap: React.FC<DroneMapProps> = ({
  websocketUrl = 'ws://localhost:8000/ws',
  onWaypointAdd,
  onWaypointSelect,
  onDroneSelect,
}) => {
  const cesiumContainer = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<Cesium.Viewer | null>(null);
  const websocketRef = useRef<WebSocket | null>(null);
  
  const [drones, setDrones] = useState<Map<string, DroneTelemetry>>(new Map());
  const [waypoints, setWaypoints] = useState<Waypoint[]>([]);
  const [selectedDrone, setSelectedDrone] = useState<string | null>(null);
  const [selectedWaypoint, setSelectedWaypoint] = useState<string | null>(null);
  const [missionMode, setMissionMode] = useState<'view' | 'plan'>('view');
  
  // Cesium实体引用
  const droneEntitiesRef = useRef<Map<string, Cesium.Entity>>(new Map());
  const waypointEntitiesRef = useRef<Map<string, Cesium.Entity>>(new Map());
  const pathEntitiesRef = useRef<Map<string, Cesium.Entity>>(new Map());
  
  // 初始化Cesium
  useEffect(() => {
    if (!cesiumContainer.current) return;
    
    // 设置Cesium Ion访问令牌（需要替换为实际的token）
    Cesium.Ion.defaultAccessToken = 'YOUR_CESIUM_ION_TOKEN';
    
    // 创建Viewer
    const viewer = new Cesium.Viewer(cesiumContainer.current, {
      terrainProvider: Cesium.createWorldTerrain(),
      baseLayerPicker: true,
      geocoder: true,
      homeButton: true,
      sceneModePicker: true,
      navigationHelpButton: true,
      animation: false,
      timeline: false,
      fullscreenButton: true,
      vrButton: false,
      infoBox: true,
      selectionIndicator: true,
    });
    
    viewerRef.current = viewer;
    
    // 设置初始视角（北京）
    viewer.camera.setView({
      destination: Cesium.Cartesian3.fromDegrees(116.4074, 39.9042, 10000),
      orientation: {
        heading: Cesium.Math.toRadians(0),
        pitch: Cesium.Math.toRadians(-45),
        roll: 0,
      },
    });
    
    // 点击事件
    const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
    
    handler.setInputAction((movement: Cesium.ScreenSpaceEventHandler.PositionedEvent) => {
      const pickedObject = viewer.scene.pick(movement.position);
      
      if (Cesium.defined(pickedObject) && Cesium.defined(pickedObject.id)) {
        const entity = pickedObject.id;
        
        // 检查是否是无人机
        if (entity.properties && entity.properties.device_id) {
          const device_id = entity.properties.device_id.getValue();
          setSelectedDrone(device_id);
          if (onDroneSelect) {
            onDroneSelect(device_id);
          }
        }
        
        // 检查是否是航点
        if (entity.properties && entity.properties.waypoint_id) {
          const waypoint_id = entity.properties.waypoint_id.getValue();
          setSelectedWaypoint(waypoint_id);
          if (onWaypointSelect) {
            onWaypointSelect(waypoint_id);
          }
        }
      } else if (missionMode === 'plan') {
        // 任务规划模式：添加航点
        const cartesian = viewer.camera.pickEllipsoid(
          movement.position,
          viewer.scene.globe.ellipsoid
        );
        
        if (cartesian) {
          const cartographic = Cesium.Cartographic.fromCartesian(cartesian);
          const longitude = Cesium.Math.toDegrees(cartographic.longitude);
          const latitude = Cesium.Math.toDegrees(cartographic.latitude);
          
          const newWaypoint: Waypoint = {
            waypoint_id: `wp_${Date.now()}`,
            position: {
              latitude,
              longitude,
              altitude: 50, // 默认高度
            },
            waypoint_type: 'waypoint',
            speed: 5,
            hold_time: 0,
            name: `Waypoint ${waypoints.length + 1}`,
          };
          
          addWaypointToMap(newWaypoint);
          setWaypoints(prev => [...prev, newWaypoint]);
          
          if (onWaypointAdd) {
            onWaypointAdd(newWaypoint);
          }
        }
      }
    }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
    
    return () => {
      handler.destroy();
      viewer.destroy();
    };
  }, []);
  
  // 更新任务模式
  useEffect(() => {
    // 可以在这里根据missionMode改变鼠标样式等
  }, [missionMode]);
  
  // 连接WebSocket
  useEffect(() => {
    const ws = new WebSocket(websocketUrl);
    websocketRef.current = ws;
    
    ws.onopen = () => {
      console.log('WebSocket connected');
    };
    
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      
      if (data.type === 'telemetry') {
        updateDronePosition(data.device_id, data.data);
      }
    };
    
    ws.onerror = (error) => {
      console.error('WebSocket error:', error);
    };
    
    ws.onclose = () => {
      console.log('WebSocket disconnected');
    };
    
    return () => {
      ws.close();
    };
  }, [websocketUrl]);
  
  // 更新无人机位置
  const updateDronePosition = useCallback((device_id: string, telemetry: DroneTelemetry) => {
    setDrones(prev => {
      const newMap = new Map(prev);
      newMap.set(device_id, telemetry);
      return newMap;
    });
    
    if (!viewerRef.current) return;
    
    const viewer = viewerRef.current;
    const position = Cesium.Cartesian3.fromDegrees(
      telemetry.position.longitude,
      telemetry.position.latitude,
      telemetry.position.altitude
    );
    
    // 检查是否已存在实体
    if (droneEntitiesRef.current.has(device_id)) {
      // 更新位置
      const entity = droneEntitiesRef.current.get(device_id)!;
      
      if (entity.position) {
        entity.position.setValue(position);
      }
      
      // 更新姿态
      if (entity.orientation) {
        const heading = Cesium.Math.toRadians(telemetry.attitude.yaw);
        const pitch = Cesium.Math.toRadians(telemetry.attitude.pitch);
        const roll = Cesium.Math.toRadians(telemetry.attitude.roll);
        
        const hpr = new Cesium.HeadingPitchRoll(heading, pitch, roll);
        const orientation = Cesium.Transforms.headingPitchRollQuaternion(position, hpr);
        
        entity.orientation.setValue(orientation);
      }
      
      // 更新轨迹
      updateDronePath(device_id, telemetry.position);
    } else {
      // 创建新实体
      const droneColor = getDroneColor(telemetry.status.flight_mode, telemetry.battery.remaining);
      
      const entity = viewer.entities.add({
        id: `drone_${device_id}`,
        position: position,
        orientation: new Cesium.VelocityOrientationProperty(
          new Cesium.ConstantPositionProperty(position)
        ),
        model: {
          uri: '/models/drone.glb', // 无人机3D模型
          minimumPixelSize: 64,
          maximumScale: 200,
          color: droneColor,
        },
        // 备用：如果没有模型，使用点
        point: {
          pixelSize: 10,
          color: droneColor,
          outlineColor: Cesium.Color.WHITE,
          outlineWidth: 2,
        },
        label: {
          text: device_id,
          font: '14pt sans-serif',
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          outlineWidth: 2,
          verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
          pixelOffset: new Cesium.Cartesian2(0, -20),
          showBackground: true,
          backgroundColor: Cesium.Color.fromCssColorString('#000000aa'),
        },
        properties: {
          device_id: device_id,
        },
      });
      
      droneEntitiesRef.current.set(device_id, entity);
      
      // 创建轨迹
      createDronePath(device_id);
    }
  }, []);
  
  // 创建无人机轨迹
  const createDronePath = (device_id: string) => {
    if (!viewerRef.current) return;
    
    const viewer = viewerRef.current;
    
    const pathEntity = viewer.entities.add({
      id: `path_${device_id}`,
      polyline: {
        positions: new Cesium.CallbackProperty(() => {
          // 返回轨迹点
          return pathEntitiesRef.current.get(device_id)?.positions || [];
        }, false),
        width: 2,
        material: Cesium.Color.YELLOW.withAlpha(0.8),
        clampToGround: false,
      },
    });
    
    pathEntitiesRef.current.set(device_id, pathEntity);
  };
  
  // 更新无人机轨迹
  const updateDronePath = (device_id: string, position: Position) => {
    const pathEntity = pathEntitiesRef.current.get(device_id);
    
    if (pathEntity && pathEntity.polyline) {
      const currentPositions = pathEntity.polyline.positions?.getValue(Cesium.JulianDate.now()) || [];
      const newPosition = Cesium.Cartesian3.fromDegrees(
        position.longitude,
        position.latitude,
        position.altitude
      );
      
      // 限制轨迹长度
      const maxPathLength = 1000;
      let newPositions = [...currentPositions, newPosition];
      
      if (newPositions.length > maxPathLength) {
        newPositions = newPositions.slice(-maxPathLength);
      }
      
      pathEntity.polyline.positions = newPositions as any;
    }
  };
  
  // 获取无人机颜色
  const getDroneColor = (flightMode: string, batteryLevel: number): Cesium.Color => {
    if (batteryLevel < 20) {
      return DRONE_COLORS.warning;
    }
    
    if (flightMode === 'OFFBOARD' || flightMode === 'AUTO.MISSION') {
      return DRONE_COLORS.flying;
    }
    
    return DRONE_COLORS.online;
  };
  
  // 添加航点到地图
  const addWaypointToMap = (waypoint: Waypoint) => {
    if (!viewerRef.current) return;
    
    const viewer = viewerRef.current;
    const position = Cesium.Cartesian3.fromDegrees(
      waypoint.position.longitude,
      waypoint.position.latitude,
      waypoint.position.altitude
    );
    
    const entity = viewer.entities.add({
      id: `waypoint_${waypoint.waypoint_id}`,
      position: position,
      point: {
        pixelSize: 12,
        color: Cesium.Color.CYAN,
        outlineColor: Cesium.Color.WHITE,
        outlineWidth: 2,
        heightReference: Cesium.HeightReference.NONE,
      },
      label: {
        text: waypoint.name || waypoint.waypoint_id,
        font: '12pt sans-serif',
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        outlineWidth: 2,
        verticalOrigin: Cesium.VerticalOrigin.TOP,
        pixelOffset: new Cesium.Cartesian2(0, 10),
        showBackground: true,
        backgroundColor: Cesium.Color.fromCssColorString('#00000088'),
      },
      properties: {
        waypoint_id: waypoint.waypoint_id,
      },
    });
    
    waypointEntitiesRef.current.set(waypoint.waypoint_id, entity);
    
    // 更新航线
    updateMissionPath();
  };
  
  // 更新任务航线
  const updateMissionPath = () => {
    if (!viewerRef.current || waypoints.length < 2) return;
    
    const viewer = viewerRef.current;
    
    // 删除旧航线
    const oldPath = viewer.entities.getById('mission_path');
    if (oldPath) {
      viewer.entities.remove(oldPath);
    }
    
    // 创建新航线
    const positions = waypoints.map(wp =>
      Cesium.Cartesian3.fromDegrees(
        wp.position.longitude,
        wp.position.latitude,
        wp.position.altitude
      )
    );
    
    viewer.entities.add({
      id: 'mission_path',
      polyline: {
        positions: positions,
        width: 2,
        material: new Cesium.PolylineGlowMaterialProperty({
          glowPower: 0.2,
          color: Cesium.Color.CYAN,
        }),
        clampToGround: false,
      },
    });
  };
  
  // 飞到无人机
  const flyToDrone = (device_id: string) => {
    if (!viewerRef.current) return;
    
    const entity = droneEntitiesRef.current.get(device_id);
    if (entity) {
      viewerRef.current.zoomTo(entity, new Cesium.HeadingPitchRange(0, -45, 500));
    }
  };
  
  // 飞到航点
  const flyToWaypoint = (waypoint_id: string) => {
    if (!viewerRef.current) return;
    
    const entity = waypointEntitiesRef.current.get(waypoint_id);
    if (entity) {
      viewerRef.current.zoomTo(entity, new Cesium.HeadingPitchRange(0, -45, 200));
    }
  };
  
  // 清除所有航点
  const clearWaypoints = () => {
    if (!viewerRef.current) return;
    
    // 删除所有航点实体
    waypointEntitiesRef.current.forEach((entity) => {
      viewerRef.current!.entities.remove(entity);
    });
    
    waypointEntitiesRef.current.clear();
    
    // 删除航线
    const missionPath = viewerRef.current.entities.getById('mission_path');
    if (missionPath) {
      viewerRef.current.entities.remove(missionPath);
    }
    
    setWaypoints([]);
  };
  
  // 导出组件方法
  React.useImperativeHandle(ref, () => ({
    flyToDrone,
    flyToWaypoint,
    clearWaypoints,
    addWaypoint: addWaypointToMap,
  }));
  
  return (
    <div className="drone-map-container" style={{ width: '100%', height: '100%', position: 'relative' }}>
      <div ref={cesiumContainer} style={{ width: '100%', height: '100%' }} />
      
      {/* 控制面板 */}
      <div className="map-controls" style={{
        position: 'absolute',
        top: '10px',
        left: '10px',
        zIndex: 1000,
        backgroundColor: 'rgba(0, 0, 0, 0.7)',
        padding: '15px',
        borderRadius: '8px',
        color: 'white',
      }}>
        <div style={{ marginBottom: '10px' }}>
          <button
            onClick={() => setMissionMode(missionMode === 'plan' ? 'view' : 'plan')}
            style={{
              padding: '8px 16px',
              backgroundColor: missionMode === 'plan' ? '#0088ff' : '#444',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
              marginRight: '10px',
            }}
          >
            {missionMode === 'plan' ? '退出规划' : '任务规划'}
          </button>
          
          {missionMode === 'plan' && (
            <button
              onClick={clearWaypoints}
              style={{
                padding: '8px 16px',
                backgroundColor: '#ff4444',
                color: 'white',
                border: 'none',
                borderRadius: '4px',
                cursor: 'pointer',
              }}
            >
              清除航点
            </button>
          )}
        </div>
        
        <div style={{ fontSize: '14px' }}>
          <div>在线无人机: {drones.size}</div>
          <div>航点数量: {waypoints.length}</div>
        </div>
      </div>
      
      {/* 无人机列表 */}
      <div className="drone-list" style={{
        position: 'absolute',
        top: '10px',
        right: '10px',
        zIndex: 1000,
        backgroundColor: 'rgba(0, 0, 0, 0.7)',
        padding: '15px',
        borderRadius: '8px',
        color: 'white',
        maxHeight: '400px',
        overflowY: 'auto',
      }}>
        <h3 style={{ margin: '0 0 10px 0', fontSize: '16px' }}>无人机列表</h3>
        {Array.from(drones.entries()).map(([device_id, telemetry]) => (
          <div
            key={device_id}
            onClick={() => flyToDrone(device_id)}
            style={{
              padding: '8px',
              margin: '5px 0',
              backgroundColor: selectedDrone === device_id ? 'rgba(0, 136, 255, 0.5)' : 'rgba(255, 255, 255, 0.1)',
              borderRadius: '4px',
              cursor: 'pointer',
              fontSize: '13px',
            }}
          >
            <div style={{ fontWeight: 'bold' }}>{device_id}</div>
            <div style={{ fontSize: '11px', opacity: 0.8 }}>
              模式: {telemetry.status.flight_mode} | 
              电量: {telemetry.battery.remaining}%
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default DroneMap;
