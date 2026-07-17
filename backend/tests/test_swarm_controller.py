"""
集群控制器单元测试
测试集群管理、编队控制、任务分配、碰撞避免、紧急控制
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock, patch
from datetime import datetime
import math

import sys
sys.path.insert(0, '/home/dudu/.nanobot/workspace/skymaster-drone-platform/backend')

from core.swarm.controller import (
    SwarmController,
    SwarmConfig,
    SwarmState,
    SwarmStatus,
    FormationType,
    FormationSlot,
    FormationGenerator,
    TaskAllocator,
    CollisionAvoidance
)
from core.devices.manager import DeviceManager, DroneDevice, DeviceStatus
from core.missions.planner import Mission, MissionPlanner, Waypoint, Position, MissionType
from core.mavlink.connector import DroneConfig, DroneType, ConnectionState, TelemetryData


# Fixtures
@pytest.fixture
def device_manager():
    """设备管理器实例"""
    return DeviceManager()


@pytest.fixture
def swarm_controller(device_manager):
    """集群控制器实例"""
    return SwarmController(device_manager)


@pytest.fixture
def swarm_config():
    """集群配置"""
    return SwarmConfig(
        swarm_id="swarm_001",
        name="Alpha Team",
        formation_type=FormationType.V_SHAPE,
        spacing=10.0,
        altitude_offset=5.0,
        min_separation=5.0,
        collision_avoidance=True
    )


@pytest.fixture
def sample_position():
    """示例位置"""
    return Position(
        latitude=39.9042,
        longitude=116.4074,
        altitude=50.0
    )


@pytest.fixture
def sample_mission():
    """示例任务"""
    mission = Mission(
        mission_id="mission_001",
        name="Test Mission",
        mission_type=MissionType.SURVEY
    )
    
    for i in range(5):
        wp = Waypoint(
            waypoint_id=f"wp_{i:03d}",
            position=Position(39.9042 + i*0.01, 116.4074 + i*0.01, 50.0)
        )
        mission.add_waypoint(wp)
    
    return mission


@pytest.fixture
def mock_device():
    """模拟设备"""
    config = DroneConfig(
        drone_id="drone_001",
        drone_type=DroneType.PX4,
        connection_string="udp:127.0.0.1:14550"
    )
    
    device = DroneDevice(
        device_id="drone_001",
        name="Test Drone",
        drone_type=DroneType.PX4,
        config=config,
        status=DeviceStatus.ONLINE
    )
    
    # 模拟连接器
    mock_connector = MagicMock()
    mock_connector.state = ConnectionState.CONNECTED
    mock_connector.telemetry = TelemetryData(
        latitude=39.9042,
        longitude=116.4074,
        altitude=50.0
    )
    device.connector = mock_connector
    
    return device


class TestFormationGenerator:
    """测试编队生成器"""
    
    def test_generate_line_formation(self):
        """测试生成直线编队"""
        slots = FormationGenerator.generate_formation(
            FormationType.LINE,
            num_slots=5,
            spacing=10.0
        )
        
        assert len(slots) == 5
        assert all(isinstance(slot, FormationSlot) for slot in slots)
        
        # 检查中间槽位在中心
        center_idx = len(slots) // 2
        assert slots[center_idx].offset_east == 0
    
    def test_generate_v_shape_formation(self):
        """测试生成V形编队"""
        slots = FormationGenerator.generate_formation(
            FormationType.V_SHAPE,
            num_slots=5,
            spacing=10.0
        )
        
        assert len(slots) == 5
        
        # 领机应该在第一个位置
        assert slots[0].offset_north == 0
        assert slots[0].offset_east == 0
    
    def test_generate_circle_formation(self):
        """测试生成圆形编队"""
        slots = FormationGenerator.generate_formation(
            FormationType.CIRCLE,
            num_slots=8,
            spacing=10.0
        )
        
        assert len(slots) == 8
        
        # 检查圆形分布
        for slot in slots:
            distance = math.sqrt(slot.offset_north**2 + slot.offset_east**2)
            # 所有槽位应该近似在圆周上
            assert distance > 0
    
    def test_generate_grid_formation(self):
        """测试生成网格编队"""
        slots = FormationGenerator.generate_formation(
            FormationType.GRID,
            num_slots=9,
            spacing=10.0
        )
        
        assert len(slots) == 9
        
        # 9个设备应该是3x3网格
        unique_north = set(slot.offset_north for slot in slots)
        unique_east = set(slot.offset_east for slot in slots)
        
        assert len(unique_north) == 3
        assert len(unique_east) == 3
    
    def test_generate_formation_single_drone(self):
        """测试单机编队"""
        slots = FormationGenerator.generate_formation(
            FormationType.LINE,
            num_slots=1,
            spacing=10.0
        )
        
        assert len(slots) == 1
        assert slots[0].offset_north == 0
        assert slots[0].offset_east == 0
    
    def test_generate_formation_with_altitude_offset(self):
        """测试带高度偏移的编队"""
        slots = FormationGenerator.generate_formation(
            FormationType.LINE,
            num_slots=3,
            spacing=10.0,
            altitude_offset=5.0
        )
        
        # 检查高度分层
        altitude_offsets = [slot.offset_altitude for slot in slots]
        assert 0.0 in altitude_offsets  # 第一个应该在基准高度


class TestTaskAllocator:
    """测试任务分配器"""
    
    def test_allocate_mission_balanced(self, mock_device):
        """测试平衡分配策略"""
        devices = [mock_device]
        
        # 修改设备ID创建多个设备
        devices = []
        for i in range(3):
            config = DroneConfig(
                drone_id=f"drone_{i:03d}",
                drone_type=DroneType.PX4,
                connection_string=f"udp:127.0.0.1:{14550+i}"
            )
            device = DroneDevice(
                device_id=f"drone_{i:03d}",
                name=f"Drone {i}",
                drone_type=DroneType.PX4,
                config=config,
                status=DeviceStatus.ONLINE
            )
            devices.append(device)
        
        mission = Mission(
            mission_id="mission_001",
            name="Test",
            mission_type=MissionType.SURVEY
        )
        
        for i in range(9):
            wp = Waypoint(
                waypoint_id=f"wp_{i:03d}",
                position=Position(39.9042 + i*0.01, 116.4074, 50.0)
            )
            mission.add_waypoint(wp)
        
        allocation = TaskAllocator.allocate_mission(
            devices,
            mission,
            allocation_strategy="balanced"
        )
        
        assert len(allocation) == 3
        # 每个设备应该分配3个航点
        for device_id, waypoints in allocation.items():
            assert len(waypoints) == 3
    
    def test_allocate_mission_empty_devices(self):
        """测试空设备列表分配"""
        mission = Mission(
            mission_id="mission_001",
            name="Test",
            mission_type=MissionType.SURVEY
        )
        
        allocation = TaskAllocator.allocate_mission([], mission)
        
        assert allocation == {}
    
    def test_allocate_mission_empty_waypoints(self, mock_device):
        """测试空航点列表分配"""
        mission = Mission(
            mission_id="mission_001",
            name="Test",
            mission_type=MissionType.SURVEY
        )
        
        allocation = TaskAllocator.allocate_mission([mock_device], mission)
        
        assert allocation == {mock_device.device_id: []}
    
    def test_allocate_mission_more_devices_than_waypoints(self):
        """测试设备多于航点的情况"""
        devices = []
        for i in range(5):
            config = DroneConfig(
                drone_id=f"drone_{i:03d}",
                drone_type=DroneType.PX4,
                connection_string=f"udp:127.0.0.1:{14550+i}"
            )
            device = DroneDevice(
                device_id=f"drone_{i:03d}",
                name=f"Drone {i}",
                drone_type=DroneType.PX4,
                config=config
            )
            devices.append(device)
        
        mission = Mission(
            mission_id="mission_001",
            name="Test",
            mission_type=MissionType.SURVEY
        )
        
        # 只添加2个航点
        for i in range(2):
            wp = Waypoint(
                waypoint_id=f"wp_{i:03d}",
                position=Position(39.9042 + i*0.01, 116.4074, 50.0)
            )
            mission.add_waypoint(wp)
        
        allocation = TaskAllocator.allocate_mission(
            devices,
            mission,
            allocation_strategy="balanced"
        )
        
        # 检查分配结果
        total_assigned = sum(len(wps) for wps in allocation.values())
        assert total_assigned == 2


class TestCollisionAvoidance:
    """测试碰撞避免系统"""
    
    def test_check_no_collisions(self):
        """测试无碰撞情况"""
        ca = CollisionAvoidance(min_separation=5.0)
        
        telemetry_data = {
            "drone_001": TelemetryData(latitude=39.9042, longitude=116.4074, altitude=50.0),
            "drone_002": TelemetryData(latitude=39.9142, longitude=116.4174, altitude=50.0)
        }
        
        collisions = ca.check_collisions(telemetry_data)
        
        assert len(collisions) == 0
    
    def test_check_collision_detected(self):
        """测试检测到碰撞"""
        ca = CollisionAvoidance(min_separation=100.0)  # 设置较大的最小间距
        
        telemetry_data = {
            "drone_001": TelemetryData(latitude=39.9042, longitude=116.4074, altitude=50.0),
            "drone_002": TelemetryData(latitude=39.9043, longitude=116.4075, altitude=50.0)
        }
        
        collisions = ca.check_collisions(telemetry_data)
        
        assert len(collisions) > 0
        assert collisions[0][0] == "drone_001"
        assert collisions[0][1] == "drone_002"
    
    def test_check_single_drone(self):
        """测试单机无碰撞"""
        ca = CollisionAvoidance(min_separation=5.0)
        
        telemetry_data = {
            "drone_001": TelemetryData(latitude=39.9042, longitude=116.4074, altitude=50.0)
        }
        
        collisions = ca.check_collisions(telemetry_data)
        
        assert len(collisions) == 0
    
    def test_calculate_avoidance_vector(self):
        """测试计算避碰向量"""
        ca = CollisionAvoidance(min_separation=5.0)
        
        t1 = TelemetryData(latitude=39.9042, longitude=116.4074, altitude=50.0)
        t2 = TelemetryData(latitude=39.9043, longitude=116.4075, altitude=50.0)
        
        avoid_north, avoid_east = ca.calculate_avoidance_vector(t1, t2)
        
        # 应该产生非零的避碰向量
        assert avoid_north != 0 or avoid_east != 0
    
    def test_calculate_avoidance_vector_same_position(self):
        """测试相同位置的避碰向量"""
        ca = CollisionAvoidance(min_separation=5.0)
        
        t1 = TelemetryData(latitude=39.9042, longitude=116.4074, altitude=50.0)
        t2 = TelemetryData(latitude=39.9042, longitude=116.4074, altitude=50.0)
        
        avoid_north, avoid_east = ca.calculate_avoidance_vector(t1, t2)
        
        # 相同位置应该返回零向量
        assert avoid_north == 0.0
        assert avoid_east == 0.0
    
    def test_multiple_drones_collision_check(self):
        """测试多机碰撞检测"""
        ca = CollisionAvoidance(min_separation=50.0)
        
        telemetry_data = {
            "drone_001": TelemetryData(latitude=39.9042, longitude=116.4074, altitude=50.0),
            "drone_002": TelemetryData(latitude=39.9043, longitude=116.4075, altitude=50.0),
            "drone_003": TelemetryData(latitude=39.9044, longitude=116.4076, altitude=50.0)
        }
        
        collisions = ca.check_collisions(telemetry_data)
        
        # 应该检测到多对碰撞
        assert len(collisions) >= 2


class TestSwarmConfig:
    """测试集群配置"""
    
    def test_swarm_config_creation(self):
        """测试创建集群配置"""
        config = SwarmConfig(
            swarm_id="swarm_001",
            name="Test Swarm",
            formation_type=FormationType.LINE,
            spacing=10.0
        )
        
        assert config.swarm_id == "swarm_001"
        assert config.name == "Test Swarm"
        assert config.formation_type == FormationType.LINE
        assert config.spacing == 10.0
    
    def test_swarm_config_defaults(self):
        """测试集群配置默认值"""
        config = SwarmConfig(
            swarm_id="swarm_001",
            name="Test"
        )
        
        assert config.formation_type == FormationType.LINE
        assert config.spacing == 10.0
        assert config.collision_avoidance == True
        assert config.min_separation == 5.0


class TestSwarmStatus:
    """测试集群状态"""
    
    def test_swarm_status_creation(self):
        """测试创建集群状态"""
        status = SwarmStatus()
        
        assert status.state == SwarmState.IDLE
        assert status.leader_id is None
        assert status.formation_complete == False
        assert status.active_count == 0
    
    def test_swarm_status_with_values(self):
        """测试带值的集群状态"""
        status = SwarmStatus(
            state=SwarmState.FLYING,
            leader_id="drone_001",
            formation_complete=True,
            active_count=5
        )
        
        assert status.state == SwarmState.FLYING
        assert status.leader_id == "drone_001"
        assert status.formation_complete == True
        assert status.active_count == 5


class TestSwarmController:
    """测试集群控制器"""
    
    @pytest.mark.asyncio
    async def test_create_swarm(self, swarm_controller, swarm_config):
        """测试创建集群"""
        result = await swarm_controller.create_swarm(swarm_config)
        
        assert result == True
        assert "swarm_001" in swarm_controller.swarms
        assert "swarm_001" in swarm_controller.swarm_status
    
    @pytest.mark.asyncio
    async def test_create_duplicate_swarm(self, swarm_controller, swarm_config):
        """测试创建重复集群"""
        await swarm_controller.create_swarm(swarm_config)
        
        result = await swarm_controller.create_swarm(swarm_config)
        
        assert result == False
    
    @pytest.mark.asyncio
    async def test_delete_swarm(self, swarm_controller, swarm_config):
        """测试删除集群"""
        await swarm_controller.create_swarm(swarm_config)
        
        result = await swarm_controller.delete_swarm("swarm_001")
        
        assert result == True
        assert "swarm_001" not in swarm_controller.swarms
    
    @pytest.mark.asyncio
    async def test_delete_nonexistent_swarm(self, swarm_controller):
        """测试删除不存在的集群"""
        result = await swarm_controller.delete_swarm("nonexistent")
        
        assert result == False
    
    @pytest.mark.asyncio
    async def test_add_device_to_swarm(self, swarm_controller, swarm_config):
        """测试添加设备到集群"""
        await swarm_controller.create_swarm(swarm_config)
        
        # 先注册设备
        config = DroneConfig(
            drone_id="drone_001",
            drone_type=DroneType.PX4,
            connection_string="udp:127.0.0.1:14550"
        )
        await swarm_controller.device_manager.register_device(config)
        
        result = await swarm_controller.add_device_to_swarm("drone_001", "swarm_001")
        
        assert result == True
        assert "drone_001" in swarm_controller.swarm_devices["swarm_001"]
    
    @pytest.mark.asyncio
    async def test_add_nonexistent_device_to_swarm(self, swarm_controller, swarm_config):
        """测试添加不存在的设备到集群"""
        await swarm_controller.create_swarm(swarm_config)
        
        result = await swarm_controller.add_device_to_swarm("nonexistent", "swarm_001")
        
        assert result == False
    
    @pytest.mark.asyncio
    async def test_add_device_to_nonexistent_swarm(self, swarm_controller):
        """测试添加设备到不存在的集群"""
        result = await swarm_controller.add_device_to_swarm("drone_001", "nonexistent")
        
        assert result == False
    
    @pytest.mark.asyncio
    async def test_remove_device_from_swarm(self, swarm_controller, swarm_config):
        """测试从集群移除设备"""
        await swarm_controller.create_swarm(swarm_config)
        
        config = DroneConfig(
            drone_id="drone_001",
            drone_type=DroneType.PX4,
            connection_string="udp:127.0.0.1:14550"
        )
        await swarm_controller.device_manager.register_device(config)
        await swarm_controller.add_device_to_swarm("drone_001", "swarm_001")
        
        result = await swarm_controller.remove_device_from_swarm("drone_001", "swarm_001")
        
        assert result == True
        assert "drone_001" not in swarm_controller.swarm_devices["swarm_001"]
    
    @pytest.mark.asyncio
    async def test_get_swarm_status(self, swarm_controller, swarm_config):
        """测试获取集群状态"""
        await swarm_controller.create_swarm(swarm_config)
        
        status = swarm_controller.get_swarm_status("swarm_001")
        
        assert status is not None
        assert status.state == SwarmState.IDLE
    
    @pytest.mark.asyncio
    async def test_get_nonexistent_swarm_status(self, swarm_controller):
        """测试获取不存在集群的状态"""
        status = swarm_controller.get_swarm_status("nonexistent")
        
        assert status is None
    
    @pytest.mark.asyncio
    async def test_get_all_swarms(self, swarm_controller):
        """测试获取所有集群"""
        config1 = SwarmConfig(swarm_id="swarm_001", name="Alpha")
        config2 = SwarmConfig(swarm_id="swarm_002", name="Beta")
        
        await swarm_controller.create_swarm(config1)
        await swarm_controller.create_swarm(config2)
        
        swarms = swarm_controller.get_all_swarms()
        
        assert len(swarms) == 2
    
    @pytest.mark.asyncio
    async def test_form_formation(self, swarm_controller, swarm_config, sample_position):
        """测试编队成形"""
        await swarm_controller.create_swarm(swarm_config)
        
        # 添加设备
        for i in range(3):
            config = DroneConfig(
                drone_id=f"drone_{i:03d}",
                drone_type=DroneType.PX4,
                connection_string=f"udp:127.0.0.1:{14550+i}"
            )
            await swarm_controller.device_manager.register_device(config)
            await swarm_controller.add_device_to_swarm(f"drone_{i:03d}", "swarm_001")
        
        result = await swarm_controller.form_formation("swarm_001", sample_position)
        
        assert result == True
        status = swarm_controller.get_swarm_status("swarm_001")
        assert status.formation_complete == True
    
    @pytest.mark.asyncio
    async def test_form_formation_nonexistent_swarm(self, swarm_controller, sample_position):
        """测试不存在集群的编队成形"""
        result = await swarm_controller.form_formation("nonexistent", sample_position)
        
        assert result == False
    
    @pytest.mark.asyncio
    async def test_move_formation(self, swarm_controller, swarm_config, sample_position):
        """测试移动编队"""
        await swarm_controller.create_swarm(swarm_config)
        
        # 添加设备并完成编队
        for i in range(3):
            config = DroneConfig(
                drone_id=f"drone_{i:03d}",
                drone_type=DroneType.PX4,
                connection_string=f"udp:127.0.0.1:{14550+i}"
            )
            await swarm_controller.device_manager.register_device(config)
            await swarm_controller.add_device_to_swarm(f"drone_{i:03d}", "swarm_001")
        
        await swarm_controller.form_formation("swarm_001", sample_position)
        
        # 移动到新位置
        new_position = Position(40.0, 117.0, 60.0)
        result = await swarm_controller.move_formation("swarm_001", new_position)
        
        assert result == True
    
    @pytest.mark.asyncio
    async def test_change_formation(self, swarm_controller, swarm_config, sample_position):
        """测试改变编队队形"""
        await swarm_controller.create_swarm(swarm_config)
        
        # 添加设备
        for i in range(3):
            config = DroneConfig(
                drone_id=f"drone_{i:03d}",
                drone_type=DroneType.PX4,
                connection_string=f"udp:127.0.0.1:{14550+i}"
            )
            await swarm_controller.device_manager.register_device(config)
            await swarm_controller.add_device_to_swarm(f"drone_{i:03d}", "swarm_001")
        
        result = await swarm_controller.change_formation("swarm_001", FormationType.CIRCLE)
        
        assert swarm_controller.swarms["swarm_001"].formation_type == FormationType.CIRCLE


class TestEmergencyControl:
    """测试紧急控制"""
    
    @pytest.mark.asyncio
    async def test_emergency_stop(self, swarm_controller, swarm_config):
        """测试紧急停止"""
        await swarm_controller.create_swarm(swarm_config)
        
        # 添加设备
        for i in range(3):
            config = DroneConfig(
                drone_id=f"drone_{i:03d}",
                drone_type=DroneType.PX4,
                connection_string=f"udp:127.0.0.1:{14550+i}"
            )
            await swarm_controller.device_manager.register_device(config)
            
            device = swarm_controller.device_manager.get_device(f"drone_{i:03d}")
            mock_connector = MagicMock()
            mock_connector.state = ConnectionState.CONNECTED
            device.connector = mock_connector
            device.status = DeviceStatus.FLYING
            
            await swarm_controller.add_device_to_swarm(f"drone_{i:03d}", "swarm_001")
        
        result = await swarm_controller.emergency_stop("swarm_001")
        
        assert result == True
        status = swarm_controller.get_swarm_status("swarm_001")
        assert status.state == SwarmState.EMERGENCY
    
    @pytest.mark.asyncio
    async def test_return_to_home(self, swarm_controller, swarm_config):
        """测试返航"""
        await swarm_controller.create_swarm(swarm_config)
        
        # 添加设备
        for i in range(2):
            config = DroneConfig(
                drone_id=f"drone_{i:03d}",
                drone_type=DroneType.PX4,
                connection_string=f"udp:127.0.0.1:{14550+i}"
            )
            await swarm_controller.device_manager.register_device(config)
            
            device = swarm_controller.device_manager.get_device(f"drone_{i:03d}")
            mock_connector = MagicMock()
            mock_connector.state = ConnectionState.CONNECTED
            device.connector = mock_connector
            device.status = DeviceStatus.FLYING
            
            await swarm_controller.add_device_to_swarm(f"drone_{i:03d}", "swarm_001")
        
        result = await swarm_controller.return_to_home("swarm_001")
        
        assert result == True
        status = swarm_controller.get_swarm_status("swarm_001")
        assert status.state == SwarmState.RETURNING
    
    @pytest.mark.asyncio
    async def test_land_all(self, swarm_controller, swarm_config):
        """测试降落所有设备"""
        await swarm_controller.create_swarm(swarm_config)
        
        # 添加设备
        for i in range(2):
            config = DroneConfig(
                drone_id=f"drone_{i:03d}",
                drone_type=DroneType.PX4,
                connection_string=f"udp:127.0.0.1:{14550+i}"
            )
            await swarm_controller.device_manager.register_device(config)
            
            device = swarm_controller.device_manager.get_device(f"drone_{i:03d}")
            mock_connector = MagicMock()
            mock_connector.state = ConnectionState.CONNECTED
            device.connector = mock_connector
            device.status = DeviceStatus.FLYING
            
            await swarm_controller.add_device_to_swarm(f"drone_{i:03d}", "swarm_001")
        
        result = await swarm_controller.land_all("swarm_001")
        
        assert result == True
    
    @pytest.mark.asyncio
    async def test_emergency_stop_nonexistent_swarm(self, swarm_controller):
        """测试不存在集群的紧急停止"""
        result = await swarm_controller.emergency_stop("nonexistent")
        
        assert result == False


class TestSwarmControllerLifecycle:
    """测试集群控制器生命周期"""
    
    @pytest.mark.asyncio
    async def test_start_controller(self, swarm_controller):
        """测试启动控制器"""
        await swarm_controller.start()
        
        assert swarm_controller._running == True
        assert len(swarm_controller._tasks) > 0
        
        await swarm_controller.stop()
    
    @pytest.mark.asyncio
    async def test_stop_controller(self, swarm_controller):
        """测试停止控制器"""
        await swarm_controller.start()
        await swarm_controller.stop()
        
        assert swarm_controller._running == False
    
    @pytest.mark.asyncio
    async def test_controller_with_multiple_swarms(self, swarm_controller):
        """测试控制器管理多个集群"""
        await swarm_controller.start()
        
        # 创建多个集群
        for i in range(3):
            config = SwarmConfig(
                swarm_id=f"swarm_{i:03d}",
                name=f"Team {i}",
                formation_type=FormationType.LINE
            )
            await swarm_controller.create_swarm(config)
        
        assert len(swarm_controller.swarms) == 3
        
        await swarm_controller.stop()


class TestFormationSlot:
    """测试编队槽位"""
    
    def test_slot_creation(self):
        """测试创建槽位"""
        slot = FormationSlot(
            slot_id="slot_001",
            position=Position(39.9042, 116.4074, 50.0),
            offset_north=10.0,
            offset_east=5.0,
            offset_altitude=2.0
        )
        
        assert slot.slot_id == "slot_001"
        assert slot.offset_north == 10.0
        assert slot.offset_east == 5.0
        assert slot.offset_altitude == 2.0
        assert slot.device_id is None
    
    def test_slot_with_device(self):
        """测试带设备的槽位"""
        slot = FormationSlot(
            slot_id="slot_001",
            position=Position(0, 0, 0),
            device_id="drone_001"
        )
        
        assert slot.device_id == "drone_001"


class TestSwarmState:
    """测试集群状态枚举"""
    
    def test_swarm_states(self):
        """测试集群状态值"""
        assert SwarmState.IDLE.value == "idle"
        assert SwarmState.FORMING.value == "forming"
        assert SwarmState.FLYING.value == "flying"
        assert SwarmState.EXECUTING_MISSION.value == "executing_mission"
        assert SwarmState.RETURNING.value == "returning"
        assert SwarmState.EMERGENCY.value == "emergency"


class TestFormationType:
    """测试编队类型枚举"""
    
    def test_formation_types(self):
        """测试编队类型值"""
        assert FormationType.LINE.value == "line"
        assert FormationType.V_SHAPE.value == "v_shape"
        assert FormationType.CIRCLE.value == "circle"
        assert FormationType.GRID.value == "grid"
        assert FormationType.FREE.value == "free"


class TestSwarmMonitorLoop:
    """测试集群监控循环"""
    
    @pytest.mark.asyncio
    async def test_monitor_updates_status(self, swarm_controller, swarm_config):
        """测试监控循环更新状态"""
        await swarm_controller.start()
        await swarm_controller.create_swarm(swarm_config)
        
        # 添加设备
        config = DroneConfig(
            drone_id="drone_001",
            drone_type=DroneType.PX4,
            connection_string="udp:127.0.0.1:14550"
        )
        await swarm_controller.device_manager.register_device(config)
        
        device = swarm_controller.device_manager.get_device("drone_001")
        device.status = DeviceStatus.FLYING
        
        await swarm_controller.add_device_to_swarm("drone_001", "swarm_001")
        
        # 等待监控循环运行
        await asyncio.sleep(0.1)
        
        status = swarm_controller.get_swarm_status("swarm_001")
        assert status.last_update is not None
        
        await swarm_controller.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
