"""
MAVLink Connector - 统一的MAVLink协议连接器
支持PX4、ArduPilot、DJI等飞控系统
"""

import asyncio
import logging
from typing import Optional, Dict, List, Callable, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json
import struct
from abc import ABC, abstractmethod

# MAVLink protocol imports
try:
    from pymavlink import mavutil, mavlink
    MAVLINK_AVAILABLE = True
except ImportError:
    MAVLINK_AVAILABLE = False
    logging.warning("pymavlink not available, using mock implementation")

logger = logging.getLogger(__name__)


class DroneType(Enum):
    """无人机类型"""
    PX4 = "px4"
    ARDUPILOT = "ardupilot"
    DJI = "dji"
    GENERIC = "generic"


class ConnectionState(Enum):
    """连接状态"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class TelemetryData:
    """遥测数据"""
    timestamp: datetime = field(default_factory=datetime.now)
    
    # 位置信息
    latitude: float = 0.0
    longitude: float = 0.0
    altitude: float = 0.0  # 海拔高度（米）
    relative_altitude: float = 0.0  # 相对高度（米）
    
    # 速度信息
    ground_speed: float = 0.0  # 地速（m/s）
    air_speed: float = 0.0  # 空速（m/s）
    vertical_speed: float = 0.0  # 垂直速度（m/s）
    
    # 姿态信息
    roll: float = 0.0  # 横滚角（度）
    pitch: float = 0.0  # 俯仰角（度）
    yaw: float = 0.0  # 偏航角（度）
    
    # 电池信息
    battery_voltage: float = 0.0  # 电压（V）
    battery_current: float = 0.0  # 电流（A）
    battery_remaining: int = 0  # 剩余电量（%）
    
    # 信号强度
    rssi: int = 0  # 信号强度
    snr: float = 0.0  # 信噪比
    
    # 卫星信息
    satellites: int = 0  # 卫星数量
    gps_fix: int = 0  # GPS定位类型
    
    # 飞行模式
    flight_mode: str = "UNKNOWN"
    armed: bool = False  # 是否解锁
    system_status: int = 0  # 系统状态
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'timestamp': self.timestamp.isoformat(),
            'position': {
                'latitude': self.latitude,
                'longitude': self.longitude,
                'altitude': self.altitude,
                'relative_altitude': self.relative_altitude
            },
            'speed': {
                'ground_speed': self.ground_speed,
                'air_speed': self.air_speed,
                'vertical_speed': self.vertical_speed
            },
            'attitude': {
                'roll': self.roll,
                'pitch': self.pitch,
                'yaw': self.yaw
            },
            'battery': {
                'voltage': self.battery_voltage,
                'current': self.battery_current,
                'remaining': self.battery_remaining
            },
            'signal': {
                'rssi': self.rssi,
                'snr': self.snr
            },
            'gps': {
                'satellites': self.satellites,
                'fix': self.gps_fix
            },
            'status': {
                'flight_mode': self.flight_mode,
                'armed': self.armed,
                'system_status': self.system_status
            }
        }


@dataclass
class DroneConfig:
    """无人机配置"""
    drone_id: str
    drone_type: DroneType
    connection_string: str  # 连接字符串（串口/UDP/TCP）
    baud_rate: int = 57600  # 波特率（串口）
    timeout: float = 5.0  # 超时时间
    retry_count: int = 3  # 重试次数
    heartbeat_interval: float = 1.0  # 心跳间隔
    telemetry_interval: float = 0.1  # 遥测数据更新间隔


class MAVLinkConnector(ABC):
    """MAVLink连接器抽象基类"""
    
    def __init__(self, config: DroneConfig):
        self.config = config
        self.state = ConnectionState.DISCONNECTED
        self.telemetry = TelemetryData()
        self.telemetry_callbacks: List[Callable] = []
        self.message_handlers: Dict[int, Callable] = {}
        self._running = False
        self._tasks: List[asyncio.Task] = []
        
    @abstractmethod
    async def connect(self) -> bool:
        """连接到无人机"""
        pass
    
    @abstractmethod
    async def disconnect(self) -> bool:
        """断开连接"""
        pass
    
    @abstractmethod
    async def send_command(self, command: int, params: List[float] = None) -> bool:
        """发送命令"""
        pass
    
    def add_telemetry_callback(self, callback: Callable):
        """添加遥测数据回调"""
        self.telemetry_callbacks.append(callback)
    
    async def _notify_telemetry_update(self):
        """通知遥测数据更新"""
        for callback in self.telemetry_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(self.config.drone_id, self.telemetry)
                else:
                    callback(self.config.drone_id, self.telemetry)
            except Exception as e:
                logger.error(f"Error in telemetry callback: {e}")


class PX4Connector(MAVLinkConnector):
    """PX4飞控连接器"""
    
    def __init__(self, config: DroneConfig):
        super().__init__(config)
        self.mavlink_connection: Optional[mavutil.mavlink_connection] = None
        self.target_system = 1
        self.target_component = 1
        
    async def connect(self) -> bool:
        """连接到PX4飞控"""
        if not MAVLINK_AVAILABLE:
            logger.error("pymavlink not available")
            return False
            
        try:
            self.state = ConnectionState.CONNECTING
            
            # 创建MAVLink连接
            if self.config.connection_string.startswith('serial:'):
                device = self.config.connection_string.replace('serial:', '')
                self.mavlink_connection = mavutil.mavlink_connection(
                    device,
                    baud=self.config.baud_rate
                )
            elif self.config.connection_string.startswith('udp:'):
                self.mavlink_connection = mavutil.mavlink_connection(
                    self.config.connection_string
                )
            elif self.config.connection_string.startswith('tcp:'):
                self.mavlink_connection = mavutil.mavlink_connection(
                    self.config.connection_string
                )
            else:
                # 默认串口
                self.mavlink_connection = mavutil.mavlink_connection(
                    self.config.connection_string,
                    baud=self.config.baud_rate
                )
            
            # 等待心跳包
            logger.info(f"Waiting for heartbeat from {self.config.drone_id}")
            heartbeat = self.mavlink_connection.wait_heartbeat(timeout=self.config.timeout)
            
            if heartbeat:
                self.target_system = self.mavlink_connection.target_system
                self.target_component = self.mavlink_connection.target_component
                self.state = ConnectionState.CONNECTED
                logger.info(f"Connected to PX4: System={self.target_system}, Component={self.target_component}")
                
                # 启动后台任务
                self._running = True
                self._tasks.append(asyncio.create_task(self._receive_loop()))
                self._tasks.append(asyncio.create_task(self._heartbeat_loop()))
                
                return True
            else:
                self.state = ConnectionState.ERROR
                logger.error("No heartbeat received")
                return False
                
        except Exception as e:
            self.state = ConnectionState.ERROR
            logger.error(f"Connection error: {e}")
            return False
    
    async def disconnect(self) -> bool:
        """断开连接"""
        try:
            self._running = False
            
            # 取消所有任务
            for task in self._tasks:
                task.cancel()
            
            # 关闭连接
            if self.mavlink_connection:
                self.mavlink_connection.close()
            
            self.state = ConnectionState.DISCONNECTED
            logger.info(f"Disconnected from {self.config.drone_id}")
            return True
            
        except Exception as e:
            logger.error(f"Disconnect error: {e}")
            return False
    
    async def send_command(self, command: int, params: List[float] = None) -> bool:
        """发送MAVLink命令"""
        if self.state != ConnectionState.CONNECTED:
            logger.error("Not connected")
            return False
        
        try:
            if params is None:
                params = [0.0] * 7
            
            self.mavlink_connection.mav.command_long_send(
                self.target_system,
                self.target_component,
                command,
                0,  # confirmation
                params[0], params[1], params[2], params[3],
                params[4], params[5], params[6]
            )
            
            logger.debug(f"Sent command {command} to {self.config.drone_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error sending command: {e}")
            return False
    
    async def arm(self) -> bool:
        """解锁"""
        return await self.send_command(
            mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            [1.0, 0, 0, 0, 0, 0, 0]
        )
    
    async def disarm(self) -> bool:
        """上锁"""
        return await self.send_command(
            mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            [0.0, 0, 0, 0, 0, 0, 0]
        )
    
    async def takeoff(self, altitude: float) -> bool:
        """起飞到指定高度"""
        return await self.send_command(
            mavlink.MAV_CMD_NAV_TAKEOFF,
            [0, 0, 0, 0, 0, 0, altitude]
        )
    
    async def land(self) -> bool:
        """降落"""
        return await self.send_command(
            mavlink.MAV_CMD_NAV_LAND,
            [0, 0, 0, 0, 0, 0, 0]
        )
    
    async def goto(self, lat: float, lon: float, alt: float) -> bool:
        """飞往指定位置"""
        return await self.send_command(
            mavlink.MAV_CMD_NAV_WAYPOINT,
            [0, 0, 0, 0, lat, lon, alt]
        )
    
    async def set_mode(self, mode: str) -> bool:
        """设置飞行模式"""
        # PX4飞行模式映射
        mode_map = {
            'MANUAL': 0,
            'ACRO': 1,
            'OFFBOARD': 2,
            'STABILIZED': 3,
            'RATTITUDE': 4,
            'ALTCTL': 5,
            'POSCTL': 6,
            'AUTO.LOITER': 7,
            'AUTO.RTL': 8,
            'AUTO.MISSION': 9,
            'AUTO.LAND': 10,
            'AUTO.TAKEOFF': 11
        }
        
        if mode not in mode_map:
            logger.error(f"Unknown flight mode: {mode}")
            return False
        
        return await self.send_command(
            mavlink.MAV_CMD_DO_SET_MODE,
            [mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
             mode_map[mode], 0, 0, 0, 0, 0]
        )
    
    async def _receive_loop(self):
        """接收消息循环"""
        while self._running:
            try:
                # 接收MAVLink消息
                msg = self.mavlink_connection.recv_match(blocking=False)
                
                if msg:
                    await self._handle_message(msg)
                
                await asyncio.sleep(0.001)  # 1ms延迟
                
            except Exception as e:
                logger.error(f"Error in receive loop: {e}")
                await asyncio.sleep(0.1)
    
    async def _handle_message(self, msg):
        """处理MAVLink消息"""
        msg_type = msg.get_type()
        
        # 全局位置
        if msg_type == 'GLOBAL_POSITION_INT':
            self.telemetry.latitude = msg.lat / 1e7
            self.telemetry.longitude = msg.lon / 1e7
            self.telemetry.altitude = msg.alt / 1000.0
            self.telemetry.relative_altitude = msg.relative_alt / 1000.0
            self.telemetry.ground_speed = (msg.vx**2 + msg.vy**2)**0.5 / 100.0
            self.telemetry.yaw = msg.hdg / 100.0
            self.telemetry.timestamp = datetime.now()
            
        # 姿态
        elif msg_type == 'ATTITUDE':
            self.telemetry.roll = msg.roll * 57.2958  # 弧度转度
            self.telemetry.pitch = msg.pitch * 57.2958
            self.telemetry.yaw = msg.yaw * 57.2958
            self.telemetry.timestamp = datetime.now()
            
        # 电池状态
        elif msg_type == 'SYS_STATUS':
            self.telemetry.battery_voltage = msg.voltage_battery / 1000.0
            self.telemetry.battery_current = msg.current_battery / 100.0
            self.telemetry.battery_remaining = msg.battery_remaining
            self.telemetry.timestamp = datetime.now()
            
        # 心跳
        elif msg_type == 'HEARTBEAT':
            self.telemetry.armed = (msg.base_mode & mavlink.MAV_MODE_FLAG_SAFETY_ARMED) != 0
            self.telemetry.system_status = msg.system_status
            # 解析飞行模式
            if msg.autopilot == mavlink.MAV_AUTOPILOT_PX4:
                self.telemetry.flight_mode = self._px4_mode_from_custom_mode(msg.custom_mode)
            self.telemetry.timestamp = datetime.now()
            
        # GPS原始数据
        elif msg_type == 'GPS_RAW_INT':
            self.telemetry.satellites = msg.satellites_visible
            self.telemetry.gps_fix = msg.fix_type
            self.telemetry.timestamp = datetime.now()
            
        # 无线电状态
        elif msg_type == 'RADIO_STATUS':
            self.telemetry.rssi = msg.rssi
            self.telemetry.snr = msg.remrssi
            self.telemetry.timestamp = datetime.now()
        
        # 通知回调
        await self._notify_telemetry_update()
    
    def _px4_mode_from_custom_mode(self, custom_mode: int) -> str:
        """从PX4自定义模式获取飞行模式名称"""
        mode_map = {
            0: 'MANUAL',
            1: 'ACRO',
            2: 'OFFBOARD',
            3: 'STABILIZED',
            4: 'RATTITUDE',
            5: 'ALTCTL',
            6: 'POSCTL',
            7: 'AUTO.LOITER',
            8: 'AUTO.RTL',
            9: 'AUTO.MISSION',
            10: 'AUTO.LAND',
            11: 'AUTO.TAKEOFF'
        }
        return mode_map.get(custom_mode, 'UNKNOWN')
    
    async def _heartbeat_loop(self):
        """心跳循环"""
        while self._running:
            try:
                if self.state == ConnectionState.CONNECTED:
                    # 发送心跳包
                    self.mavlink_connection.mav.heartbeat_send(
                        mavlink.MAV_TYPE_GCS,
                        mavlink.MAV_AUTOPILOT_INVALID,
                        0, 0, 0
                    )
                
                await asyncio.sleep(self.config.heartbeat_interval)
                
            except Exception as e:
                logger.error(f"Error in heartbeat loop: {e}")


class ArduPilotConnector(MAVLinkConnector):
    """ArduPilot飞控连接器"""
    
    def __init__(self, config: DroneConfig):
        super().__init__(config)
        self.mavlink_connection: Optional[mavutil.mavlink_connection] = None
        self.target_system = 1
        self.target_component = 1
        
    async def connect(self) -> bool:
        """连接到ArduPilot飞控"""
        if not MAVLINK_AVAILABLE:
            logger.error("pymavlink not available")
            return False
            
        try:
            self.state = ConnectionState.CONNECTING
            
            # 创建MAVLink连接（与PX4类似）
            self.mavlink_connection = mavutil.mavlink_connection(
                self.config.connection_string,
                baud=self.config.baud_rate
            )
            
            # 等待心跳包
            logger.info(f"Waiting for heartbeat from {self.config.drone_id}")
            heartbeat = self.mavlink_connection.wait_heartbeat(timeout=self.config.timeout)
            
            if heartbeat:
                self.target_system = self.mavlink_connection.target_system
                self.target_component = self.mavlink_connection.target_component
                self.state = ConnectionState.CONNECTED
                logger.info(f"Connected to ArduPilot: System={self.target_system}")
                
                # 启动后台任务
                self._running = True
                self._tasks.append(asyncio.create_task(self._receive_loop()))
                self._tasks.append(asyncio.create_task(self._heartbeat_loop()))
                
                return True
            else:
                self.state = ConnectionState.ERROR
                logger.error("No heartbeat received")
                return False
                
        except Exception as e:
            self.state = ConnectionState.ERROR
            logger.error(f"Connection error: {e}")
            return False
    
    async def disconnect(self) -> bool:
        """断开连接"""
        try:
            self._running = False
            for task in self._tasks:
                task.cancel()
            if self.mavlink_connection:
                self.mavlink_connection.close()
            self.state = ConnectionState.DISCONNECTED
            logger.info(f"Disconnected from {self.config.drone_id}")
            return True
        except Exception as e:
            logger.error(f"Disconnect error: {e}")
            return False
    
    async def send_command(self, command: int, params: List[float] = None) -> bool:
        """发送命令"""
        if self.state != ConnectionState.CONNECTED:
            return False
        
        try:
            if params is None:
                params = [0.0] * 7
            
            self.mavlink_connection.mav.command_long_send(
                self.target_system,
                self.target_component,
                command,
                0,
                params[0], params[1], params[2], params[3],
                params[4], params[5], params[6]
            )
            return True
        except Exception as e:
            logger.error(f"Error sending command: {e}")
            return False
    
    async def set_mode(self, mode: str) -> bool:
        """设置飞行模式（ArduPilot特有）"""
        mode_map = {
            'STABILIZE': 0,
            'ACRO': 1,
            'ALT_HOLD': 2,
            'AUTO': 3,
            'GUIDED': 4,
            'LOITER': 5,
            'RTL': 6,
            'CIRCLE': 7,
            'LAND': 9
        }
        
        if mode not in mode_map:
            logger.error(f"Unknown flight mode: {mode}")
            return False
        
        # ArduPilot使用DO_SET_MODE命令
        return await self.send_command(
            mavlink.MAV_CMD_DO_SET_MODE,
            [mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
             mode_map[mode], 0, 0, 0, 0, 0]
        )
    
    async def _receive_loop(self):
        """接收消息循环"""
        while self._running:
            try:
                msg = self.mavlink_connection.recv_match(blocking=False)
                if msg:
                    await self._handle_message(msg)
                await asyncio.sleep(0.001)
            except Exception as e:
                logger.error(f"Error in receive loop: {e}")
                await asyncio.sleep(0.1)
    
    async def _handle_message(self, msg):
        """处理MAVLink消息（与PX4类似，但ArduPilot有些消息格式不同）"""
        msg_type = msg.get_type()
        
        # ArduPilot使用不同的消息格式
        if msg_type == 'GLOBAL_POSITION_INT':
            self.telemetry.latitude = msg.lat / 1e7
            self.telemetry.longitude = msg.lon / 1e7
            self.telemetry.altitude = msg.alt / 1000.0
            self.telemetry.relative_altitude = msg.relative_alt / 1000.0
            self.telemetry.timestamp = datetime.now()
            
        elif msg_type == 'ATTITUDE':
            self.telemetry.roll = msg.roll * 57.2958
            self.telemetry.pitch = msg.pitch * 57.2958
            self.telemetry.yaw = msg.yaw * 57.2958
            self.telemetry.timestamp = datetime.now()
            
        elif msg_type == 'SYS_STATUS':
            self.telemetry.battery_voltage = msg.voltage_battery / 1000.0
            self.telemetry.battery_current = msg.current_battery / 100.0
            self.telemetry.battery_remaining = msg.battery_remaining
            self.telemetry.timestamp = datetime.now()
            
        elif msg_type == 'HEARTBEAT':
            self.telemetry.armed = (msg.base_mode & mavlink.MAV_MODE_FLAG_SAFETY_ARMED) != 0
            self.telemetry.flight_mode = self._ardupilot_mode_from_custom_mode(msg.custom_mode)
            self.telemetry.timestamp = datetime.now()
            
        elif msg_type == 'GPS_RAW_INT':
            self.telemetry.satellites = msg.satellites_visible
            self.telemetry.gps_fix = msg.fix_type
            self.telemetry.timestamp = datetime.now()
        
        await self._notify_telemetry_update()
    
    def _ardupilot_mode_from_custom_mode(self, custom_mode: int) -> str:
        """从ArduPilot自定义模式获取飞行模式名称"""
        mode_map = {
            0: 'STABILIZE',
            1: 'ACRO',
            2: 'ALT_HOLD',
            3: 'AUTO',
            4: 'GUIDED',
            5: 'LOITER',
            6: 'RTL',
            7: 'CIRCLE',
            9: 'LAND'
        }
        return mode_map.get(custom_mode, 'UNKNOWN')
    
    async def _heartbeat_loop(self):
        """心跳循环"""
        while self._running:
            try:
                if self.state == ConnectionState.CONNECTED:
                    self.mavlink_connection.mav.heartbeat_send(
                        mavlink.MAV_TYPE_GCS,
                        mavlink.MAV_AUTOPILOT_INVALID,
                        0, 0, 0
                    )
                await asyncio.sleep(self.config.heartbeat_interval)
            except Exception as e:
                logger.error(f"Error in heartbeat loop: {e}")


class DJIConnector(MAVLinkConnector):
    """DJI无人机连接器（通过DJI SDK转换为MAVLink协议）"""
    
    def __init__(self, config: DroneConfig):
        super().__init__(config)
        # DJI SDK连接（需要实现DJI SDK到MAVLink的转换）
        self.dji_connected = False
        
    async def connect(self) -> bool:
        """连接到DJI无人机"""
        # TODO: 实现DJI SDK连接
        logger.warning("DJI connector not yet implemented")
        return False
    
    async def disconnect(self) -> bool:
        """断开连接"""
        # TODO: 实现DJI SDK断开连接
        return False
    
    async def send_command(self, command: int, params: List[float] = None) -> bool:
        """发送命令（转换为DJI SDK命令）"""
        # TODO: 实现命令转换
        return False


class ConnectorFactory:
    """连接器工厂"""
    
    @staticmethod
    def create_connector(config: DroneConfig) -> MAVLinkConnector:
        """根据无人机类型创建对应的连接器"""
        if config.drone_type == DroneType.PX4:
            return PX4Connector(config)
        elif config.drone_type == DroneType.ARDUPILOT:
            return ArduPilotConnector(config)
        elif config.drone_type == DroneType.DJI:
            return DJIConnector(config)
        else:
            # 默认使用PX4连接器
            return PX4Connector(config)


# 测试代码
if __name__ == "__main__":
    import asyncio
    
    async def test_connector():
        """测试连接器"""
        config = DroneConfig(
            drone_id="drone_001",
            drone_type=DroneType.PX4,
            connection_string="udp:127.0.0.1:14550"
        )
        
        connector = ConnectorFactory.create_connector(config)
        
        def telemetry_callback(drone_id, telemetry):
            print(f"[{drone_id}] Position: {telemetry.latitude}, {telemetry.longitude}")
        
        connector.add_telemetry_callback(telemetry_callback)
        
        if await connector.connect():
            print("Connected successfully!")
            
            # 等待10秒接收数据
            await asyncio.sleep(10)
            
            await connector.disconnect()
        else:
            print("Connection failed")
    
    # 运行测试
    asyncio.run(test_connector())
