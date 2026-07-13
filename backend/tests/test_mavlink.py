"""
MAVLink连接器单元测试
测试连接建立、心跳包、遥测数据、命令发送和异常处理
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock, patch
from datetime import datetime

import sys
sys.path.insert(0, '/home/dudu/.nanobot/workspace/skymaster-drone-platform/backend')

from core.mavlink.connector import (
    MAVLinkConnector,
    PX4Connector,
    ArduPilotConnector,
    DJIConnector,
    ConnectorFactory,
    DroneConfig,
    DroneType,
    ConnectionState,
    TelemetryData
)


# Fixtures
@pytest.fixture
def px4_config():
    """PX4无人机配置"""
    return DroneConfig(
        drone_id="drone_001",
        drone_type=DroneType.PX4,
        connection_string="udp:127.0.0.1:14550",
        baud_rate=57600,
        timeout=5.0,
        heartbeat_interval=1.0
    )


@pytest.fixture
def ardupilot_config():
    """ArduPilot无人机配置"""
    return DroneConfig(
        drone_id="drone_002",
        drone_type=DroneType.ARDUPILOT,
        connection_string="tcp:127.0.0.1:5760",
        timeout=5.0
    )


@pytest.fixture
def mock_mavlink_connection():
    """模拟MAVLink连接"""
    mock_conn = MagicMock()
    mock_conn.target_system = 1
    mock_conn.target_component = 1
    mock_conn.wait_heartbeat = MagicMock(return_value=True)
    mock_conn.recv_match = MagicMock(return_value=None)
    mock_conn.close = MagicMock()
    return mock_conn


class TestDroneConfig:
    """测试无人机配置"""
    
    def test_config_creation(self):
        """测试配置创建"""
        config = DroneConfig(
            drone_id="test_001",
            drone_type=DroneType.PX4,
            connection_string="udp:127.0.0.1:14550"
        )
        
        assert config.drone_id == "test_001"
        assert config.drone_type == DroneType.PX4
        assert config.connection_string == "udp:127.0.0.1:14550"
        assert config.baud_rate == 57600
        assert config.timeout == 5.0
        assert config.retry_count == 3
    
    def test_config_custom_values(self):
        """测试自定义配置值"""
        config = DroneConfig(
            drone_id="test_002",
            drone_type=DroneType.ARDUPILOT,
            connection_string="serial:/dev/ttyUSB0",
            baud_rate=115200,
            timeout=10.0,
            heartbeat_interval=2.0
        )
        
        assert config.baud_rate == 115200
        assert config.timeout == 10.0
        assert config.heartbeat_interval == 2.0


class TestTelemetryData:
    """测试遥测数据"""
    
    def test_telemetry_creation(self):
        """测试遥测数据创建"""
        telemetry = TelemetryData()
        
        assert telemetry.latitude == 0.0
        assert telemetry.longitude == 0.0
        assert telemetry.altitude == 0.0
        assert telemetry.armed == False
        assert telemetry.flight_mode == "UNKNOWN"
    
    def test_telemetry_to_dict(self):
        """测试遥测数据转换为字典"""
        telemetry = TelemetryData(
            latitude=39.9042,
            longitude=116.4074,
            altitude=100.0,
            battery_remaining=85
        )
        
        data = telemetry.to_dict()
        
        assert data['position']['latitude'] == 39.9042
        assert data['position']['longitude'] == 116.4074
        assert data['battery']['remaining'] == 85
        assert 'timestamp' in data


class TestPX4Connector:
    """测试PX4连接器"""
    
    def test_connector_creation(self, px4_config):
        """测试PX4连接器创建"""
        connector = PX4Connector(px4_config)
        
        assert connector.config.drone_id == "drone_001"
        assert connector.state == ConnectionState.DISCONNECTED
        assert connector.telemetry is not None
    
    @pytest.mark.asyncio
    async def test_connect_success(self, px4_config, mock_mavlink_connection):
        """测试成功连接"""
        with patch('core.mavlink.connector.MAVLINK_AVAILABLE', True):
            with patch('core.mavlink.connector.mavutil.mavlink_connection', return_value=mock_mavlink_connection):
                connector = PX4Connector(px4_config)
                result = await connector.connect()
                
                assert result == True
                assert connector.state == ConnectionState.CONNECTED
                assert connector.target_system == 1
    
    @pytest.mark.asyncio
    async def test_connect_no_heartbeat(self, px4_config):
        """测试连接失败 - 无心跳"""
        mock_conn = MagicMock()
        mock_conn.wait_heartbeat = MagicMock(return_value=None)
        
        with patch('core.mavlink.connector.MAVLINK_AVAILABLE', True):
            with patch('core.mavlink.connector.mavutil.mavlink_connection', return_value=mock_conn):
                connector = PX4Connector(px4_config)
                result = await connector.connect()
                
                assert result == False
                assert connector.state == ConnectionState.ERROR
    
    @pytest.mark.asyncio
    async def test_connect_no_pymavlink(self, px4_config):
        """测试连接失败 - 缺少pymavlink"""
        with patch('core.mavlink.connector.MAVLINK_AVAILABLE', False):
            connector = PX4Connector(px4_config)
            result = await connector.connect()
            
            assert result == False
    
    @pytest.mark.asyncio
    async def test_disconnect(self, px4_config, mock_mavlink_connection):
        """测试断开连接"""
        with patch('core.mavlink.connector.MAVLINK_AVAILABLE', True):
            with patch('core.mavlink.connector.mavutil.mavlink_connection', return_value=mock_mavlink_connection):
                connector = PX4Connector(px4_config)
                await connector.connect()
                result = await connector.disconnect()
                
                assert result == True
                assert connector.state == ConnectionState.DISCONNECTED
                mock_mavlink_connection.close.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_send_command_success(self, px4_config, mock_mavlink_connection):
        """测试发送命令成功"""
        with patch('core.mavlink.connector.MAVLINK_AVAILABLE', True):
            with patch('core.mavlink.connector.mavutil.mavlink_connection', return_value=mock_mavlink_connection):
                with patch('core.mavlink.connector.mavlink') as mock_mavlink:
                    mock_mavlink.MAV_CMD_COMPONENT_ARM_DISARM = 400
                    
                    connector = PX4Connector(px4_config)
                    await connector.connect()
                    
                    result = await connector.send_command(400, [1.0, 0, 0, 0, 0, 0, 0])
                    
                    assert result == True
                    mock_mavlink_connection.mav.command_long_send.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_send_command_not_connected(self, px4_config):
        """测试未连接时发送命令"""
        connector = PX4Connector(px4_config)
        result = await connector.send_command(400)
        
        assert result == False
    
    @pytest.mark.asyncio
    async def test_arm_command(self, px4_config, mock_mavlink_connection):
        """测试解锁命令"""
        with patch('core.mavlink.connector.MAVLINK_AVAILABLE', True):
            with patch('core.mavlink.connector.mavutil.mavlink_connection', return_value=mock_mavlink_connection):
                with patch('core.mavlink.connector.mavlink') as mock_mavlink:
                    mock_mavlink.MAV_CMD_COMPONENT_ARM_DISARM = 400
                    
                    connector = PX4Connector(px4_config)
                    await connector.connect()
                    result = await connector.arm()
                    
                    assert result == True
    
    @pytest.mark.asyncio
    async def test_takeoff_command(self, px4_config, mock_mavlink_connection):
        """测试起飞命令"""
        with patch('core.mavlink.connector.MAVLINK_AVAILABLE', True):
            with patch('core.mavlink.connector.mavutil.mavlink_connection', return_value=mock_mavlink_connection):
                with patch('core.mavlink.connector.mavlink') as mock_mavlink:
                    mock_mavlink.MAV_CMD_NAV_TAKEOFF = 22
                    
                    connector = PX4Connector(px4_config)
                    await connector.connect()
                    result = await connector.takeoff(50.0)
                    
                    assert result == True
    
    def test_telemetry_callback(self, px4_config):
        """测试遥测回调"""
        connector = PX4Connector(px4_config)
        
        callback = Mock()
        connector.add_telemetry_callback(callback)
        
        assert callback in connector.telemetry_callbacks
    
    @pytest.mark.asyncio
    async def test_handle_heartbeat_message(self, px4_config, mock_mavlink_connection):
        """测试处理心跳消息"""
        with patch('core.mavlink.connector.MAVLINK_AVAILABLE', True):
            with patch('core.mavlink.connector.mavutil.mavlink_connection', return_value=mock_mavlink_connection):
                with patch('core.mavlink.connector.mavlink') as mock_mavlink:
                    mock_mavlink.MAV_MODE_FLAG_SAFETY_ARMED = 128
                    mock_mavlink.MAV_AUTOPILOT_PX4 = 12
                    
                    connector = PX4Connector(px4_config)
                    await connector.connect()
                    
                    # 模拟心跳消息
                    heartbeat_msg = MagicMock()
                    heartbeat_msg.get_type.return_value = 'HEARTBEAT'
                    heartbeat_msg.base_mode = 128  # ARMED
                    heartbeat_msg.custom_mode = 2  # OFFBOARD
                    heartbeat_msg.system_status = 4
                    heartbeat_msg.autopilot = 12
                    
                    await connector._handle_message(heartbeat_msg)
                    
                    assert connector.telemetry.armed == True
                    assert connector.telemetry.flight_mode == 'OFFBOARD'


class TestArduPilotConnector:
    """测试ArduPilot连接器"""
    
    def test_connector_creation(self, ardupilot_config):
        """测试ArduPilot连接器创建"""
        connector = ArduPilotConnector(ardupilot_config)
        
        assert connector.config.drone_id == "drone_002"
        assert connector.config.drone_type == DroneType.ARDUPILOT
    
    @pytest.mark.asyncio
    async def test_set_mode_ardupilot(self, ardupilot_config, mock_mavlink_connection):
        """测试设置ArduPilot飞行模式"""
        with patch('core.mavlink.connector.MAVLINK_AVAILABLE', True):
            with patch('core.mavlink.connector.mavutil.mavlink_connection', return_value=mock_mavlink_connection):
                with patch('core.mavlink.connector.mavlink') as mock_mavlink:
                    mock_mavlink.MAV_CMD_DO_SET_MODE = 176
                    mock_mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED = 1
                    
                    connector = ArduPilotConnector(ardupilot_config)
                    await connector.connect()
                    
                    result = await connector.set_mode('GUIDED')
                    
                    assert result == True
    
    def test_ardupilot_mode_mapping(self, ardupilot_config):
        """测试ArduPilot模式映射"""
        connector = ArduPilotConnector(ardupilot_config)
        
        mode = connector._ardupilot_mode_from_custom_mode(4)
        assert mode == 'GUIDED'
        
        mode = connector._ardupilot_mode_from_custom_mode(99)
        assert mode == 'UNKNOWN'


class TestDJIConnector:
    """测试DJI连接器"""
    
    def test_connector_creation(self):
        """测试DJI连接器创建"""
        config = DroneConfig(
            drone_id="dji_001",
            drone_type=DroneType.DJI,
            connection_string="dji_sdk://192.168.1.100"
        )
        
        connector = DJIConnector(config)
        
        assert connector.config.drone_id == "dji_001"
        assert connector.config.drone_type == DroneType.DJI
    
    @pytest.mark.asyncio
    async def test_connect_not_implemented(self):
        """测试DJI连接未实现"""
        config = DroneConfig(
            drone_id="dji_001",
            drone_type=DroneType.DJI,
            connection_string="dji_sdk://192.168.1.100"
        )
        
        connector = DJIConnector(config)
        result = await connector.connect()
        
        assert result == False


class TestConnectorFactory:
    """测试连接器工厂"""
    
    def test_create_px4_connector(self):
        """测试创建PX4连接器"""
        config = DroneConfig(
            drone_id="factory_001",
            drone_type=DroneType.PX4,
            connection_string="udp:127.0.0.1:14550"
        )
        
        connector = ConnectorFactory.create_connector(config)
        
        assert isinstance(connector, PX4Connector)
    
    def test_create_ardupilot_connector(self):
        """测试创建ArduPilot连接器"""
        config = DroneConfig(
            drone_id="factory_002",
            drone_type=DroneType.ARDUPILOT,
            connection_string="tcp:127.0.0.1:5760"
        )
        
        connector = ConnectorFactory.create_connector(config)
        
        assert isinstance(connector, ArduPilotConnector)
    
    def test_create_dji_connector(self):
        """测试创建DJI连接器"""
        config = DroneConfig(
            drone_id="factory_003",
            drone_type=DroneType.DJI,
            connection_string="dji_sdk://192.168.1.100"
        )
        
        connector = ConnectorFactory.create_connector(config)
        
        assert isinstance(connector, DJIConnector)
    
    def test_create_generic_connector(self):
        """测试创建通用连接器（默认PX4）"""
        config = DroneConfig(
            drone_id="factory_004",
            drone_type=DroneType.GENERIC,
            connection_string="udp:127.0.0.1:14551"
        )
        
        connector = ConnectorFactory.create_connector(config)
        
        assert isinstance(connector, PX4Connector)


class TestExceptionHandling:
    """测试异常处理"""
    
    @pytest.mark.asyncio
    async def test_connect_exception(self, px4_config):
        """测试连接异常处理"""
        with patch('core.mavlink.connector.MAVLINK_AVAILABLE', True):
            with patch('core.mavlink.connector.mavutil.mavlink_connection', side_effect=Exception("Connection error")):
                connector = PX4Connector(px4_config)
                result = await connector.connect()
                
                assert result == False
                assert connector.state == ConnectionState.ERROR
    
    @pytest.mark.asyncio
    async def test_send_command_exception(self, px4_config, mock_mavlink_connection):
        """测试发送命令异常处理"""
        mock_mavlink_connection.mav.command_long_send = MagicMock(side_effect=Exception("Send error"))
        
        with patch('core.mavlink.connector.MAVLINK_AVAILABLE', True):
            with patch('core.mavlink.connector.mavutil.mavlink_connection', return_value=mock_mavlink_connection):
                connector = PX4Connector(px4_config)
                await connector.connect()
                
                result = await connector.send_command(400)
                
                assert result == False
    
    @pytest.mark.asyncio
    async def test_disconnect_exception(self, px4_config, mock_mavlink_connection):
        """测试断开连接异常处理"""
        mock_mavlink_connection.close = MagicMock(side_effect=Exception("Close error"))
        
        with patch('core.mavlink.connector.MAVLINK_AVAILABLE', True):
            with patch('core.mavlink.connector.mavutil.mavlink_connection', return_value=mock_mavlink_connection):
                connector = PX4Connector(px4_config)
                await connector.connect()
                
                result = await connector.disconnect()
                
                # 断开应该返回True，即使有异常
                assert result == True


class TestTelemetryUpdate:
    """测试遥测更新"""
    
    @pytest.mark.asyncio
    async def test_position_update(self, px4_config, mock_mavlink_connection):
        """测试位置更新"""
        with patch('core.mavlink.connector.MAVLINK_AVAILABLE', True):
            with patch('core.mavlink.connector.mavutil.mavlink_connection', return_value=mock_mavlink_connection):
                connector = PX4Connector(px4_config)
                await connector.connect()
                
                # 模拟位置消息
                pos_msg = MagicMock()
                pos_msg.get_type.return_value = 'GLOBAL_POSITION_INT'
                pos_msg.lat = 399042000  # 39.9042度
                pos_msg.lon = 1164074000  # 116.4074度
                pos_msg.alt = 100000  # 100米
                pos_msg.relative_alt = 50000  # 50米
                pos_msg.vx = 100  # 1 m/s
                pos_msg.vy = 100  # 1 m/s
                pos_msg.hdg = 9000  # 90度
                
                await connector._handle_message(pos_msg)
                
                assert abs(connector.telemetry.latitude - 39.9042) < 0.0001
                assert abs(connector.telemetry.longitude - 116.4074) < 0.0001
    
    @pytest.mark.asyncio
    async def test_battery_update(self, px4_config, mock_mavlink_connection):
        """测试电池状态更新"""
        with patch('core.mavlink.connector.MAVLINK_AVAILABLE', True):
            with patch('core.mavlink.connector.mavutil.mavlink_connection', return_value=mock_mavlink_connection):
                connector = PX4Connector(px4_config)
                await connector.connect()
                
                # 模拟系统状态消息
                sys_msg = MagicMock()
                sys_msg.get_type.return_value = 'SYS_STATUS'
                sys_msg.voltage_battery = 16000  # 16V
                sys_msg.current_battery = 1000  # 10A
                sys_msg.battery_remaining = 85
                
                await connector._handle_message(sys_msg)
                
                assert connector.telemetry.battery_voltage == 16.0
                assert connector.telemetry.battery_remaining == 85


class TestAsyncOperations:
    """测试异步操作"""
    
    @pytest.mark.asyncio
    async def test_receive_loop_handles_exception(self, px4_config, mock_mavlink_connection):
        """测试接收循环异常处理"""
        with patch('core.mavlink.connector.MAVLINK_AVAILABLE', True):
            with patch('core.mavlink.connector.mavutil.mavlink_connection', return_value=mock_mavlink_connection):
                connector = PX4Connector(px4_config)
                await connector.connect()
                
                # 模拟接收循环中的异常
                mock_mavlink_connection.recv_match = MagicMock(side_effect=Exception("Receive error"))
                
                # 运行一次接收循环迭代
                connector._running = True
                try:
                    await asyncio.wait_for(connector._receive_loop(), timeout=0.1)
                except asyncio.TimeoutError:
                    pass
                
                # 连接器应该仍然在运行
                assert connector._running
    
    @pytest.mark.asyncio
    async def test_heartbeat_loop_sends_heartbeat(self, px4_config, mock_mavlink_connection):
        """测试心跳循环发送心跳"""
        with patch('core.mavlink.connector.MAVLINK_AVAILABLE', True):
            with patch('core.mavlink.connector.mavutil.mavlink_connection', return_value=mock_mavlink_connection):
                with patch('core.mavlink.connector.mavlink') as mock_mavlink:
                    mock_mavlink.MAV_TYPE_GCS = 6
                    mock_mavlink.MAV_AUTOPILOT_INVALID = 8
                    
                    connector = PX4Connector(px4_config)
                    await connector.connect()
                    
                    # 运行一次心跳循环迭代
                    connector._running = True
                    await connector._heartbeat_loop()
                    
                    # 应该发送了心跳
                    mock_mavlink_connection.mav.heartbeat_send.assert_called()
    
    @pytest.mark.asyncio
    async def test_concurrent_telemetry_callbacks(self, px4_config, mock_mavlink_connection):
        """测试并发遥测回调"""
        with patch('core.mavlink.connector.MAVLINK_AVAILABLE', True):
            with patch('core.mavlink.connector.mavutil.mavlink_connection', return_value=mock_mavlink_connection):
                connector = PX4Connector(px4_config)
                await connector.connect()
                
                callbacks = [AsyncMock() for _ in range(5)]
                for cb in callbacks:
                    connector.add_telemetry_callback(cb)
                
                # 触发遥测更新
                await connector._notify_telemetry_update()
                
                # 所有回调应该被调用
                for cb in callbacks:
                    cb.assert_called_once()


class TestAttitudeMessage:
    """测试姿态消息处理"""
    
    @pytest.mark.asyncio
    async def test_attitude_update(self, px4_config, mock_mavlink_connection):
        """测试姿态更新"""
        with patch('core.mavlink.connector.MAVLINK_AVAILABLE', True):
            with patch('core.mavlink.connector.mavutil.mavlink_connection', return_value=mock_mavlink_connection):
                connector = PX4Connector(px4_config)
                await connector.connect()
                
                # 模拟姿态消息
                attitude_msg = MagicMock()
                attitude_msg.get_type.return_value = 'ATTITUDE'
                attitude_msg.roll = 0.1  # 弧度
                attitude_msg.pitch = 0.2
                attitude_msg.yaw = 0.3
                
                await connector._handle_message(attitude_msg)
                
                # 检查转换为度
                assert abs(connector.telemetry.roll - 0.1 * 57.2958) < 0.1
                assert abs(connector.telemetry.pitch - 0.2 * 57.2958) < 0.1
                assert abs(connector.telemetry.yaw - 0.3 * 57.2958) < 0.1


class TestGPSMessage:
    """测试GPS消息处理"""
    
    @pytest.mark.asyncio
    async def test_gps_raw_update(self, px4_config, mock_mavlink_connection):
        """测试GPS原始数据更新"""
        with patch('core.mavlink.connector.MAVLINK_AVAILABLE', True):
            with patch('core.mavlink.connector.mavutil.mavlink_connection', return_value=mock_mavlink_connection):
                connector = PX4Connector(px4_config)
                await connector.connect()
                
                # 模拟GPS消息
                gps_msg = MagicMock()
                gps_msg.get_type.return_value = 'GPS_RAW_INT'
                gps_msg.satellites_visible = 12
                gps_msg.fix_type = 3
                
                await connector._handle_message(gps_msg)
                
                assert connector.telemetry.satellites == 12
                assert connector.telemetry.gps_fix == 3


class TestRadioStatus:
    """测试无线电状态"""
    
    @pytest.mark.asyncio
    async def test_radio_status_update(self, px4_config, mock_mavlink_connection):
        """测试无线电状态更新"""
        with patch('core.mavlink.connector.MAVLINK_AVAILABLE', True):
            with patch('core.mavlink.connector.mavutil.mavlink_connection', return_value=mock_mavlink_connection):
                connector = PX4Connector(px4_config)
                await connector.connect()
                
                # 模拟无线电状态消息
                radio_msg = MagicMock()
                radio_msg.get_type.return_value = 'RADIO_STATUS'
                radio_msg.rssi = 80
                radio_msg.remrssi = 90
                
                await connector._handle_message(radio_msg)
                
                assert connector.telemetry.rssi == 80
                assert connector.telemetry.snr == 90


class TestModeSetting:
    """测试飞行模式设置"""
    
    @pytest.mark.asyncio
    async def test_set_px4_mode_offboard(self, px4_config, mock_mavlink_connection):
        """测试设置PX4 OFFBOARD模式"""
        with patch('core.mavlink.connector.MAVLINK_AVAILABLE', True):
            with patch('core.mavlink.connector.mavutil.mavlink_connection', return_value=mock_mavlink_connection):
                with patch('core.mavlink.connector.mavlink') as mock_mavlink:
                    mock_mavlink.MAV_CMD_DO_SET_MODE = 176
                    mock_mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED = 1
                    
                    connector = PX4Connector(px4_config)
                    await connector.connect()
                    
                    result = await connector.set_mode('OFFBOARD')
                    
                    assert result == True
    
    @pytest.mark.asyncio
    async def test_set_px4_mode_unknown(self, px4_config, mock_mavlink_connection):
        """测试设置未知PX4模式"""
        with patch('core.mavlink.connector.MAVLINK_AVAILABLE', True):
            with patch('core.mavlink.connector.mavutil.mavlink_connection', return_value=mock_mavlink_connection):
                connector = PX4Connector(px4_config)
                await connector.connect()
                
                result = await connector.set_mode('UNKNOWN_MODE')
                
                assert result == False
    
    @pytest.mark.asyncio
    async def test_set_ardupilot_mode_auto(self, ardupilot_config, mock_mavlink_connection):
        """测试设置ArduPilot AUTO模式"""
        with patch('core.mavlink.connector.MAVLINK_AVAILABLE', True):
            with patch('core.mavlink.connector.mavutil.mavlink_connection', return_value=mock_mavlink_connection):
                with patch('core.mavlink.connector.mavlink') as mock_mavlink:
                    mock_mavlink.MAV_CMD_DO_SET_MODE = 176
                    mock_mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED = 1
                    
                    connector = ArduPilotConnector(ardupilot_config)
                    await connector.connect()
                    
                    result = await connector.set_mode('AUTO')
                    
                    assert result == True


class TestNavigationCommands:
    """测试导航命令"""
    
    @pytest.mark.asyncio
    async def test_goto_command(self, px4_config, mock_mavlink_connection):
        """测试飞往命令"""
        with patch('core.mavlink.connector.MAVLINK_AVAILABLE', True):
            with patch('core.mavlink.connector.mavutil.mavlink_connection', return_value=mock_mavlink_connection):
                with patch('core.mavlink.connector.mavlink') as mock_mavlink:
                    mock_mavlink.MAV_CMD_NAV_WAYPOINT = 16
                    
                    connector = PX4Connector(px4_config)
                    await connector.connect()
                    
                    result = await connector.goto(39.9042, 116.4074, 100.0)
                    
                    assert result == True
    
    @pytest.mark.asyncio
    async def test_land_command(self, px4_config, mock_mavlink_connection):
        """测试降落命令"""
        with patch('core.mavlink.connector.MAVLINK_AVAILABLE', True):
            with patch('core.mavlink.connector.mavutil.mavlink_connection', return_value=mock_mavlink_connection):
                with patch('core.mavlink.connector.mavlink') as mock_mavlink:
                    mock_mavlink.MAV_CMD_NAV_LAND = 21
                    
                    connector = PX4Connector(px4_config)
                    await connector.connect()
                    
                    result = await connector.land()
                    
                    assert result == True


class TestConnectionTypes:
    """测试不同连接类型"""
    
    @pytest.mark.asyncio
    async def test_serial_connection(self):
        """测试串口连接"""
        config = DroneConfig(
            drone_id="serial_001",
            drone_type=DroneType.PX4,
            connection_string="serial:/dev/ttyUSB0",
            baud_rate=115200
        )
        
        mock_conn = MagicMock()
        mock_conn.wait_heartbeat = MagicMock(return_value=True)
        
        with patch('core.mavlink.connector.MAVLINK_AVAILABLE', True):
            with patch('core.mavlink.connector.mavutil.mavlink_connection', return_value=mock_conn) as mock_mavlink_conn:
                connector = PX4Connector(config)
                await connector.connect()
                
                # 检查串口连接参数
                mock_mavlink_conn.assert_called()
    
    @pytest.mark.asyncio
    async def test_tcp_connection(self):
        """测试TCP连接"""
        config = DroneConfig(
            drone_id="tcp_001",
            drone_type=DroneType.PX4,
            connection_string="tcp:127.0.0.1:5760"
        )
        
        mock_conn = MagicMock()
        mock_conn.wait_heartbeat = MagicMock(return_value=True)
        
        with patch('core.mavlink.connector.MAVLINK_AVAILABLE', True):
            with patch('core.mavlink.connector.mavutil.mavlink_connection', return_value=mock_conn):
                connector = PX4Connector(config)
                result = await connector.connect()
                
                assert result == True
    
    @pytest.mark.asyncio
    async def test_udp_connection(self):
        """测试UDP连接"""
        config = DroneConfig(
            drone_id="udp_001",
            drone_type=DroneType.PX4,
            connection_string="udp:127.0.0.1:14550"
        )
        
        mock_conn = MagicMock()
        mock_conn.wait_heartbeat = MagicMock(return_value=True)
        
        with patch('core.mavlink.connector.MAVLINK_AVAILABLE', True):
            with patch('core.mavlink.connector.mavutil.mavlink_connection', return_value=mock_conn):
                connector = PX4Connector(config)
                result = await connector.connect()
                
                assert result == True


class TestCommandParameters:
    """测试命令参数"""
    
    @pytest.mark.asyncio
    async def test_send_command_with_all_params(self, px4_config, mock_mavlink_connection):
        """测试发送带所有参数的命令"""
        with patch('core.mavlink.connector.MAVLINK_AVAILABLE', True):
            with patch('core.mavlink.connector.mavutil.mavlink_connection', return_value=mock_mavlink_connection):
                connector = PX4Connector(px4_config)
                await connector.connect()
                
                params = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
                result = await connector.send_command(400, params)
                
                assert result == True
                mock_mavlink_connection.mav.command_long_send.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_send_command_with_partial_params(self, px4_config, mock_mavlink_connection):
        """测试发送带部分参数的命令"""
        with patch('core.mavlink.connector.MAVLINK_AVAILABLE', True):
            with patch('core.mavlink.connector.mavutil.mavlink_connection', return_value=mock_mavlink_connection):
                connector = PX4Connector(px4_config)
                await connector.connect()
                
                params = [1.0, 2.0]
                result = await connector.send_command(400, params)
                
                assert result == True
    
    @pytest.mark.asyncio
    async def test_send_command_no_params(self, px4_config, mock_mavlink_connection):
        """测试发送无参数的命令"""
        with patch('core.mavlink.connector.MAVLINK_AVAILABLE', True):
            with patch('core.mavlink.connector.mavutil.mavlink_connection', return_value=mock_mavlink_connection):
                connector = PX4Connector(px4_config)
                await connector.connect()
                
                result = await connector.send_command(400)
                
                assert result == True


class TestDisarm:
    """测试上锁命令"""
    
    @pytest.mark.asyncio
    async def test_disarm_command(self, px4_config, mock_mavlink_connection):
        """测试上锁命令"""
        with patch('core.mavlink.connector.MAVLINK_AVAILABLE', True):
            with patch('core.mavlink.connector.mavutil.mavlink_connection', return_value=mock_mavlink_connection):
                with patch('core.mavlink.connector.mavlink') as mock_mavlink:
                    mock_mavlink.MAV_CMD_COMPONENT_ARM_DISARM = 400
                    
                    connector = PX4Connector(px4_config)
                    await connector.connect()
                    result = await connector.disarm()
                    
                    assert result == True


class TestDroneTypeEnum:
    """测试无人机类型枚举"""
    
    def test_drone_type_values(self):
        """测试无人机类型枚举值"""
        assert DroneType.PX4.value == "px4"
        assert DroneType.ARDUPILOT.value == "ardupilot"
        assert DroneType.DJI.value == "dji"
        assert DroneType.GENERIC.value == "generic"


class TestConnectionStateEnum:
    """测试连接状态枚举"""
    
    def test_connection_state_values(self):
        """测试连接状态枚举值"""
        assert ConnectionState.DISCONNECTED.value == "disconnected"
        assert ConnectionState.CONNECTING.value == "connecting"
        assert ConnectionState.CONNECTED.value == "connected"
        assert ConnectionState.ERROR.value == "error"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
