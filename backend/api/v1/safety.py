"""
SkyMaster 安全API端点
障碍检测、避障决策和安全状态查询
"""

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime
import logging
import asyncio

from ...core.safety.obstacle_detector import (
    ObstacleDetector, Obstacle, ObstacleType, ObstacleStatus, RiskLevel,
    Position, Velocity, SensorData
)
from ...core.safety.collision_avoidance import (
    CollisionAvoidance, AvoidanceStrategy, AvoidanceStatus,
    CollisionRisk, DroneState
)
from ...core.safety.safety_manager import (
    SafetyManager, SafetyLevel, SafetyEvent, SafetyAction,
    SafetyRule, GeoFence
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/safety", tags=["安全管理"])

# 全局安全管理器实例
_safety_manager: Optional[SafetyManager] = None


def get_safety_manager() -> SafetyManager:
    """获取安全管理器依赖"""
    global _safety_manager
    if _safety_manager is None:
        raise HTTPException(status_code=503, detail="Safety manager not initialized")
    return _safety_manager


def init_safety_manager() -> SafetyManager:
    """初始化安全管理器"""
    global _safety_manager
    if _safety_manager is None:
        _safety_manager = SafetyManager()
    return _safety_manager


async def start_safety_manager() -> None:
    """启动安全管理器"""
    global _safety_manager
    if _safety_manager:
        await _safety_manager.start()


async def stop_safety_manager() -> None:
    """停止安全管理器"""
    global _safety_manager
    if _safety_manager:
        await _safety_manager.stop()


# ==================== Pydantic 模型 ====================

class PositionModel(BaseModel):
    """位置模型"""
    x: float = Field(..., description="X坐标（米）")
    y: float = Field(..., description="Y坐标（米）")
    z: float = Field(..., description="高度（米）")
    timestamp: Optional[float] = None


class VelocityModel(BaseModel):
    """速度模型"""
    vx: float = Field(..., description="X方向速度（m/s）")
    vy: float = Field(..., description="Y方向速度（m/s）")
    vz: float = Field(..., description="Z方向速度（m/s）")
    timestamp: Optional[float] = None


class SensorDataModel(BaseModel):
    """传感器数据模型"""
    sensor_id: str
    sensor_type: str = Field(..., description="lidar/camera/radar/ultrasonic")
    timestamp: float
    data: Dict[str, Any]
    confidence: float = Field(default=1.0, ge=0, le=1)


class ObstacleModel(BaseModel):
    """障碍物模型"""
    id: str
    type: str
    status: str
    position: PositionModel
    velocity: Optional[VelocityModel] = None
    size: Tuple[float, float, float] = (1.0, 1.0, 1.0)
    confidence: float = 1.0
    risk_level: int = 1


class DroneStateModel(BaseModel):
    """无人机状态模型"""
    drone_id: str
    position: PositionModel
    velocity: VelocityModel
    heading: float = Field(default=0, description="航向角（度）")
    speed: float = Field(default=0, description="速度大小（m/s）")
    max_speed: float = Field(default=15.0)
    max_acceleration: float = Field(default=5.0)
    safety_radius: float = Field(default=3.0)


class CollisionRiskModel(BaseModel):
    """碰撞风险模型"""
    obstacle_id: str
    probability: float
    time_to_collision: float
    collision_point: PositionModel
    risk_level: int
    avoidance_strategy: str


class GeofenceModel(BaseModel):
    """地理围栏模型"""
    fence_id: str
    name: str
    fence_type: str = Field(..., description="inclusion/exclusion")
    vertices: List[Tuple[float, float]]
    min_altitude: Optional[float] = None
    max_altitude: Optional[float] = None
    enabled: bool = True


class SafetyRuleModel(BaseModel):
    """安全规则模型"""
    rule_id: str
    name: str
    description: str
    action: str
    priority: int = 0
    enabled: bool = True
    cooldown: float = 0.0


class SafetyEventModel(BaseModel):
    """安全事件模型"""
    event_id: str
    event_type: str
    safety_level: str
    message: str
    source: str
    details: Dict[str, Any] = {}
    timestamp: float
    acknowledged: bool = False
    resolved: bool = False


class DetectRequest(BaseModel):
    """检测请求"""
    sensor_data: List[SensorDataModel]
    drone_position: Optional[PositionModel] = None
    drone_velocity: Optional[VelocityModel] = None


class AvoidRequest(BaseModel):
    """避障请求"""
    drone_state: DroneStateModel
    obstacles: List[ObstacleModel] = []
    target_position: Optional[PositionModel] = None


class CheckGeofenceRequest(BaseModel):
    """检查地理围栏请求"""
    latitude: float
    longitude: float
    altitude: float


# ==================== API 端点 ====================

@router.post("/detect", summary="检测障碍")
async def detect_obstacles(
    request: DetectRequest,
    manager: SafetyManager = Depends(get_safety_manager)
) -> Dict[str, Any]:
    """
    使用传感器数据检测障碍物
    
    - **sensor_data**: 传感器数据列表
    - **drone_position**: 当前无人机位置（用于风险评估）
    - **drone_velocity**: 当前无人机速度（用于动态障碍预测）
    """
    try:
        detected_obstacles = []
        
        # 处理每个传感器数据
        for sensor_data_model in request.sensor_data:
            sensor_data = SensorData(
                sensor_id=sensor_data_model.sensor_id,
                sensor_type=sensor_data_model.sensor_type,
                timestamp=sensor_data_model.timestamp,
                data=sensor_data_model.data,
                confidence=sensor_data_model.confidence
            )
            
            # 处理传感器数据
            obstacles = manager.obstacle_detector.process_sensor_data(sensor_data)
            detected_obstacles.extend(obstacles)
        
        # 如果提供了无人机位置，进行风险评估
        if request.drone_position:
            drone_pos = Position(
                request.drone_position.x,
                request.drone_position.y,
                request.drone_position.z
            )
            
            drone_vel = None
            if request.drone_velocity:
                drone_vel = Velocity(
                    request.drone_velocity.vx,
                    request.drone_velocity.vy,
                    request.drone_velocity.vz
                )
            
            # 评估每个障碍物的风险
            for obstacle in detected_obstacles:
                risk = manager.obstacle_detector.assess_risk(
                    obstacle, drone_pos, drone_vel
                )
        
        # 获取所有障碍物
        all_obstacles = manager.obstacle_detector.get_obstacles()
        
        return {
            'status': 'success',
            'detected_count': len(detected_obstacles),
            'total_obstacles': len(all_obstacles),
            'obstacles': [obs.to_dict() for obs in detected_obstacles],
            'all_obstacles': [obs.to_dict() for obs in all_obstacles],
            'stats': manager.obstacle_detector.get_stats()
        }
    
    except Exception as e:
        logger.error(f"Error in detect_obstacles: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/avoid", summary="避障决策")
async def avoid_collisions(
    request: AvoidRequest,
    manager: SafetyManager = Depends(get_safety_manager)
) -> Dict[str, Any]:
    """
    根据当前状态做出避障决策
    
    - **drone_state**: 无人机当前状态
    - **obstacles**: 障碍物列表
    - **target_position**: 目标位置（可选）
    """
    try:
        # 更新无人机状态
        drone_state = DroneState(
            drone_id=request.drone_state.drone_id,
            position=Position(
                request.drone_state.position.x,
                request.drone_state.position.y,
                request.drone_state.position.z
            ),
            velocity=Velocity(
                request.drone_state.velocity.vx,
                request.drone_state.velocity.vy,
                request.drone_state.velocity.vz
            ),
            heading=request.drone_state.heading,
            speed=request.drone_state.speed,
            max_speed=request.drone_state.max_speed,
            max_acceleration=request.drone_state.max_acceleration,
            safety_radius=request.drone_state.safety_radius
        )
        
        manager.collision_avoidance.update_drone_state(drone_state)
        
        # 更新障碍物
        obstacles = []
        for obs_model in request.obstacles:
            obstacle = Obstacle(
                id=obs_model.id,
                obstacle_type=ObstacleType(obs_model.type),
                status=ObstacleStatus(obs_model.status),
                position=Position(
                    obs_model.position.x,
                    obs_model.position.y,
                    obs_model.position.z
                ),
                velocity=Velocity(
                    obs_model.velocity.vx,
                    obs_model.velocity.vy,
                    obs_model.velocity.vz
                ) if obs_model.velocity else None,
                size=obs_model.size,
                confidence=obs_model.confidence,
                risk_level=RiskLevel(obs_model.risk_level)
            )
            obstacles.append(obstacle)
        
        manager.collision_avoidance.update_obstacles(obstacles)
        
        # 获取碰撞风险
        collision_risks = manager.collision_avoidance.get_collision_risks()
        
        # 获取当前避障路径
        current_path = manager.collision_avoidance.get_current_path()
        
        # 获取避障状态
        avoidance_status = manager.collision_avoidance.get_status()
        
        return {
            'status': 'success',
            'avoidance_status': avoidance_status.value,
            'collision_risks': [risk.to_dict() for risk in collision_risks],
            'current_path': current_path.to_dict() if current_path else None,
            'risk_count': len(collision_risks),
            'high_risk_count': sum(
                1 for r in collision_risks 
                if r.risk_level.value >= RiskLevel.HIGH.value
            ),
            'recommended_action': _get_recommended_action(collision_risks, avoidance_status),
            'stats': manager.collision_avoidance.get_stats()
        }
    
    except Exception as e:
        logger.error(f"Error in avoid_collisions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status", summary="安全状态")
async def get_safety_status(
    manager: SafetyManager = Depends(get_safety_manager)
) -> Dict[str, Any]:
    """
    获取当前安全状态
    
    返回安全等级、活动事件、障碍物统计等信息
    """
    try:
        # 获取安全等级
        safety_level = manager.get_safety_level()
        
        # 获取活动事件
        active_events = manager.get_active_events()
        
        # 获取障碍物统计
        obstacle_stats = manager.obstacle_detector.get_stats()
        
        # 获取碰撞避免统计
        avoidance_stats = manager.collision_avoidance.get_stats()
        
        # 获取总体统计
        manager_stats = manager.get_stats()
        
        return {
            'status': 'success',
            'safety_level': safety_level.value,
            'is_safe': safety_level in [SafetyLevel.SAFE, SafetyLevel.CAUTION],
            'active_events': {
                'count': len(active_events),
                'events': [event.to_dict() for event in active_events[:10]]  # 最多返回10个
            },
            'obstacles': {
                'active_count': obstacle_stats['active_obstacles'],
                'dynamic_count': obstacle_stats['dynamic_obstacles'],
                'high_risk_count': obstacle_stats['high_risk_count'],
                'total_detected': obstacle_stats['total_detected']
            },
            'avoidance': {
                'status': manager.collision_avoidance.get_status().value,
                'total_avoidances': avoidance_stats['total_avoidances'],
                'emergency_brakes': avoidance_stats['emergency_brakes'],
                'coordinated_avoidances': avoidance_stats['coordinated_avoidances']
            },
            'statistics': manager_stats,
            'timestamp': datetime.now().isoformat()
        }
    
    except Exception as e:
        logger.error(f"Error in get_safety_status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/obstacles", summary="获取障碍物列表")
async def get_obstacles(
    obstacle_type: Optional[str] = None,
    status: Optional[str] = None,
    min_risk: Optional[int] = None,
    manager: SafetyManager = Depends(get_safety_manager)
) -> Dict[str, Any]:
    """
    获取障碍物列表
    
    - **obstacle_type**: 按类型过滤（static/dynamic/ground/airborne）
    - **status**: 按状态过滤（active/tracked/lost）
    - **min_risk**: 按最小风险等级过滤（1-4）
    """
    try:
        obs_type = ObstacleType(obstacle_type) if obstacle_type else None
        obs_status = ObstacleStatus(status) if status else None
        risk_level = RiskLevel(min_risk) if min_risk else None
        
        obstacles = manager.obstacle_detector.get_obstacles(
            obstacle_type=obs_type,
            status=obs_status,
            min_risk=risk_level
        )
        
        return {
            'status': 'success',
            'count': len(obstacles),
            'obstacles': [obs.to_dict() for obs in obstacles]
        }
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid parameter: {e}")
    except Exception as e:
        logger.error(f"Error in get_obstacles: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/obstacles/{obstacle_id}", summary="获取障碍物详情")
async def get_obstacle(
    obstacle_id: str,
    manager: SafetyManager = Depends(get_safety_manager)
) -> Dict[str, Any]:
    """获取单个障碍物的详细信息"""
    obstacle = manager.obstacle_detector.get_obstacle_by_id(obstacle_id)
    
    if not obstacle:
        raise HTTPException(status_code=404, detail="Obstacle not found")
    
    return {
        'status': 'success',
        'obstacle': obstacle.to_dict()
    }


@router.delete("/obstacles/{obstacle_id}", summary="清除障碍物")
async def clear_obstacle(
    obstacle_id: str,
    manager: SafetyManager = Depends(get_safety_manager)
) -> Dict[str, Any]:
    """清除指定的障碍物"""
    success = manager.obstacle_detector.clear_obstacle(obstacle_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Obstacle not found")
    
    return {
        'status': 'success',
        'message': f'Obstacle {obstacle_id} cleared'
    }


@router.get("/events", summary="获取安全事件")
async def get_safety_events(
    limit: int = 50,
    include_resolved: bool = False,
    manager: SafetyManager = Depends(get_safety_manager)
) -> Dict[str, Any]:
    """
    获取安全事件列表
    
    - **limit**: 返回事件数量限制
    - **include_resolved**: 是否包含已解决的事件
    """
    try:
        if include_resolved:
            events = manager.get_event_history(limit)
        else:
            events = manager.get_active_events()
        
        return {
            'status': 'success',
            'count': len(events),
            'events': [event.to_dict() for event in events]
        }
    
    except Exception as e:
        logger.error(f"Error in get_safety_events: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/events/{event_id}/acknowledge", summary="确认安全事件")
async def acknowledge_event(
    event_id: str,
    manager: SafetyManager = Depends(get_safety_manager)
) -> Dict[str, Any]:
    """确认安全事件"""
    success = manager.acknowledge_event(event_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Event not found")
    
    return {
        'status': 'success',
        'message': f'Event {event_id} acknowledged'
    }


@router.post("/events/{event_id}/resolve", summary="解决安全事件")
async def resolve_event(
    event_id: str,
    action: Optional[str] = None,
    manager: SafetyManager = Depends(get_safety_manager)
) -> Dict[str, Any]:
    """解决安全事件"""
    safety_action = SafetyAction(action) if action else None
    success = manager.resolve_event(event_id, safety_action)
    
    if not success:
        raise HTTPException(status_code=404, detail="Event not found")
    
    return {
        'status': 'success',
        'message': f'Event {event_id} resolved'
    }


@router.get("/geofences", summary="获取地理围栏")
async def get_geofences(
    manager: SafetyManager = Depends(get_safety_manager)
) -> Dict[str, Any]:
    """获取所有地理围栏"""
    geofences = manager.get_geofences()
    
    return {
        'status': 'success',
        'count': len(geofences),
        'geofences': [fence.to_dict() for fence in geofences]
    }


@router.post("/geofences", summary="添加地理围栏")
async def add_geofence(
    geofence: GeofenceModel,
    manager: SafetyManager = Depends(get_safety_manager)
) -> Dict[str, Any]:
    """添加地理围栏"""
    try:
        fence = GeoFence(
            fence_id=geofence.fence_id,
            name=geofence.name,
            fence_type=geofence.fence_type,
            vertices=geofence.vertices,
            min_altitude=geofence.min_altitude,
            max_altitude=geofence.max_altitude,
            enabled=geofence.enabled
        )
        
        manager.add_geofence(fence)
        
        return {
            'status': 'success',
            'message': f'Geofence {geofence.fence_id} added'
        }
    
    except Exception as e:
        logger.error(f"Error in add_geofence: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/geofences/{fence_id}", summary="删除地理围栏")
async def remove_geofence(
    fence_id: str,
    manager: SafetyManager = Depends(get_safety_manager)
) -> Dict[str, Any]:
    """删除地理围栏"""
    success = manager.remove_geofence(fence_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Geofence not found")
    
    return {
        'status': 'success',
        'message': f'Geofence {fence_id} removed'
    }


@router.post("/geofences/check", summary="检查地理围栏")
async def check_geofence(
    request: CheckGeofenceRequest,
    manager: SafetyManager = Depends(get_safety_manager)
) -> Dict[str, Any]:
    """检查位置是否符合地理围栏规则"""
    result = manager.check_geofence(
        request.latitude,
        request.longitude,
        request.altitude
    )
    
    return {
        'status': 'success',
        'compliant': result['compliant'],
        'violations': result['violations']
    }


@router.get("/rules", summary="获取安全规则")
async def get_safety_rules(
    manager: SafetyManager = Depends(get_safety_manager)
) -> Dict[str, Any]:
    """获取所有安全规则"""
    rules = manager.get_rules()
    
    return {
        'status': 'success',
        'count': len(rules),
        'rules': [rule.to_dict() for rule in rules]
    }


@router.post("/emergency-stop", summary="紧急停止")
async def emergency_stop(
    drone_id: Optional[str] = None,
    manager: SafetyManager = Depends(get_safety_manager)
) -> Dict[str, Any]:
    """
    触发紧急停止
    
    这是一个紧急操作，将立即停止所有无人机
    """
    try:
        await manager.emergency_stop(drone_id)
        
        return {
            'status': 'success',
            'message': 'Emergency stop triggered',
            'drone_id': drone_id,
            'timestamp': datetime.now().isoformat()
        }
    
    except Exception as e:
        logger.error(f"Error in emergency_stop: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/return-home", summary="强制返航")
async def force_return_home(
    drone_id: Optional[str] = None,
    manager: SafetyManager = Depends(get_safety_manager)
) -> Dict[str, Any]:
    """
    触发强制返航
    
    无人机将返回到起飞点
    """
    try:
        await manager.force_return_home(drone_id)
        
        return {
            'status': 'success',
            'message': 'Return to home triggered',
            'drone_id': drone_id,
            'timestamp': datetime.now().isoformat()
        }
    
    except Exception as e:
        logger.error(f"Error in force_return_home: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/logs", summary="获取安全日志")
async def get_safety_logs(
    limit: int = 100,
    level: Optional[str] = None,
    manager: SafetyManager = Depends(get_safety_manager)
) -> Dict[str, Any]:
    """
    获取安全日志
    
    - **limit**: 返回日志数量限制
    - **level**: 按日志级别过滤（INFO/WARNING/CRITICAL）
    """
    logs = manager.get_logs(limit, level)
    
    return {
        'status': 'success',
        'count': len(logs),
        'logs': [log.to_dict() for log in logs]
    }


@router.post("/logs/export", summary="导出日志")
async def export_logs(
    filepath: str = "/tmp/safety_logs.jsonl",
    manager: SafetyManager = Depends(get_safety_manager)
) -> Dict[str, Any]:
    """导出安全日志到文件"""
    try:
        manager.export_logs(filepath)
        
        return {
            'status': 'success',
            'message': f'Logs exported to {filepath}'
        }
    
    except Exception as e:
        logger.error(f"Error in export_logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 辅助函数 ====================

def _get_recommended_action(
    risks: List[CollisionRisk],
    status: AvoidanceStatus
) -> str:
    """获取推荐动作"""
    if not risks:
        return "continue"  # 继续飞行
    
    if status == AvoidanceStatus.EMERGENCY:
        return "emergency_brake"  # 紧急制动
    
    if status == AvoidanceStatus.AVOIDING:
        return "following_avoidance_path"  # 遵循避障路径
    
    # 找到最高风险
    highest_risk = max(risks, key=lambda r: r.risk_level.value)
    
    if highest_risk.risk_level == RiskLevel.CRITICAL:
        return "immediate_action_required"  # 需要立即行动
    
    if highest_risk.risk_level == RiskLevel.HIGH:
        return "avoidance_recommended"  # 建议避障
    
    return "monitor"  # 监控
