"""
集群控制器 - 多机协同、编队飞行、任务分配
支持集群管理、编队控制、碰撞避免
"""

import asyncio
import logging
from typing import Dict, List, Optional, Tuple, Any, Set
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import math
import random
from collections import defaultdict

from ..devices.manager import DeviceManager, DroneDevice, DeviceStatus
from ..missions.planner import Mission, MissionPlanner, Waypoint, Position
from ..mavlink.connector import TelemetryData

logger = logging.getLogger(__name__)


class FormationType(Enum):
    """编队类型"""
    LINE = "line"  # 直线编队
    V_SHAPE = "v_shape"  # V形编队
    CIRCLE = "circle"  # 圆形编队
    GRID = "grid"  # 网格编队
    FREE = "free"  # 自由编队


class SwarmState(Enum):
    """集群状态"""
    IDLE = "idle"  # 空闲
    FORMING = "forming"  # 编队中
    FLYING = "flying"  # 飞行中
    EXECUTING_MISSION = "executing_mission"  # 执行任务中
    RETURNING = "returning"  # 返航中
    EMERGENCY = "emergency"  # 紧急状态


@dataclass
class FormationSlot:
    """编队槽位"""
    slot_id: str
    position: Position  # 相对位置
    device_id: Optional[str] = None  # 占用的设备ID
    offset_north: float = 0.0  # 北向偏移（米）
    offset_east: float = 0.0  # 东向偏移（米）
    offset_altitude: float = 0.0  # 高度偏移（米）


@dataclass
class SwarmConfig:
    """集群配置"""
    swarm_id: str
    name: str
    formation_type: FormationType = FormationType.LINE
    spacing: float = 10.0  # 编队间距（米）
    altitude_offset: float = 5.0  # 高度层差（米）
    
    # 碰撞避免
    min_separation: float = 5.0  # 最小间隔（米）
    collision_avoidance: bool = True
    
    # 同步参数
    sync_tolerance: float = 2.0  # 同步容差（米）
    wait_timeout: float = 30.0  # 等待超时（秒）


@dataclass
class SwarmStatus:
    """集群状态"""
    state: SwarmState = SwarmState.IDLE
    leader_id: Optional[str] = None  # 领机ID
    formation_complete: bool = False  # 编队是否完成
    active_count: int = 0  # 活跃数量
    total_distance: float = 0.0  # 总飞行距离
    average_speed: float = 0.0  # 平均速度
    last_update: datetime = field(default_factory=datetime.now)


class FormationGenerator:
    """编队生成器"""
    
    @staticmethod
    def generate_formation(formation_type: FormationType, 
                          num_slots: int,
                          spacing: float,
                          altitude_offset: float = 5.0) -> List[FormationSlot]:
        """生成编队槽位"""
        slots = []
        
        if formation_type == FormationType.LINE:
            # 直线编队
            for i in range(num_slots):
                offset = (i - (num_slots - 1) / 2) * spacing
                slot = FormationSlot(
                    slot_id=f"slot_{i}",
                    position=Position(0, 0, 0),
                    offset_north=0,
                    offset_east=offset,
                    offset_altitude=i * altitude_offset if i > 0 else 0
                )
                slots.append(slot)
        
        elif formation_type == FormationType.V_SHAPE:
            # V形编队
            for i in range(num_slots):
                row = i // 2
                side = i % 2  # 0=左，1=右
                
                if i == 0:
                    # 领机
                    offset_north = 0
                    offset_east = 0
                else:
                    offset_north = -row * spacing
                    offset_east = (side * 2 - 1) * row * spacing / 2
                
                slot = FormationSlot(
                    slot_id=f"slot_{i}",
                    position=Position(0, 0, 0),
                    offset_north=offset_north,
                    offset_east=offset_east,
                    offset_altitude=row * altitude_offset
                )
                slots.append(slot)
        
        elif formation_type == FormationType.CIRCLE:
            # 圆形编队
            radius = spacing * num_slots / (2 * math.pi)
            
            for i in range(num_slots):
                angle = 2 * math.pi * i / num_slots
                offset_north = radius * math.cos(angle)
                offset_east = radius * math.sin(angle)
                
                slot = FormationSlot(
                    slot_id=f"slot_{i}",
                    position=Position(0, 0, 0),
                    offset_north=offset_north,
                    offset_east=offset_east,
                    offset_altitude=0
                )
                slots.append(slot)
        
        elif formation_type == FormationType.GRID:
            # 网格编队
            cols = int(math.ceil(math.sqrt(num_slots)))
            rows = int(math.ceil(num_slots / cols))
            
            idx = 0
            for row in range(rows):
                for col in range(cols):
                    if idx >= num_slots:
                        break
                    
                    offset_north = (row - rows / 2) * spacing
                    offset_east = (col - cols / 2) * spacing
                    
                    slot = FormationSlot(
                        slot_id=f"slot_{idx}",
                        position=Position(0, 0, 0),
                        offset_north=offset_north,
                        offset_east=offset_east,
                        offset_altitude=0
                    )
                    slots.append(slot)
                    idx += 1
        
        return slots


class TaskAllocator:
    """任务分配器"""
    
    @staticmethod
    def allocate_mission(devices: List[DroneDevice], 
                        mission: Mission,
                        allocation_strategy: str = "nearest") -> Dict[str, List[Waypoint]]:
        """分配任务给设备
        
        Args:
            devices: 设备列表
            mission: 任务
            allocation_strategy: 分配策略（nearest/balanced/random）
        
        Returns:
            设备ID到航点列表的映射
        """
        if not devices or not mission.waypoints:
            return {}
        
        allocation = {device.device_id: [] for device in devices}
        
        if allocation_strategy == "nearest":
            # 最近分配：将航点分配给最近的设备
            remaining_waypoints = list(mission.waypoints)
            device_positions = {
                device.device_id: device.connector.telemetry if device.connector else None
                for device in devices
            }
            
            while remaining_waypoints:
                for device in devices:
                    if not remaining_waypoints:
                        break
                    
                    if device.connector and device.connector.state.name == "CONNECTED":
                        # 找到最近的航点
                        device_pos = Position(
                            device.connector.telemetry.latitude,
                            device.connector.telemetry.longitude,
                            device.connector.telemetry.altitude
                        )
                        
                        nearest_idx = 0
                        min_dist = float('inf')
                        
                        for i, wp in enumerate(remaining_waypoints):
                            dist = device_pos.distance_to(wp.position)
                            if dist < min_dist:
                                min_dist = dist
                                nearest_idx = i
                        
                        allocation[device.device_id].append(remaining_waypoints.pop(nearest_idx))
        
        elif allocation_strategy == "balanced":
            # 平衡分配：均匀分配航点
            waypoints_per_device = len(mission.waypoints) // len(devices)
            remainder = len(mission.waypoints) % len(devices)
            
            idx = 0
            for i, device in enumerate(devices):
                count = waypoints_per_device + (1 if i < remainder else 0)
                allocation[device.device_id] = mission.waypoints[idx:idx+count]
                idx += count
        
        elif allocation_strategy == "random":
            # 随机分配
            random.shuffle(mission.waypoints)
            waypoints_per_device = len(mission.waypoints) // len(devices)
            
            idx = 0
            for device in devices:
                allocation[device.device_id] = mission.waypoints[idx:idx+waypoints_per_device]
                idx += waypoints_per_device
        
        return allocation


class CollisionAvoidance:
    """碰撞避免系统"""
    
    def __init__(self, min_separation: float = 5.0):
        self.min_separation = min_separation
        self.warning_separation = min_separation * 2
    
    def check_collisions(self, 
                        telemetry_data: Dict[str, TelemetryData]) -> List[Tuple[str, str, float]]:
        """检查碰撞风险
        
        Returns:
            冲突列表 [(device_id1, device_id2, distance), ...]
        """
        collisions = []
        device_ids = list(telemetry_data.keys())
        
        for i in range(len(device_ids)):
            for j in range(i + 1, len(device_ids)):
                id1 = device_ids[i]
                id2 = device_ids[j]
                
                t1 = telemetry_data[id1]
                t2 = telemetry_data[id2]
                
                # 计算距离
                pos1 = Position(t1.latitude, t1.longitude, t1.altitude)
                pos2 = Position(t2.latitude, t2.longitude, t2.altitude)
                
                distance = pos1.distance_to(pos2)
                
                if distance < self.min_separation:
                    collisions.append((id1, id2, distance))
        
        return collisions
    
    def calculate_avoidance_vector(self,
                                   telemetry1: TelemetryData,
                                   telemetry2: TelemetryData) -> Tuple[float, float]:
        """计算避碰向量
        
        Returns:
            (北向偏移, 东向偏移)
        """
        # 计算相对位置
        lat_diff = telemetry2.latitude - telemetry1.latitude
        lon_diff = telemetry2.longitude - telemetry1.longitude
        
        # 转换为米
        north_diff = lat_diff * 111000
        east_diff = lon_diff * 111000 * math.cos(math.radians(telemetry1.latitude))
        
        # 计算反方向向量
        distance = math.sqrt(north_diff**2 + east_diff**2)
        
        if distance > 0:
            # 归一化并缩放
            scale = self.min_separation - distance + 2  # 额外2米安全距离
            avoid_north = -north_diff / distance * scale
            avoid_east = -east_diff / distance * scale
            
            return avoid_north, avoid_east
        
        return 0.0, 0.0


class SwarmController:
    """集群控制器"""
    
    def __init__(self, device_manager: DeviceManager):
        self.device_manager = device_manager
        self.swarms: Dict[str, SwarmConfig] = {}
        self.swarm_status: Dict[str, SwarmStatus] = {}
        self.swarm_devices: Dict[str, Set[str]] = {}  # swarm_id -> device_ids
        self.swarm_formations: Dict[str, List[FormationSlot]] = {}
        
        # 组件
        self.task_allocator = TaskAllocator()
        self.collision_avoidance = CollisionAvoidance()
        
        # 回调
        self.status_callbacks: List[Any] = []
        
        # 运行标志
        self._running = False
        self._tasks: List[asyncio.Task] = []
    
    async def start(self):
        """启动集群控制器"""
        self._running = True
        self._tasks.append(asyncio.create_task(self._monitor_loop()))
        self._tasks.append(asyncio.create_task(self._collision_check_loop()))
        logger.info("Swarm controller started")
    
    async def stop(self):
        """停止集群控制器"""
        self._running = False
        
        for task in self._tasks:
            task.cancel()
        
        logger.info("Swarm controller stopped")
    
    # 集群管理
    async def create_swarm(self, config: SwarmConfig) -> bool:
        """创建集群"""
        if config.swarm_id in self.swarms:
            logger.warning(f"Swarm {config.swarm_id} already exists")
            return False
        
        self.swarms[config.swarm_id] = config
        self.swarm_status[config.swarm_id] = SwarmStatus()
        self.swarm_devices[config.swarm_id] = set()
        
        logger.info(f"Swarm created: {config.swarm_id}")
        
        return True
    
    async def delete_swarm(self, swarm_id: str) -> bool:
        """删除集群"""
        if swarm_id not in self.swarms:
            return False
        
        del self.swarms[swarm_id]
        del self.swarm_status[swarm_id]
        del self.swarm_devices[swarm_id]
        
        if swarm_id in self.swarm_formations:
            del self.swarm_formations[swarm_id]
        
        logger.info(f"Swarm deleted: {swarm_id}")
        
        return True
    
    async def add_device_to_swarm(self, device_id: str, swarm_id: str) -> bool:
        """将设备添加到集群"""
        if swarm_id not in self.swarms:
            logger.error(f"Swarm {swarm_id} not found")
            return False
        
        if device_id not in self.device_manager.devices:
            logger.error(f"Device {device_id} not found")
            return False
        
        self.swarm_devices[swarm_id].add(device_id)
        
        # 重新生成编队
        await self._regenerate_formation(swarm_id)
        
        logger.info(f"Device {device_id} added to swarm {swarm_id}")
        
        return True
    
    async def remove_device_from_swarm(self, device_id: str, swarm_id: str) -> bool:
        """从集群中移除设备"""
        if swarm_id not in self.swarms:
            return False
        
        if device_id in self.swarm_devices[swarm_id]:
            self.swarm_devices[swarm_id].remove(device_id)
            
            # 重新生成编队
            await self._regenerate_formation(swarm_id)
            
            logger.info(f"Device {device_id} removed from swarm {swarm_id}")
        
        return True
    
    async def _regenerate_formation(self, swarm_id: str):
        """重新生成编队"""
        config = self.swarms.get(swarm_id)
        if not config:
            return
        
        device_ids = self.swarm_devices.get(swarm_id, [])
        num_slots = len(device_ids)
        
        # 生成编队槽位
        slots = FormationGenerator.generate_formation(
            config.formation_type,
            num_slots,
            config.spacing,
            config.altitude_offset
        )
        
        # 分配设备到槽位
        for i, device_id in enumerate(device_ids):
            if i < len(slots):
                slots[i].device_id = device_id
        
        self.swarm_formations[swarm_id] = slots
        
        logger.info(f"Formation regenerated for swarm {swarm_id}")
    
    # 编队控制
    async def form_formation(self, swarm_id: str, 
                            center: Position) -> bool:
        """编队成形
        
        Args:
            swarm_id: 集群ID
            center: 编队中心位置
        """
        if swarm_id not in self.swarms:
            return False
        
        config = self.swarms[swarm_id]
        status = self.swarm_status[swarm_id]
        formation = self.swarm_formations.get(swarm_id, [])
        
        status.state = SwarmState.FORMING
        
        # 发送每个设备到其编队位置
        for slot in formation:
            if not slot.device_id:
                continue
            
            # 计算目标位置
            target_lat = center.latitude + slot.offset_north / 111000.0
            target_lon = center.longitude + slot.offset_east / \
                        (111000.0 * math.cos(math.radians(center.latitude)))
            target_alt = center.altitude + slot.offset_altitude
            
            # 发送goto命令
            await self.device_manager.send_command(
                slot.device_id,
                "goto",
                {
                    'latitude': target_lat,
                    'longitude': target_lon,
                    'altitude': target_alt
                }
            )
        
        # 等待编队完成
        await asyncio.sleep(5)  # 简化：等待5秒
        
        status.formation_complete = True
        status.state = SwarmState.FLYING
        
        logger.info(f"Swarm {swarm_id} formation completed")
        
        return True
    
    async def move_formation(self, swarm_id: str, 
                           target: Position,
                           speed: float = 5.0) -> bool:
        """移动编队
        
        Args:
            swarm_id: 集群ID
            target: 目标位置（编队中心）
            speed: 移动速度
        """
        if swarm_id not in self.swarms:
            return False
        
        config = self.swarms[swarm_id]
        status = self.swarm_status[swarm_id]
        formation = self.swarm_formations.get(swarm_id, [])
        
        if not status.formation_complete:
            logger.warning(f"Swarm {swarm_id} formation not complete")
            return False
        
        status.state = SwarmState.FLYING
        
        # 移动所有设备到新位置
        tasks = []
        for slot in formation:
            if not slot.device_id:
                continue
            
            target_lat = target.latitude + slot.offset_north / 111000.0
            target_lon = target.longitude + slot.offset_east / \
                        (111000.0 * math.cos(math.radians(target.latitude)))
            target_alt = target.altitude + slot.offset_altitude
            
            task = self.device_manager.send_command(
                slot.device_id,
                "goto",
                {
                    'latitude': target_lat,
                    'longitude': target_lon,
                    'altitude': target_alt
                }
            )
            tasks.append(task)
        
        # 并行发送命令
        await asyncio.gather(*tasks)
        
        logger.info(f"Swarm {swarm_id} moving to new position")
        
        return True
    
    async def change_formation(self, swarm_id: str,
                              new_formation: FormationType) -> bool:
        """改变编队队形"""
        if swarm_id not in self.swarms:
            return False
        
        config = self.swarms[swarm_id]
        config.formation_type = new_formation
        
        # 重新生成编队
        await self._regenerate_formation(swarm_id)
        
        # 重新编队
        # 获取当前中心位置（领机位置）
        status = self.swarm_status[swarm_id]
        if status.leader_id:
            leader_device = self.device_manager.get_device(status.leader_id)
            if leader_device and leader_device.connector:
                center = Position(
                    leader_device.connector.telemetry.latitude,
                    leader_device.connector.telemetry.longitude,
                    leader_device.connector.telemetry.altitude
                )
                
                return await self.form_formation(swarm_id, center)
        
        logger.info(f"Swarm {swarm_id} formation changed to {new_formation.value}")
        
        return True
    
    # 任务执行
    async def execute_mission(self, swarm_id: str,
                             mission: Mission,
                             allocation_strategy: str = "nearest") -> bool:
        """执行集群任务"""
        if swarm_id not in self.swarms:
            return False
        
        config = self.swarms[swarm_id]
        status = self.swarm_status[swarm_id]
        
        # 获取集群设备
        device_ids = list(self.swarm_devices.get(swarm_id, []))
        devices = [self.device_manager.get_device(did) for did in device_ids]
        devices = [d for d in devices if d is not None]
        
        # 分配任务
        allocation = self.task_allocator.allocate_mission(
            devices,
            mission,
            allocation_strategy
        )
        
        status.state = SwarmState.EXECUTING_MISSION
        
        # 发送任务给每个设备
        for device_id, waypoints in allocation.items():
            # 创建子任务
            sub_mission_id = f"{mission.mission_id}_{device_id}"
            sub_mission = self.device_manager.mission_planner.create_mission(
                sub_mission_id,
                f"Sub-task for {device_id}",
                mission.mission_type
            )
            
            for wp in waypoints:
                sub_mission.add_waypoint(wp)
            
            # TODO: 上传任务到设备并启动
        
        logger.info(f"Swarm {swarm_id} executing mission {mission.mission_id}")
        
        return True
    
    # 紧急控制
    async def emergency_stop(self, swarm_id: str) -> bool:
        """紧急停止"""
        if swarm_id not in self.swarms:
            return False
        
        status = self.swarm_status[swarm_id]
        status.state = SwarmState.EMERGENCY
        
        # 悬停所有设备
        for device_id in self.swarm_devices.get(swarm_id, []):
            await self.device_manager.send_command(device_id, "set_mode", {'mode': 'LOITER'})
        
        logger.warning(f"Swarm {swarm_id} emergency stop")
        
        return True
    
    async def return_to_home(self, swarm_id: str) -> bool:
        """返航"""
        if swarm_id not in self.swarms:
            return False
        
        status = self.swarm_status[swarm_id]
        status.state = SwarmState.RETURNING
        
        # 所有设备返航
        for device_id in self.swarm_devices.get(swarm_id, []):
            await self.device_manager.send_command(device_id, "set_mode", {'mode': 'RTL'})
        
        logger.info(f"Swarm {swarm_id} returning to home")
        
        return True
    
    async def land_all(self, swarm_id: str) -> bool:
        """降落所有设备"""
        if swarm_id not in self.swarms:
            return False
        
        for device_id in self.swarm_devices.get(swarm_id, []):
            await self.device_manager.send_command(device_id, "land")
        
        logger.info(f"Swarm {swarm_id} landing all devices")
        
        return True
    
    # 监控循环
    async def _monitor_loop(self):
        """监控循环"""
        while self._running:
            try:
                for swarm_id, config in self.swarms.items():
                    status = self.swarm_status[swarm_id]
                    device_ids = self.swarm_devices.get(swarm_id, set())
                    
                    # 统计活跃设备
                    active_count = 0
                    for device_id in device_ids:
                        device = self.device_manager.get_device(device_id)
                        if device and device.status in [DeviceStatus.ONLINE, DeviceStatus.FLYING]:
                            active_count += 1
                    
                    status.active_count = active_count
                    status.last_update = datetime.now()
                    
                    # 更新领机（第一个在线设备）
                    if device_ids and not status.leader_id:
                        for device_id in device_ids:
                            device = self.device_manager.get_device(device_id)
                            if device and device.status == DeviceStatus.FLYING:
                                status.leader_id = device_id
                                break
                
                await asyncio.sleep(1.0)
                
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
                await asyncio.sleep(1.0)
    
    async def _collision_check_loop(self):
        """碰撞检查循环"""
        while self._running:
            try:
                for swarm_id, config in self.swarms.items():
                    if not config.collision_avoidance:
                        continue
                    
                    device_ids = self.swarm_devices.get(swarm_id, set())
                    
                    # 收集遥测数据
                    telemetry_data = {}
                    for device_id in device_ids:
                        device = self.device_manager.get_device(device_id)
                        if device and device.connector:
                            telemetry_data[device_id] = device.connector.telemetry
                    
                    # 检查碰撞
                    collisions = self.collision_avoidance.check_collisions(telemetry_data)
                    
                    if collisions:
                        logger.warning(f"Swarm {swarm_id} collision warnings: {collisions}")
                        
                        # TODO: 执行避碰机动
                
                await asyncio.sleep(0.5)  # 0.5秒检查一次
                
            except Exception as e:
                logger.error(f"Error in collision check loop: {e}")
                await asyncio.sleep(1.0)
    
    # 状态查询
    def get_swarm_status(self, swarm_id: str) -> Optional[SwarmStatus]:
        """获取集群状态"""
        return self.swarm_status.get(swarm_id)
    
    def get_all_swarms(self) -> List[Dict]:
        """获取所有集群信息"""
        result = []
        
        for swarm_id, config in self.swarms.items():
            status = self.swarm_status[swarm_id]
            device_ids = self.swarm_devices.get(swarm_id, set())
            
            result.append({
                'swarm_id': swarm_id,
                'name': config.name,
                'formation_type': config.formation_type.value,
                'state': status.state.value,
                'device_count': len(device_ids),
                'active_count': status.active_count,
                'formation_complete': status.formation_complete,
                'leader_id': status.leader_id
            })
        
        return result


# 测试代码
if __name__ == "__main__":
    import asyncio
    
    async def test_swarm_controller():
        """测试集群控制器"""
        # 创建设备管理器和集群控制器
        device_manager = DeviceManager()
        swarm_controller = SwarmController(device_manager)
        
        await device_manager.start()
        await swarm_controller.start()
        
        # 创建集群
        config = SwarmConfig(
            swarm_id="swarm_001",
            name="Alpha Team",
            formation_type=FormationType.V_SHAPE,
            spacing=10.0
        )
        
        await swarm_controller.create_swarm(config)
        
        # 添加设备
        await swarm_controller.add_device_to_swarm("drone_001", "swarm_001")
        await swarm_controller.add_device_to_swarm("drone_002", "swarm_001")
        await swarm_controller.add_device_to_swarm("drone_003", "swarm_001")
        
        # 查看状态
        status = swarm_controller.get_swarm_status("swarm_001")
        print(f"Swarm status: {status.state.value}")
        
        # 运行10秒
        await asyncio.sleep(10)
        
        await swarm_controller.stop()
        await device_manager.stop()
    
    asyncio.run(test_swarm_controller())
