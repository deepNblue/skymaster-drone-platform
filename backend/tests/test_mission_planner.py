"""
任务规划器单元测试
测试任务创建、航点验证、任务上传、任务执行
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock, patch
from datetime import datetime
import math
import json

import sys
sys.path.insert(0, '/home/dudu/.nanobot/workspace/skymaster-drone-platform/backend')

from core.missions.planner import (
    MissionPlanner,
    Mission,
    Waypoint,
    Position,
    MissionType,
    WaypointType
)


# Fixtures
@pytest.fixture
def mission_planner():
    """任务规划器实例"""
    return MissionPlanner()


@pytest.fixture
def sample_position():
    """示例位置"""
    return Position(
        latitude=39.9042,
        longitude=116.4074,
        altitude=50.0
    )


@pytest.fixture
def sample_waypoint(sample_position):
    """示例航点"""
    return Waypoint(
        waypoint_id="wp_001",
        position=sample_position,
        waypoint_type=WaypointType.WAYPOINT,
        name="Test Waypoint"
    )


@pytest.fixture
def sample_mission(mission_planner):
    """示例任务"""
    mission = mission_planner.create_mission(
        "mission_001",
        "Test Mission",
        MissionType.SURVEY,
        "Test survey mission"
    )
    
    # 添加航点
    wp1 = Waypoint(
        waypoint_id="wp_001",
        position=Position(39.9042, 116.4074, 50.0),
        waypoint_type=WaypointType.TAKEOFF
    )
    wp2 = Waypoint(
        waypoint_id="wp_002",
        position=Position(39.9142, 116.4174, 50.0)
    )
    wp3 = Waypoint(
        waypoint_id="wp_003",
        position=Position(39.9242, 116.4274, 50.0),
        waypoint_type=WaypointType.LAND
    )
    
    mission.add_waypoint(wp1)
    mission.add_waypoint(wp2)
    mission.add_waypoint(wp3)
    
    return mission


class TestPosition:
    """测试位置类"""
    
    def test_position_creation(self):
        """测试位置创建"""
        pos = Position(39.9042, 116.4074, 100.0)
        
        assert pos.latitude == 39.9042
        assert pos.longitude == 116.4074
        assert pos.altitude == 100.0
    
    def test_position_to_dict(self, sample_position):
        """测试位置转换为字典"""
        data = sample_position.to_dict()
        
        assert data['latitude'] == 39.9042
        assert data['longitude'] == 116.4074
        assert data['altitude'] == 50.0
    
    def test_distance_to_same_position(self, sample_position):
        """测试相同位置的距离"""
        distance = sample_position.distance_to(sample_position)
        
        assert distance == 0.0
    
    def test_distance_to_different_position(self):
        """测试不同位置的距离"""
        pos1 = Position(39.9042, 116.4074, 0)
        pos2 = Position(39.9142, 116.4174, 0)
        
        distance = pos1.distance_to(pos2)
        
        # 大约1.5公里
        assert 1000 < distance < 2000
    
    def test_distance_with_altitude(self):
        """测试包含高度差的距离"""
        pos1 = Position(39.9042, 116.4074, 0)
        pos2 = Position(39.9042, 116.4074, 100)
        
        distance = pos1.distance_to(pos2)
        
        assert abs(distance - 100) < 0.1
    
    def test_bearing_to(self):
        """测试方位角计算"""
        pos1 = Position(39.9042, 116.4074, 0)
        pos2 = Position(40.0042, 116.4074, 0)  # 正北
        
        bearing = pos1.bearing_to(pos2)
        
        assert 0 <= bearing < 360
        # 正北方向应接近0度
        assert bearing < 10 or bearing > 350


class TestWaypoint:
    """测试航点类"""
    
    def test_waypoint_creation(self, sample_position):
        """测试航点创建"""
        wp = Waypoint(
            waypoint_id="wp_test",
            position=sample_position,
            name="Test WP"
        )
        
        assert wp.waypoint_id == "wp_test"
        assert wp.waypoint_type == WaypointType.WAYPOINT
        assert wp.speed == 5.0
    
    def test_waypoint_types(self, sample_position):
        """测试航点类型"""
        takeoff = Waypoint(
            waypoint_id="wp_takeoff",
            position=sample_position,
            waypoint_type=WaypointType.TAKEOFF
        )
        
        land = Waypoint(
            waypoint_id="wp_land",
            position=sample_position,
            waypoint_type=WaypointType.LAND
        )
        
        loiter = Waypoint(
            waypoint_id="wp_loiter",
            position=sample_position,
            waypoint_type=WaypointType.LOITER
        )
        
        assert takeoff.waypoint_type == WaypointType.TAKEOFF
        assert land.waypoint_type == WaypointType.LAND
        assert loiter.waypoint_type == WaypointType.LOITER
    
    def test_waypoint_camera_action(self, sample_position):
        """测试航点相机动作"""
        wp = Waypoint(
            waypoint_id="wp_photo",
            position=sample_position,
            camera_action="take_photo",
            camera_angle=-45.0
        )
        
        assert wp.camera_action == "take_photo"
        assert wp.camera_angle == -45.0
    
    def test_waypoint_to_dict(self, sample_waypoint):
        """测试航点转换为字典"""
        data = sample_waypoint.to_dict()
        
        assert data['waypoint_id'] == "wp_001"
        assert 'position' in data
        assert data['position']['latitude'] == 39.9042


class TestMission:
    """测试任务类"""
    
    def test_mission_creation(self):
        """测试任务创建"""
        mission = Mission(
            mission_id="mission_test",
            name="Test Mission",
            mission_type=MissionType.SURVEY
        )
        
        assert mission.mission_id == "mission_test"
        assert mission.mission_type == MissionType.SURVEY
        assert len(mission.waypoints) == 0
    
    def test_mission_add_waypoint(self):
        """测试添加航点"""
        mission = Mission(
            mission_id="mission_test",
            name="Test",
            mission_type=MissionType.SURVEY
        )
        
        wp = Waypoint(
            waypoint_id="wp_001",
            position=Position(39.9042, 116.4074, 50.0)
        )
        
        mission.add_waypoint(wp)
        
        assert len(mission.waypoints) == 1
        assert mission.waypoints[0].waypoint_id == "wp_001"
    
    def test_mission_remove_waypoint(self):
        """测试删除航点"""
        mission = Mission(
            mission_id="mission_test",
            name="Test",
            mission_type=MissionType.SURVEY
        )
        
        wp1 = Waypoint(
            waypoint_id="wp_001",
            position=Position(39.9042, 116.4074, 50.0)
        )
        wp2 = Waypoint(
            waypoint_id="wp_002",
            position=Position(39.9142, 116.4174, 50.0)
        )
        
        mission.add_waypoint(wp1)
        mission.add_waypoint(wp2)
        
        result = mission.remove_waypoint("wp_001")
        
        assert result == True
        assert len(mission.waypoints) == 1
        assert mission.waypoints[0].waypoint_id == "wp_002"
    
    def test_mission_remove_nonexistent_waypoint(self):
        """测试删除不存在的航点"""
        mission = Mission(
            mission_id="mission_test",
            name="Test",
            mission_type=MissionType.SURVEY
        )
        
        result = mission.remove_waypoint("nonexistent")
        
        assert result == False
    
    def test_mission_reorder_waypoints(self):
        """测试重排序航点"""
        mission = Mission(
            mission_id="mission_test",
            name="Test",
            mission_type=MissionType.SURVEY
        )
        
        for i in range(5):
            wp = Waypoint(
                waypoint_id=f"wp_{i:03d}",
                position=Position(39.9042 + i*0.01, 116.4074, 50.0)
            )
            mission.add_waypoint(wp)
        
        # 反向排序
        new_order = [f"wp_{i:03d}" for i in reversed(range(5))]
        mission.reorder_waypoints(new_order)
        
        assert mission.waypoints[0].waypoint_id == "wp_004"
        assert mission.waypoints[-1].waypoint_id == "wp_000"
    
    def test_mission_calculate_total_distance(self, sample_mission):
        """测试计算总距离"""
        distance = sample_mission.calculate_total_distance()
        
        assert distance > 0
    
    def test_mission_estimate_flight_time(self, sample_mission):
        """测试估算飞行时间"""
        time = sample_mission.estimate_flight_time()
        
        assert time > 0
    
    def test_mission_to_dict(self, sample_mission):
        """测试任务转换为字典"""
        data = sample_mission.to_dict()
        
        assert data['mission_id'] == "mission_001"
        assert data['name'] == "Test Mission"
        assert data['waypoint_count'] == 3
        assert 'parameters' in data


class TestMissionPlanner:
    """测试任务规划器"""
    
    def test_planner_creation(self, mission_planner):
        """测试规划器创建"""
        assert mission_planner is not None
        assert len(mission_planner.missions) == 0
    
    def test_create_mission(self, mission_planner):
        """测试创建任务"""
        mission = mission_planner.create_mission(
            "mission_001",
            "Test Mission",
            MissionType.SURVEY,
            "Test description"
        )
        
        assert mission.mission_id == "mission_001"
        assert mission.name == "Test Mission"
        assert mission.mission_type == MissionType.SURVEY
        assert "mission_001" in mission_planner.missions
    
    def test_get_mission(self, mission_planner):
        """测试获取任务"""
        mission_planner.create_mission(
            "mission_001",
            "Test",
            MissionType.SURVEY
        )
        
        mission = mission_planner.get_mission("mission_001")
        
        assert mission is not None
        assert mission.mission_id == "mission_001"
    
    def test_get_nonexistent_mission(self, mission_planner):
        """测试获取不存在的任务"""
        mission = mission_planner.get_mission("nonexistent")
        
        assert mission is None
    
    def test_delete_mission(self, mission_planner):
        """测试删除任务"""
        mission_planner.create_mission(
            "mission_001",
            "Test",
            MissionType.SURVEY
        )
        
        result = mission_planner.delete_mission("mission_001")
        
        assert result == True
        assert "mission_001" not in mission_planner.missions
    
    def test_delete_nonexistent_mission(self, mission_planner):
        """测试删除不存在的任务"""
        result = mission_planner.delete_mission("nonexistent")
        
        assert result == False
    
    def test_get_all_missions(self, mission_planner):
        """测试获取所有任务"""
        mission_planner.create_mission("m1", "Mission 1", MissionType.SURVEY)
        mission_planner.create_mission("m2", "Mission 2", MissionType.INSPECTION)
        mission_planner.create_mission("m3", "Mission 3", MissionType.PATROL)
        
        missions = mission_planner.get_all_missions()
        
        assert len(missions) == 3
    
    def test_add_waypoint_to_mission(self, mission_planner):
        """测试添加航点到任务"""
        mission_planner.create_mission("mission_001", "Test", MissionType.SURVEY)
        
        wp = Waypoint(
            waypoint_id="wp_001",
            position=Position(39.9042, 116.4074, 50.0)
        )
        
        result = mission_planner.add_waypoint("mission_001", wp)
        
        assert result == True
        assert len(mission_planner.get_mission("mission_001").waypoints) == 1
    
    def test_add_waypoint_to_nonexistent_mission(self, mission_planner, sample_waypoint):
        """测试添加航点到不存在的任务"""
        result = mission_planner.add_waypoint("nonexistent", sample_waypoint)
        
        assert result == False
    
    def test_remove_waypoint_from_mission(self, mission_planner):
        """测试从任务删除航点"""
        mission = mission_planner.create_mission("mission_001", "Test", MissionType.SURVEY)
        
        wp = Waypoint(
            waypoint_id="wp_001",
            position=Position(39.9042, 116.4074, 50.0)
        )
        mission.add_waypoint(wp)
        
        result = mission_planner.remove_waypoint("mission_001", "wp_001")
        
        assert result == True
        assert len(mission_planner.get_mission("mission_001").waypoints) == 0
    
    def test_update_waypoint(self, mission_planner):
        """测试更新航点"""
        mission = mission_planner.create_mission("mission_001", "Test", MissionType.SURVEY)
        
        wp = Waypoint(
            waypoint_id="wp_001",
            position=Position(39.9042, 116.4074, 50.0),
            speed=5.0
        )
        mission.add_waypoint(wp)
        
        # 更新航点
        updated_wp = Waypoint(
            waypoint_id="wp_001",
            position=Position(39.9142, 116.4174, 60.0),
            speed=10.0
        )
        
        result = mission_planner.update_waypoint("mission_001", updated_wp)
        
        assert result == True
        assert mission_planner.get_mission("mission_001").waypoints[0].speed == 10.0


class TestMissionValidation:
    """测试任务验证"""
    
    def test_validate_empty_mission(self, mission_planner):
        """测试验证空任务"""
        mission_planner.create_mission("mission_001", "Test", MissionType.SURVEY)
        
        valid, errors = mission_planner.validate_mission("mission_001")
        
        assert valid == False
        assert "Mission has no waypoints" in errors
    
    def test_validate_mission_altitude_too_low(self, mission_planner):
        """测试验证高度过低的任务"""
        mission = mission_planner.create_mission("mission_001", "Test", MissionType.SURVEY)
        mission.min_altitude = 10.0
        
        wp = Waypoint(
            waypoint_id="wp_001",
            position=Position(39.9042, 116.4074, 5.0)  # 低于最低高度
        )
        mission.add_waypoint(wp)
        
        valid, errors = mission_planner.validate_mission("mission_001")
        
        assert valid == False
        assert any("altitude below minimum" in e for e in errors)
    
    def test_validate_mission_altitude_too_high(self, mission_planner):
        """测试验证高度过高的任务"""
        mission = mission_planner.create_mission("mission_001", "Test", MissionType.SURVEY)
        mission.max_altitude = 120.0
        
        wp = Waypoint(
            waypoint_id="wp_001",
            position=Position(39.9042, 116.4074, 150.0)  # 高于最高高度
        )
        mission.add_waypoint(wp)
        
        valid, errors = mission_planner.validate_mission("mission_001")
        
        assert valid == False
        assert any("altitude above maximum" in e for e in errors)
    
    def test_validate_invalid_latitude(self, mission_planner):
        """测试验证无效纬度"""
        mission = mission_planner.create_mission("mission_001", "Test", MissionType.SURVEY)
        
        wp = Waypoint(
            waypoint_id="wp_001",
            position=Position(100.0, 116.4074, 50.0)  # 无效纬度
        )
        mission.add_waypoint(wp)
        
        valid, errors = mission_planner.validate_mission("mission_001")
        
        assert valid == False
        assert any("Invalid latitude" in e for e in errors)
    
    def test_validate_invalid_longitude(self, mission_planner):
        """测试验证无效经度"""
        mission = mission_planner.create_mission("mission_001", "Test", MissionType.SURVEY)
        
        wp = Waypoint(
            waypoint_id="wp_001",
            position=Position(39.9042, 200.0, 50.0)  # 无效经度
        )
        mission.add_waypoint(wp)
        
        valid, errors = mission_planner.validate_mission("mission_001")
        
        assert valid == False
        assert any("Invalid longitude" in e for e in errors)
    
    def test_validate_valid_mission(self, mission_planner):
        """测试验证有效任务"""
        mission = mission_planner.create_mission("mission_001", "Test", MissionType.SURVEY)
        
        wp1 = Waypoint(
            waypoint_id="wp_001",
            position=Position(39.9042, 116.4074, 50.0)
        )
        wp2 = Waypoint(
            waypoint_id="wp_002",
            position=Position(39.9142, 116.4174, 50.0)
        )
        
        mission.add_waypoint(wp1)
        mission.add_waypoint(wp2)
        
        valid, errors = mission_planner.validate_mission("mission_001")
        
        assert valid == True
        assert len(errors) == 0


class TestPathGeneration:
    """测试航线生成"""
    
    def test_generate_survey_grid(self, mission_planner, sample_position):
        """测试生成测绘网格"""
        waypoints = mission_planner.generate_survey_grid(
            center=sample_position,
            width=100,
            height=100,
            spacing=50,
            altitude=50.0,
            angle=0.0
        )
        
        assert len(waypoints) > 0
        assert all(isinstance(wp, Position) for wp in waypoints)
    
    def test_generate_circle_path(self, mission_planner, sample_position):
        """测试生成圆形航线"""
        waypoints = mission_planner.generate_circle_path(
            center=sample_position,
            radius=50,
            altitude=50.0,
            num_points=8
        )
        
        assert len(waypoints) == 8
        assert all(isinstance(wp, Position) for wp in waypoints)
    
    def test_generate_patrol_circular(self, mission_planner):
        """测试生成环形巡逻航线"""
        points = [
            Position(39.9042, 116.4074, 50.0),
            Position(39.9142, 116.4174, 50.0),
            Position(39.9242, 116.4274, 50.0)
        ]
        
        patrol = mission_planner.generate_patrol_path(points, "circular")
        
        assert len(patrol) == 4  # 3个点 + 返回起点
        assert patrol[-1] == points[0]
    
    def test_generate_patrol_back_forth(self, mission_planner):
        """测试生成往返巡逻航线"""
        points = [
            Position(39.9042, 116.4074, 50.0),
            Position(39.9142, 116.4174, 50.0),
            Position(39.9242, 116.4274, 50.0)
        ]
        
        patrol = mission_planner.generate_patrol_path(points, "back_forth")
        
        assert len(patrol) == 5  # 3个点 + 2个返回点


class TestObstacleAvoidance:
    """测试避障功能"""
    
    def test_add_obstacle_avoidance(self, mission_planner):
        """测试添加障碍物规避"""
        mission = mission_planner.create_mission("mission_001", "Test", MissionType.SURVEY)
        
        # 添加经过障碍物的航线
        wp1 = Waypoint(
            waypoint_id="wp_001",
            position=Position(39.9042, 116.4074, 50.0)
        )
        wp2 = Waypoint(
            waypoint_id="wp_002",
            position=Position(39.9142, 116.4174, 50.0)
        )
        
        mission.add_waypoint(wp1)
        mission.add_waypoint(wp2)
        
        # 添加障碍物（在航线上）
        obstacles = [
            (Position(39.9092, 116.4124, 50.0), 30.0)  # 位置和半径
        ]
        
        result = mission_planner.add_obstacle_avoidance("mission_001", obstacles)
        
        # 可能添加了规避航点
        assert result == True


class TestTemplates:
    """测试任务模板"""
    
    def test_get_template_survey(self, mission_planner):
        """测试获取测绘模板"""
        template = mission_planner.get_template("survey")
        
        assert template is not None
        assert template.mission_type == MissionType.SURVEY
    
    def test_get_template_inspection(self, mission_planner):
        """测试获取巡检模板"""
        template = mission_planner.get_template("inspection")
        
        assert template is not None
        assert template.mission_type == MissionType.INSPECTION
    
    def test_get_template_patrol(self, mission_planner):
        """测试获取巡逻模板"""
        template = mission_planner.get_template("patrol")
        
        assert template is not None
        assert template.mission_type == MissionType.PATROL
    
    def test_get_nonexistent_template(self, mission_planner):
        """测试获取不存在的模板"""
        template = mission_planner.get_template("nonexistent")
        
        assert template is None
    
    def test_create_from_template(self, mission_planner):
        """测试从模板创建任务"""
        mission = mission_planner.create_from_template(
            "survey",
            "new_survey",
            "New Survey Mission"
        )
        
        assert mission is not None
        assert mission.mission_id == "new_survey"
        assert mission.name == "New Survey Mission"
        assert "new_survey" in mission_planner.missions


class TestExportImport:
    """测试导出导入"""
    
    def test_export_mission(self, mission_planner, sample_mission):
        """测试导出任务"""
        data = mission_planner.export_mission("mission_001")
        
        assert data is not None
        assert data['mission_id'] == "mission_001"
        assert 'waypoints' in data
    
    def test_export_nonexistent_mission(self, mission_planner):
        """测试导出不存在的任务"""
        data = mission_planner.export_mission("nonexistent")
        
        assert data is None
    
    def test_import_mission(self, mission_planner):
        """测试导入任务"""
        mission_data = {
            'mission_id': 'imported_001',
            'name': 'Imported Mission',
            'mission_type': 'survey',
            'description': 'Imported from JSON',
            'waypoints': [
                {
                    'waypoint_id': 'wp_001',
                    'position': {
                        'latitude': 39.9042,
                        'longitude': 116.4074,
                        'altitude': 50.0
                    },
                    'waypoint_type': 'waypoint',
                    'speed': 5.0,
                    'hold_time': 0.0
                }
            ],
            'parameters': {
                'auto_takeoff': True,
                'takeoff_altitude': 10.0,
                'default_speed': 5.0
            }
        }
        
        mission = mission_planner.import_mission(mission_data)
        
        assert mission is not None
        assert mission.mission_id == "imported_001"
        assert len(mission.waypoints) == 1
        assert "imported_001" in mission_planner.missions
    
    def test_import_invalid_mission(self, mission_planner):
        """测试导入无效任务数据"""
        invalid_data = {
            'mission_id': 'invalid_001'
            # 缺少必需字段
        }
        
        mission = mission_planner.import_mission(invalid_data)
        
        assert mission is None


class TestMissionTypes:
    """测试不同任务类型"""
    
    def test_survey_mission(self, mission_planner):
        """测试测绘任务"""
        mission = mission_planner.create_mission(
            "survey_001",
            "Survey Mission",
            MissionType.SURVEY
        )
        
        assert mission.mission_type == MissionType.SURVEY
    
    def test_inspection_mission(self, mission_planner):
        """测试巡检任务"""
        mission = mission_planner.create_mission(
            "inspection_001",
            "Inspection Mission",
            MissionType.INSPECTION
        )
        
        assert mission.mission_type == MissionType.INSPECTION
    
    def test_delivery_mission(self, mission_planner):
        """测试投递任务"""
        mission = mission_planner.create_mission(
            "delivery_001",
            "Delivery Mission",
            MissionType.DELIVERY
        )
        
        assert mission.mission_type == MissionType.DELIVERY
    
    def test_patrol_mission(self, mission_planner):
        """测试巡逻任务"""
        mission = mission_planner.create_mission(
            "patrol_001",
            "Patrol Mission",
            MissionType.PATROL
        )
        
        assert mission.mission_type == MissionType.PATROL


class TestDistanceExceeded:
    """测试距离超限"""
    
    def test_validate_distance_exceeded(self, mission_planner):
        """测试验证距离超限"""
        mission = mission_planner.create_mission("mission_001", "Test", MissionType.SURVEY)
        mission.max_distance = 100.0  # 设置很小的最大距离
        
        # 添加距离较远的航点
        wp1 = Waypoint(
            waypoint_id="wp_001",
            position=Position(39.9042, 116.4074, 50.0)
        )
        wp2 = Waypoint(
            waypoint_id="wp_002",
            position=Position(40.0042, 117.4074, 50.0)  # 很远
        )
        
        mission.add_waypoint(wp1)
        mission.add_waypoint(wp2)
        
        valid, errors = mission_planner.validate_mission("mission_001")
        
        assert valid == False
        assert any("exceeds maximum" in e for e in errors)


class TestWaypointHoldTime:
    """测试航点悬停时间"""
    
    def test_waypoint_with_hold_time(self):
        """测试带悬停时间的航点"""
        wp = Waypoint(
            waypoint_id="wp_001",
            position=Position(39.9042, 116.4074, 50.0),
            hold_time=10.0
        )
        
        assert wp.hold_time == 10.0
    
    def test_mission_estimate_time_with_hold(self):
        """测试带悬停时间的任务时间估算"""
        mission = Mission(
            mission_id="mission_001",
            name="Test",
            mission_type=MissionType.INSPECTION
        )
        
        wp1 = Waypoint(
            waypoint_id="wp_001",
            position=Position(39.9042, 116.4074, 50.0),
            hold_time=5.0
        )
        wp2 = Waypoint(
            waypoint_id="wp_002",
            position=Position(39.9142, 116.4174, 50.0),
            hold_time=10.0
        )
        
        mission.add_waypoint(wp1)
        mission.add_waypoint(wp2)
        
        time1 = mission.estimate_flight_time()
        
        # 增加悬停时间
        wp1.hold_time = 20.0
        time2 = mission.estimate_flight_time()
        
        assert time2 > time1


class TestWaypointParameters:
    """测试航点参数"""
    
    def test_waypoint_acceptance_radius(self):
        """测试航点接受半径"""
        wp = Waypoint(
            waypoint_id="wp_001",
            position=Position(39.9042, 116.4074, 50.0),
            acceptance_radius=5.0
        )
        
        assert wp.acceptance_radius == 5.0
    
    def test_waypoint_pass_radius(self):
        """测试航点通过半径"""
        wp = Waypoint(
            waypoint_id="wp_001",
            position=Position(39.9042, 116.4074, 50.0),
            pass_radius=2.0
        )
        
        assert wp.pass_radius == 2.0
    
    def test_waypoint_heading(self):
        """测试航点航向"""
        wp = Waypoint(
            waypoint_id="wp_001",
            position=Position(39.9042, 116.4074, 50.0),
            heading=90.0
        )
        
        assert wp.heading == 90.0
    
    def test_waypoint_auto_heading(self):
        """测试航点自动航向"""
        wp = Waypoint(
            waypoint_id="wp_001",
            position=Position(39.9042, 116.4074, 50.0),
            heading=None
        )
        
        assert wp.heading is None


class TestMissionParameters:
    """测试任务参数"""
    
    def test_mission_auto_takeoff(self):
        """测试任务自动起飞"""
        mission = Mission(
            mission_id="mission_001",
            name="Test",
            mission_type=MissionType.SURVEY,
            auto_takeoff=True,
            takeoff_altitude=30.0
        )
        
        assert mission.auto_takeoff == True
        assert mission.takeoff_altitude == 30.0
    
    def test_mission_auto_land(self):
        """测试任务自动降落"""
        mission = Mission(
            mission_id="mission_001",
            name="Test",
            mission_type=MissionType.SURVEY,
            auto_land=True
        )
        
        assert mission.auto_land == True
    
    def test_mission_return_to_home(self):
        """测试任务返航"""
        mission = Mission(
            mission_id="mission_001",
            name="Test",
            mission_type=MissionType.SURVEY,
            return_to_home=True
        )
        
        assert mission.return_to_home == True
    
    def test_mission_speed_settings(self):
        """测试任务速度设置"""
        mission = Mission(
            mission_id="mission_001",
            name="Test",
            mission_type=MissionType.SURVEY,
            default_speed=8.0,
            max_speed=20.0
        )
        
        assert mission.default_speed == 8.0
        assert mission.max_speed == 20.0


class TestSurveyGrid:
    """测试测绘网格"""
    
    def test_survey_grid_dimensions(self, mission_planner, sample_position):
        """测试测绘网格尺寸"""
        waypoints = mission_planner.generate_survey_grid(
            center=sample_position,
            width=200,
            height=100,
            spacing=50,
            altitude=50.0
        )
        
        assert len(waypoints) > 0
    
    def test_survey_grid_with_angle(self, mission_planner, sample_position):
        """测试带角度的测绘网格"""
        waypoints1 = mission_planner.generate_survey_grid(
            center=sample_position,
            width=100,
            height=100,
            spacing=50,
            altitude=50.0,
            angle=0.0
        )
        
        waypoints2 = mission_planner.generate_survey_grid(
            center=sample_position,
            width=100,
            height=100,
            spacing=50,
            altitude=50.0,
            angle=45.0
        )
        
        # 不同角度应该产生不同的航点
        assert waypoints1[0].latitude != waypoints2[0].latitude


class TestCirclePath:
    """测试圆形航线"""
    
    def test_circle_path_points(self, mission_planner, sample_position):
        """测试圆形航线点数"""
        waypoints = mission_planner.generate_circle_path(
            center=sample_position,
            radius=50,
            altitude=50.0,
            num_points=12
        )
        
        assert len(waypoints) == 12
    
    def test_circle_path_radius(self, mission_planner, sample_position):
        """测试圆形航线半径"""
        waypoints = mission_planner.generate_circle_path(
            center=sample_position,
            radius=100,
            altitude=50.0,
            num_points=8
        )
        
        # 检查所有点与中心的距离近似相等
        for wp in waypoints:
            dist = sample_position.distance_to(wp)
            # 允许一定误差
            assert abs(dist - 100) < 10


class TestPatrolPath:
    """测试巡逻航线"""
    
    def test_patrol_circular_returns_to_start(self, mission_planner):
        """测试环形巡逻返回起点"""
        points = [
            Position(39.9042, 116.4074, 50.0),
            Position(39.9142, 116.4174, 50.0),
            Position(39.9242, 116.4274, 50.0)
        ]
        
        patrol = mission_planner.generate_patrol_path(points, "circular")
        
        assert patrol[0] == patrol[-1]
    
    def test_patrol_back_forth(self, mission_planner):
        """测试往返巡逻"""
        points = [
            Position(39.9042, 116.4074, 50.0),
            Position(39.9142, 116.4174, 50.0),
            Position(39.9242, 116.4274, 50.0)
        ]
        
        patrol = mission_planner.generate_patrol_path(points, "back_forth")
        
        # 往返应该包含正向和反向
        assert len(patrol) == len(points) * 2 - 1


class TestMissionCopy:
    """测试任务复制"""
    
    def test_create_from_template_preserves_type(self, mission_planner):
        """测试从模板创建保留类型"""
        mission = mission_planner.create_from_template(
            "survey",
            "new_survey",
            "New Survey"
        )
        
        assert mission.mission_type == MissionType.SURVEY
    
    def test_create_from_template_independent(self, mission_planner):
        """测试从模板创建独立任务"""
        mission1 = mission_planner.create_from_template(
            "survey",
            "survey_1",
            "Survey 1"
        )
        mission2 = mission_planner.create_from_template(
            "survey",
            "survey_2",
            "Survey 2"
        )
        
        # 修改一个不应该影响另一个
        mission1.default_speed = 10.0
        
        assert mission2.default_speed != 10.0


class TestWaypointTypes:
    """测试航点类型"""
    
    def test_waypoint_type_values(self):
        """测试航点类型枚举值"""
        assert WaypointType.WAYPOINT.value == "waypoint"
        assert WaypointType.TAKEOFF.value == "takeoff"
        assert WaypointType.LAND.value == "land"
        assert WaypointType.LOITER.value == "loiter"
        assert WaypointType.POI.value == "poi"
        assert WaypointType.ROI.value == "roi"
    
    def test_mission_with_mixed_waypoint_types(self, mission_planner):
        """测试混合航点类型的任务"""
        mission = mission_planner.create_mission("mission_001", "Test", MissionType.SURVEY)
        
        wp1 = Waypoint(
            waypoint_id="wp_001",
            position=Position(39.9042, 116.4074, 50.0),
            waypoint_type=WaypointType.TAKEOFF
        )
        wp2 = Waypoint(
            waypoint_id="wp_002",
            position=Position(39.9142, 116.4174, 50.0),
            waypoint_type=WaypointType.WAYPOINT
        )
        wp3 = Waypoint(
            waypoint_id="wp_003",
            position=Position(39.9242, 116.4274, 50.0),
            waypoint_type=WaypointType.LOITER,
            hold_time=30.0
        )
        wp4 = Waypoint(
            waypoint_id="wp_004",
            position=Position(39.9042, 116.4074, 0.0),
            waypoint_type=WaypointType.LAND
        )
        
        mission.add_waypoint(wp1)
        mission.add_waypoint(wp2)
        mission.add_waypoint(wp3)
        mission.add_waypoint(wp4)
        
        assert len(mission.waypoints) == 4
        assert mission.waypoints[0].waypoint_type == WaypointType.TAKEOFF
        assert mission.waypoints[-1].waypoint_type == WaypointType.LAND


class TestMissionTypesExtended:
    """测试任务类型扩展"""
    
    def test_mission_type_values(self):
        """测试任务类型枚举值"""
        assert MissionType.SURVEY.value == "survey"
        assert MissionType.INSPECTION.value == "inspection"
        assert MissionType.DELIVERY.value == "delivery"
        assert MissionType.PATROL.value == "patrol"
        assert MissionType.PHOTOGRAMMETRY.value == "photogrammetry"
        assert MissionType.CUSTOM.value == "custom"
    
    def test_photogrammetry_mission(self, mission_planner):
        """测试摄影测量任务"""
        mission = mission_planner.create_mission(
            "photo_001",
            "Photogrammetry Mission",
            MissionType.PHOTOGRAMMETRY
        )
        
        assert mission.mission_type == MissionType.PHOTOGRAMMETRY
    
    def test_delivery_mission(self, mission_planner):
        """测试投递任务"""
        mission = mission_planner.create_mission(
            "delivery_001",
            "Delivery Mission",
            MissionType.DELIVERY
        )
        
        assert mission.mission_type == MissionType.DELIVERY


class TestImportExportExtended:
    """测试导入导出扩展"""
    
    def test_import_with_all_parameters(self, mission_planner):
        """测试导入包含所有参数的任务"""
        mission_data = {
            'mission_id': 'full_001',
            'name': 'Full Mission',
            'mission_type': 'survey',
            'description': 'Full parameter test',
            'waypoints': [
                {
                    'waypoint_id': 'wp_001',
                    'position': {'latitude': 39.9042, 'longitude': 116.4074, 'altitude': 50.0},
                    'waypoint_type': 'takeoff',
                    'speed': 8.0,
                    'hold_time': 5.0,
                    'camera_action': 'take_photo',
                    'camera_angle': -45.0,
                    'heading': 90.0,
                    'acceptance_radius': 3.0,
                    'pass_radius': 1.0
                }
            ],
            'parameters': {
                'auto_takeoff': True,
                'takeoff_altitude': 20.0,
                'auto_land': True,
                'return_to_home': True,
                'default_speed': 6.0,
                'default_altitude': 40.0,
                'max_speed': 12.0
            },
            'safety': {
                'min_altitude': 5.0,
                'max_altitude': 100.0,
                'max_distance': 5000.0
            }
        }
        
        mission = mission_planner.import_mission(mission_data)
        
        assert mission is not None
        assert mission.takeoff_altitude == 20.0
        assert mission.default_speed == 6.0
        assert mission.waypoints[0].speed == 8.0
        assert mission.waypoints[0].hold_time == 5.0
    
    def test_export_import_cycle(self, mission_planner, sample_mission):
        """测试导出导入循环"""
        # 导出
        exported = mission_planner.export_mission("mission_001")
        
        # 导入到新任务
        imported = mission_planner.import_mission(exported)
        
        assert imported is not None
        assert imported.mission_id == "mission_001"
        assert len(imported.waypoints) == len(sample_mission.waypoints)


class TestEdgeCases:
    """测试边界情况"""
    
    def test_mission_with_single_waypoint(self, mission_planner):
        """测试单个航点的任务"""
        mission = mission_planner.create_mission("single_001", "Single", MissionType.SURVEY)
        
        wp = Waypoint(
            waypoint_id="wp_001",
            position=Position(39.9042, 116.4074, 50.0)
        )
        mission.add_waypoint(wp)
        
        distance = mission.calculate_total_distance()
        
        assert distance == 0.0
    
    def test_mission_with_zero_speed(self):
        """测试零速度航点"""
        wp = Waypoint(
            waypoint_id="wp_001",
            position=Position(39.9042, 116.4074, 50.0),
            speed=0.0
        )
        
        # 零速度应该被允许（可能用于悬停）
        assert wp.speed == 0.0
    
    def test_position_at_poles(self):
        """测试极地位置"""
        north_pole = Position(90.0, 0.0, 50.0)
        south_pole = Position(-90.0, 0.0, 50.0)
        
        assert north_pole.latitude == 90.0
        assert south_pole.latitude == -90.0
    
    def test_position_at_dateline(self):
        """测试国际日期变更线位置"""
        pos1 = Position(0.0, 180.0, 50.0)
        pos2 = Position(0.0, -180.0, 50.0)
        
        assert pos1.longitude == 180.0
        assert pos2.longitude == -180.0


class TestMissionTimestamps:
    """测试任务时间戳"""
    
    def test_mission_created_at(self, mission_planner):
        """测试任务创建时间"""
        before = datetime.now()
        mission = mission_planner.create_mission("mission_001", "Test", MissionType.SURVEY)
        after = datetime.now()
        
        assert before <= mission.created_at <= after
    
    def test_mission_updated_on_waypoint_add(self, mission_planner):
        """测试添加航点更新时间"""
        mission = mission_planner.create_mission("mission_001", "Test", MissionType.SURVEY)
        original_updated = mission.updated_at
        
        # 等待一小段时间
        import time
        time.sleep(0.01)
        
        wp = Waypoint(
            waypoint_id="wp_001",
            position=Position(39.9042, 116.4074, 50.0)
        )
        mission.add_waypoint(wp)
        
        assert mission.updated_at > original_updated


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
