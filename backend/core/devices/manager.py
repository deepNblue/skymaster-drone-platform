"""
设备管理器 - 统一管理所有无人机设备
支持多机同时连接、状态监控、命令分发
"""

import asyncio
import logging
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json
from collections import defaultdict

from ..mavlink.connector import (
    MAVLinkConnector, 
    DroneConfig, 
    DroneType, 
    ConnectionState,
    TelemetryData,
    ConnectorFactory
)

logger = logging.getLogger(__name__)


class DeviceStatus(Enum):
    """设备状态"""
    OFFLINE = "offline"
    ONLINE = "online"
    FLYING = "flying"
    WARNING = "warning"
    ERROR = "error"
    MAINTENANCE = "maintenance"


@dataclass
class DroneDevice:
    """无人机设备"""
    device_id: str
    name: str
    drone_type: DroneType
    config: DroneConfig
    connector: Optional[MAVLinkConnector] = None
    status: DeviceStatus = DeviceStatus.OFFLINE
    last_seen: datetime = field(default_factory=datetime.now)
    total_flight_time: float = 0.0  # 总飞行时间（秒）
    total_distance: float = 0.0  # 总飞行距离（米）
    flight_count: int = 0  # 飞行次数
    
    # 设备信息
    firmware_version: str = ""
    serial_number: str = ""
    model: str = ""
    
    # 自定义属性
    custom_properties: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'device_id': self.device_id,
            'name': self.name,
            'drone_type': self.drone_type.value,
            'status': self.status.value,
            'last_seen': self.last_seen.isoformat(),
            'statistics': {
                'total_flight_time': self.total_flight_time,
                'total_distance': self.total_distance,
                'flight_count': self.flight_count
            },
            'device_info': {
                'firmware_version': self.firmware_version,
                'serial_number': self.serial_number,
                'model': self.model
            },
            'custom_properties': self.custom_properties
        }


@dataclass
class DeviceGroup:
    """设备分组"""
    group_id: str
    name: str
    description: str = ""
    device_ids: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'group_id': self.group_id,
            'name': self.name,
            'description': self.description,
            'device_ids': self.device_ids,
            'device_count': len(self.device_ids),
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }


class DeviceManager:
    """设备管理器"""
    
    def __init__(self):
        self.devices: Dict[str, DroneDevice] = {}
        self.groups: Dict[str, DeviceGroup] = {}
        self.telemetry_callbacks: List[Callable] = []
        self.status_callbacks: List[Callable] = []
        self._running = False
        self._tasks: List[asyncio.Task] = []
        
        # 统计信息
        self.stats = {
            'total_devices': 0,
            'online_devices': 0,
            'flying_devices': 0,
            'warning_devices': 0
        }
    
    async def start(self):
        """启动设备管理器"""
        self._running = True
        self._tasks.append(asyncio.create_task(self._monitor_loop()))
        logger.info("Device manager started")
    
    async def stop(self):
        """停止设备管理器"""
        self._running = False
        
        # 断开所有设备
        for device in self.devices.values():
            if device.connector:
                await device.connector.disconnect()
        
        # 取消所有任务
        for task in self._tasks:
            task.cancel()
        
        logger.info("Device manager stopped")
    
    async def register_device(self, config: DroneConfig, name: str = None, 
                             custom_properties: Dict = None) -> str:
        """注册新设备"""
        device_id = config.drone_id
        
        if device_id in self.devices:
            logger.warning(f"Device {device_id} already registered")
            return device_id
        
        # 创建设备对象
        device = DroneDevice(
            device_id=device_id,
            name=name or f"Drone-{device_id}",
            drone_type=config.drone_type,
            config=config,
            custom_properties=custom_properties or {}
        )
        
        # 创建连接器
        device.connector = ConnectorFactory.create_connector(config)
        
        # 添加遥测回调
        device.connector.add_telemetry_callback(self._on_telemetry_update)
        
        # 保存设备
        self.devices[device_id] = device
        self.stats['total_devices'] += 1
        
        logger.info(f"Device registered: {device_id}")
        
        # 通知状态变更
        await self._notify_status_change(device_id, DeviceStatus.OFFLINE)
        
        return device_id
    
    async def unregister_device(self, device_id: str) -> bool:
        """注销设备"""
        if device_id not in self.devices:
            logger.warning(f"Device {device_id} not found")
            return False
        
        device = self.devices[device_id]
        
        # 断开连接
        if device.connector and device.connector.state == ConnectionState.CONNECTED:
            await device.connector.disconnect()
        
        # 从所有分组中移除
        for group in self.groups.values():
            if device_id in group.device_ids:
                group.device_ids.remove(device_id)
                group.updated_at = datetime.now()
        
        # 删除设备
        del self.devices[device_id]
        self.stats['total_devices'] -= 1
        
        logger.info(f"Device unregistered: {device_id}")
        
        return True
    
    async def connect_device(self, device_id: str) -> bool:
        """连接设备"""
        if device_id not in self.devices:
            logger.error(f"Device {device_id} not found")
            return False
        
        device = self.devices[device_id]
        
        if not device.connector:
            logger.error(f"No connector for device {device_id}")
            return False
        
        # 连接
        success = await device.connector.connect()
        
        if success:
            device.status = DeviceStatus.ONLINE
            device.last_seen = datetime.now()
            self.stats['online_devices'] += 1
            
            await self._notify_status_change(device_id, DeviceStatus.ONLINE)
            logger.info(f"Device connected: {device_id}")
        else:
            device.status = DeviceStatus.ERROR
            await self._notify_status_change(device_id, DeviceStatus.ERROR)
            logger.error(f"Failed to connect device: {device_id}")
        
        return success
    
    async def disconnect_device(self, device_id: str) -> bool:
        """断开设备连接"""
        if device_id not in self.devices:
            return False
        
        device = self.devices[device_id]
        
        if not device.connector:
            return False
        
        success = await device.connector.disconnect()
        
        if success:
            if device.status == DeviceStatus.ONLINE:
                self.stats['online_devices'] -= 1
            elif device.status == DeviceStatus.FLYING:
                self.stats['flying_devices'] -= 1
            
            device.status = DeviceStatus.OFFLINE
            await self._notify_status_change(device_id, DeviceStatus.OFFLINE)
            logger.info(f"Device disconnected: {device_id}")
        
        return success
    
    async def connect_all(self) -> Dict[str, bool]:
        """连接所有设备"""
        results = {}
        
        for device_id in self.devices:
            results[device_id] = await self.connect_device(device_id)
        
        return results
    
    async def disconnect_all(self) -> Dict[str, bool]:
        """断开所有设备"""
        results = {}
        
        for device_id in self.devices:
            results[device_id] = await self.disconnect_device(device_id)
        
        return results
    
    def get_device(self, device_id: str) -> Optional[DroneDevice]:
        """获取设备"""
        return self.devices.get(device_id)
    
    def get_all_devices(self) -> List[DroneDevice]:
        """获取所有设备"""
        return list(self.devices.values())
    
    def get_devices_by_status(self, status: DeviceStatus) -> List[DroneDevice]:
        """根据状态获取设备"""
        return [d for d in self.devices.values() if d.status == status]
    
    def get_devices_by_type(self, drone_type: DroneType) -> List[DroneDevice]:
        """根据类型获取设备"""
        return [d for d in self.devices.values() if d.drone_type == drone_type]
    
    async def send_command(self, device_id: str, command: str, 
                          params: Dict[str, Any] = None) -> bool:
        """向设备发送命令"""
        if device_id not in self.devices:
            logger.error(f"Device {device_id} not found")
            return False
        
        device = self.devices[device_id]
        
        if not device.connector or device.connector.state != ConnectionState.CONNECTED:
            logger.error(f"Device {device_id} not connected")
            return False
        
        # 根据命令类型调用相应方法
        try:
            if command == "arm":
                return await device.connector.arm()
            elif command == "disarm":
                return await device.connector.disarm()
            elif command == "takeoff":
                altitude = params.get('altitude', 10.0) if params else 10.0
                return await device.connector.takeoff(altitude)
            elif command == "land":
                return await device.connector.land()
            elif command == "goto":
                if not params:
                    return False
                return await device.connector.goto(
                    params['latitude'],
                    params['longitude'],
                    params['altitude']
                )
            elif command == "set_mode":
                if not params or 'mode' not in params:
                    return False
                return await device.connector.set_mode(params['mode'])
            else:
                logger.error(f"Unknown command: {command}")
                return False
                
        except Exception as e:
            logger.error(f"Error sending command to {device_id}: {e}")
            return False
    
    async def broadcast_command(self, command: str, 
                               params: Dict[str, Any] = None) -> Dict[str, bool]:
        """向所有在线设备广播命令"""
        results = {}
        
        for device_id, device in self.devices.items():
            if device.status in [DeviceStatus.ONLINE, DeviceStatus.FLYING]:
                results[device_id] = await self.send_command(device_id, command, params)
        
        return results
    
    async def send_group_command(self, group_id: str, command: str,
                                 params: Dict[str, Any] = None) -> Dict[str, bool]:
        """向分组发送命令"""
        if group_id not in self.groups:
            logger.error(f"Group {group_id} not found")
            return {}
        
        group = self.groups[group_id]
        results = {}
        
        for device_id in group.device_ids:
            results[device_id] = await self.send_command(device_id, command, params)
        
        return results
    
    # 分组管理
    async def create_group(self, group_id: str, name: str, 
                          description: str = "") -> bool:
        """创建设备分组"""
        if group_id in self.groups:
            logger.warning(f"Group {group_id} already exists")
            return False
        
        group = DeviceGroup(
            group_id=group_id,
            name=name,
            description=description
        )
        
        self.groups[group_id] = group
        logger.info(f"Group created: {group_id}")
        
        return True
    
    async def delete_group(self, group_id: str) -> bool:
        """删除分组"""
        if group_id not in self.groups:
            return False
        
        del self.groups[group_id]
        logger.info(f"Group deleted: {group_id}")
        
        return True
    
    async def add_device_to_group(self, device_id: str, group_id: str) -> bool:
        """将设备添加到分组"""
        if device_id not in self.devices:
            logger.error(f"Device {device_id} not found")
            return False
        
        if group_id not in self.groups:
            logger.error(f"Group {group_id} not found")
            return False
        
        group = self.groups[group_id]
        
        if device_id in group.device_ids:
            logger.warning(f"Device {device_id} already in group {group_id}")
            return True
        
        group.device_ids.append(device_id)
        group.updated_at = datetime.now()
        
        logger.info(f"Device {device_id} added to group {group_id}")
        
        return True
    
    async def remove_device_from_group(self, device_id: str, group_id: str) -> bool:
        """从分组中移除设备"""
        if group_id not in self.groups:
            return False
        
        group = self.groups[group_id]
        
        if device_id not in group.device_ids:
            return False
        
        group.device_ids.remove(device_id)
        group.updated_at = datetime.now()
        
        logger.info(f"Device {device_id} removed from group {group_id}")
        
        return True
    
    def get_group(self, group_id: str) -> Optional[DeviceGroup]:
        """获取分组"""
        return self.groups.get(group_id)
    
    def get_all_groups(self) -> List[DeviceGroup]:
        """获取所有分组"""
        return list(self.groups.values())
    
    # 回调管理
    def add_telemetry_callback(self, callback: Callable):
        """添加遥测数据回调"""
        self.telemetry_callbacks.append(callback)
    
    def add_status_callback(self, callback: Callable):
        """添加状态变更回调"""
        self.status_callbacks.append(callback)
    
    async def _on_telemetry_update(self, device_id: str, telemetry: TelemetryData):
        """遥测数据更新回调"""
        if device_id not in self.devices:
            return
        
        device = self.devices[device_id]
        device.last_seen = datetime.now()
        
        # 更新设备状态
        if telemetry.armed:
            if device.status != DeviceStatus.FLYING:
                if device.status == DeviceStatus.ONLINE:
                    self.stats['online_devices'] -= 1
                device.status = DeviceStatus.FLYING
                self.stats['flying_devices'] += 1
        else:
            if device.status == DeviceStatus.FLYING:
                self.stats['flying_devices'] -= 1
                device.status = DeviceStatus.ONLINE
                self.stats['online_devices'] += 1
        
        # 检查电池电量
        if telemetry.battery_remaining < 20:
            device.status = DeviceStatus.WARNING
            self.stats['warning_devices'] += 1
        
        # 通知所有回调
        for callback in self.telemetry_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(device_id, telemetry)
                else:
                    callback(device_id, telemetry)
            except Exception as e:
                logger.error(f"Error in telemetry callback: {e}")
    
    async def _notify_status_change(self, device_id: str, status: DeviceStatus):
        """通知状态变更"""
        for callback in self.status_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(device_id, status)
                else:
                    callback(device_id, status)
            except Exception as e:
                logger.error(f"Error in status callback: {e}")
    
    async def _monitor_loop(self):
        """监控循环"""
        while self._running:
            try:
                # 检查设备超时
                now = datetime.now()
                for device_id, device in list(self.devices.items()):
                    if device.connector and device.connector.state == ConnectionState.CONNECTED:
                        # 检查最后更新时间
                        time_since_last_seen = (now - device.last_seen).total_seconds()
                        
                        if time_since_last_seen > 10.0:  # 10秒超时
                            logger.warning(f"Device {device_id} timeout")
                            device.status = DeviceStatus.WARNING
                            await self._notify_status_change(device_id, DeviceStatus.WARNING)
                
                # 更新统计
                self.stats['online_devices'] = len([d for d in self.devices.values() 
                                                    if d.status in [DeviceStatus.ONLINE, DeviceStatus.FLYING]])
                self.stats['flying_devices'] = len([d for d in self.devices.values() 
                                                    if d.status == DeviceStatus.FLYING])
                
                await asyncio.sleep(5.0)  # 5秒检查一次
                
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
                await asyncio.sleep(1.0)
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            'devices': self.stats,
            'groups': len(self.groups),
            'timestamp': datetime.now().isoformat()
        }
    
    def export_devices(self) -> List[Dict]:
        """导出所有设备配置"""
        return [device.to_dict() for device in self.devices.values()]
    
    def export_groups(self) -> List[Dict]:
        """导出所有分组配置"""
        return [group.to_dict() for group in self.groups.values()]


# 测试代码
if __name__ == "__main__":
    import asyncio
    
    async def test_device_manager():
        """测试设备管理器"""
        manager = DeviceManager()
        
        await manager.start()
        
        # 注册设备
        config1 = DroneConfig(
            drone_id="drone_001",
            drone_type=DroneType.PX4,
            connection_string="udp:127.0.0.1:14550"
        )
        
        config2 = DroneConfig(
            drone_id="drone_002",
            drone_type=DroneType.ARDUPILOT,
            connection_string="udp:127.0.0.1:14551"
        )
        
        await manager.register_device(config1, name="Alpha")
        await manager.register_device(config2, name="Beta")
        
        # 创建分组
        await manager.create_group("team_a", "Team Alpha", "Primary fleet")
        await manager.add_device_to_group("drone_001", "team_a")
        await manager.add_device_to_group("drone_002", "team_a")
        
        # 连接设备
        # await manager.connect_all()
        
        # 显示统计
        print("Statistics:", manager.get_statistics())
        
        # 运行10秒
        await asyncio.sleep(10)
        
        await manager.stop()
    
    asyncio.run(test_device_manager())
