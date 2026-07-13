# SkyMaster API 文档

## 概述

SkyMaster API 提供了完整的无人机管控平台接口，支持设备管理、任务规划、集群控制、数据查询等功能。

**基础信息**:
- **Base URL**: `https://api.skymaster.io/v1`
- **协议**: HTTPS
- **数据格式**: JSON
- **字符编码**: UTF-8
- **API版本**: v1.0.0

---

## 认证

### JWT Token 认证

SkyMaster API 使用 JWT (JSON Web Token) 进行身份认证。

**获取Token**:
```http
POST /auth/login
Content-Type: application/json

{
  "username": "admin@skymaster.io",
  "password": "your_password"
}
```

**响应**:
```json
{
  "success": true,
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "expires_in": 3600,
    "token_type": "Bearer"
  },
  "message": "登录成功",
  "timestamp": "2026-03-11T12:00:00Z"
}
```

**使用Token**:
```http
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### API Key 认证

用于第三方应用访问。

```http
X-API-Key: sk_live_abc123def456
```

---

## 通用响应格式

### 成功响应

```json
{
  "success": true,
  "data": {
    // 响应数据
  },
  "message": "操作成功",
  "timestamp": "2026-03-11T12:00:00Z"
}
```

### 错误响应

```json
{
  "success": false,
  "error": {
    "code": "DEVICE_NOT_FOUND",
    "message": "设备不存在",
    "details": {
      "device_id": "drone_001"
    }
  },
  "timestamp": "2026-03-11T12:00:00Z"
}
```

---

## 错误码说明

### HTTP状态码

| 状态码 | 说明 |
|--------|------|
| 200 | 请求成功 |
| 201 | 资源创建成功 |
| 204 | 删除成功（无内容） |
| 400 | 请求参数错误 |
| 401 | 未授权（未登录） |
| 403 | 禁止访问（权限不足） |
| 404 | 资源不存在 |
| 409 | 资源冲突 |
| 422 | 请求格式正确，但语义错误 |
| 429 | 请求过于频繁 |
| 500 | 服务器内部错误 |
| 503 | 服务不可用 |

### 业务错误码

| 错误码 | 说明 | HTTP状态码 |
|--------|------|-----------|
| AUTH_FAILED | 认证失败 | 401 |
| INVALID_TOKEN | Token无效 | 401 |
| TOKEN_EXPIRED | Token已过期 | 401 |
| PERMISSION_DENIED | 权限不足 | 403 |
| DEVICE_NOT_FOUND | 设备不存在 | 404 |
| MISSION_NOT_FOUND | 任务不存在 | 404 |
| SWARM_NOT_FOUND | 集群不存在 | 404 |
| DEVICE_OFFLINE | 设备离线 | 400 |
| MISSION_EXECUTING | 任务执行中 | 409 |
| BATTERY_LOW | 电池电量低 | 400 |
| GEOFENCE_VIOLATION | 违反地理围栏 | 403 |
| CONNECTION_FAILED | 连接失败 | 500 |
| COMMAND_FAILED | 命令执行失败 | 500 |
| VALIDATION_ERROR | 数据验证失败 | 422 |
| RATE_LIMIT_EXCEEDED | 超出限流 | 429 |

---

## API端点列表

### 认证相关 (5个端点)

#### 1. 用户登录

```http
POST /auth/login
```

**请求体**:
```json
{
  "username": "admin@skymaster.io",
  "password": "your_password"
}
```

**响应**: 参见[认证](#认证)章节

---

#### 2. 刷新Token

```http
POST /auth/refresh
```

**请求头**:
```http
Authorization: Bearer <refresh_token>
```

**响应**:
```json
{
  "success": true,
  "data": {
    "access_token": "eyJhbGci...",
    "expires_in": 3600
  }
}
```

---

#### 3. 用户登出

```http
POST /auth/logout
```

**响应**:
```json
{
  "success": true,
  "message": "登出成功"
}
```

---

#### 4. 获取当前用户信息

```http
GET /auth/me
```

**响应**:
```json
{
  "success": true,
  "data": {
    "user_id": "user_001",
    "username": "admin@skymaster.io",
    "role": "admin",
    "permissions": ["device:read", "device:write", "mission:execute"],
    "created_at": "2025-01-01T00:00:00Z"
  }
}
```

---

#### 5. 修改密码

```http
PUT /auth/password
```

**请求体**:
```json
{
  "old_password": "old_pass",
  "new_password": "new_pass123"
}
```

---

### 设备管理 (8个端点)

#### 6. 获取设备列表

```http
GET /api/devices
```

**查询参数**:
- `status` (可选): 设备状态 (online/offline/all)
- `drone_type` (可选): 无人机类型 (px4/ardupilot/dji)
- `page` (可选): 页码，默认1
- `per_page` (可选): 每页数量，默认20

**响应**:
```json
{
  "success": true,
  "data": {
    "devices": [
      {
        "device_id": "drone_001",
        "name": "Alpha Drone",
        "drone_type": "px4",
        "status": "online",
        "connection_string": "udp:192.168.1.100:14550",
        "last_seen": "2026-03-11T12:00:00Z",
        "battery": 85,
        "flight_mode": "HOLD",
        "armed": false,
        "position": {
          "latitude": 39.9042,
          "longitude": 116.4074,
          "altitude": 50.5
        }
      }
    ],
    "total": 10,
    "page": 1,
    "per_page": 20
  }
}
```

---

#### 7. 注册新设备

```http
POST /api/devices
```

**请求体**:
```json
{
  "device_id": "drone_002",
  "name": "Beta Drone",
  "drone_type": "px4",
  "connection_string": "udp:192.168.1.101:14550",
  "description": "测绘无人机",
  "config": {
    "max_speed": 15.0,
    "max_altitude": 120.0,
    "battery_capacity": 5000
  }
}
```

**响应**:
```json
{
  "success": true,
  "data": {
    "device_id": "drone_002",
    "name": "Beta Drone",
    "status": "offline",
    "created_at": "2026-03-11T12:00:00Z"
  },
  "message": "设备注册成功"
}
```

---

#### 8. 获取设备详情

```http
GET /api/devices/{device_id}
```

**响应**:
```json
{
  "success": true,
  "data": {
    "device_id": "drone_001",
    "name": "Alpha Drone",
    "drone_type": "px4",
    "status": "online",
    "connection_string": "udp:192.168.1.100:14550",
    "battery": 85,
    "flight_mode": "HOLD",
    "armed": false,
    "position": {
      "latitude": 39.9042,
      "longitude": 116.4074,
      "altitude": 50.5,
      "relative_altitude": 50.0
    },
    "attitude": {
      "roll": 0.5,
      "pitch": -1.2,
      "yaw": 45.0
    },
    "velocity": {
      "vx": 5.0,
      "vy": 2.0,
      "vz": 0.0
    },
    "gps_info": {
      "fix_type": 3,
      "satellites": 12,
      "hdop": 0.8
    },
    "home_position": {
      "latitude": 39.9040,
      "longitude": 116.4070,
      "altitude": 50.0
    },
    "last_seen": "2026-03-11T12:00:00Z"
  }
}
```

---

#### 9. 连接设备

```http
POST /api/devices/{device_id}/connect
```

**响应**:
```json
{
  "success": true,
  "data": {
    "device_id": "drone_001",
    "status": "connecting",
    "message": "正在连接设备..."
  }
}
```

---

#### 10. 断开设备连接

```http
POST /api/devices/{device_id}/disconnect
```

---

#### 11. 解锁设备

```http
POST /api/devices/{device_id}/arm
```

**响应**:
```json
{
  "success": true,
  "data": {
    "device_id": "drone_001",
    "armed": true,
    "message": "设备已解锁"
  }
}
```

---

#### 12. 上锁设备

```http
POST /api/devices/{device_id}/disarm
```

---

#### 13. 更新设备信息

```http
PUT /api/devices/{device_id}
```

**请求体**:
```json
{
  "name": "Updated Drone Name",
  "description": "更新后的描述"
}
```

---

### 任务管理 (7个端点)

#### 14. 获取任务列表

```http
GET /api/missions
```

**查询参数**:
- `status` (可选): 任务状态
- `device_id` (可选): 设备ID
- `mission_type` (可选): 任务类型

**响应**:
```json
{
  "success": true,
  "data": {
    "missions": [
      {
        "mission_id": "mission_001",
        "name": "Survey Mission",
        "mission_type": "survey",
        "status": "pending",
        "device_id": "drone_001",
        "waypoints_count": 15,
        "created_at": "2026-03-11T12:00:00Z",
        "executed_at": null,
        "completed_at": null
      }
    ],
    "total": 5
  }
}
```

---

#### 15. 创建任务

```http
POST /api/missions
```

**请求体**:
```json
{
  "mission_id": "mission_002",
  "name": "Area Survey",
  "mission_type": "survey",
  "device_id": "drone_001",
  "waypoints": [
    {
      "waypoint_id": "wp_001",
      "sequence": 1,
      "position": {
        "latitude": 39.9042,
        "longitude": 116.4074,
        "altitude": 50
      },
      "speed": 5.0,
      "hold_time": 3.0,
      "actions": [
        {
          "type": "take_photo",
          "params": {}
        }
      ]
    },
    {
      "waypoint_id": "wp_002",
      "sequence": 2,
      "position": {
        "latitude": 39.9050,
        "longitude": 116.4080,
        "altitude": 50
      },
      "speed": 5.0
    }
  ],
  "settings": {
    "return_to_home": true,
    "max_flight_time": 1800
  }
}
```

**响应**:
```json
{
  "success": true,
  "data": {
    "mission_id": "mission_002",
    "name": "Area Survey",
    "status": "created",
    "waypoints_count": 2,
    "created_at": "2026-03-11T12:00:00Z"
  },
  "message": "任务创建成功"
}
```

---

#### 16. 获取任务详情

```http
GET /api/missions/{mission_id}
```

---

#### 17. 上传任务到设备

```http
POST /api/missions/{mission_id}/upload/{device_id}
```

**响应**:
```json
{
  "success": true,
  "data": {
    "mission_id": "mission_002",
    "device_id": "drone_001",
    "upload_status": "success",
    "waypoints_uploaded": 2
  },
  "message": "任务上传成功"
}
```

---

#### 18. 开始执行任务

```http
POST /api/missions/{mission_id}/execute
```

**请求体**:
```json
{
  "device_id": "drone_001",
  "start_immediately": true
}
```

---

#### 19. 暂停任务

```http
POST /api/missions/{mission_id}/pause
```

---

#### 20. 取消任务

```http
POST /api/missions/{mission_id}/cancel
```

---

### 飞行控制 (6个端点)

#### 21. 起飞

```http
POST /api/devices/{device_id}/takeoff
```

**请求体**:
```json
{
  "altitude": 50.0
}
```

**响应**:
```json
{
  "success": true,
  "data": {
    "device_id": "drone_001",
    "command": "takeoff",
    "target_altitude": 50.0,
    "status": "executing"
  },
  "message": "起飞命令已发送"
}
```

---

#### 22. 降落

```http
POST /api/devices/{device_id}/land
```

---

#### 23. 返航

```http
POST /api/devices/{device_id}/rtl
```

**请求体**:
```json
{
  "rtl_altitude": 50.0
}
```

---

#### 24. 悬停

```http
POST /api/devices/{device_id}/hold
```

---

#### 25. 飞往指定位置

```http
POST /api/devices/{device_id}/goto
```

**请求体**:
```json
{
  "latitude": 39.9050,
  "longitude": 116.4080,
  "altitude": 60.0,
  "speed": 10.0
}
```

---

#### 26. 设置飞行模式

```http
POST /api/devices/{device_id}/mode
```

**请求体**:
```json
{
  "mode": "AUTO"
}
```

**支持的飞行模式**:
- `MANUAL` - 手动模式
- `STABILIZE` - 自稳模式
- `ALT_HOLD` - 定高模式
- `LOITER` - 悬停模式
- `AUTO` - 自动模式
- `RTL` - 返航模式
- `LAND` - 降落模式
- `GUIDED` - 引导模式

---

### 集群管理 (5个端点)

#### 27. 创建集群

```http
POST /api/swarms
```

**请求体**:
```json
{
  "swarm_id": "swarm_001",
  "name": "Alpha Team",
  "formation_type": "v_shape",
  "device_ids": ["drone_001", "drone_002", "drone_003"],
  "config": {
    "spacing": 10.0,
    "angle": 45.0
  }
}
```

**响应**:
```json
{
  "success": true,
  "data": {
    "swarm_id": "swarm_001",
    "name": "Alpha Team",
    "formation_type": "v_shape",
    "device_count": 3,
    "status": "created",
    "created_at": "2026-03-11T12:00:00Z"
  },
  "message": "集群创建成功"
}
```

---

#### 28. 获取集群列表

```http
GET /api/swarms
```

---

#### 29. 获取集群详情

```http
GET /api/swarms/{swarm_id}
```

---

#### 30. 编队成形

```http
POST /api/swarms/{swarm_id}/form
```

**请求体**:
```json
{
  "center_position": {
    "latitude": 39.9042,
    "longitude": 116.4074,
    "altitude": 50.0
  },
  "heading": 0.0
}
```

**响应**:
```json
{
  "success": true,
  "data": {
    "swarm_id": "swarm_001",
    "status": "forming",
    "positions": {
      "drone_001": {"latitude": 39.9042, "longitude": 116.4074, "altitude": 50.0},
      "drone_002": {"latitude": 39.9043, "longitude": 116.4075, "altitude": 50.0},
      "drone_003": {"latitude": 39.9043, "longitude": 116.4073, "altitude": 50.0}
    }
  },
  "message": "编队成形中..."
}
```

---

#### 31. 集群移动

```http
POST /api/swarms/{swarm_id}/move
```

**请求体**:
```json
{
  "target_position": {
    "latitude": 39.9100,
    "longitude": 116.4100,
    "altitude": 60.0
  },
  "speed": 10.0,
  "maintain_formation": true
}
```

---

### 数据查询 (5个端点)

#### 32. 获取遥测数据

```http
GET /api/telemetry/{device_id}
```

**查询参数**:
- `start_time` (必需): 开始时间 (ISO 8601)
- `end_time` (必需): 结束时间 (ISO 8601)
- `interval` (可选): 采样间隔 (秒)

**响应**:
```json
{
  "success": true,
  "data": {
    "device_id": "drone_001",
    "records": [
      {
        "time": "2026-03-11T12:00:00Z",
        "latitude": 39.9042,
        "longitude": 116.4074,
        "altitude": 50.5,
        "speed": 5.2,
        "battery": 85,
        "flight_mode": "AUTO"
      }
    ],
    "total_records": 3600
  }
}
```

---

#### 33. 获取飞行轨迹

```http
GET /api/telemetry/{device_id}/trajectory
```

**查询参数**:
- `start_time`: 开始时间
- `end_time`: 结束时间
- `simplify` (可选): 轨迹简化 (true/false)

---

#### 34. 获取飞行统计

```http
GET /api/statistics/{device_id}
```

**查询参数**:
- `period`: 统计周期 (day/week/month/year)

**响应**:
```json
{
  "success": true,
  "data": {
    "device_id": "drone_001",
    "period": "month",
    "statistics": {
      "total_flights": 15,
      "total_distance": 125.5,
      "total_flight_time": 1800,
      "average_battery_consumption": 45,
      "max_altitude": 120.0,
      "max_speed": 15.0
    }
  }
}
```

---

#### 35. 获取飞行日志

```http
GET /api/logs/{device_id}
```

**查询参数**:
- `start_time`: 开始时间
- `end_time`: 结束时间
- `log_level` (可选): 日志级别 (info/warning/error)

---

#### 36. 获取系统事件

```http
GET /api/events
```

**查询参数**:
- `event_type` (可选): 事件类型
- `device_id` (可选): 设备ID
- `start_time`: 开始时间
- `end_time`: 结束时间

---

### 安全管理 (4个端点)

#### 37. 创建地理围栏

```http
POST /api/geofences
```

**请求体**:
```json
{
  "geofence_id": "gf_001",
  "name": "Airport Restriction",
  "type": "polygon",
  "coordinates": [
    [116.4000, 39.9000],
    [116.4100, 39.9000],
    [116.4100, 39.9100],
    [116.4000, 39.9100]
  ],
  "min_altitude": 0,
  "max_altitude": 120,
  "action": "forbid"
}
```

---

#### 38. 获取地理围栏列表

```http
GET /api/geofences
```

---

#### 39. 检查位置合规性

```http
POST /api/geofences/check
```

**请求体**:
```json
{
  "latitude": 39.9050,
  "longitude": 116.4050,
  "altitude": 50.0
}
```

**响应**:
```json
{
  "success": true,
  "data": {
    "compliant": false,
    "violations": [
      {
        "geofence_id": "gf_001",
        "name": "Airport Restriction",
        "type": "forbidden_area"
      }
    ]
  }
}
```

---

#### 40. 获取安全事件

```http
GET /api/safety/events
```

---

## WebSocket API

### 连接

```
wss://api.skymaster.io/ws
```

**认证**:
```javascript
ws.send(JSON.stringify({
  "type": "auth",
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}));
```

### 订阅消息

#### 订阅遥测数据

```javascript
ws.send(JSON.stringify({
  "type": "subscribe_telemetry",
  "device_id": "drone_001"
}));
```

#### 接收遥测数据

```json
{
  "type": "telemetry",
  "device_id": "drone_001",
  "data": {
    "latitude": 39.9042,
    "longitude": 116.4074,
    "altitude": 50.5,
    "battery": 85,
    "flight_mode": "AUTO"
  },
  "timestamp": "2026-03-11T12:00:00Z"
}
```

### 订阅设备状态

```javascript
ws.send(JSON.stringify({
  "type": "subscribe_device_status",
  "device_id": "drone_001"
}));
```

### 订阅任务事件

```javascript
ws.send(JSON.stringify({
  "type": "subscribe_mission_events",
  "mission_id": "mission_001"
}));
```

---

## 限流策略

| API类型 | 限制 | 时间窗口 |
|---------|------|----------|
| 认证API | 10次 | 1分钟 |
| 查询API | 100次 | 1分钟 |
| 控制API | 30次 | 1分钟 |
| WebSocket连接 | 5个 | - |

**限流响应**:
```json
{
  "success": false,
  "error": {
    "code": "RATE_LIMIT_EXCEEDED",
    "message": "请求过于频繁，请稍后再试",
    "retry_after": 60
  }
}
```

---

## API版本控制

- **当前版本**: v1
- **版本策略**: URL路径版本控制
- **向后兼容**: 至少支持2个主要版本

**弃用通知**:
```http
Deprecation: true
Sunset: Sat, 01 Jan 2027 00:00:00 GMT
Link: </v2/endpoint>; rel="successor-version"
```

---

## SDK示例

### Python SDK

```python
from skymaster import SkyMasterClient

# 初始化客户端
client = SkyMasterClient(
    api_key="sk_live_abc123",
    base_url="https://api.skymaster.io/v1"
)

# 获取设备列表
devices = client.devices.list(status="online")

# 创建任务
mission = client.missions.create(
    mission_id="mission_001",
    name="Survey Mission",
    waypoints=[...]
)

# 执行任务
client.missions.execute(mission.mission_id, device_id="drone_001")
```

### JavaScript SDK

```javascript
import { SkyMasterClient } from '@skymaster/sdk';

const client = new SkyMasterClient({
  apiKey: 'sk_live_abc123',
  baseUrl: 'https://api.skymaster.io/v1'
});

// 获取设备
const device = await client.devices.get('drone_001');

// 起飞
await client.devices.takeoff('drone_001', { altitude: 50 });

// WebSocket连接
const ws = client.websocket.connect();
ws.subscribe('telemetry', 'drone_001', (data) => {
  console.log('Telemetry:', data);
});
```

---

## 常见问题

### Q: Token过期如何处理？

A: 使用refresh_token刷新access_token，或在请求返回401时重新登录。

### Q: 如何批量操作设备？

A: 使用集群API或将多个操作放入队列异步执行。

### Q: 遥测数据如何存储？

A: 遥测数据存储在TimescaleDB时序数据库中，默认保留90天。

### Q: API支持GraphQL吗？

A: v2版本将支持GraphQL，当前版本仅支持REST API。

---

## 更新日志

### v1.0.0 (2026-03-11)
- 初始版本发布
- 支持设备管理、任务规划、集群控制等核心功能
- 提供WebSocket实时通信
- 完整的认证授权机制

---

**文档版本**: 1.0.0  
**最后更新**: 2026-03-11  
**维护者**: SkyMaster API团队
