"""
SkyMaster 碰撞避免模块
碰撞预测、避障路径生成、紧急制动和多机协同避障
"""

import asyncio
import time
import math
from typing import Dict, List, Optional, Tuple, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import logging
from threading import Lock
import numpy as np
from collections import deque

from .obstacle_detector import (
    Obstacle, ObstacleType, ObstacleStatus, RiskLevel,
    Position, Velocity
)

logger = logging.getLogger(__name__)


class AvoidanceStrategy(Enum):
    """避障策略"""
    NONE = "none"                   # 无需避障
    HORIZONTAL = "horizontal"       # 水平避障
    VERTICAL = "vertical"           # 垂直避障
    STOP_AND_HOVER = "stop_hover"   # 停止悬停
    DETOUR = "detour"               # 绕行
    EMERGENCY_BRAKE = "emergency"   # 紧急制动
    COORDINATED = "coordinated"     # 协同避障


class AvoidanceStatus(Enum):
    """避障状态"""
    IDLE = "idle"                   # 空闲
    MONITORING = "monitoring"       # 监控中
    AVOIDING = "avoiding"           # 避障中
    EMERGENCY = "emergency"         # 紧急状态
    RECOVERING = "recovering"       # 恢复中


@dataclass
class CollisionRisk:
    """碰撞风险"""
    obstacle_id: str
    probability: float              # 碰撞概率 0-1
    time_to_collision: float       # 碰撞时间（秒）
    collision_point: Position      # 碰撞点
    risk_level: RiskLevel
    avoidance_strategy: AvoidanceStrategy
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict:
        return {
            'obstacle_id': self.obstacle_id,
            'probability': self.probability,
            'time_to_collision': self.time_to_collision,
            'collision_point': self.collision_point.to_dict(),
            'risk_level': self.risk_level.value,
            'avoidance_strategy': self.avoidance_strategy.value,
            'timestamp': self.timestamp
        }


@dataclass
class AvoidancePath:
    """避障路径"""
    waypoints: List[Position]
    strategy: AvoidanceStrategy
    estimated_time: float          # 预计完成时间（秒）
    distance: float                # 路径长度（米）
    safety_margin: float           # 安全边距（米）
    created_at: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict:
        return {
            'waypoints': [wp.to_dict() for wp in self.waypoints],
            'strategy': self.strategy.value,
            'estimated_time': self.estimated_time,
            'distance': self.distance,
            'safety_margin': self.safety_margin,
            'created_at': self.created_at
        }


@dataclass
class DroneState:
    """无人机状态"""
    drone_id: str
    position: Position
    velocity: Velocity
    heading: float                 # 航向角（度）
    speed: float                   # 速度大小（m/s）
    max_speed: float = 15.0        # 最大速度
    max_acceleration: float = 5.0  # 最大加速度
    safety_radius: float = 3.0     # 安全半径
    
    def to_dict(self) -> Dict:
        return {
            'drone_id': self.drone_id,
            'position': self.position.to_dict(),
            'velocity': self.velocity.to_dict(),
            'heading': self.heading,
            'speed': self.speed,
            'max_speed': self.max_speed,
            'max_acceleration': self.max_acceleration,
            'safety_radius': self.safety_radius
        }


class CollisionAvoidance:
    """
    碰撞避免系统
    负责碰撞预测、避障路径生成、紧急制动和多机协同避障
    """
    
    def __init__(
        self,
        safety_margin: float = 5.0,          # 安全边距（米）
        critical_distance: float = 3.0,      # 临界距离（米）
        prediction_horizon: float = 5.0,     # 预测时间范围（秒）
        update_interval: float = 0.05,       # 更新间隔（秒）
        enable_coordinated: bool = True      # 启用协同避障
    ):
        self.safety_margin = safety_margin
        self.critical_distance = critical_distance
        self.prediction_horizon = prediction_horizon
        self.update_interval = update_interval
        self.enable_coordinated = enable_coordinated
        
        # 状态
        self._status = AvoidanceStatus.IDLE
        self._running = False
        self._avoidance_task: Optional[asyncio.Task] = None
        
        # 无人机状态
        self._drone_state: Optional[DroneState] = None
        self._other_drones: Dict[str, DroneState] = {}
        self._lock = Lock()
        
        # 碰撞风险和避障路径
        self._collision_risks: List[CollisionRisk] = []
        self._current_path: Optional[AvoidancePath] = None
        self._path_history: deque = deque(maxlen=100)
        
        # 统计
        self._stats = {
            'total_avoidances': 0,
            'emergency_brakes': 0,
            'coordinated_avoidances': 0,
            'avg_avoidance_time': 0.0
        }
        
        # 回调
        self._on_collision_warning: Optional[Callable] = None
        self._on_avoidance_start: Optional[Callable] = None
        self._on_avoidance_complete: Optional[Callable] = None
        self._on_emergency: Optional[Callable] = None
        
        logger.info(f"CollisionAvoidance initialized with safety_margin={safety_margin}m")
    
    async def start(self) -> None:
        """启动碰撞避免系统"""
        if self._running:
            logger.warning("CollisionAvoidance is already running")
            return
        
        self._running = True
        self._status = AvoidanceStatus.MONITORING
        self._avoidance_task = asyncio.create_task(self._avoidance_loop())
        logger.info("CollisionAvoidance started")
    
    async def stop(self) -> None:
        """停止碰撞避免系统"""
        self._running = False
        if self._avoidance_task:
            self._avoidance_task.cancel()
            try:
                await self._avoidance_task
            except asyncio.CancelledError:
                pass
        self._status = AvoidanceStatus.IDLE
        logger.info("CollisionAvoidance stopped")
    
    async def _avoidance_loop(self) -> None:
        """避障循环"""
        while self._running:
            try:
                if self._drone_state:
                    # 预测碰撞风险
                    await self._predict_collisions()
                    
                    # 执行避障决策
                    await self._execute_avoidance()
                
                await asyncio.sleep(self.update_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in avoidance loop: {e}")
                await asyncio.sleep(0.5)
    
    def update_drone_state(self, state: DroneState) -> None:
        """更新无人机状态"""
        with self._lock:
            self._drone_state = state
    
    def update_obstacles(self, obstacles: List[Obstacle]) -> None:
        """更新障碍物列表"""
        with self._lock:
            self._obstacles = obstacles
    
    def update_other_drones(self, drones: List[DroneState]) -> None:
        """更新其他无人机状态（用于协同避障）"""
        with self._lock:
            self._other_drones = {d.drone_id: d for d in drones}
    
    async def _predict_collisions(self) -> None:
        """预测碰撞风险"""
        if not self._drone_state:
            return
        
        collision_risks = []
        
        # 检查每个障碍物
        obstacles = getattr(self, '_obstacles', [])
        for obstacle in obstacles:
            risk = self._calculate_collision_risk(obstacle)
            if risk and risk.probability > 0.1:  # 概率大于10%
                collision_risks.append(risk)
        
        # 检查其他无人机（协同避障）
        if self.enable_coordinated:
            for drone_id, other_drone in self._other_drones.items():
                risk = self._calculate_drone_collision_risk(other_drone)
                if risk and risk.probability > 0.1:
                    collision_risks.append(risk)
        
        with self._lock:
            self._collision_risks = collision_risks
        
        # 触发警告回调
        if collision_risks and self._on_collision_warning:
            high_risks = [r for r in collision_risks if r.risk_level.value >= RiskLevel.HIGH.value]
            if high_risks:
                await self._on_collision_warning(high_risks)
    
    def _calculate_collision_risk(self, obstacle: Obstacle) -> Optional[CollisionRisk]:
        """计算与障碍物的碰撞风险"""
        if not self._drone_state:
            return None
        
        # 计算距离
        distance = self._drone_state.position.distance_to(obstacle.position)
        
        if distance > self.safety_margin + self.prediction_horizon * self._drone_state.speed:
            return None
        
        # 计算碰撞概率
        probability = self._estimate_collision_probability(
            self._drone_state, obstacle, distance
        )
        
        # 计算碰撞时间
        ttc = self._calculate_time_to_collision(
            self._drone_state.position,
            self._drone_state.velocity,
            obstacle.position,
            obstacle.velocity or Velocity(0, 0, 0)
        )
        
        if ttc is None or ttc > self.prediction_horizon:
            return None
        
        # 确定风险等级
        if distance < self.critical_distance or (ttc and ttc < 2.0):
            risk_level = RiskLevel.CRITICAL
        elif distance < self.safety_margin or (ttc and ttc < 5.0):
            risk_level = RiskLevel.HIGH
        else:
            risk_level = RiskLevel.MEDIUM
        
        # 确定避障策略
        strategy = self._determine_avoidance_strategy(obstacle, distance, ttc)
        
        # 计算碰撞点
        collision_point = self._predict_collision_point(
            self._drone_state, obstacle, ttc
        )
        
        return CollisionRisk(
            obstacle_id=obstacle.id,
            probability=probability,
            time_to_collision=ttc,
            collision_point=collision_point,
            risk_level=risk_level,
            avoidance_strategy=strategy
        )
    
    def _calculate_drone_collision_risk(self, other_drone: DroneState) -> Optional[CollisionRisk]:
        """计算与其他无人机的碰撞风险"""
        if not self._drone_state:
            return None
        
        distance = self._drone_state.position.distance_to(other_drone.position)
        
        if distance > self.safety_margin * 2:
            return None
        
        ttc = self._calculate_time_to_collision(
            self._drone_state.position,
            self._drone_state.velocity,
            other_drone.position,
            other_drone.velocity
        )
        
        if ttc is None or ttc > self.prediction_horizon:
            return None
        
        probability = self._estimate_drone_collision_probability(
            self._drone_state, other_drone, distance
        )
        
        risk_level = RiskLevel.HIGH if distance < self.safety_margin else RiskLevel.MEDIUM
        
        strategy = AvoidanceStrategy.COORDINATED if self.enable_coordinated else AvoidanceStrategy.HORIZONTAL
        
        collision_point = self._predict_collision_point_drones(
            self._drone_state, other_drone, ttc
        )
        
        return CollisionRisk(
            obstacle_id=f"drone_{other_drone.drone_id}",
            probability=probability,
            time_to_collision=ttc,
            collision_point=collision_point,
            risk_level=risk_level,
            avoidance_strategy=strategy
        )
    
    def _estimate_collision_probability(
        self, 
        drone_state: DroneState,
        obstacle: Obstacle,
        distance: float
    ) -> float:
        """估算碰撞概率"""
        # 基于距离的概率估算
        if distance < self.critical_distance:
            base_prob = 0.95
        elif distance < self.safety_margin:
            base_prob = 0.7
        else:
            base_prob = max(0, 1 - distance / (self.safety_margin * 2))
        
        # 根据障碍物类型调整
        if obstacle.is_dynamic():
            base_prob *= 1.2  # 动态障碍风险更高
        
        # 根据检测置信度调整
        base_prob *= obstacle.confidence
        
        return min(1.0, base_prob)
    
    def _estimate_drone_collision_probability(
        self,
        drone1: DroneState,
        drone2: DroneState,
        distance: float
    ) -> float:
        """估算无人机间碰撞概率"""
        if distance < self.critical_distance * 2:
            return 0.9
        elif distance < self.safety_margin * 2:
            return 0.6
        else:
            return max(0, 1 - distance / (self.safety_margin * 3))
    
    def _calculate_time_to_collision(
        self,
        pos1: Position, vel1: Velocity,
        pos2: Position, vel2: Velocity
    ) -> Optional[float]:
        """计算碰撞时间"""
        rel_pos = np.array([pos1.x - pos2.x, pos1.y - pos2.y, pos1.z - pos2.z])
        rel_vel = np.array([
            vel1.vx - vel2.vx,
            vel1.vy - vel2.vy,
            vel1.vz - vel2.vz
        ])
        
        a = np.dot(rel_vel, rel_vel)
        if a == 0:
            return None
        
        b = 2 * np.dot(rel_pos, rel_vel)
        collision_distance = 2.0  # 碰撞距离阈值
        c = np.dot(rel_pos, rel_pos) - collision_distance ** 2
        
        discriminant = b * b - 4 * a * c
        if discriminant < 0:
            return None
        
        t1 = (-b - math.sqrt(discriminant)) / (2 * a)
        t2 = (-b + math.sqrt(discriminant)) / (2 * a)
        
        times = [t for t in [t1, t2] if t > 0]
        return min(times) if times else None
    
    def _determine_avoidance_strategy(
        self,
        obstacle: Obstacle,
        distance: float,
        ttc: Optional[float]
    ) -> AvoidanceStrategy:
        """确定避障策略"""
        # 紧急制动条件
        if distance < self.critical_distance or (ttc and ttc < 1.5):
            return AvoidanceStrategy.EMERGENCY_BRAKE
        
        # 根据障碍物类型和位置选择策略
        if obstacle.obstacle_type == ObstacleType.GROUND:
            return AvoidanceStrategy.VERTICAL
        elif obstacle.obstacle_type == ObstacleType.AIRBORNE:
            # 优先水平避障
            return AvoidanceStrategy.HORIZONTAL
        elif obstacle.is_dynamic():
            # 动态障碍 - 绕行
            return AvoidanceStrategy.DETOUR
        else:
            # 默认水平避障
            return AvoidanceStrategy.HORIZONTAL
    
    def _predict_collision_point(
        self,
        drone_state: DroneState,
        obstacle: Obstacle,
        ttc: Optional[float]
    ) -> Position:
        """预测碰撞点"""
        if ttc is None:
            return obstacle.position
        
        # 预测无人机位置
        drone_future = Position(
            drone_state.position.x + drone_state.velocity.vx * ttc,
            drone_state.position.y + drone_state.velocity.vy * ttc,
            drone_state.position.z + drone_state.velocity.vz * ttc
        )
        
        # 预测障碍物位置
        if obstacle.velocity:
            obs_future = Position(
                obstacle.position.x + obstacle.velocity.vx * ttc,
                obstacle.position.y + obstacle.velocity.vy * ttc,
                obstacle.position.z + obstacle.velocity.vz * ttc
            )
        else:
            obs_future = obstacle.position
        
        # 碰撞点为中间点
        return Position(
            (drone_future.x + obs_future.x) / 2,
            (drone_future.y + obs_future.y) / 2,
            (drone_future.z + obs_future.z) / 2
        )
    
    def _predict_collision_point_drones(
        self,
        drone1: DroneState,
        drone2: DroneState,
        ttc: Optional[float]
    ) -> Position:
        """预测两无人机碰撞点"""
        if ttc is None:
            return Position(
                (drone1.position.x + drone2.position.x) / 2,
                (drone1.position.y + drone2.position.y) / 2,
                (drone1.position.z + drone2.position.z) / 2
            )
        
        pos1 = Position(
            drone1.position.x + drone1.velocity.vx * ttc,
            drone1.position.y + drone1.velocity.vy * ttc,
            drone1.position.z + drone1.velocity.vz * ttc
        )
        
        pos2 = Position(
            drone2.position.x + drone2.velocity.vx * ttc,
            drone2.position.y + drone2.velocity.vy * ttc,
            drone2.position.z + drone2.velocity.vz * ttc
        )
        
        return Position(
            (pos1.x + pos2.x) / 2,
            (pos1.y + pos2.y) / 2,
            (pos1.z + pos2.z) / 2
        )
    
    async def _execute_avoidance(self) -> None:
        """执行避障"""
        if not self._collision_risks:
            self._status = AvoidanceStatus.MONITORING
            return
        
        # 获取最高风险
        highest_risk = max(self._collision_risks, key=lambda r: r.risk_level.value)
        
        # 紧急制动
        if highest_risk.avoidance_strategy == AvoidanceStrategy.EMERGENCY_BRAKE:
            await self._emergency_brake(highest_risk)
            return
        
        # 生成避障路径
        if not self._current_path or self._should_replan():
            self._current_path = self._generate_avoidance_path(highest_risk)
            self._status = AvoidanceStatus.AVOIDING
            
            if self._on_avoidance_start:
                await self._on_avoidance_start(self._current_path)
    
    async def _emergency_brake(self, risk: CollisionRisk) -> None:
        """紧急制动"""
        logger.warning(f"Emergency brake triggered for obstacle {risk.obstacle_id}")
        
        self._status = AvoidanceStatus.EMERGENCY
        
        # 生成紧急停止路径
        if self._drone_state:
            stop_point = Position(
                self._drone_state.position.x,
                self._drone_state.position.y,
                self._drone_state.position.z
            )
            
            emergency_path = AvoidancePath(
                waypoints=[stop_point],
                strategy=AvoidanceStrategy.EMERGENCY_BRAKE,
                estimated_time=2.0,
                distance=0.0,
                safety_margin=self.safety_margin
            )
            
            with self._lock:
                self._current_path = emergency_path
            
            # 更新统计
            self._stats['emergency_brakes'] += 1
            
            if self._on_emergency:
                await self._on_emergency(risk, emergency_path)
    
    def _generate_avoidance_path(self, risk: CollisionRisk) -> AvoidancePath:
        """生成避障路径"""
        if not self._drone_state:
            raise ValueError("Drone state not available")
        
        strategy = risk.avoidance_strategy
        
        if strategy == AvoidanceStrategy.VERTICAL:
            waypoints = self._generate_vertical_avoidance(risk)
        elif strategy == AvoidanceStrategy.HORIZONTAL:
            waypoints = self._generate_horizontal_avoidance(risk)
        elif strategy == AvoidanceStrategy.DETOUR:
            waypoints = self._generate_detour_path(risk)
        elif strategy == AvoidanceStrategy.COORDINATED:
            waypoints = self._generate_coordinated_avoidance(risk)
        else:
            waypoints = self._generate_horizontal_avoidance(risk)
        
        # 计算路径长度和时间
        distance = self._calculate_path_distance(waypoints)
        estimated_time = distance / (self._drone_state.max_speed * 0.7)  # 使用70%最大速度
        
        path = AvoidancePath(
            waypoints=waypoints,
            strategy=strategy,
            estimated_time=estimated_time,
            distance=distance,
            safety_margin=self.safety_margin
        )
        
        self._path_history.append(path)
        self._stats['total_avoidances'] += 1
        
        return path
    
    def _generate_vertical_avoidance(self, risk: CollisionRisk) -> List[Position]:
        """生成垂直避障路径"""
        if not self._drone_state:
            return []
        
        current = self._drone_state.position
        
        # 向上或向下避障
        altitude_change = self.safety_margin * 1.5
        
        # 判断向上还是向下
        if risk.collision_point.z > current.z:
            # 障碍物在上方，向下
            new_z = max(5.0, current.z - altitude_change)  # 最低5米
        else:
            # 障碍物在下方，向上
            new_z = current.z + altitude_change
        
        waypoint1 = Position(current.x, current.y, new_z)
        
        # 保持高度前进一段距离
        forward_distance = self.safety_margin * 2
        heading_rad = math.radians(self._drone_state.heading)
        waypoint2 = Position(
            current.x + forward_distance * math.cos(heading_rad),
            current.y + forward_distance * math.sin(heading_rad),
            new_z
        )
        
        return [waypoint1, waypoint2]
    
    def _generate_horizontal_avoidance(self, risk: CollisionRisk) -> List[Position]:
        """生成水平避障路径"""
        if not self._drone_state:
            return []
        
        current = self._drone_state.position
        obstacle_pos = risk.collision_point
        
        # 计算避障方向（垂直于当前航向）
        heading_rad = math.radians(self._drone_state.heading)
        
        # 选择左转或右转
        to_obstacle = np.array([
            obstacle_pos.x - current.x,
            obstacle_pos.y - current.y
        ])
        
        right_vector = np.array([
            math.cos(heading_rad + math.pi / 2),
            math.sin(heading_rad + math.pi / 2)
        ])
        
        # 如果障碍物在右侧，向左转；反之亦然
        dot_product = np.dot(to_obstacle[:2], right_vector)
        turn_direction = -1 if dot_product > 0 else 1
        
        # 生成避障航点
        lateral_distance = self.safety_margin * 1.5
        forward_distance = self.safety_margin * 2
        
        # 侧向移动
        lateral_rad = heading_rad + turn_direction * math.pi / 2
        waypoint1 = Position(
            current.x + lateral_distance * math.cos(lateral_rad),
            current.y + lateral_distance * math.sin(lateral_rad),
            current.z
        )
        
        # 前进
        waypoint2 = Position(
            waypoint1.x + forward_distance * math.cos(heading_rad),
            waypoint1.y + forward_distance * math.sin(heading_rad),
            current.z
        )
        
        # 回到原航线
        waypoint3 = Position(
            waypoint2.x - lateral_distance * math.cos(lateral_rad),
            waypoint2.y - lateral_distance * math.sin(lateral_rad),
            current.z
        )
        
        return [waypoint1, waypoint2, waypoint3]
    
    def _generate_detour_path(self, risk: CollisionRisk) -> List[Position]:
        """生成绕行路径"""
        if not self._drone_state:
            return []
        
        # 使用A*或RRT算法生成绕行路径（简化版）
        # 实际应用中应使用完整的路径规划算法
        
        current = self._drone_state.position
        heading_rad = math.radians(self._drone_state.heading)
        
        # 生成弧形绕行路径
        waypoints = []
        turn_direction = 1  # 1为右转，-1为左转
        
        radius = self.safety_margin * 2
        num_points = 5
        
        for i in range(num_points):
            angle = heading_rad + turn_direction * (math.pi / 2) * (i / (num_points - 1))
            forward = radius * (1 - math.cos(angle - heading_rad))
            lateral = radius * math.sin(angle - heading_rad)
            
            waypoint = Position(
                current.x + forward * math.cos(heading_rad) - lateral * math.sin(heading_rad),
                current.y + forward * math.sin(heading_rad) + lateral * math.cos(heading_rad),
                current.z
            )
            waypoints.append(waypoint)
        
        return waypoints
    
    def _generate_coordinated_avoidance(self, risk: CollisionRisk) -> List[Position]:
        """生成协同避障路径"""
        if not self._drone_state:
            return []
        
        # 协同避障 - 两架无人机都移动
        # 基于右行规则
        current = self._drone_state.position
        heading_rad = math.radians(self._drone_state.heading)
        
        # 向右移动
        lateral_distance = self.safety_margin * 0.75
        right_rad = heading_rad + math.pi / 2
        
        waypoint1 = Position(
            current.x + lateral_distance * math.cos(right_rad),
            current.y + lateral_distance * math.sin(right_rad),
            current.z
        )
        
        # 前进
        forward_distance = self.safety_margin * 1.5
        waypoint2 = Position(
            waypoint1.x + forward_distance * math.cos(heading_rad),
            waypoint1.y + forward_distance * math.sin(heading_rad),
            current.z
        )
        
        # 回到航线
        waypoint3 = Position(
            waypoint2.x - lateral_distance * math.cos(right_rad),
            waypoint2.y - lateral_distance * math.sin(right_rad),
            current.z
        )
        
        self._stats['coordinated_avoidances'] += 1
        
        return [waypoint1, waypoint2, waypoint3]
    
    def _should_replan(self) -> bool:
        """判断是否需要重新规划"""
        if not self._current_path:
            return True
        
        # 路径过期（超过5秒）
        if time.time() - self._current_path.created_at > 5.0:
            return True
        
        # 风险变化
        if self._collision_risks:
            highest_risk = max(self._collision_risks, key=lambda r: r.risk_level.value)
            if highest_risk.risk_level == RiskLevel.CRITICAL:
                return True
        
        return False
    
    def _calculate_path_distance(self, waypoints: List[Position]) -> float:
        """计算路径总长度"""
        if len(waypoints) < 2:
            return 0.0
        
        distance = 0.0
        for i in range(len(waypoints) - 1):
            distance += waypoints[i].distance_to(waypoints[i + 1])
        
        return distance
    
    def get_current_path(self) -> Optional[AvoidancePath]:
        """获取当前避障路径"""
        with self._lock:
            return self._current_path
    
    def get_collision_risks(self) -> List[CollisionRisk]:
        """获取碰撞风险列表"""
        with self._lock:
            return self._collision_risks.copy()
    
    def get_status(self) -> AvoidanceStatus:
        """获取状态"""
        return self._status
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        return self._stats.copy()
    
    def set_callbacks(
        self,
        on_warning: Optional[Callable] = None,
        on_avoidance_start: Optional[Callable] = None,
        on_avoidance_complete: Optional[Callable] = None,
        on_emergency: Optional[Callable] = None
    ) -> None:
        """设置回调函数"""
        self._on_collision_warning = on_warning
        self._on_avoidance_start = on_avoidance_start
        self._on_avoidance_complete = on_avoidance_complete
        self._on_emergency = on_emergency
