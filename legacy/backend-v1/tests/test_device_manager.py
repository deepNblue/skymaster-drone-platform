"""
设备管理器单元测试
测试设备注册/注销、状态管理、并发访问、分组管理
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock, patch
from datetime import datetime, timedelta
import time

import sys
sys.path.insert(0, '/home/dudu/.nanobot/workspace/skymaster-drone-platform/backend')

from core.devices.manager import (
    DeviceManager,
    DroneDevice,
    DeviceGroup,
    DeviceStatus
)
from core.mavlink.connector import (
    DroneConfig,
    DroneType,
    ConnectionState,
    TelemetryData
)


# Fixtures
@pytest.fixture
def device_manager():
    """设备管理器实例"""
    return DeviceManager()


@pytest.fixture
def px4_config():
    """PX4无人机配置"""
    return DroneConfig(
        drone_id="drone_001",
        drone_type=DroneType.PX4,
        connection_string="udp:127.0.0.1:14550"
    )


@pytest.fixture
def ardupilot_config():
    """ArduPilot无人机配置"""
    return DroneConfig(
        drone_id="drone_002",
        drone_type=DroneType.ARDUPILOT,
        connection_string="tcp:127.0.0.1:5760"
    )


@pytest.fixture
def mock_connector():
    """模拟连接器"""
    connector = MagicMock()
    connector.state = ConnectionState.DISCONNECTED
    connector.connect = AsyncMock(return_value=True)
    connector.disconnect = AsyncMock(return_value=True)
    connector.send_command = AsyncMock(return_value=True)
    connector.telemetry = TelemetryData()
    connector.add_telemetry_callback = MagicMock()
    return connector


class TestDeviceRegistration:
    """测试设备注册"""
    
    @pytest.mark.asyncio
    async def test_register_device(self, device_manager, px4_config):
        """测试注册设备"""
        device_id = await device_manager.register_device(px4_config, name="Test Drone")
        
        assert device_id == "drone_001"
        assert "drone_001" in device_manager.devices
        assert device_manager.devices["drone_001"].name == "Test Drone"
        assert device_manager.devices["drone_001"].drone_type == DroneType.PX4
    
    @pytest.mark.asyncio
    async def test_register_device_with_properties(self, device_manager, px4_config):
        """测试带自定义属性注册设备"""
        custom_props = {
            "location": "Building A",
            "owner": "Team Alpha"
        }
        
        device_id = await device_manager.register_device(
            px4_config,
            name="Custom Drone",
            custom_properties=custom_props
        )
        
        device = device_manager.get_device(device_id)
        assert device.custom_properties["location"] == "Building A"
        assert device.custom_properties["owner"] == "Team Alpha"
    
    @pytest.mark.asyncio
    async def test_register_duplicate_device(self, device_manager, px4_config):
        """测试注册重复设备"""
        await device_manager.register_device(px4_config)
        
        # 再次注册相同设备
        device_id = await device_manager.register_device(px4_config)
        
        assert device_id == "drone_001"
        assert len(device_manager.devices) == 1
    
    @pytest.mark.asyncio
    async def test_register_multiple_devices(self, device_manager, px4_config, ardupilot_config):
        """测试注册多个设备"""
        await device_manager.register_device(px4_config, name="Alpha")
        await device_manager.register_device(ardupilot_config, name="Beta")
        
        assert len(device_manager.devices) == 2
        assert device_manager.stats['total_devices'] == 2
    
    @pytest.mark.asyncio
    async def test_unregister_device(self, device_manager, px4_config):
        """测试注销设备"""
        await device_manager.register_device(px4_config)
        
        result = await device_manager.unregister_device("drone_001")
        
        assert result == True
        assert "drone_001" not in device_manager.devices
        assert device_manager.stats['total_devices'] == 0
    
    @pytest.mark.asyncio
    async def test_unregister_nonexistent_device(self, device_manager):
        """测试注销不存在的设备"""
        result = await device_manager.unregister_device("nonexistent")
        
        assert result == False
    
    @pytest.mark.asyncio
    async def test_unregister_connected_device(self, device_manager, px4_config, mock_connector):
        """测试注销已连接的设备"""
        device_id = await device_manager.register_device(px4_config)
        device = device_manager.get_device(device_id)
        device.connector = mock_connector
        device.connector.state = ConnectionState.CONNECTED
        
        result = await device_manager.unregister_device(device_id)
        
        assert result == True
        mock_connector.disconnect.assert_called_once()


class TestDeviceConnection:
    """测试设备连接"""
    
    @pytest.mark.asyncio
    async def test_connect_device(self, device_manager, px4_config, mock_connector):
        """测试连接设备"""
        device_id = await device_manager.register_device(px4_config)
        device = device_manager.get_device(device_id)
        device.connector = mock_connector
        
        result = await device_manager.connect_device(device_id)
        
        assert result == True
        assert device.status == DeviceStatus.ONLINE
        mock_connector.connect.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_connect_nonexistent_device(self, device_manager):
        """测试连接不存在的设备"""
        result = await device_manager.connect_device("nonexistent")
        
        assert result == False
    
    @pytest.mark.asyncio
    async def test_disconnect_device(self, device_manager, px4_config, mock_connector):
        """测试断开设备连接"""
        device_id = await device_manager.register_device(px4_config)
        device = device_manager.get_device(device_id)
        device.connector = mock_connector
        device.status = DeviceStatus.ONLINE
        device.connector.state = ConnectionState.CONNECTED
        
        result = await device_manager.disconnect_device(device_id)
        
        assert result == True
        assert device.status == DeviceStatus.OFFLINE
        mock_connector.disconnect.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_connect_all_devices(self, device_manager, px4_config, ardupilot_config, mock_connector):
        """测试连接所有设备"""
        await device_manager.register_device(px4_config)
        await device_manager.register_device(ardupilot_config)
        
        for device in device_manager.devices.values():
            device.connector = mock_connector
        
        results = await device_manager.connect_all()
        
        assert len(results) == 2
        assert all(results.values())
    
    @pytest.mark.asyncio
    async def test_disconnect_all_devices(self, device_manager, px4_config, ardupilot_config, mock_connector):
        """测试断开所有设备"""
        await device_manager.register_device(px4_config)
        await device_manager.register_device(ardupilot_config)
        
        for device in device_manager.devices.values():
            device.connector = mock_connector
            device.status = DeviceStatus.ONLINE
            device.connector.state = ConnectionState.CONNECTED
        
        results = await device_manager.disconnect_all()
        
        assert len(results) == 2
        assert all(results.values())


class TestDeviceStatus:
    """测试设备状态管理"""
    
    def test_get_device(self, device_manager, px4_config):
        """测试获取设备"""
        asyncio.run(device_manager.register_device(px4_config))
        
        device = device_manager.get_device("drone_001")
        
        assert device is not None
        assert device.device_id == "drone_001"
    
    def test_get_nonexistent_device(self, device_manager):
        """测试获取不存在的设备"""
        device = device_manager.get_device("nonexistent")
        
        assert device is None
    
    def test_get_all_devices(self, device_manager, px4_config, ardupilot_config):
        """测试获取所有设备"""
        asyncio.run(device_manager.register_device(px4_config))
        asyncio.run(device_manager.register_device(ardupilot_config))
        
        devices = device_manager.get_all_devices()
        
        assert len(devices) == 2
    
    def test_get_devices_by_status(self, device_manager, px4_config):
        """测试按状态获取设备"""
        asyncio.run(device_manager.register_device(px4_config))
        device = device_manager.get_device("drone_001")
        device.status = DeviceStatus.ONLINE
        
        online_devices = device_manager.get_devices_by_status(DeviceStatus.ONLINE)
        
        assert len(online_devices) == 1
        assert online_devices[0].device_id == "drone_001"
    
    def test_get_devices_by_type(self, device_manager, px4_config, ardupilot_config):
        """测试按类型获取设备"""
        asyncio.run(device_manager.register_device(px4_config))
        asyncio.run(device_manager.register_device(ardupilot_config))
        
        px4_devices = device_manager.get_devices_by_type(DroneType.PX4)
        
        assert len(px4_devices) == 1
        assert px4_devices[0].drone_type == DroneType.PX4
    
    @pytest.mark.asyncio
    async def test_status_change_notification(self, device_manager, px4_config, mock_connector):
        """测试状态变更通知"""
        callback = AsyncMock()
        device_manager.add_status_callback(callback)
        
        device_id = await device_manager.register_device(px4_config)
        device = device_manager.get_device(device_id)
        device.connector = mock_connector
        
        await device_manager.connect_device(device_id)
        
        callback.assert_called()


class TestDeviceCommands:
    """测试设备命令"""
    
    @pytest.mark.asyncio
    async def test_send_arm_command(self, device_manager, px4_config, mock_connector):
        """测试发送解锁命令"""
        device_id = await device_manager.register_device(px4_config)
        device = device_manager.get_device(device_id)
        device.connector = mock_connector
        device.connector.state = ConnectionState.CONNECTED
        device.connector.arm = AsyncMock(return_value=True)
        device.status = DeviceStatus.ONLINE
        
        result = await device_manager.send_command(device_id, "arm")
        
        assert result == True
        device.connector.arm.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_send_takeoff_command(self, device_manager, px4_config, mock_connector):
        """测试发送起飞命令"""
        device_id = await device_manager.register_device(px4_config)
        device = device_manager.get_device(device_id)
        device.connector = mock_connector
        device.connector.state = ConnectionState.CONNECTED
        device.connector.takeoff = AsyncMock(return_value=True)
        device.status = DeviceStatus.ONLINE
        
        result = await device_manager.send_command(
            device_id,
            "takeoff",
            {"altitude": 50.0}
        )
        
        assert result == True
        device.connector.takeoff.assert_called_once_with(50.0)
    
    @pytest.mark.asyncio
    async def test_send_goto_command(self, device_manager, px4_config, mock_connector):
        """测试发送飞往命令"""
        device_id = await device_manager.register_device(px4_config)
        device = device_manager.get_device(device_id)
        device.connector = mock_connector
        device.connector.state = ConnectionState.CONNECTED
        device.connector.goto = AsyncMock(return_value=True)
        device.status = DeviceStatus.ONLINE
        
        params = {
            "latitude": 39.9042,
            "longitude": 116.4074,
            "altitude": 100.0
        }
        
        result = await device_manager.send_command(device_id, "goto", params)
        
        assert result == True
    
    @pytest.mark.asyncio
    async def test_send_command_to_disconnected_device(self, device_manager, px4_config):
        """测试向未连接设备发送命令"""
        device_id = await device_manager.register_device(px4_config)
        
        result = await device_manager.send_command(device_id, "arm")
        
        assert result == False
    
    @pytest.mark.asyncio
    async def test_send_unknown_command(self, device_manager, px4_config, mock_connector):
        """测试发送未知命令"""
        device_id = await device_manager.register_device(px4_config)
        device = device_manager.get_device(device_id)
        device.connector = mock_connector
        device.connector.state = ConnectionState.CONNECTED
        device.status = DeviceStatus.ONLINE
        
        result = await device_manager.send_command(device_id, "unknown_command")
        
        assert result == False
    
    @pytest.mark.asyncio
    async def test_broadcast_command(self, device_manager, px4_config, ardupilot_config, mock_connector):
        """测试广播命令"""
        await device_manager.register_device(px4_config)
        await device_manager.register_device(ardupilot_config)
        
        for device in device_manager.devices.values():
            device.connector = mock_connector
            device.connector.state = ConnectionState.CONNECTED
            device.connector.arm = AsyncMock(return_value=True)
            device.status = DeviceStatus.ONLINE
        
        results = await device_manager.broadcast_command("arm")
        
        assert len(results) == 2
        assert all(results.values())


class TestDeviceGroups:
    """测试设备分组"""
    
    @pytest.mark.asyncio
    async def test_create_group(self, device_manager):
        """测试创建分组"""
        result = await device_manager.create_group(
            "group_001",
            "Team Alpha",
            "Primary fleet"
        )
        
        assert result == True
        assert "group_001" in device_manager.groups
        assert device_manager.groups["group_001"].name == "Team Alpha"
    
    @pytest.mark.asyncio
    async def test_create_duplicate_group(self, device_manager):
        """测试创建重复分组"""
        await device_manager.create_group("group_001", "Team Alpha")
        
        result = await device_manager.create_group("group_001", "Team Beta")
        
        assert result == False
    
    @pytest.mark.asyncio
    async def test_delete_group(self, device_manager):
        """测试删除分组"""
        await device_manager.create_group("group_001", "Team Alpha")
        
        result = await device_manager.delete_group("group_001")
        
        assert result == True
        assert "group_001" not in device_manager.groups
    
    @pytest.mark.asyncio
    async def test_delete_nonexistent_group(self, device_manager):
        """测试删除不存在的分组"""
        result = await device_manager.delete_group("nonexistent")
        
        assert result == False
    
    @pytest.mark.asyncio
    async def test_add_device_to_group(self, device_manager, px4_config):
        """测试将设备添加到分组"""
        device_id = await device_manager.register_device(px4_config)
        await device_manager.create_group("group_001", "Team Alpha")
        
        result = await device_manager.add_device_to_group(device_id, "group_001")
        
        assert result == True
        assert device_id in device_manager.groups["group_001"].device_ids
    
    @pytest.mark.asyncio
    async def test_add_nonexistent_device_to_group(self, device_manager):
        """测试将不存在的设备添加到分组"""
        await device_manager.create_group("group_001", "Team Alpha")
        
        result = await device_manager.add_device_to_group("nonexistent", "group_001")
        
        assert result == False
    
    @pytest.mark.asyncio
    async def test_remove_device_from_group(self, device_manager, px4_config):
        """测试从分组中移除设备"""
        device_id = await device_manager.register_device(px4_config)
        await device_manager.create_group("group_001", "Team Alpha")
        await device_manager.add_device_to_group(device_id, "group_001")
        
        result = await device_manager.remove_device_from_group(device_id, "group_001")
        
        assert result == True
        assert device_id not in device_manager.groups["group_001"].device_ids
    
    @pytest.mark.asyncio
    async def test_send_group_command(self, device_manager, px4_config, ardupilot_config, mock_connector):
        """测试向分组发送命令"""
        await device_manager.register_device(px4_config)
        await device_manager.register_device(ardupilot_config)
        await device_manager.create_group("group_001", "Team Alpha")
        
        for device_id in ["drone_001", "drone_002"]:
            await device_manager.add_device_to_group(device_id, "group_001")
            device = device_manager.get_device(device_id)
            device.connector = mock_connector
            device.connector.state = ConnectionState.CONNECTED
            device.connector.arm = AsyncMock(return_value=True)
            device.status = DeviceStatus.ONLINE
        
        results = await device_manager.send_group_command("group_001", "arm")
        
        assert len(results) == 2
    
    def test_get_group(self, device_manager):
        """测试获取分组"""
        asyncio.run(device_manager.create_group("group_001", "Team Alpha"))
        
        group = device_manager.get_group("group_001")
        
        assert group is not None
        assert group.group_id == "group_001"
    
    def test_get_all_groups(self, device_manager):
        """测试获取所有分组"""
        asyncio.run(device_manager.create_group("group_001", "Team Alpha"))
        asyncio.run(device_manager.create_group("group_002", "Team Beta"))
        
        groups = device_manager.get_all_groups()
        
        assert len(groups) == 2


class TestConcurrency:
    """测试并发访问"""
    
    @pytest.mark.asyncio
    async def test_concurrent_device_registration(self, device_manager):
        """测试并发设备注册"""
        configs = [
            DroneConfig(
                drone_id=f"drone_{i:03d}",
                drone_type=DroneType.PX4,
                connection_string=f"udp:127.0.0.1:{14550+i}"
            )
            for i in range(10)
        ]
        
        # 并发注册
        tasks = [
            device_manager.register_device(config)
            for config in configs
        ]
        
        results = await asyncio.gather(*tasks)
        
        assert len(results) == 10
        assert len(device_manager.devices) == 10
    
    @pytest.mark.asyncio
    async def test_concurrent_commands(self, device_manager, mock_connector):
        """测试并发命令发送"""
        # 注册10个设备
        for i in range(10):
            config = DroneConfig(
                drone_id=f"drone_{i:03d}",
                drone_type=DroneType.PX4,
                connection_string=f"udp:127.0.0.1:{14550+i}"
            )
            await device_manager.register_device(config)
            device = device_manager.get_device(f"drone_{i:03d}")
            device.connector = mock_connector
            device.connector.state = ConnectionState.CONNECTED
            device.connector.arm = AsyncMock(return_value=True)
            device.status = DeviceStatus.ONLINE
        
        # 并发发送命令
        tasks = [
            device_manager.send_command(f"drone_{i:03d}", "arm")
            for i in range(10)
        ]
        
        results = await asyncio.gather(*tasks)
        
        assert all(results)
    
    @pytest.mark.asyncio
    async def test_concurrent_group_operations(self, device_manager, px4_config):
        """测试并发分组操作"""
        # 创建多个分组
        for i in range(5):
            await device_manager.create_group(f"group_{i}", f"Team {i}")
        
        # 注册设备
        device_ids = []
        for i in range(20):
            config = DroneConfig(
                drone_id=f"drone_{i:03d}",
                drone_type=DroneType.PX4,
                connection_string=f"udp:127.0.0.1:{14550+i}"
            )
            device_id = await device_manager.register_device(config)
            device_ids.append(device_id)
        
        # 并发添加设备到分组
        tasks = []
        for i, device_id in enumerate(device_ids):
            group_id = f"group_{i % 5}"
            tasks.append(device_manager.add_device_to_group(device_id, group_id))
        
        await asyncio.gather(*tasks)
        
        # 验证
        total_devices = sum(len(g.device_ids) for g in device_manager.groups.values())
        assert total_devices == 20


class TestStatistics:
    """测试统计功能"""
    
    @pytest.mark.asyncio
    async def test_device_statistics(self, device_manager, px4_config):
        """测试设备统计"""
        await device_manager.register_device(px4_config)
        
        stats = device_manager.get_statistics()
        
        assert stats['devices']['total_devices'] == 1
        assert 'timestamp' in stats
    
    @pytest.mark.asyncio
    async def test_export_devices(self, device_manager, px4_config, ardupilot_config):
        """测试导出设备"""
        await device_manager.register_device(px4_config, name="Alpha")
        await device_manager.register_device(ardupilot_config, name="Beta")
        
        exported = device_manager.export_devices()
        
        assert len(exported) == 2
        assert all('device_id' in d for d in exported)
    
    @pytest.mark.asyncio
    async def test_export_groups(self, device_manager, px4_config):
        """测试导出分组"""
        await device_manager.create_group("group_001", "Team Alpha")
        await device_manager.create_group("group_002", "Team Beta")
        
        exported = device_manager.export_groups()
        
        assert len(exported) == 2


class TestDroneDevice:
    """测试无人机设备"""
    
    def test_device_creation(self):
        """测试设备创建"""
        config = DroneConfig(
            drone_id="test_001",
            drone_type=DroneType.PX4,
            connection_string="udp:127.0.0.1:14550"
        )
        
        device = DroneDevice(
            device_id="test_001",
            name="Test Drone",
            drone_type=DroneType.PX4,
            config=config
        )
        
        assert device.device_id == "test_001"
        assert device.status == DeviceStatus.OFFLINE
    
    def test_device_to_dict(self):
        """测试设备转换为字典"""
        config = DroneConfig(
            drone_id="test_001",
            drone_type=DroneType.PX4,
            connection_string="udp:127.0.0.1:14550"
        )
        
        device = DroneDevice(
            device_id="test_001",
            name="Test Drone",
            drone_type=DroneType.PX4,
            config=config,
            firmware_version="1.12.0",
            serial_number="SN12345"
        )
        
        data = device.to_dict()
        
        assert data['device_id'] == "test_001"
        assert data['name'] == "Test Drone"
        assert data['device_info']['firmware_version'] == "1.12.0"


class TestDeviceGroup:
    """测试设备分组"""
    
    def test_group_creation(self):
        """测试分组创建"""
        group = DeviceGroup(
            group_id="group_001",
            name="Team Alpha",
            description="Primary fleet"
        )
        
        assert group.group_id == "group_001"
        assert group.name == "Team Alpha"
        assert len(group.device_ids) == 0
    
    def test_group_to_dict(self):
        """测试分组转换为字典"""
        group = DeviceGroup(
            group_id="group_001",
            name="Team Alpha",
            description="Primary fleet",
            device_ids=["drone_001", "drone_002"]
        )
        
        data = group.to_dict()
        
        assert data['group_id'] == "group_001"
        assert data['device_count'] == 2


class TestTelemetryCallback:
    """测试遥测回调"""
    
    @pytest.mark.asyncio
    async def test_telemetry_callback_invoked(self, device_manager, px4_config, mock_connector):
        """测试遥测回调被调用"""
        callback = AsyncMock()
        device_manager.add_telemetry_callback(callback)
        
        device_id = await device_manager.register_device(px4_config)
        device = device_manager.get_device(device_id)
        device.connector = mock_connector
        
        # 触发遥测更新
        telemetry = TelemetryData(latitude=39.9042, longitude=116.4074)
        await device_manager._on_telemetry_update(device_id, telemetry)
        
        callback.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_telemetry_callback_updates_flying_status(self, device_manager, px4_config, mock_connector):
        """测试遥测回调更新飞行状态"""
        device_id = await device_manager.register_device(px4_config)
        device = device_manager.get_device(device_id)
        device.connector = mock_connector
        device.status = DeviceStatus.ONLINE
        
        # 模拟解锁遥测数据
        telemetry = TelemetryData(armed=True)
        await device_manager._on_telemetry_update(device_id, telemetry)
        
        assert device.status == DeviceStatus.FLYING
    
    @pytest.mark.asyncio
    async def test_telemetry_callback_low_battery_warning(self, device_manager, px4_config, mock_connector):
        """测试低电量警告"""
        device_id = await device_manager.register_device(px4_config)
        device = device_manager.get_device(device_id)
        device.connector = mock_connector
        device.status = DeviceStatus.ONLINE
        
        # 模拟低电量遥测数据
        telemetry = TelemetryData(battery_remaining=15)
        await device_manager._on_telemetry_update(device_id, telemetry)
        
        assert device.status == DeviceStatus.WARNING


class TestManagerLifecycle:
    """测试管理器生命周期"""
    
    @pytest.mark.asyncio
    async def test_start_manager(self, device_manager):
        """测试启动管理器"""
        await device_manager.start()
        
        assert device_manager._running == True
        assert len(device_manager._tasks) > 0
        
        await device_manager.stop()
    
    @pytest.mark.asyncio
    async def test_stop_manager(self, device_manager):
        """测试停止管理器"""
        await device_manager.start()
        await device_manager.stop()
        
        assert device_manager._running == False
    
    @pytest.mark.asyncio
    async def test_stop_manager_disconnects_all(self, device_manager, px4_config, mock_connector):
        """测试停止管理器断开所有设备"""
        await device_manager.start()
        
        await device_manager.register_device(px4_config)
        device = device_manager.get_device("drone_001")
        device.connector = mock_connector
        device.status = DeviceStatus.ONLINE
        device.connector.state = ConnectionState.CONNECTED
        
        await device_manager.stop()
        
        mock_connector.disconnect.assert_called()


class TestMonitorLoop:
    """测试监控循环"""
    
    @pytest.mark.asyncio
    async def test_monitor_detects_timeout(self, device_manager, px4_config, mock_connector):
        """测试监控检测超时"""
        await device_manager.start()
        
        device_id = await device_manager.register_device(px4_config)
        device = device_manager.get_device(device_id)
        device.connector = mock_connector
        device.connector.state = ConnectionState.CONNECTED
        device.status = DeviceStatus.ONLINE
        
        # 设置最后更新时间为很久以前
        device.last_seen = datetime.now() - timedelta(seconds=15)
        
        # 等待监控循环运行
        await asyncio.sleep(0.5)
        
        # 设备应该被标记为警告
        assert device.status == DeviceStatus.WARNING
        
        await device_manager.stop()
    
    @pytest.mark.asyncio
    async def test_monitor_updates_statistics(self, device_manager, px4_config):
        """测试监控更新统计"""
        await device_manager.start()
        
        await device_manager.register_device(px4_config)
        
        # 等待监控循环运行
        await asyncio.sleep(0.5)
        
        stats = device_manager.get_statistics()
        assert 'devices' in stats
        
        await device_manager.stop()


class TestDeviceCommandsExtended:
    """测试设备命令扩展"""
    
    @pytest.mark.asyncio
    async def test_send_land_command(self, device_manager, px4_config, mock_connector):
        """测试发送降落命令"""
        device_id = await device_manager.register_device(px4_config)
        device = device_manager.get_device(device_id)
        device.connector = mock_connector
        device.connector.state = ConnectionState.CONNECTED
        device.connector.land = AsyncMock(return_value=True)
        device.status = DeviceStatus.ONLINE
        
        result = await device_manager.send_command(device_id, "land")
        
        assert result == True
        device.connector.land.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_send_disarm_command(self, device_manager, px4_config, mock_connector):
        """测试发送上锁命令"""
        device_id = await device_manager.register_device(px4_config)
        device = device_manager.get_device(device_id)
        device.connector = mock_connector
        device.connector.state = ConnectionState.CONNECTED
        device.connector.disarm = AsyncMock(return_value=True)
        device.status = DeviceStatus.ONLINE
        
        result = await device_manager.send_command(device_id, "disarm")
        
        assert result == True
        device.connector.disarm.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_send_set_mode_command(self, device_manager, px4_config, mock_connector):
        """测试发送设置模式命令"""
        device_id = await device_manager.register_device(px4_config)
        device = device_manager.get_device(device_id)
        device.connector = mock_connector
        device.connector.state = ConnectionState.CONNECTED
        device.connector.set_mode = AsyncMock(return_value=True)
        device.status = DeviceStatus.ONLINE
        
        result = await device_manager.send_command(device_id, "set_mode", {"mode": "GUIDED"})
        
        assert result == True
        device.connector.set_mode.assert_called_once_with("GUIDED")
    
    @pytest.mark.asyncio
    async def test_send_goto_command_missing_params(self, device_manager, px4_config, mock_connector):
        """测试发送goto命令缺少参数"""
        device_id = await device_manager.register_device(px4_config)
        device = device_manager.get_device(device_id)
        device.connector = mock_connector
        device.connector.state = ConnectionState.CONNECTED
        device.status = DeviceStatus.ONLINE
        
        result = await device_manager.send_command(device_id, "goto")
        
        assert result == False
    
    @pytest.mark.asyncio
    async def test_send_set_mode_command_missing_mode(self, device_manager, px4_config, mock_connector):
        """测试发送设置模式命令缺少模式"""
        device_id = await device_manager.register_device(px4_config)
        device = device_manager.get_device(device_id)
        device.connector = mock_connector
        device.connector.state = ConnectionState.CONNECTED
        device.status = DeviceStatus.ONLINE
        
        result = await device_manager.send_command(device_id, "set_mode", {})
        
        assert result == False


class TestGroupOperations:
    """测试分组操作"""
    
    @pytest.mark.asyncio
    async def test_add_device_to_group_twice(self, device_manager, px4_config):
        """测试重复添加设备到分组"""
        device_id = await device_manager.register_device(px4_config)
        await device_manager.create_group("group_001", "Team Alpha")
        
        result1 = await device_manager.add_device_to_group(device_id, "group_001")
        result2 = await device_manager.add_device_to_group(device_id, "group_001")
        
        assert result1 == True
        assert result2 == True
        assert len(device_manager.groups["group_001"].device_ids) == 1
    
    @pytest.mark.asyncio
    async def test_remove_nonexistent_device_from_group(self, device_manager):
        """测试从分组移除不存在的设备"""
        await device_manager.create_group("group_001", "Team Alpha")
        
        result = await device_manager.remove_device_from_group("nonexistent", "group_001")
        
        assert result == False
    
    @pytest.mark.asyncio
    async def test_remove_device_from_nonexistent_group(self, device_manager, px4_config):
        """测试从不存在的分组移除设备"""
        device_id = await device_manager.register_device(px4_config)
        
        result = await device_manager.remove_device_from_group(device_id, "nonexistent")
        
        assert result == False
    
    @pytest.mark.asyncio
    async def test_unregister_device_removes_from_groups(self, device_manager, px4_config):
        """测试注销设备从所有分组移除"""
        device_id = await device_manager.register_device(px4_config)
        await device_manager.create_group("group_001", "Team Alpha")
        await device_manager.create_group("group_002", "Team Beta")
        
        await device_manager.add_device_to_group(device_id, "group_001")
        await device_manager.add_device_to_group(device_id, "group_002")
        
        await device_manager.unregister_device(device_id)
        
        assert device_id not in device_manager.groups["group_001"].device_ids
        assert device_id not in device_manager.groups["group_002"].device_ids


class TestDeviceProperties:
    """测试设备属性"""
    
    @pytest.mark.asyncio
    async def test_device_custom_properties(self, device_manager, px4_config):
        """测试设备自定义属性"""
        custom_props = {
            "location": "Hangar A",
            "model": "DJI M300",
            "payload": "Camera"
        }
        
        device_id = await device_manager.register_device(px4_config, custom_properties=custom_props)
        device = device_manager.get_device(device_id)
        
        assert device.custom_properties["location"] == "Hangar A"
        assert device.custom_properties["model"] == "DJI M300"
    
    @pytest.mark.asyncio
    async def test_device_statistics(self, device_manager, px4_config):
        """测试设备统计信息"""
        device_id = await device_manager.register_device(px4_config)
        device = device_manager.get_device(device_id)
        
        device.total_flight_time = 3600.0  # 1小时
        device.total_distance = 10000.0  # 10公里
        device.flight_count = 5
        
        data = device.to_dict()
        
        assert data['statistics']['total_flight_time'] == 3600.0
        assert data['statistics']['total_distance'] == 10000.0
        assert data['statistics']['flight_count'] == 5
    
    @pytest.mark.asyncio
    async def test_device_info(self, device_manager, px4_config):
        """测试设备信息"""
        device_id = await device_manager.register_device(px4_config)
        device = device_manager.get_device(device_id)
        
        device.firmware_version = "1.12.0"
        device.serial_number = "SN123456"
        device.model = "Custom Quad"
        
        data = device.to_dict()
        
        assert data['device_info']['firmware_version'] == "1.12.0"
        assert data['device_info']['serial_number'] == "SN123456"
        assert data['device_info']['model'] == "Custom Quad"


class TestMultipleDeviceTypes:
    """测试多种设备类型"""
    
    @pytest.mark.asyncio
    async def test_mixed_device_types(self, device_manager):
        """测试混合设备类型"""
        configs = [
            DroneConfig(f"px4_{i}", DroneType.PX4, f"udp:127.0.0.1:{14550+i}")
            for i in range(3)
        ] + [
            DroneConfig(f"ardupilot_{i}", DroneType.ARDUPILOT, f"tcp:127.0.0.1:{5760+i}")
            for i in range(2)
        ]
        
        for config in configs:
            await device_manager.register_device(config)
        
        px4_devices = device_manager.get_devices_by_type(DroneType.PX4)
        ardupilot_devices = device_manager.get_devices_by_type(DroneType.ARDUPILOT)
        
        assert len(px4_devices) == 3
        assert len(ardupilot_devices) == 2


class TestErrorHandling:
    """测试错误处理"""
    
    @pytest.mark.asyncio
    async def test_connect_device_exception(self, device_manager, px4_config):
        """测试连接设备异常"""
        device_id = await device_manager.register_device(px4_config)
        device = device_manager.get_device(device_id)
        
        mock_connector = MagicMock()
        mock_connector.connect = AsyncMock(side_effect=Exception("Connection failed"))
        device.connector = mock_connector
        
        result = await device_manager.connect_device(device_id)
        
        assert result == False
        assert device.status == DeviceStatus.ERROR
    
    @pytest.mark.asyncio
    async def test_disconnect_device_exception(self, device_manager, px4_config):
        """测试断开设备异常"""
        device_id = await device_manager.register_device(px4_config)
        device = device_manager.get_device(device_id)
        
        mock_connector = MagicMock()
        mock_connector.disconnect = AsyncMock(side_effect=Exception("Disconnect failed"))
        mock_connector.state = ConnectionState.CONNECTED
        device.connector = mock_connector
        device.status = DeviceStatus.ONLINE
        
        result = await device_manager.disconnect_device(device_id)
        
        assert result == False
    
    @pytest.mark.asyncio
    async def test_send_command_exception(self, device_manager, px4_config):
        """测试发送命令异常"""
        device_id = await device_manager.register_device(px4_config)
        device = device_manager.get_device(device_id)
        
        mock_connector = MagicMock()
        mock_connector.arm = AsyncMock(side_effect=Exception("Command failed"))
        mock_connector.state = ConnectionState.CONNECTED
        device.connector = mock_connector
        device.status = DeviceStatus.ONLINE
        
        result = await device_manager.send_command(device_id, "arm")
        
        assert result == False


class TestDeviceStatusEnum:
    """测试设备状态枚举"""
    
    def test_device_status_values(self):
        """测试设备状态枚举值"""
        assert DeviceStatus.OFFLINE.value == "offline"
        assert DeviceStatus.ONLINE.value == "online"
        assert DeviceStatus.FLYING.value == "flying"
        assert DeviceStatus.WARNING.value == "warning"
        assert DeviceStatus.ERROR.value == "error"
        assert DeviceStatus.MAINTENANCE.value == "maintenance"


class TestExportImport:
    """测试导出导入"""
    
    @pytest.mark.asyncio
    async def test_export_empty_devices(self, device_manager):
        """测试导出空设备列表"""
        exported = device_manager.export_devices()
        
        assert exported == []
    
    @pytest.mark.asyncio
    async def test_export_empty_groups(self, device_manager):
        """测试导出空分组列表"""
        exported = device_manager.export_groups()
        
        assert exported == []


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
