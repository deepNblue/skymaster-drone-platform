"""
任务规划器 - 航点规划、航线生成、任务管理
支持可视化规划、自动避障、任务模板
"""

import asyncio
import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json
import math
from collections import defaultdict

logger = logging.getLogger(__name__)


class MissionType(Enum):
    """任务类型"""
    SURVEY = "survey"  # 测绘
    INSPECTION = "inspection"  # 巡检
    DELIVERY = "delivery"  # 投递
    PATROL = "patrol"  # 巡逻
    PHOTOGRAMMETRY = "photogrammetry"  # 摄影测量
    CUSTOM = "custom"  # 自定义


class WaypointType(Enum):
    """航点类型"""
    WAYPOINT = "waypoint"  # 普通航点
    TAKEOFF = "takeoff"  # 起飞点
    LAND = "land"  # 降落点
    LOITER = "loiter"  # 悬停点
    POI = "poi"  # 兴趣点
    ROI = "roi"  # 区域关注点


@dataclass
class Position:
    """位置"""
    latitude: float
    longitude: float
    altitude: float
    
    def to_dict(self) -> Dict:
        return {
            'latitude': self.latitude,
            'longitude': self.longitude,
            'altitude': self.altitude
        }
    
    def distance_to(self, other: 'Position') -> float:
        """计算到另一个位置的距离（米）"""
        # 使用Haversine公式
        R = 6371000  # 地球半径（米）
        
        lat1_rad = math.radians(self.latitude)
        lat2_rad = math.radians(other.latitude)
        delta_lat = math.radians(other.latitude - self.latitude)
        delta_lon = math.radians(other.longitude - self.longitude)
        
        a = math.sin(delta_lat/2) ** 2 + \
            math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon/2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        
        horizontal_dist = R * c
        vertical_dist = abs(self.altitude - other.altitude)
        
        return math.sqrt(horizontal_dist**2 + vertical_dist**2)
    
    def bearing_to(self, other: 'Position') -> float:
        """计算到另一个位置的方位角（度）"""
        lat1_rad = math.radians(self.latitude)
        lat2_rad = math.radians(other.latitude)
        delta_lon = math.radians(other.longitude - self.longitude)
        
        y = math.sin(delta_lon) * math.cos(lat2_rad)
        x = math.cos(lat1_rad) * math.sin(lat2_rad) - \
            math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(delta_lon)
        
        bearing = math.atan2(y, x)
        return math.degrees(bearing) % 360


@dataclass
class Waypoint:
    """航点"""
    waypoint_id: str
    position: Position
    waypoint_type: WaypointType = WaypointType.WAYPOINT
    
    # 飞行参数
    speed: float = 5.0  # 飞行速度（m/s）
    hold_time: float = 0.0  # 悬停时间（秒）
    
    # 相机参数
    camera_action: str = "none"  # 相机动作：none, take_photo, start_video, stop_video
    camera_angle: float = -90.0  # 相机角度（度，-90为垂直向下）
    
    # 高级参数
    heading: Optional[float] = None  # 航向角（度），None为自动
    acceptance_radius: float = 2.0  # 接受半径（米）
    pass_radius: float = 0.0  # 通过半径（米），0为精确到达
    
    # 元数据
    name: str = ""
    description: str = ""
    
    def to_dict(self) -> Dict:
        return {
            'waypoint_id': self.waypoint_id,
            'position': self.position.to_dict(),
            'waypoint_type': self.waypoint_type.value,
            'speed': self.speed,
            'hold_time': self.hold_time,
            'camera_action': self.camera_action,
            'camera_angle': self.camera_angle,
            'heading': self.heading,
            'acceptance_radius': self.acceptance_radius,
            'pass_radius': self.pass_radius,
            'name': self.name,
            'description': self.description
        }


@dataclass
class Mission:
    """任务"""
    mission_id: str
    name: str
    mission_type: MissionType
    waypoints: List[Waypoint] = field(default_factory=list)
    
    # 任务参数
    auto_takeoff: bool = True
    takeoff_altitude: float = 10.0  # 起飞高度（米）
    auto_land: bool = True
    return_to_home: bool = True  # 任务结束后返航
    
    # 全局参数
    default_speed: float = 5.0  # 默认飞行速度（m/s）
    default_altitude: float = 50.0  # 默认飞行高度（米）
    max_speed: float = 15.0  # 最大速度（m/s）
    
    # 安全参数
    min_altitude: float = 10.0  # 最低高度（米）
    max_altitude: float = 120.0  # 最高高度（米）
    max_distance: float = 1000.0  # 最大距离（米）
    
    # 元数据
    description: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict:
        return {
            'mission_id': self.mission_id,
            'name': self.name,
            'mission_type': self.mission_type.value,
            'waypoints': [wp.to_dict() for wp in self.waypoints],
            'waypoint_count': len(self.waypoints),
            'parameters': {
                'auto_takeoff': self.auto_takeoff,
                'takeoff_altitude': self.takeoff_altitude,
                'auto_land': self.auto_land,
                'return_to_home': self.return_to_home,
                'default_speed': self.default_speed,
                'default_altitude': self.default_altitude,
                'max_speed': self.max_speed
            },
            'safety': {
                'min_altitude': self.min_altitude,
                'max_altitude': self.max_altitude,
                'max_distance': self.max_distance
            },
            'description': self.description,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }
    
    def add_waypoint(self, waypoint: Waypoint):
        """添加航点"""
        self.waypoints.append(waypoint)
        self.updated_at = datetime.now()
    
    def remove_waypoint(self, waypoint_id: str) -> bool:
        """删除航点"""
        for i, wp in enumerate(self.waypoints):
            if wp.waypoint_id == waypoint_id:
                self.waypoints.pop(i)
                self.updated_at = datetime.now()
                return True
        return False
    
    def reorder_waypoints(self, waypoint_ids: List[str]):
        """重新排序航点"""
        new_waypoints = []
        for wp_id in waypoint_ids:
            for wp in self.waypoints:
                if wp.waypoint_id == wp_id:
                    new_waypoints.append(wp)
                    break
        self.waypoints = new_waypoints
        self.updated_at = datetime.now()
    
    def calculate_total_distance(self) -> float:
        """计算总距离"""
        if len(self.waypoints) < 2:
            return 0.0
        
        total_distance = 0.0
        for i in range(len(self.waypoints) - 1):
            total_distance += self.waypoints[i].position.distance_to(
                self.waypoints[i+1].position
            )
        
        return total_distance
    
    def estimate_flight_time(self) -> float:
        """估算飞行时间（秒）"""
        if len(self.waypoints) < 2:
            return 0.0
        
        total_time = 0.0
        
        # 起飞时间
        if self.auto_takeoff:
            total_time += self.takeoff_altitude / 2.0  # 假设2m/s爬升速度
        
        # 航线时间
        for i in range(len(self.waypoints) - 1):
            distance = self.waypoints[i].position.distance_to(
                self.waypoints[i+1].position
            )
            speed = self.waypoints[i].speed or self.default_speed
            total_time += distance / speed
            total_time += self.waypoints[i].hold_time
        
        # 降落时间
        if self.auto_land:
            total_time += self.default_altitude / 2.0  # 假设2m/s下降速度
        
        # 返航时间
        if self.return_to_home and len(self.waypoints) > 0:
            last_wp = self.waypoints[-1]
            home_wp = self.waypoints[0]
            return_distance = last_wp.position.distance_to(home_wp.position)
            total_time += return_distance / self.default_speed
        
        return total_time


class MissionPlanner:
    """任务规划器"""
    
    def __init__(self):
        self.missions: Dict[str, Mission] = {}
        self.templates: Dict[str, Mission] = {}
        self._load_templates()
    
    def create_mission(self, mission_id: str, name: str, 
                      mission_type: MissionType,
                      description: str = "") -> Mission:
        """创建任务"""
        mission = Mission(
            mission_id=mission_id,
            name=name,
            mission_type=mission_type,
            description=description
        )
        
        self.missions[mission_id] = mission
        logger.info(f"Mission created: {mission_id}")
        
        return mission
    
    def get_mission(self, mission_id: str) -> Optional[Mission]:
        """获取任务"""
        return self.missions.get(mission_id)
    
    def delete_mission(self, mission_id: str) -> bool:
        """删除任务"""
        if mission_id in self.missions:
            del self.missions[mission_id]
            logger.info(f"Mission deleted: {mission_id}")
            return True
        return False
    
    def get_all_missions(self) -> List[Mission]:
        """获取所有任务"""
        return list(self.missions.values())
    
    # 航点管理
    def add_waypoint(self, mission_id: str, waypoint: Waypoint) -> bool:
        """添加航点"""
        mission = self.get_mission(mission_id)
        if not mission:
            return False
        
        mission.add_waypoint(waypoint)
        logger.info(f"Waypoint {waypoint.waypoint_id} added to mission {mission_id}")
        return True
    
    def remove_waypoint(self, mission_id: str, waypoint_id: str) -> bool:
        """删除航点"""
        mission = self.get_mission(mission_id)
        if not mission:
            return False
        
        return mission.remove_waypoint(waypoint_id)
    
    def update_waypoint(self, mission_id: str, waypoint: Waypoint) -> bool:
        """更新航点"""
        mission = self.get_mission(mission_id)
        if not mission:
            return False
        
        for i, wp in enumerate(mission.waypoints):
            if wp.waypoint_id == waypoint.waypoint_id:
                mission.waypoints[i] = waypoint
                mission.updated_at = datetime.now()
                logger.info(f"Waypoint {waypoint.waypoint_id} updated")
                return True
        
        return False
    
    # 航线生成
    def generate_survey_grid(self, center: Position, 
                            width: float, height: float,
                            spacing: float, altitude: float,
                            angle: float = 0.0) -> List[Position]:
        """生成测绘网格航线
        
        Args:
            center: 中心位置
            width: 区域宽度（米）
            height: 区域高度（米）
            spacing: 航线间距（米）
            altitude: 飞行高度（米）
            angle: 航线角度（度）
        
        Returns:
            航点位置列表
        """
        waypoints = []
        
        # 计算需要的航线数量
        num_lines = int(height / spacing) + 1
        
        # 生成网格点
        for i in range(num_lines):
            y_offset = (i - num_lines/2) * spacing
            
            # 奇偶行反向（之字形）
            if i % 2 == 0:
                x_range = range(-int(width/2), int(width/2) + 1, int(width))
            else:
                x_range = range(int(width/2), -int(width/2) - 1, -int(width))
            
            for x_offset in x_range:
                # 计算实际位置（简化计算，未考虑地球曲率）
                lat_offset = y_offset / 111000.0  # 1度纬度约111km
                lon_offset = x_offset / (111000.0 * math.cos(math.radians(center.latitude)))
                
                # 应用旋转角度
                rotated_x = x_offset * math.cos(math.radians(angle)) - \
                           y_offset * math.sin(math.radians(angle))
                rotated_y = x_offset * math.sin(math.radians(angle)) + \
                           y_offset * math.cos(math.radians(angle))
                
                lat_offset = rotated_y / 111000.0
                lon_offset = rotated_x / (111000.0 * math.cos(math.radians(center.latitude)))
                
                position = Position(
                    latitude=center.latitude + lat_offset,
                    longitude=center.longitude + lon_offset,
                    altitude=altitude
                )
                
                waypoints.append(position)
        
        return waypoints
    
    def generate_circle_path(self, center: Position, 
                            radius: float, altitude: float,
                            num_points: int = 8) -> List[Position]:
        """生成圆形航线
        
        Args:
            center: 圆心位置
            radius: 半径（米）
            altitude: 飞行高度（米）
            num_points: 航点数量
        
        Returns:
            航点位置列表
        """
        waypoints = []
        
        for i in range(num_points):
            angle = 2 * math.pi * i / num_points
            
            # 计算位置偏移
            x_offset = radius * math.cos(angle)
            y_offset = radius * math.sin(angle)
            
            lat_offset = y_offset / 111000.0
            lon_offset = x_offset / (111000.0 * math.cos(math.radians(center.latitude)))
            
            position = Position(
                latitude=center.latitude + lat_offset,
                longitude=center.longitude + lon_offset,
                altitude=altitude
            )
            
            waypoints.append(position)
        
        return waypoints
    
    def generate_patrol_path(self, points: List[Position], 
                            patrol_type: str = "circular") -> List[Position]:
        """生成巡逻航线
        
        Args:
            points: 巡逻点列表
            patrol_type: 巡逻类型（circular/back_forth）
        
        Returns:
            航点位置列表
        """
        if patrol_type == "circular":
            # 环形巡逻
            return points + [points[0]]  # 返回起点
        elif patrol_type == "back_forth":
            # 往返巡逻
            return points + points[-2::-1]  # 反向返回
        else:
            return points
    
    # 自动避障（简化版本）
    def add_obstacle_avoidance(self, mission_id: str,
                               obstacles: List[Tuple[Position, float]]) -> bool:
        """添加障碍物规避航点
        
        Args:
            mission_id: 任务ID
            obstacles: 障碍物列表 [(位置, 半径), ...]
        
        Returns:
            是否成功
        """
        mission = self.get_mission(mission_id)
        if not mission or len(mission.waypoints) < 2:
            return False
        
        new_waypoints = [mission.waypoints[0]]
        
        for i in range(len(mission.waypoints) - 1):
            wp1 = mission.waypoints[i]
            wp2 = mission.waypoints[i + 1]
            
            # 检查航线是否与障碍物相交
            for obstacle_pos, obstacle_radius in obstacles:
                # 简化：检查航点是否在障碍物内
                if wp1.position.distance_to(obstacle_pos) < obstacle_radius + 10 or \
                   wp2.position.distance_to(obstacle_pos) < obstacle_radius + 10:
                    # 添加规避航点
                    # 计算垂直方向
                    bearing = wp1.position.bearing_to(wp2.position)
                    avoid_bearing = (bearing + 90) % 360
                    
                    # 添加规避点
                    avoid_dist = obstacle_radius + 20
                    lat_offset = avoid_dist * math.cos(math.radians(avoid_bearing)) / 111000.0
                    lon_offset = avoid_dist * math.sin(math.radians(avoid_bearing)) / \
                                (111000.0 * math.cos(math.radians(obstacle_pos.latitude)))
                    
                    avoid_wp = Waypoint(
                        waypoint_id=f"avoid_{i}",
                        position=Position(
                            latitude=obstacle_pos.latitude + lat_offset,
                            longitude=obstacle_pos.longitude + lon_offset,
                            altitude=obstacle_pos.altitude + 10
                        ),
                        waypoint_type=WaypointType.WAYPOINT
                    )
                    
                    new_waypoints.append(avoid_wp)
                    logger.info(f"Added avoidance waypoint for obstacle at mission {mission_id}")
            
            new_waypoints.append(wp2)
        
        mission.waypoints = new_waypoints
        mission.updated_at = datetime.now()
        
        return True
    
    # 任务模板
    def _load_templates(self):
        """加载任务模板"""
        # 测绘模板
        survey_template = Mission(
            mission_id="template_survey",
            name="Survey Template",
            mission_type=MissionType.SURVEY,
            description="Grid survey mission template",
            default_speed=5.0,
            default_altitude=50.0
        )
        
        # 巡检模板
        inspection_template = Mission(
            mission_id="template_inspection",
            name="Inspection Template",
            mission_type=MissionType.INSPECTION,
            description="Point inspection mission template",
            default_speed=3.0,
            default_altitude=30.0
        )
        
        # 巡逻模板
        patrol_template = Mission(
            mission_id="template_patrol",
            name="Patrol Template",
            mission_type=MissionType.PATROL,
            description="Circular patrol mission template",
            default_speed=8.0,
            default_altitude=60.0
        )
        
        self.templates = {
            "survey": survey_template,
            "inspection": inspection_template,
            "patrol": patrol_template
        }
    
    def get_template(self, template_name: str) -> Optional[Mission]:
        """获取模板"""
        return self.templates.get(template_name)
    
    def create_from_template(self, template_name: str, mission_id: str, 
                            name: str) -> Optional[Mission]:
        """从模板创建任务"""
        template = self.get_template(template_name)
        if not template:
            return None
        
        # 复制模板
        import copy
        mission = copy.deepcopy(template)
        mission.mission_id = mission_id
        mission.name = name
        mission.created_at = datetime.now()
        mission.updated_at = datetime.now()
        
        self.missions[mission_id] = mission
        logger.info(f"Mission {mission_id} created from template {template_name}")
        
        return mission
    
    # 任务验证
    def validate_mission(self, mission_id: str) -> Tuple[bool, List[str]]:
        """验证任务
        
        Returns:
            (是否有效, 错误列表)
        """
        mission = self.get_mission(mission_id)
        if not mission:
            return False, ["Mission not found"]
        
        errors = []
        
        # 检查航点数量
        if len(mission.waypoints) == 0:
            errors.append("Mission has no waypoints")
        
        # 检查航点高度
        for wp in mission.waypoints:
            if wp.position.altitude < mission.min_altitude:
                errors.append(f"Waypoint {wp.waypoint_id} altitude below minimum")
            elif wp.position.altitude > mission.max_altitude:
                errors.append(f"Waypoint {wp.waypoint_id} altitude above maximum")
        
        # 检查总距离
        total_distance = mission.calculate_total_distance()
        if total_distance > mission.max_distance:
            errors.append(f"Total distance {total_distance:.1f}m exceeds maximum {mission.max_distance}m")
        
        # 检查航点有效性
        for wp in mission.waypoints:
            if not (-90 <= wp.position.latitude <= 90):
                errors.append(f"Invalid latitude in waypoint {wp.waypoint_id}")
            if not (-180 <= wp.position.longitude <= 180):
                errors.append(f"Invalid longitude in waypoint {wp.waypoint_id}")
        
        return len(errors) == 0, errors
    
    # 导出/导入
    def export_mission(self, mission_id: str) -> Optional[Dict]:
        """导出任务为JSON"""
        mission = self.get_mission(mission_id)
        if not mission:
            return None
        
        return mission.to_dict()
    
    def import_mission(self, mission_data: Dict) -> Optional[Mission]:
        """从JSON导入任务"""
        try:
            mission = Mission(
                mission_id=mission_data['mission_id'],
                name=mission_data['name'],
                mission_type=MissionType(mission_data['mission_type']),
                description=mission_data.get('description', '')
            )
            
            # 导入航点
            for wp_data in mission_data.get('waypoints', []):
                waypoint = Waypoint(
                    waypoint_id=wp_data['waypoint_id'],
                    position=Position(
                        latitude=wp_data['position']['latitude'],
                        longitude=wp_data['position']['longitude'],
                        altitude=wp_data['position']['altitude']
                    ),
                    waypoint_type=WaypointType(wp_data.get('waypoint_type', 'waypoint')),
                    speed=wp_data.get('speed', 5.0),
                    hold_time=wp_data.get('hold_time', 0.0),
                    camera_action=wp_data.get('camera_action', 'none'),
                    camera_angle=wp_data.get('camera_angle', -90.0)
                )
                mission.waypoints.append(waypoint)
            
            # 导入参数
            params = mission_data.get('parameters', {})
            mission.auto_takeoff = params.get('auto_takeoff', True)
            mission.takeoff_altitude = params.get('takeoff_altitude', 10.0)
            mission.auto_land = params.get('auto_land', True)
            mission.return_to_home = params.get('return_to_home', True)
            mission.default_speed = params.get('default_speed', 5.0)
            mission.default_altitude = params.get('default_altitude', 50.0)
            
            self.missions[mission.mission_id] = mission
            logger.info(f"Mission imported: {mission.mission_id}")
            
            return mission
            
        except Exception as e:
            logger.error(f"Error importing mission: {e}")
            return None


# 测试代码
if __name__ == "__main__":
    # 创建任务规划器
    planner = MissionPlanner()
    
    # 创建任务
    mission = planner.create_mission(
        "mission_001",
        "Test Survey",
        MissionType.SURVEY,
        "Test survey mission"
    )
    
    # 添加航点
    wp1 = Waypoint(
        waypoint_id="wp_001",
        position=Position(39.9042, 116.4074, 50.0),
        waypoint_type=WaypointType.TAKEOFF,
        name="Home"
    )
    
    wp2 = Waypoint(
        waypoint_id="wp_002",
        position=Position(39.9142, 116.4174, 50.0),
        name="Point A"
    )
    
    wp3 = Waypoint(
        waypoint_id="wp_003",
        position=Position(39.9242, 116.4274, 50.0),
        waypoint_type=WaypointType.LAND,
        name="Land"
    )
    
    planner.add_waypoint("mission_001", wp1)
    planner.add_waypoint("mission_001", wp2)
    planner.add_waypoint("mission_001", wp3)
    
    # 计算距离和时间
    print(f"Total distance: {mission.calculate_total_distance():.2f}m")
    print(f"Estimated time: {mission.estimate_flight_time():.1f}s")
    
    # 验证任务
    valid, errors = planner.validate_mission("mission_001")
    print(f"Mission valid: {valid}")
    if errors:
        print("Errors:", errors)
    
    # 导出任务
    mission_json = planner.export_mission("mission_001")
    print("Mission exported:", json.dumps(mission_json, indent=2))
