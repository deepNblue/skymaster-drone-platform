"""
SkyMaster 障碍检测模块
实时障碍检测、分类、追踪和风险评估
"""

import asyncio
import time
import math
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import logging
from threading import Lock
import numpy as np

logger = logging.getLogger(__name__)


class ObstacleType(Enum):
    """障碍物类型"""
    STATIC = "static"           # 静态障碍（建筑物、树木等）
    DYNAMIC = "dynamic"         # 动态障碍（飞行器、鸟类等）
    GROUND = "ground"           # 地面障碍
    AIRBORNE = "airborne"       # 空中障碍
    WEATHER = "weather"         # 天气障碍（云、雾等）
    UNKNOWN = "unknown"         # 未知类型


class ObstacleStatus(Enum):
    """障碍物状态"""
    ACTIVE = "active"           # 活动中
    TRACKED = "tracked"         # 追踪中
    LOST = "lost"               # 丢失
    CLEARED = "cleared"         # 已清除
    POTENTIAL = "potential"     # 潜在障碍


class RiskLevel(Enum):
    """风险等级"""
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class Position:
    """3D位置"""
    x: float  # 米
    y: float  # 米
    z: float  # 米（高度）
    timestamp: float = field(default_factory=time.time)
    
    def distance_to(self, other: 'Position') -> float:
        """计算到另一个位置的距离"""
        return math.sqrt(
            (self.x - other.x) ** 2 +
            (self.y - other.y) ** 2 +
            (self.z - other.z) ** 2
        )
    
    def to_dict(self) -> Dict:
        return {
            'x': self.x,
            'y': self.y,
            'z': self.z,
            'timestamp': self.timestamp
        }


@dataclass
class Velocity:
    """3D速度"""
    vx: float  # m/s
    vy: float  # m/s
    vz: float  # m/s
    timestamp: float = field(default_factory=time.time)
    
    def magnitude(self) -> float:
        """计算速度大小"""
        return math.sqrt(self.vx ** 2 + self.vy ** 2 + self.vz ** 2)
    
    def to_dict(self) -> Dict:
        return {
            'vx': self.vx,
            'vy': self.vy,
            'vz': self.vz,
            'timestamp': self.timestamp
        }


@dataclass
class Obstacle:
    """障碍物"""
    id: str
    obstacle_type: ObstacleType
    status: ObstacleStatus
    position: Position
    velocity: Optional[Velocity] = None
    size: Tuple[float, float, float] = (1.0, 1.0, 1.0)  # 长、宽、高（米）
    confidence: float = 1.0  # 检测置信度 0-1
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    risk_level: RiskLevel = RiskLevel.LOW
    metadata: Dict = field(default_factory=dict)
    
    def update_position(self, new_position: Position) -> None:
        """更新位置"""
        if self.position:
            # 计算速度
            dt = new_position.timestamp - self.position.timestamp
            if dt > 0:
                vx = (new_position.x - self.position.x) / dt
                vy = (new_position.y - self.position.y) / dt
                vz = (new_position.z - self.position.z) / dt
                self.velocity = Velocity(vx, vy, vz, new_position.timestamp)
        
        self.position = new_position
        self.last_seen = time.time()
    
    def is_dynamic(self) -> bool:
        """判断是否为动态障碍"""
        if self.obstacle_type == ObstacleType.DYNAMIC:
            return True
        if self.velocity and self.velocity.magnitude() > 0.5:  # 速度>0.5m/s视为动态
            return True
        return False
    
    def get_bounding_box(self) -> Tuple[Position, Position]:
        """获取包围盒"""
        half_size = (self.size[0] / 2, self.size[1] / 2, self.size[2] / 2)
        min_pos = Position(
            self.position.x - half_size[0],
            self.position.y - half_size[1],
            self.position.z - half_size[2]
        )
        max_pos = Position(
            self.position.x + half_size[0],
            self.position.y + half_size[1],
            self.position.z + half_size[2]
        )
        return min_pos, max_pos
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            'id': self.id,
            'type': self.obstacle_type.value,
            'status': self.status.value,
            'position': self.position.to_dict(),
            'velocity': self.velocity.to_dict() if self.velocity else None,
            'size': self.size,
            'confidence': self.confidence,
            'first_seen': self.first_seen,
            'last_seen': self.last_seen,
            'risk_level': self.risk_level.value,
            'metadata': self.metadata
        }


@dataclass
class SensorData:
    """传感器数据"""
    sensor_id: str
    sensor_type: str  # 'lidar', 'camera', 'radar', 'ultrasonic'
    timestamp: float
    data: Dict
    confidence: float = 1.0


class ObstacleDetector:
    """
    障碍检测器
    负责实时检测、分类、追踪障碍物并进行风险评估
    """
    
    def __init__(
        self,
        detection_range: float = 50.0,  # 检测范围（米）
        update_interval: float = 0.1,   # 更新间隔（秒）
        min_confidence: float = 0.6,    # 最小置信度
        max_obstacles: int = 100        # 最大障碍物数量
    ):
        self.detection_range = detection_range
        self.update_interval = update_interval
        self.min_confidence = min_confidence
        self.max_obstacles = max_obstacles
        
        # 障碍物存储
        self._obstacles: Dict[str, Obstacle] = {}
        self._lock = Lock()
        
        # 检测器状态
        self._running = False
        self._detection_task: Optional[asyncio.Task] = None
        
        # 统计信息
        self._stats = {
            'total_detected': 0,
            'active_obstacles': 0,
            'dynamic_obstacles': 0,
            'high_risk_count': 0
        }
        
        # 回调函数
        self._on_obstacle_detected = None
        self._on_obstacle_updated = None
        self._on_obstacle_cleared = None
        
        logger.info(f"ObstacleDetector initialized with range={detection_range}m")
    
    async def start(self) -> None:
        """启动检测器"""
        if self._running:
            logger.warning("ObstacleDetector is already running")
            return
        
        self._running = True
        self._detection_task = asyncio.create_task(self._detection_loop())
        logger.info("ObstacleDetector started")
    
    async def stop(self) -> None:
        """停止检测器"""
        self._running = False
        if self._detection_task:
            self._detection_task.cancel()
            try:
                await self._detection_task
            except asyncio.CancelledError:
                pass
        logger.info("ObstacleDetector stopped")
    
    async def _detection_loop(self) -> None:
        """检测循环"""
        while self._running:
            try:
                await self._update_obstacles()
                await asyncio.sleep(self.update_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in detection loop: {e}")
                await asyncio.sleep(1.0)
    
    async def _update_obstacles(self) -> None:
        """更新障碍物状态"""
        current_time = time.time()
        
        with self._lock:
            # 清理过期障碍物
            obstacles_to_remove = []
            for obs_id, obstacle in self._obstacles.items():
                # 超过5秒未更新视为丢失
                if current_time - obstacle.last_seen > 5.0:
                    obstacle.status = ObstacleStatus.LOST
                    obstacles_to_remove.append(obs_id)
            
            for obs_id in obstacles_to_remove:
                del self._obstacles[obs_id]
                if self._on_obstacle_cleared:
                    await self._on_obstacle_cleared(obs_id)
            
            # 更新统计信息
            self._update_stats()
    
    def process_sensor_data(self, sensor_data: SensorData) -> List[Obstacle]:
        """
        处理传感器数据并检测障碍物
        
        Args:
            sensor_data: 传感器数据
            
        Returns:
            检测到的障碍物列表
        """
        if sensor_data.confidence < self.min_confidence:
            return []
        
        detected_obstacles = []
        
        # 根据传感器类型处理数据
        if sensor_data.sensor_type == 'lidar':
            detected_obstacles = self._process_lidar_data(sensor_data)
        elif sensor_data.sensor_type == 'camera':
            detected_obstacles = self._process_camera_data(sensor_data)
        elif sensor_data.sensor_type == 'radar':
            detected_obstacles = self._process_radar_data(sensor_data)
        elif sensor_data.sensor_type == 'ultrasonic':
            detected_obstacles = self._process_ultrasonic_data(sensor_data)
        
        # 更新障碍物存储
        for obstacle in detected_obstacles:
            self._add_or_update_obstacle(obstacle)
        
        return detected_obstacles
    
    def _process_lidar_data(self, sensor_data: SensorData) -> List[Obstacle]:
        """处理激光雷达数据"""
        obstacles = []
        points = sensor_data.data.get('points', [])
        
        # 聚类点云数据
        clusters = self._cluster_points(points)
        
        for cluster in clusters:
            if len(cluster) < 3:  # 最小点数
                continue
            
            # 计算聚类中心和大小
            center, size = self._calculate_cluster_bounds(cluster)
            
            obstacle = Obstacle(
                id=f"lidar_{sensor_data.sensor_id}_{len(obstacles)}",
                obstacle_type=ObstacleType.STATIC,
                status=ObstacleStatus.ACTIVE,
                position=Position(*center, sensor_data.timestamp),
                size=size,
                confidence=sensor_data.confidence
            )
            obstacles.append(obstacle)
        
        return obstacles
    
    def _process_camera_data(self, sensor_data: SensorData) -> List[Obstacle]:
        """处理摄像头数据"""
        obstacles = []
        detections = sensor_data.data.get('detections', [])
        
        for detection in detections:
            obstacle_type = self._classify_detection(detection)
            
            # 从2D检测估算3D位置（简化）
            position = self._estimate_3d_position(detection, sensor_data)
            
            obstacle = Obstacle(
                id=f"cam_{sensor_data.sensor_id}_{detection.get('id', 'unknown')}",
                obstacle_type=obstacle_type,
                status=ObstacleStatus.ACTIVE,
                position=position,
                size=detection.get('size', (1.0, 1.0, 1.0)),
                confidence=detection.get('confidence', 0.8)
            )
            obstacles.append(obstacle)
        
        return obstacles
    
    def _process_radar_data(self, sensor_data: SensorData) -> List[Obstacle]:
        """处理雷达数据"""
        obstacles = []
        targets = sensor_data.data.get('targets', [])
        
        for target in targets:
            # 雷达提供速度信息，可用于检测动态障碍
            obstacle_type = ObstacleType.DYNAMIC if target.get('speed', 0) > 0.5 else ObstacleType.STATIC
            
            obstacle = Obstacle(
                id=f"radar_{sensor_data.sensor_id}_{target.get('id', 'unknown')}",
                obstacle_type=obstacle_type,
                status=ObstacleStatus.ACTIVE,
                position=Position(
                    target.get('x', 0),
                    target.get('y', 0),
                    target.get('z', 0),
                    sensor_data.timestamp
                ),
                velocity=Velocity(
                    target.get('vx', 0),
                    target.get('vy', 0),
                    target.get('vz', 0),
                    sensor_data.timestamp
                ) if 'vx' in target else None,
                confidence=sensor_data.confidence
            )
            obstacles.append(obstacle)
        
        return obstacles
    
    def _process_ultrasonic_data(self, sensor_data: SensorData) -> List[Obstacle]:
        """处理超声波数据"""
        obstacles = []
        distances = sensor_data.data.get('distances', [])
        
        for i, distance in enumerate(distances):
            if distance < self.detection_range:
                # 简化的位置估算
                angle = sensor_data.data.get('angles', [0])[i] if i < len(sensor_data.data.get('angles', [])) else 0
                
                obstacle = Obstacle(
                    id=f"ultra_{sensor_data.sensor_id}_{i}",
                    obstacle_type=ObstacleType.STATIC,
                    status=ObstacleStatus.POTENTIAL,
                    position=Position(
                        distance * math.cos(angle),
                        distance * math.sin(angle),
                        0,
                        sensor_data.timestamp
                    ),
                    confidence=0.7  # 超声波精度较低
                )
                obstacles.append(obstacle)
        
        return obstacles
    
    def _cluster_points(self, points: List[Tuple[float, float, float]]) -> List[List[Tuple[float, float, float]]]:
        """点云聚类（简化版DBSCAN）"""
        if not points:
            return []
        
        clusters = []
        visited = set()
        eps = 0.5  # 聚类半径
        min_points = 3
        
        points_array = np.array(points)
        
        for i, point in enumerate(points_array):
            if i in visited:
                continue
            
            # 找到邻近点
            distances = np.linalg.norm(points_array - point, axis=1)
            neighbors = np.where(distances < eps)[0]
            
            if len(neighbors) >= min_points:
                cluster = []
                for neighbor_idx in neighbors:
                    if neighbor_idx not in visited:
                        visited.add(neighbor_idx)
                        cluster.append(tuple(points_array[neighbor_idx]))
                if cluster:
                    clusters.append(cluster)
        
        return clusters
    
    def _calculate_cluster_bounds(
        self, 
        cluster: List[Tuple[float, float, float]]
    ) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
        """计算聚类边界"""
        points_array = np.array(cluster)
        center = tuple(points_array.mean(axis=0))
        
        # 计算包围盒大小
        min_vals = points_array.min(axis=0)
        max_vals = points_array.max(axis=0)
        size = tuple(max_vals - min_vals)
        
        return center, size
    
    def _classify_detection(self, detection: Dict) -> ObstacleType:
        """分类检测到的物体"""
        label = detection.get('label', '').lower()
        
        if label in ['bird', 'drone', 'aircraft', 'helicopter']:
            return ObstacleType.DYNAMIC
        elif label in ['building', 'tree', 'pole', 'tower']:
            return ObstacleType.STATIC
        elif label in ['cloud', 'fog']:
            return ObstacleType.WEATHER
        else:
            return ObstacleType.UNKNOWN
    
    def _estimate_3d_position(self, detection: Dict, sensor_data: SensorData) -> Position:
        """从2D检测估算3D位置"""
        # 简化估算 - 实际应用中需要相机标定和深度估计
        bbox = detection.get('bbox', [0, 0, 100, 100])
        depth = detection.get('depth', 10.0)  # 默认10米
        
        # 假设相机朝向前方
        x = (bbox[0] + bbox[2]) / 2 - 320  # 假设图像宽度640
        y = (bbox[1] + bbox[3]) / 2 - 240  # 假设图像高度480
        
        return Position(
            x * depth / 320,
            y * depth / 240,
            depth,
            sensor_data.timestamp
        )
    
    def _add_or_update_obstacle(self, obstacle: Obstacle) -> None:
        """添加或更新障碍物"""
        with self._lock:
            if obstacle.id in self._obstacles:
                # 更新现有障碍物
                existing = self._obstacles[obstacle.id]
                existing.update_position(obstacle.position)
                existing.status = ObstacleStatus.TRACKED
                existing.confidence = (existing.confidence + obstacle.confidence) / 2
            else:
                # 添加新障碍物
                if len(self._obstacles) < self.max_obstacles:
                    self._obstacles[obstacle.id] = obstacle
                    self._stats['total_detected'] += 1
    
    def assess_risk(
        self, 
        obstacle: Obstacle, 
        drone_position: Position,
        drone_velocity: Optional[Velocity] = None
    ) -> RiskLevel:
        """
        评估障碍物风险等级
        
        Args:
            obstacle: 障碍物
            drone_position: 无人机位置
            drone_velocity: 无人机速度
            
        Returns:
            风险等级
        """
        # 计算距离
        distance = obstacle.position.distance_to(drone_position)
        
        # 基于距离的风险评估
        if distance < 5:
            base_risk = RiskLevel.CRITICAL
        elif distance < 10:
            base_risk = RiskLevel.HIGH
        elif distance < 20:
            base_risk = RiskLevel.MEDIUM
        else:
            base_risk = RiskLevel.LOW
        
        # 动态障碍增加风险
        if obstacle.is_dynamic():
            if base_risk.value < RiskLevel.HIGH.value:
                base_risk = RiskLevel(base_risk.value + 1)
        
        # 考虑碰撞时间(TTC)
        if drone_velocity and obstacle.velocity:
            ttc = self._calculate_time_to_collision(
                drone_position, drone_velocity,
                obstacle.position, obstacle.velocity
            )
            if ttc is not None and ttc < 3.0:  # 3秒内可能碰撞
                base_risk = RiskLevel.CRITICAL
            elif ttc is not None and ttc < 5.0:  # 5秒内可能碰撞
                if base_risk.value < RiskLevel.HIGH.value:
                    base_risk = RiskLevel(base_risk.value + 1)
        
        obstacle.risk_level = base_risk
        return base_risk
    
    def _calculate_time_to_collision(
        self,
        pos1: Position, vel1: Velocity,
        pos2: Position, vel2: Velocity
    ) -> Optional[float]:
        """计算碰撞时间"""
        # 相对位置和速度
        rel_pos = np.array([pos1.x - pos2.x, pos1.y - pos2.y, pos1.z - pos2.z])
        rel_vel = np.array([
            vel1.vx - vel2.vx,
            vel1.vy - vel2.vy,
            vel1.vz - vel2.vz
        ])
        
        # 求解二次方程
        a = np.dot(rel_vel, rel_vel)
        b = 2 * np.dot(rel_pos, rel_vel)
        c = np.dot(rel_pos, rel_pos) - 1  # 假设碰撞距离1米
        
        if a == 0:
            return None
        
        discriminant = b * b - 4 * a * c
        if discriminant < 0:
            return None
        
        t1 = (-b - math.sqrt(discriminant)) / (2 * a)
        t2 = (-b + math.sqrt(discriminant)) / (2 * a)
        
        # 返回最小的正时间
        times = [t for t in [t1, t2] if t > 0]
        return min(times) if times else None
    
    def get_obstacles(
        self,
        obstacle_type: Optional[ObstacleType] = None,
        status: Optional[ObstacleStatus] = None,
        min_risk: Optional[RiskLevel] = None
    ) -> List[Obstacle]:
        """
        获取障碍物列表
        
        Args:
            obstacle_type: 障碍物类型过滤
            status: 状态过滤
            min_risk: 最小风险等级过滤
            
        Returns:
            障碍物列表
        """
        with self._lock:
            obstacles = list(self._obstacles.values())
        
        # 应用过滤
        if obstacle_type:
            obstacles = [o for o in obstacles if o.obstacle_type == obstacle_type]
        if status:
            obstacles = [o for o in obstacles if o.status == status]
        if min_risk:
            obstacles = [o for o in obstacles if o.risk_level.value >= min_risk.value]
        
        return obstacles
    
    def get_obstacle_by_id(self, obstacle_id: str) -> Optional[Obstacle]:
        """根据ID获取障碍物"""
        with self._lock:
            return self._obstacles.get(obstacle_id)
    
    def clear_obstacle(self, obstacle_id: str) -> bool:
        """清除障碍物"""
        with self._lock:
            if obstacle_id in self._obstacles:
                del self._obstacles[obstacle_id]
                return True
            return False
    
    def _update_stats(self) -> None:
        """更新统计信息"""
        obstacles = list(self._obstacles.values())
        self._stats['active_obstacles'] = len(obstacles)
        self._stats['dynamic_obstacles'] = sum(1 for o in obstacles if o.is_dynamic())
        self._stats['high_risk_count'] = sum(
            1 for o in obstacles 
            if o.risk_level.value >= RiskLevel.HIGH.value
        )
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        with self._lock:
            return self._stats.copy()
    
    def set_callbacks(
        self,
        on_detected=None,
        on_updated=None,
        on_cleared=None
    ) -> None:
        """设置回调函数"""
        self._on_obstacle_detected = on_detected
        self._on_obstacle_updated = on_updated
        self._on_obstacle_cleared = on_cleared
