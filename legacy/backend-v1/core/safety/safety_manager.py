"""
SkyMaster 安全管理器
统一安全管理、安全规则引擎、紧急响应和安全日志
"""

import asyncio
import time
import json
import math
from typing import Dict, List, Optional, Callable, Any, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from pathlib import Path
import logging
from threading import Lock
from collections import deque
import uuid

from .obstacle_detector import (
    ObstacleDetector, Obstacle, ObstacleType, ObstacleStatus, RiskLevel,
    Position, Velocity
)
from .collision_avoidance import (
    CollisionAvoidance, AvoidanceStrategy, AvoidanceStatus,
    CollisionRisk, DroneState
)

logger = logging.getLogger(__name__)


class SafetyLevel(Enum):
    """安全等级"""
    SAFE = "safe"                    # 安全
    CAUTION = "caution"              # 注意
    WARNING = "warning"              # 警告
    CRITICAL = "critical"            # 危险
    EMERGENCY = "emergency"          # 紧急


class SafetyEventType(Enum):
    """安全事件类型"""
    OBSTACLE_DETECTED = "obstacle_detected"
    COLLISION_WARNING = "collision_warning"
    COLLISION_AVOIDANCE = "collision_avoidance"
    EMERGENCY_BRAKE = "emergency_brake"
    GEOFENCE_BREACH = "geofence_breach"
    ALTITUDE_LIMIT = "altitude_limit"
    BATTERY_LOW = "battery_low"
    SIGNAL_LOST = "signal_lost"
    WEATHER_ALERT = "weather_alert"
    SYSTEM_ERROR = "system_error"
    MANUAL_OVERRIDE = "manual_override"


class SafetyAction(Enum):
    """安全动作"""
    NONE = "none"
    ALERT = "alert"
    SLOW_DOWN = "slow_down"
    HOVER = "hover"
    AVOID = "avoid"
    RETURN_HOME = "return_home"
    EMERGENCY_LAND = "emergency_land"
    EMERGENCY_STOP = "emergency_stop"


@dataclass
class SafetyRule:
    """安全规则"""
    rule_id: str
    name: str
    description: str
    condition: Callable[[Dict], bool]  # 条件函数
    action: SafetyAction
    priority: int = 0  # 优先级，数字越大优先级越高
    enabled: bool = True
    cooldown: float = 0.0  # 冷却时间（秒）
    last_triggered: float = 0.0
    
    def should_trigger(self, context: Dict) -> bool:
        """判断是否应该触发"""
        if not self.enabled:
            return False
        
        # 检查冷却时间
        if time.time() - self.last_triggered < self.cooldown:
            return False
        
        try:
            return self.condition(context)
        except Exception as e:
            logger.error(f"Error evaluating rule {self.rule_id}: {e}")
            return False
    
    def to_dict(self) -> Dict:
        return {
            'rule_id': self.rule_id,
            'name': self.name,
            'description': self.description,
            'action': self.action.value,
            'priority': self.priority,
            'enabled': self.enabled,
            'cooldown': self.cooldown
        }


@dataclass
class SafetyEvent:
    """安全事件"""
    event_id: str
    event_type: SafetyEventType
    safety_level: SafetyLevel
    message: str
    source: str  # 来源组件
    details: Dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    acknowledged: bool = False
    resolved: bool = False
    resolved_at: Optional[float] = None
    action_taken: Optional[SafetyAction] = None
    
    def acknowledge(self) -> None:
        """确认事件"""
        self.acknowledged = True
    
    def resolve(self, action: Optional[SafetyAction] = None) -> None:
        """解决事件"""
        self.resolved = True
        self.resolved_at = time.time()
        if action:
            self.action_taken = action
    
    def to_dict(self) -> Dict:
        return {
            'event_id': self.event_id,
            'event_type': self.event_type.value,
            'safety_level': self.safety_level.value,
            'message': self.message,
            'source': self.source,
            'details': self.details,
            'timestamp': self.timestamp,
            'acknowledged': self.acknowledged,
            'resolved': self.resolved,
            'resolved_at': self.resolved_at,
            'action_taken': self.action_taken.value if self.action_taken else None
        }


@dataclass
class GeoFence:
    """地理围栏"""
    fence_id: str
    name: str
    fence_type: str  # 'inclusion' 或 'exclusion'
    vertices: List[Tuple[float, float]]  # 多边形顶点 (lat, lon)
    min_altitude: Optional[float] = None
    max_altitude: Optional[float] = None
    enabled: bool = True
    
    def contains(self, lat: float, lon: float) -> bool:
        """判断点是否在围栏内（射线法）"""
        n = len(self.vertices)
        inside = False
        
        p1x, p1y = self.vertices[0]
        for i in range(1, n + 1):
            p2x, p2y = self.vertices[i % n]
            if lat > min(p1y, p2y):
                if lat <= max(p1y, p2y):
                    if lon <= max(p1x, p2x):
                        if p1y != p2y:
                            xinters = (lat - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                        if p1x == p2x or lon <= xinters:
                            inside = not inside
            p1x, p1y = p2x, p2y
        
        return inside
    
    def check_altitude(self, altitude: float) -> bool:
        """检查高度是否在范围内"""
        if self.min_altitude is not None and altitude < self.min_altitude:
            return False
        if self.max_altitude is not None and altitude > self.max_altitude:
            return False
        return True
    
    def to_dict(self) -> Dict:
        return {
            'fence_id': self.fence_id,
            'name': self.name,
            'fence_type': self.fence_type,
            'vertices': self.vertices,
            'min_altitude': self.min_altitude,
            'max_altitude': self.max_altitude,
            'enabled': self.enabled
        }


@dataclass
class SafetyLog:
    """安全日志条目"""
    log_id: str
    timestamp: float
    level: str
    component: str
    message: str
    details: Dict
    
    def to_dict(self) -> Dict:
        return {
            'log_id': self.log_id,
            'timestamp': self.timestamp,
            'level': self.level,
            'component': self.component,
            'message': self.message,
            'details': self.details
        }


class SafetyManager:
    """
    安全管理器
    统一管理所有安全相关的功能
    """
    
    def __init__(
        self,
        max_altitude: float = 120.0,      # 最大高度（米）
        min_altitude: float = 5.0,        # 最小高度（米）
        max_speed: float = 15.0,          # 最大速度（m/s）
        max_distance: float = 1000.0,     # 最大距离（米）
        battery_low_threshold: float = 20.0,  # 低电量阈值（%）
        battery_critical_threshold: float = 10.0,  # 临界电量阈值（%）
        log_size: int = 1000,             # 日志最大数量
        event_history_size: int = 500     # 事件历史最大数量
    ):
        # 基本参数
        self.max_altitude = max_altitude
        self.min_altitude = min_altitude
        self.max_speed = max_speed
        self.max_distance = max_distance
        self.battery_low_threshold = battery_low_threshold
        self.battery_critical_threshold = battery_critical_threshold
        
        # 组件
        self.obstacle_detector = ObstacleDetector()
        self.collision_avoidance = CollisionAvoidance()
        
        # 状态
        self._safety_level = SafetyLevel.SAFE
        self._running = False
        self._safety_task: Optional[asyncio.Task] = None
        self._lock = Lock()
        
        # 安全规则
        self._rules: Dict[str, SafetyRule] = {}
        self._geofences: Dict[str, GeoFence] = {}
        
        # 事件和日志
        self._active_events: Dict[str, SafetyEvent] = {}
        self._event_history: deque = deque(maxlen=event_history_size)
        self._safety_logs: deque = deque(maxlen=log_size)
        
        # 无人机状态
        self._drone_states: Dict[str, DroneState] = {}
        
        # 统计
        self._stats = {
            'total_events': 0,
            'critical_events': 0,
            'emergencies': 0,
            'avoidances_executed': 0,
            'rules_triggered': 0
        }
        
        # 回调
        self._on_safety_event: Optional[Callable] = None
        self._on_safety_level_change: Optional[Callable] = None
        self._on_emergency: Optional[Callable] = None
        
        # 初始化默认规则
        self._init_default_rules()
        
        logger.info("SafetyManager initialized")
    
    def _init_default_rules(self) -> None:
        """初始化默认安全规则"""
        
        # 高度限制规则
        self.add_rule(SafetyRule(
            rule_id="altitude_max",
            name="最大高度限制",
            description="飞行高度不能超过最大限制",
            condition=lambda ctx: ctx.get('altitude', 0) > self.max_altitude,
            action=SafetyAction.ALERT,
            priority=8,
            cooldown=5.0
        ))
        
        # 最小高度规则
        self.add_rule(SafetyRule(
            rule_id="altitude_min",
            name="最小高度限制",
            description="飞行高度不能低于最小限制",
            condition=lambda ctx: 0 < ctx.get('altitude', 100) < self.min_altitude,
            action=SafetyAction.ALERT,
            priority=7,
            cooldown=5.0
        ))
        
        # 速度限制规则
        self.add_rule(SafetyRule(
            rule_id="speed_max",
            name="最大速度限制",
            description="飞行速度不能超过最大限制",
            condition=lambda ctx: ctx.get('speed', 0) > self.max_speed,
            action=SafetyAction.SLOW_DOWN,
            priority=6,
            cooldown=3.0
        ))
        
        # 低电量规则
        self.add_rule(SafetyRule(
            rule_id="battery_low",
            name="低电量警告",
            description="电池电量低于警告阈值",
            condition=lambda ctx: ctx.get('battery', 100) < self.battery_low_threshold,
            action=SafetyAction.ALERT,
            priority=7,
            cooldown=30.0
        ))
        
        # 临界电量规则
        self.add_rule(SafetyRule(
            rule_id="battery_critical",
            name="临界电量",
            description="电池电量低于临界阈值，需要立即返航",
            condition=lambda ctx: ctx.get('battery', 100) < self.battery_critical_threshold,
            action=SafetyAction.RETURN_HOME,
            priority=10,
            cooldown=0.0
        ))
        
        # 碰撞风险规则
        self.add_rule(SafetyRule(
            rule_id="collision_risk",
            name="碰撞风险",
            description="检测到碰撞风险",
            condition=lambda ctx: ctx.get('collision_risk', False),
            action=SafetyAction.AVOID,
            priority=9,
            cooldown=0.0
        ))
        
        # 信号丢失规则
        self.add_rule(SafetyRule(
            rule_id="signal_lost",
            name="信号丢失",
            description="与地面站失去连接",
            condition=lambda ctx: ctx.get('signal_lost', False),
            action=SafetyAction.RETURN_HOME,
            priority=9,
            cooldown=0.0
        ))
        
        # 地理围栏违规规则
        self.add_rule(SafetyRule(
            rule_id="geofence_breach",
            name="地理围栏违规",
            description="飞出允许区域或进入禁止区域",
            condition=lambda ctx: ctx.get('geofence_breach', False),
            action=SafetyAction.RETURN_HOME,
            priority=8,
            cooldown=5.0
        ))
    
    async def start(self) -> None:
        """启动安全管理器"""
        if self._running:
            logger.warning("SafetyManager is already running")
            return
        
        self._running = True
        
        # 启动子组件
        await self.obstacle_detector.start()
        await self.collision_avoidance.start()
        
        # 启动主循环
        self._safety_task = asyncio.create_task(self._safety_loop())
        
        self._log("INFO", "SafetyManager", "SafetyManager started")
        logger.info("SafetyManager started")
    
    async def stop(self) -> None:
        """停止安全管理器"""
        self._running = False
        
        # 停止子组件
        await self.obstacle_detector.stop()
        await self.collision_avoidance.stop()
        
        # 取消主循环
        if self._safety_task:
            self._safety_task.cancel()
            try:
                await self._safety_task
            except asyncio.CancelledError:
                pass
        
        self._log("INFO", "SafetyManager", "SafetyManager stopped")
        logger.info("SafetyManager stopped")
    
    async def _safety_loop(self) -> None:
        """安全检查主循环"""
        while self._running:
            try:
                # 评估当前状态
                await self._evaluate_safety()
                
                # 检查规则
                await self._check_rules()
                
                # 更新安全等级
                self._update_safety_level()
                
                await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in safety loop: {e}")
                await asyncio.sleep(0.5)
    
    async def _evaluate_safety(self) -> None:
        """评估安全状态"""
        # 获取碰撞风险
        risks = self.collision_avoidance.get_collision_risks()
        
        # 检查是否有高风险
        high_risks = [r for r in risks if r.risk_level.value >= RiskLevel.HIGH.value]
        
        if high_risks:
            # 创建安全事件
            for risk in high_risks:
                await self._create_safety_event(
                    SafetyEventType.COLLISION_WARNING,
                    SafetyLevel.WARNING if risk.risk_level == RiskLevel.HIGH else SafetyLevel.CRITICAL,
                    f"Collision risk detected with {risk.obstacle_id}",
                    "CollisionAvoidance",
                    {'risk': risk.to_dict()}
                )
    
    async def _check_rules(self) -> None:
        """检查安全规则"""
        # 构建上下文
        context = self._build_context()
        
        # 按优先级排序规则
        sorted_rules = sorted(
            self._rules.values(),
            key=lambda r: r.priority,
            reverse=True
        )
        
        for rule in sorted_rules:
            if rule.should_trigger(context):
                # 触发规则
                await self._trigger_rule(rule, context)
                
                # 只执行一个高优先级规则
                if rule.priority >= 8:
                    break
    
    def _build_context(self) -> Dict:
        """构建规则检查上下文"""
        context = {
            'altitude': 0,
            'speed': 0,
            'battery': 100,
            'collision_risk': False,
            'signal_lost': False,
            'geofence_breach': False
        }
        
        # 从无人机状态更新
        if self._drone_states:
            # 使用第一个无人机的状态
            state = list(self._drone_states.values())[0]
            context['altitude'] = state.position.z
            context['speed'] = state.speed
        
        # 从碰撞避免系统更新
        risks = self.collision_avoidance.get_collision_risks()
        context['collision_risk'] = any(
            r.risk_level.value >= RiskLevel.HIGH.value for r in risks
        )
        
        return context
    
    async def _trigger_rule(self, rule: SafetyRule, context: Dict) -> None:
        """触发安全规则"""
        rule.last_triggered = time.time()
        self._stats['rules_triggered'] += 1
        
        # 创建安全事件
        event = await self._create_safety_event(
            SafetyEventType.SYSTEM_ERROR,  # 通用类型
            SafetyLevel.WARNING if rule.priority < 8 else SafetyLevel.CRITICAL,
            f"Rule triggered: {rule.name}",
            "RuleEngine",
            {'rule': rule.to_dict(), 'context': context}
        )
        
        # 执行动作
        await self._execute_safety_action(rule.action, event)
        
        self._log("WARNING", "RuleEngine", 
                 f"Rule '{rule.name}' triggered, action: {rule.action.value}")
    
    async def _execute_safety_action(self, action: SafetyAction, event: SafetyEvent) -> None:
        """执行安全动作"""
        if action == SafetyAction.NONE:
            return
        
        self._log("INFO", "SafetyAction", 
                 f"Executing safety action: {action.value}")
        
        # 根据动作类型执行
        if action == SafetyAction.ALERT:
            # 警报 - 只通知
            if self._on_safety_event:
                await self._on_safety_event(event)
        
        elif action == SafetyAction.SLOW_DOWN:
            # 减速
            # TODO: 实现减速逻辑
            pass
        
        elif action == SafetyAction.HOVER:
            # 悬停
            # TODO: 实现悬停逻辑
            pass
        
        elif action == SafetyAction.AVOID:
            # 避障
            self._stats['avoidances_executed'] += 1
            # 避障由 collision_avoidance 模块处理
        
        elif action == SafetyAction.RETURN_HOME:
            # 返航
            await self._trigger_return_home(event)
        
        elif action == SafetyAction.EMERGENCY_LAND:
            # 紧急降落
            await self._trigger_emergency_land(event)
        
        elif action == SafetyAction.EMERGENCY_STOP:
            # 紧急停止
            await self._trigger_emergency_stop(event)
    
    async def _trigger_return_home(self, event: SafetyEvent) -> None:
        """触发返航"""
        self._log("WARNING", "SafetyAction", "Triggering return to home")
        
        # 创建返航事件
        await self._create_safety_event(
            SafetyEventType.MANUAL_OVERRIDE,
            SafetyLevel.WARNING,
            "Return to home triggered",
            "SafetyManager",
            {'trigger_event': event.event_id}
        )
        
        if self._on_emergency:
            await self._on_emergency('return_home', event)
    
    async def _trigger_emergency_land(self, event: SafetyEvent) -> None:
        """触发紧急降落"""
        self._log("CRITICAL", "SafetyAction", "Triggering emergency landing")
        
        # 创建紧急降落事件
        await self._create_safety_event(
            SafetyEventType.EMERGENCY_BRAKE,
            SafetyLevel.EMERGENCY,
            "Emergency landing triggered",
            "SafetyManager",
            {'trigger_event': event.event_id}
        )
        
        self._stats['emergencies'] += 1
        
        if self._on_emergency:
            await self._on_emergency('emergency_land', event)
    
    async def _trigger_emergency_stop(self, event: SafetyEvent) -> None:
        """触发紧急停止"""
        self._log("CRITICAL", "SafetyAction", "Triggering emergency stop")
        
        # 创建紧急停止事件
        await self._create_safety_event(
            SafetyEventType.EMERGENCY_BRAKE,
            SafetyLevel.EMERGENCY,
            "Emergency stop triggered",
            "SafetyManager",
            {'trigger_event': event.event_id}
        )
        
        self._stats['emergencies'] += 1
        
        if self._on_emergency:
            await self._on_emergency('emergency_stop', event)
    
    def _update_safety_level(self) -> None:
        """更新安全等级"""
        old_level = self._safety_level
        
        # 基于当前状态确定安全等级
        risks = self.collision_avoidance.get_collision_risks()
        
        if any(r.risk_level == RiskLevel.CRITICAL for r in risks):
            new_level = SafetyLevel.CRITICAL
        elif any(r.risk_level == RiskLevel.HIGH for r in risks):
            new_level = SafetyLevel.WARNING
        elif any(r.risk_level == RiskLevel.MEDIUM for r in risks):
            new_level = SafetyLevel.CAUTION
        else:
            # 检查其他因素
            context = self._build_context()
            if context.get('battery', 100) < self.battery_critical_threshold:
                new_level = SafetyLevel.CRITICAL
            elif context.get('battery', 100) < self.battery_low_threshold:
                new_level = SafetyLevel.WARNING
            elif context.get('signal_lost', False):
                new_level = SafetyLevel.WARNING
            else:
                new_level = SafetyLevel.SAFE
        
        # 更新并通知
        with self._lock:
            self._safety_level = new_level
        
        if new_level != old_level and self._on_safety_level_change:
            asyncio.create_task(
                self._on_safety_level_change(old_level, new_level)
            )
    
    async def _create_safety_event(
        self,
        event_type: SafetyEventType,
        safety_level: SafetyLevel,
        message: str,
        source: str,
        details: Dict = None
    ) -> SafetyEvent:
        """创建安全事件"""
        event = SafetyEvent(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            safety_level=safety_level,
            message=message,
            source=source,
            details=details or {}
        )
        
        with self._lock:
            self._active_events[event.event_id] = event
            self._event_history.append(event)
            self._stats['total_events'] += 1
            
            if safety_level == SafetyLevel.CRITICAL:
                self._stats['critical_events'] += 1
        
        # 触发回调
        if self._on_safety_event:
            await self._on_safety_event(event)
        
        self._log(
            safety_level.value.upper(),
            source,
            message
        )
        
        return event
    
    def _log(self, level: str, component: str, message: str, details: Dict = None) -> None:
        """记录安全日志"""
        log_entry = SafetyLog(
            log_id=str(uuid.uuid4()),
            timestamp=time.time(),
            level=level,
            component=component,
            message=message,
            details=details or {}
        )
        
        with self._lock:
            self._safety_logs.append(log_entry)
    
    # ==================== 公共API ====================
    
    def add_rule(self, rule: SafetyRule) -> None:
        """添加安全规则"""
        with self._lock:
            self._rules[rule.rule_id] = rule
        logger.info(f"Safety rule added: {rule.rule_id}")
    
    def remove_rule(self, rule_id: str) -> bool:
        """移除安全规则"""
        with self._lock:
            if rule_id in self._rules:
                del self._rules[rule_id]
                return True
        return False
    
    def get_rules(self) -> List[SafetyRule]:
        """获取所有规则"""
        with self._lock:
            return list(self._rules.values())
    
    def add_geofence(self, geofence: GeoFence) -> None:
        """添加地理围栏"""
        with self._lock:
            self._geofences[geofence.fence_id] = geofence
        logger.info(f"Geofence added: {geofence.fence_id}")
    
    def remove_geofence(self, fence_id: str) -> bool:
        """移除地理围栏"""
        with self._lock:
            if fence_id in self._geofences:
                del self._geofences[fence_id]
                return True
        return False
    
    def get_geofences(self) -> List[GeoFence]:
        """获取所有地理围栏"""
        with self._lock:
            return list(self._geofences.values())
    
    def check_geofence(self, lat: float, lon: float, altitude: float) -> Dict:
        """检查位置是否符合地理围栏规则"""
        result = {
            'compliant': True,
            'violations': []
        }
        
        with self._lock:
            for fence in self._geofences.values():
                if not fence.enabled:
                    continue
                
                if fence.fence_type == 'inclusion':
                    # 必须在围栏内
                    if not fence.contains(lat, lon):
                        result['compliant'] = False
                        result['violations'].append({
                            'fence_id': fence.fence_id,
                            'type': 'outside_inclusion',
                            'message': f"Outside inclusion zone: {fence.name}"
                        })
                else:
                    # 不能在围栏内
                    if fence.contains(lat, lon):
                        result['compliant'] = False
                        result['violations'].append({
                            'fence_id': fence.fence_id,
                            'type': 'inside_exclusion',
                            'message': f"Inside exclusion zone: {fence.name}"
                        })
                
                # 检查高度
                if not fence.check_altitude(altitude):
                    result['compliant'] = False
                    result['violations'].append({
                        'fence_id': fence.fence_id,
                        'type': 'altitude_violation',
                        'message': f"Altitude violation: {fence.name}"
                    })
        
        return result
    
    def update_drone_state(self, drone_id: str, state: DroneState) -> None:
        """更新无人机状态"""
        with self._lock:
            self._drone_states[drone_id] = state
        
        # 更新碰撞避免系统
        if drone_id == 'self':  # 本机
            self.collision_avoidance.update_drone_state(state)
        else:  # 其他无人机
            self.collision_avoidance.update_other_drones([state])
    
    def update_telemetry(
        self,
        drone_id: str,
        position: Position,
        velocity: Velocity,
        battery: float,
        signal_strength: float = 100.0
    ) -> None:
        """更新遥测数据"""
        # 创建无人机状态
        speed = math.sqrt(velocity.vx**2 + velocity.vy**2 + velocity.vz**2)
        heading = math.degrees(math.atan2(velocity.vy, velocity.vx)) if speed > 0.1 else 0
        
        state = DroneState(
            drone_id=drone_id,
            position=position,
            velocity=velocity,
            heading=heading,
            speed=speed
        )
        
        self.update_drone_state(drone_id, state)
        
        # 检查地理围栏
        # TODO: 需要将本地坐标转换为经纬度
        # geofence_result = self.check_geofence(lat, lon, position.z)
    
    def get_safety_level(self) -> SafetyLevel:
        """获取当前安全等级"""
        with self._lock:
            return self._safety_level
    
    def get_active_events(self) -> List[SafetyEvent]:
        """获取活动事件"""
        with self._lock:
            return list(self._active_events.values())
    
    def get_event_history(self, limit: int = 100) -> List[SafetyEvent]:
        """获取事件历史"""
        with self._lock:
            return list(self._event_history)[-limit:]
    
    def acknowledge_event(self, event_id: str) -> bool:
        """确认事件"""
        with self._lock:
            if event_id in self._active_events:
                self._active_events[event_id].acknowledge()
                return True
        return False
    
    def resolve_event(self, event_id: str, action: Optional[SafetyAction] = None) -> bool:
        """解决事件"""
        with self._lock:
            if event_id in self._active_events:
                self._active_events[event_id].resolve(action)
                # 从活动事件中移除
                del self._active_events[event_id]
                return True
        return False
    
    def get_logs(self, limit: int = 100, level: Optional[str] = None) -> List[SafetyLog]:
        """获取安全日志"""
        with self._lock:
            logs = list(self._safety_logs)
        
        if level:
            logs = [log for log in logs if log.level == level]
        
        return logs[-limit:]
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        with self._lock:
            stats = self._stats.copy()
            stats['current_safety_level'] = self._safety_level.value
            stats['active_events'] = len(self._active_events)
            stats['total_rules'] = len(self._rules)
            stats['total_geofences'] = len(self._geofences)
            return stats
    
    async def emergency_stop(self, drone_id: Optional[str] = None) -> None:
        """紧急停止"""
        await self._create_safety_event(
            SafetyEventType.EMERGENCY_BRAKE,
            SafetyLevel.EMERGENCY,
            "Manual emergency stop triggered",
            "Manual",
            {'drone_id': drone_id}
        )
        
        self._stats['emergencies'] += 1
        
        if self._on_emergency:
            await self._on_emergency('emergency_stop', None)
    
    async def force_return_home(self, drone_id: Optional[str] = None) -> None:
        """强制返航"""
        await self._create_safety_event(
            SafetyEventType.MANUAL_OVERRIDE,
            SafetyLevel.WARNING,
            "Manual return to home triggered",
            "Manual",
            {'drone_id': drone_id}
        )
        
        if self._on_emergency:
            await self._on_emergency('return_home', None)
    
    def set_callbacks(
        self,
        on_safety_event: Optional[Callable] = None,
        on_safety_level_change: Optional[Callable] = None,
        on_emergency: Optional[Callable] = None
    ) -> None:
        """设置回调函数"""
        self._on_safety_event = on_safety_event
        self._on_safety_level_change = on_safety_level_change
        self._on_emergency = on_emergency
    
    def export_logs(self, filepath: str) -> None:
        """导出日志到文件"""
        logs = self.get_logs(limit=10000)
        
        with open(filepath, 'w') as f:
            for log in logs:
                f.write(json.dumps(log.to_dict()) + '\n')
        
        logger.info(f"Logs exported to {filepath}")
    
    def export_events(self, filepath: str) -> None:
        """导出事件历史到文件"""
        events = self.get_event_history(limit=10000)
        
        with open(filepath, 'w') as f:
            for event in events:
                f.write(json.dumps(event.to_dict()) + '\n')
        
        logger.info(f"Events exported to {filepath}")
