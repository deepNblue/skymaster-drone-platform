"""
FastAPI主应用 - SkyMaster无人机管控平台API
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any
from datetime import datetime
import asyncio
import logging
import uvicorn
import json

from ..core.devices.manager import DeviceManager, DroneDevice, DeviceStatus
from ..core.mavlink.connector import DroneType, DroneConfig, TelemetryData
from ..core.missions.planner import MissionPlanner, Mission, MissionType, Waypoint, WaypointType, Position
from ..core.swarm.controller import SwarmController, SwarmConfig, FormationType, SwarmState
from ..core.safety.safety_manager import SafetyManager
from .safety import router as safety_router, init_safety_manager, start_safety_manager, stop_safety_manager

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 创建FastAPI应用
app = FastAPI(
    title="SkyMaster API",
    description="智能无人机管控平台API",
    version="1.0.0"
)

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应该限制
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局实例
device_manager: Optional[DeviceManager] = None
mission_planner: Optional[MissionPlanner] = None
swarm_controller: Optional[SwarmController] = None
safety_manager: Optional[SafetyManager] = None
websocket_manager: Optional['WebSocketManager'] = None


# Pydantic模型
class DeviceConfigModel(BaseModel):
    """设备配置模型"""
    drone_id: str
    drone_type: str = Field(..., description="px4/ardupilot/dji")
    connection_string: str
    name: Optional[str] = None
    baud_rate: int = 57600


class PositionModel(BaseModel):
    """位置模型"""
    latitude: float
    longitude: float
    altitude: float


class WaypointModel(BaseModel):
    """航点模型"""
    waypoint_id: str
    position: PositionModel
    waypoint_type: str = "waypoint"
    speed: float = 5.0
    hold_time: float = 0.0
    camera_action: str = "none"
    camera_angle: float = -90.0
    name: str = ""
    description: str = ""


class MissionModel(BaseModel):
    """任务模型"""
    mission_id: str
    name: str
    mission_type: str = "custom"
    waypoints: List[WaypointModel]
    description: str = ""
    auto_takeoff: bool = True
    takeoff_altitude: float = 10.0
    auto_land: bool = True
    return_to_home: bool = True
    default_speed: float = 5.0
    default_altitude: float = 50.0


class SwarmConfigModel(BaseModel):
    """集群配置模型"""
    swarm_id: str
    name: str
    formation_type: str = "line"
    spacing: float = 10.0
    altitude_offset: float = 5.0
    min_separation: float = 5.0
    collision_avoidance: bool = True


class CommandModel(BaseModel):
    """命令模型"""
    command: str
    params: Optional[Dict[str, Any]] = None


# WebSocket管理器
class WebSocketManager:
    """WebSocket连接管理器"""
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.telemetry_subscribers: Dict[str, List[WebSocket]] = {}
    
    async def connect(self, websocket: WebSocket):
        """连接WebSocket"""
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket connected. Total: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket):
        """断开WebSocket"""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        
        # 从所有订阅中移除
        for device_id in list(self.telemetry_subscribers.keys()):
            if websocket in self.telemetry_subscribers[device_id]:
                self.telemetry_subscribers[device_id].remove(websocket)
        
        logger.info(f"WebSocket disconnected. Total: {len(self.active_connections)}")
    
    async def broadcast(self, message: dict):
        """广播消息到所有连接"""
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error broadcasting to WebSocket: {e}")
    
    async def subscribe_telemetry(self, device_id: str, websocket: WebSocket):
        """订阅设备遥测"""
        if device_id not in self.telemetry_subscribers:
            self.telemetry_subscribers[device_id] = []
        
        if websocket not in self.telemetry_subscribers[device_id]:
            self.telemetry_subscribers[device_id].append(websocket)
    
    async def send_telemetry(self, device_id: str, telemetry: TelemetryData):
        """发送遥测数据"""
        if device_id in self.telemetry_subscribers:
            message = {
                'type': 'telemetry',
                'device_id': device_id,
                'data': telemetry.to_dict()
            }
            
            for connection in self.telemetry_subscribers[device_id]:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    logger.error(f"Error sending telemetry: {e}")


# 启动和关闭事件
@app.on_event("startup")
async def startup_event():
    """应用启动"""
    global device_manager, mission_planner, swarm_controller, websocket_manager, safety_manager
    
    logger.info("Starting SkyMaster API...")
    
    # 初始化组件
    device_manager = DeviceManager()
    mission_planner = MissionPlanner()
    swarm_controller = SwarmController(device_manager)
    websocket_manager = WebSocketManager()
    
    # 初始化安全管理器
    safety_manager = init_safety_manager()
    
    # 添加遥测回调
    device_manager.add_telemetry_callback(on_telemetry_update)
    
    # 启动服务
    await device_manager.start()
    await swarm_controller.start()
    await start_safety_manager()
    
    # 注册安全路由
    app.include_router(safety_router)
    
    logger.info("SkyMaster API started successfully")


@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭"""
    global device_manager, swarm_controller, safety_manager
    
    logger.info("Shutting down SkyMaster API...")
    
    await stop_safety_manager()
    await swarm_controller.stop()
    await device_manager.stop()
    
    logger.info("SkyMaster API shutdown complete")


# 遥测回调
async def on_telemetry_update(device_id: str, telemetry: TelemetryData):
    """遥测数据更新回调"""
    if websocket_manager:
        await websocket_manager.send_telemetry(device_id, telemetry)


# ==================== 设备管理API ====================

@app.get("/api/devices", tags=["设备管理"])
async def get_all_devices():
    """获取所有设备"""
    devices = device_manager.get_all_devices()
    return {
        'devices': [device.to_dict() for device in devices],
        'total': len(devices)
    }


@app.get("/api/devices/{device_id}", tags=["设备管理"])
async def get_device(device_id: str):
    """获取单个设备"""
    device = device_manager.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    return device.to_dict()


@app.post("/api/devices", tags=["设备管理"])
async def register_device(config: DeviceConfigModel):
    """注册设备"""
    try:
        drone_type = DroneType(config.drone_type)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid drone type")
    
    drone_config = DroneConfig(
        drone_id=config.drone_id,
        drone_type=drone_type,
        connection_string=config.connection_string,
        baud_rate=config.baud_rate
    )
    
    device_id = await device_manager.register_device(
        drone_config,
        name=config.name
    )
    
    return {'device_id': device_id, 'status': 'registered'}


@app.delete("/api/devices/{device_id}", tags=["设备管理"])
async def unregister_device(device_id: str):
    """注销设备"""
    success = await device_manager.unregister_device(device_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Device not found")
    
    return {'status': 'unregistered'}


@app.post("/api/devices/{device_id}/connect", tags=["设备管理"])
async def connect_device(device_id: str):
    """连接设备"""
    success = await device_manager.connect_device(device_id)
    
    if not success:
        raise HTTPException(status_code=500, detail="Connection failed")
    
    return {'status': 'connected'}


@app.post("/api/devices/{device_id}/disconnect", tags=["设备管理"])
async def disconnect_device(device_id: str):
    """断开设备"""
    success = await device_manager.disconnect_device(device_id)
    
    if not success:
        raise HTTPException(status_code=500, detail="Disconnect failed")
    
    return {'status': 'disconnected'}


@app.get("/api/devices/{device_id}/telemetry", tags=["设备管理"])
async def get_device_telemetry(device_id: str):
    """获取设备遥测数据"""
    device = device_manager.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    if not device.connector:
        raise HTTPException(status_code=400, detail="Device not connected")
    
    return device.connector.telemetry.to_dict()


@app.post("/api/devices/{device_id}/command", tags=["设备管理"])
async def send_device_command(device_id: str, command: CommandModel):
    """发送命令到设备"""
    success = await device_manager.send_command(
        device_id,
        command.command,
        command.params
    )
    
    if not success:
        raise HTTPException(status_code=500, detail="Command failed")
    
    return {'status': 'command_sent'}


# ==================== 任务管理API ====================

@app.get("/api/missions", tags=["任务管理"])
async def get_all_missions():
    """获取所有任务"""
    missions = mission_planner.get_all_missions()
    return {
        'missions': [mission.to_dict() for mission in missions],
        'total': len(missions)
    }


@app.get("/api/missions/{mission_id}", tags=["任务管理"])
async def get_mission(mission_id: str):
    """获取任务详情"""
    mission = mission_planner.get_mission(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    
    return mission.to_dict()


@app.post("/api/missions", tags=["任务管理"])
async def create_mission(mission_data: MissionModel):
    """创建任务"""
    try:
        mission_type = MissionType(mission_data.mission_type)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid mission type")
    
    mission = mission_planner.create_mission(
        mission_data.mission_id,
        mission_data.name,
        mission_type,
        mission_data.description
    )
    
    # 添加航点
    for wp_data in mission_data.waypoints:
        waypoint = Waypoint(
            waypoint_id=wp_data.waypoint_id,
            position=Position(
                wp_data.position.latitude,
                wp_data.position.longitude,
                wp_data.position.altitude
            ),
            waypoint_type=WaypointType(wp_data.waypoint_type),
            speed=wp_data.speed,
            hold_time=wp_data.hold_time,
            camera_action=wp_data.camera_action,
            camera_angle=wp_data.camera_angle,
            name=wp_data.name,
            description=wp_data.description
        )
        mission.add_waypoint(waypoint)
    
    # 设置参数
    mission.auto_takeoff = mission_data.auto_takeoff
    mission.takeoff_altitude = mission_data.takeoff_altitude
    mission.auto_land = mission_data.auto_land
    mission.return_to_home = mission_data.return_to_home
    mission.default_speed = mission_data.default_speed
    mission.default_altitude = mission_data.default_altitude
    
    return mission.to_dict()


@app.delete("/api/missions/{mission_id}", tags=["任务管理"])
async def delete_mission(mission_id: str):
    """删除任务"""
    success = mission_planner.delete_mission(mission_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Mission not found")
    
    return {'status': 'deleted'}


@app.post("/api/missions/{mission_id}/validate", tags=["任务管理"])
async def validate_mission(mission_id: str):
    """验证任务"""
    valid, errors = mission_planner.validate_mission(mission_id)
    
    return {
        'valid': valid,
        'errors': errors
    }


@app.post("/api/missions/{mission_id}/upload/{device_id}", tags=["任务管理"])
async def upload_mission_to_device(mission_id: str, device_id: str):
    """上传任务到设备"""
    # TODO: 实现任务上传
    return {'status': 'uploaded', 'mission_id': mission_id, 'device_id': device_id}


# ==================== 集群管理API ====================

@app.get("/api/swarms", tags=["集群管理"])
async def get_all_swarms():
    """获取所有集群"""
    swarms = swarm_controller.get_all_swarms()
    return {
        'swarms': swarms,
        'total': len(swarms)
    }


@app.get("/api/swarms/{swarm_id}", tags=["集群管理"])
async def get_swarm(swarm_id: str):
    """获取集群详情"""
    config = swarm_controller.swarms.get(swarm_id)
    if not config:
        raise HTTPException(status_code=404, detail="Swarm not found")
    
    status = swarm_controller.get_swarm_status(swarm_id)
    
    return {
        'config': {
            'swarm_id': config.swarm_id,
            'name': config.name,
            'formation_type': config.formation_type.value,
            'spacing': config.spacing,
            'altitude_offset': config.altitude_offset,
            'min_separation': config.min_separation,
            'collision_avoidance': config.collision_avoidance
        },
        'status': {
            'state': status.state.value,
            'leader_id': status.leader_id,
            'formation_complete': status.formation_complete,
            'active_count': status.active_count
        }
    }


@app.post("/api/swarms", tags=["集群管理"])
async def create_swarm(config: SwarmConfigModel):
    """创建集群"""
    try:
        formation_type = FormationType(config.formation_type)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid formation type")
    
    swarm_config = SwarmConfig(
        swarm_id=config.swarm_id,
        name=config.name,
        formation_type=formation_type,
        spacing=config.spacing,
        altitude_offset=config.altitude_offset,
        min_separation=config.min_separation,
        collision_avoidance=config.collision_avoidance
    )
    
    success = await swarm_controller.create_swarm(swarm_config)
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to create swarm")
    
    return {'swarm_id': config.swarm_id, 'status': 'created'}


@app.delete("/api/swarms/{swarm_id}", tags=["集群管理"])
async def delete_swarm(swarm_id: str):
    """删除集群"""
    success = await swarm_controller.delete_swarm(swarm_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Swarm not found")
    
    return {'status': 'deleted'}


@app.post("/api/swarms/{swarm_id}/devices/{device_id}", tags=["集群管理"])
async def add_device_to_swarm(swarm_id: str, device_id: str):
    """添加设备到集群"""
    success = await swarm_controller.add_device_to_swarm(device_id, swarm_id)
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to add device")
    
    return {'status': 'added'}


@app.delete("/api/swarms/{swarm_id}/devices/{device_id}", tags=["集群管理"])
async def remove_device_from_swarm(swarm_id: str, device_id: str):
    """从集群移除设备"""
    success = await swarm_controller.remove_device_from_swarm(device_id, swarm_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Device not in swarm")
    
    return {'status': 'removed'}


@app.post("/api/swarms/{swarm_id}/form", tags=["集群管理"])
async def form_swarm_formation(swarm_id: str, center: PositionModel):
    """编队成形"""
    center_pos = Position(center.latitude, center.longitude, center.altitude)
    
    success = await swarm_controller.form_formation(swarm_id, center_pos)
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to form formation")
    
    return {'status': 'forming'}


@app.post("/api/swarms/{swarm_id}/emergency_stop", tags=["集群管理"])
async def swarm_emergency_stop(swarm_id: str):
    """集群紧急停止"""
    success = await swarm_controller.emergency_stop(swarm_id)
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to emergency stop")
    
    return {'status': 'emergency_stop'}


@app.post("/api/swarms/{swarm_id}/return_home", tags=["集群管理"])
async def swarm_return_home(swarm_id: str):
    """集群返航"""
    success = await swarm_controller.return_to_home(swarm_id)
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to return home")
    
    return {'status': 'returning'}


# ==================== WebSocket ====================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket端点"""
    await websocket_manager.connect(websocket)
    
    try:
        while True:
            # 接收消息
            data = await websocket.receive_text()
            
            try:
                message = json.loads(data)
                msg_type = message.get('type')
                
                if msg_type == 'subscribe_telemetry':
                    # 订阅遥测
                    device_id = message.get('device_id')
                    if device_id:
                        await websocket_manager.subscribe_telemetry(device_id, websocket)
                        await websocket.send_json({
                            'type': 'subscribed',
                            'device_id': device_id
                        })
                
                elif msg_type == 'ping':
                    # 心跳
                    await websocket.send_json({'type': 'pong'})
                
            except json.JSONDecodeError:
                await websocket.send_json({
                    'type': 'error',
                    'message': 'Invalid JSON'
                })
    
    except WebSocketDisconnect:
        websocket_manager.disconnect(websocket)


# ==================== 健康检查 ====================

@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'version': '1.0.0'
    }


@app.get("/api/statistics")
async def get_statistics():
    """获取系统统计"""
    return {
        'devices': device_manager.get_statistics(),
        'swarms': {
            'total': len(swarm_controller.swarms),
            'active': len([s for s in swarm_controller.swarm_status.values() 
                          if s.state == SwarmState.FLYING])
        },
        'missions': {
            'total': len(mission_planner.missions)
        }
    }


# 主程序
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
