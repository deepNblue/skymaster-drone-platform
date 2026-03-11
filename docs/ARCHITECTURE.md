# SkyMaster系统架构文档

## 1. 系统概述

SkyMaster是一个基于微服务架构的企业级无人机管控平台，采用前后端分离设计，支持大规模无人机集群的实时管控。

### 1.1 设计原则

- **模块化**: 各功能模块独立，低耦合
- **可扩展**: 水平扩展支持大规模部署
- **高可用**: 故障自动恢复，服务降级
- **实时性**: 低延迟数据传输和处理
- **安全性**: 多层次安全防护机制

---

## 2. 整体架构

### 2.1 架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                          客户端层                                 │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐               │
│  │  Web前端   │  │ 移动端App  │  │  第三方API │               │
│  │  (React)   │  │(React Native)│  │            │               │
│  └────────────┘  └────────────┘  └────────────┘               │
└─────────────────────────────────────────────────────────────────┘
                            ↕ HTTPS/WSS
┌─────────────────────────────────────────────────────────────────┐
│                        接入层 (Nginx)                            │
│  - 负载均衡                                                      │
│  - SSL终结                                                       │
│  - 静态资源                                                      │
└─────────────────────────────────────────────────────────────────┘
                            ↕
┌─────────────────────────────────────────────────────────────────┐
│                         API网关层                                │
│  - 请求路由                                                      │
│  - 认证授权                                                      │
│  - 限流控制                                                      │
│  - API版本管理                                                   │
└─────────────────────────────────────────────────────────────────┘
                            ↕
┌─────────────────────────────────────────────────────────────────┐
│                         服务层                                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐      │
│  │ 设备服务  │  │ 任务服务  │  │ 集群服务  │  │ 视频服务  │      │
│  │          │  │          │  │          │  │          │      │
│  │ MAVLink  │  │ 规划器    │  │ 控制器    │  │ WebRTC   │      │
│  │ 连接器   │  │ 执行器    │  │ 编队      │  │ RTSP     │      │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘      │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐      │
│  │ 数据服务  │  │ AI服务   │  │ 安全服务  │  │ 通知服务  │      │
│  │          │  │          │  │          │  │          │      │
│  │ 存储     │  │ 路径规划  │  │ 围栏      │  │ 推送     │      │
│  │ 分析     │  │ 避障      │  │ 权限      │  │ 告警     │      │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘      │
└─────────────────────────────────────────────────────────────────┘
                            ↕
┌─────────────────────────────────────────────────────────────────┐
│                        数据层                                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐      │
│  │PostgreSQL│  │TimescaleDB│  │  Redis   │  │ RabbitMQ │      │
│  │ 业务数据 │  │ 时序数据  │  │  缓存    │  │ 消息队列 │      │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘      │
│  ┌──────────┐  ┌──────────┐                                   │
│  │  MinIO   │  │Elasticsearch│                                │
│  │ 文件存储 │  │ 日志搜索  │                                   │
│  └──────────┘  └──────────┘                                   │
└─────────────────────────────────────────────────────────────────┘
                            ↕
┌─────────────────────────────────────────────────────────────────┐
│                        设备层                                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐      │
│  │   PX4    │  │ArduPilot │  │   DJI    │  │  其他    │      │
│  │  无人机  │  │  无人机  │  │  无人机  │  │MAVLink  │      │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. 核心模块详解

### 3.1 设备管理模块

**功能职责**:
- 无人机设备的注册、注销
- 连接状态管理
- 遥测数据接收和处理
- 命令发送和执行

**关键组件**:
```python
DeviceManager
├── DroneDevice (设备实体)
├── MAVLinkConnector (连接器抽象)
│   ├── PX4Connector
│   ├── ArduPilotConnector
│   └── DJIConnector
└── DeviceGroup (设备分组)
```

**数据流**:
```
无人机 → MAVLink → Connector → DeviceManager → WebSocket → 前端
```

**性能优化**:
- 异步I/O处理
- 连接池管理
- 遥测数据批量处理

---

### 3.2 任务规划模块

**功能职责**:
- 航点规划
- 航线生成
- 任务模板管理
- 任务验证和上传

**关键组件**:
```python
MissionPlanner
├── Mission (任务实体)
├── Waypoint (航点)
├── FormationGenerator (编队生成器)
└── TaskAllocator (任务分配器)
```

**航线生成算法**:
- **测绘网格**: 之字形扫描
- **圆形航线**: 圆周运动
- **巡逻航线**: 循环/往返

**任务验证**:
- 高度限制检查
- 距离限制检查
- 地理围栏检查
- 电池续航估算

---

### 3.3 集群控制模块

**功能职责**:
- 多机协同控制
- 编队飞行
- 任务分配
- 碰撞避免

**编队类型**:
- **直线编队**: 横向排列
- **V形编队**: 领机+僚机
- **圆形编队**: 环形分布
- **网格编队**: 矩阵分布

**碰撞避免**:
```
1. 实时监测无人机位置
2. 计算两两距离
3. 距离<阈值 → 生成避碰向量
4. 调整飞行路径
```

**任务分配策略**:
- **最近分配**: 将航点分配给最近的无人机
- **平衡分配**: 均匀分配航点
- **能力分配**: 根据无人机能力分配

---

### 3.4 视频服务模块

**架构**:
```
无人机摄像头
    ↓
RTSP服务器 (MediaMTX)
    ↓
WebRTC网关
    ↓
浏览器 (HLS.js/Video.js)
```

**支持协议**:
- RTSP (实时流协议)
- RTMP (实时消息协议)
- WebRTC (点对点通信)
- HLS (HTTP直播流)

---

### 3.5 数据分析模块

**遥测数据存储** (TimescaleDB):
```sql
CREATE TABLE telemetry (
    time        TIMESTAMPTZ NOT NULL,
    device_id   VARCHAR(50) NOT NULL,
    latitude    DOUBLE PRECISION,
    longitude   DOUBLE PRECISION,
    altitude    DOUBLE PRECISION,
    speed       DOUBLE PRECISION,
    battery     INTEGER,
    ...
);

SELECT create_hypertable('telemetry', 'time');
```

**数据分析功能**:
- 飞行轨迹回放
- 性能指标统计
- 异常检测
- AI辅助分析

---

### 3.6 安全管理模块

**地理围栏** (Geofencing):
```python
class Geofence:
    - 多边形围栏
    - 圆形围栏
    - 高度限制
    - 进入/离开触发
```

**安全保护机制**:
- 失联自动返航 (RTL)
- 低电量保护
- 飞行区域限制
- 权限验证

---

## 4. 数据模型

### 4.1 核心实体关系

```
Device (无人机)
  ├── has_many → Telemetry (遥测数据)
  ├── has_many → Mission (任务)
  └── belongs_to → Swarm (集群)

Mission (任务)
  ├── has_many → Waypoint (航点)
  └── belongs_to → Device

Swarm (集群)
  └── has_many → Device
```

### 4.2 数据库Schema

```sql
-- 设备表
CREATE TABLE devices (
    id              SERIAL PRIMARY KEY,
    device_id       VARCHAR(50) UNIQUE NOT NULL,
    name            VARCHAR(100),
    drone_type      VARCHAR(20),
    connection_string VARCHAR(255),
    status          VARCHAR(20),
    created_at      TIMESTAMP,
    updated_at      TIMESTAMP
);

-- 遥测数据表 (TimescaleDB)
CREATE TABLE telemetry (
    time            TIMESTAMPTZ NOT NULL,
    device_id       VARCHAR(50) NOT NULL,
    latitude        DOUBLE PRECISION,
    longitude       DOUBLE PRECISION,
    altitude        DOUBLE PRECISION,
    speed           DOUBLE PRECISION,
    battery         INTEGER,
    flight_mode     VARCHAR(50),
    armed           BOOLEAN
);

SELECT create_hypertable('telemetry', 'time');

-- 任务表
CREATE TABLE missions (
    id              SERIAL PRIMARY KEY,
    mission_id      VARCHAR(50) UNIQUE NOT NULL,
    name            VARCHAR(100),
    mission_type    VARCHAR(20),
    device_id       VARCHAR(50),
    status          VARCHAR(20),
    waypoints       JSONB,
    created_at      TIMESTAMP,
    executed_at     TIMESTAMP
);

-- 集群表
CREATE TABLE swarms (
    id              SERIAL PRIMARY KEY,
    swarm_id        VARCHAR(50) UNIQUE NOT NULL,
    name            VARCHAR(100),
    formation_type  VARCHAR(20),
    device_ids      JSONB,
    created_at      TIMESTAMP
);
```

---

## 5. 通信协议

### 5.1 MAVLink协议

**消息类型**:
- `HEARTBEAT` - 心跳包
- `GLOBAL_POSITION_INT` - 全局位置
- `ATTITUDE` - 姿态
- `SYS_STATUS` - 系统状态
- `COMMAND_LONG` - 命令

**消息流程**:
```
GCS (地面站) ←→ MAVLink ←→ 无人机
```

### 5.2 WebSocket协议

**消息格式**:
```json
{
  "type": "telemetry",
  "device_id": "drone_001",
  "data": {...},
  "timestamp": "2026-03-11T12:00:00Z"
}
```

**订阅机制**:
```javascript
// 客户端订阅
ws.send({
  "type": "subscribe_telemetry",
  "device_id": "drone_001"
});

// 服务器推送
ws.send({
  "type": "telemetry",
  "device_id": "drone_001",
  "data": {...}
});
```

### 5.3 REST API

**认证**:
```
Authorization: Bearer <JWT_TOKEN>
```

**标准响应**:
```json
{
  "success": true,
  "data": {...},
  "message": "Operation successful",
  "timestamp": "2026-03-11T12:00:00Z"
}
```

---

## 6. 性能优化

### 6.1 数据库优化

- **索引**: 在device_id, time字段上建立索引
- **分区**: TimescaleDB自动分区
- **连接池**: 使用连接池管理
- **查询优化**: 避免N+1查询

### 6.2 缓存策略

```python
# Redis缓存
- 设备状态: 5秒过期
- 任务数据: 1小时过期
- 用户会话: 30分钟过期
```

### 6.3 异步处理

```python
# Celery任务队列
- 飞行日志处理
- 数据分析任务
- 报告生成
- 邮件通知
```

### 6.4 负载均衡

```
Nginx → API Gateway → [Backend1, Backend2, Backend3]
```

---

## 7. 安全机制

### 7.1 认证授权

- **JWT认证**: 无状态认证
- **RBAC**: 基于角色的访问控制
- **API密钥**: 第三方应用访问

### 7.2 数据安全

- **HTTPS**: 加密传输
- **数据库加密**: 敏感数据加密
- **日志脱敏**: 隐藏敏感信息

### 7.3 网络安全

- **防火墙**: 端口限制
- **DDoS防护**: 限流和黑名单
- **VPN**: 内部通信加密

---

## 8. 监控运维

### 8.1 监控指标

- **系统指标**: CPU、内存、磁盘、网络
- **应用指标**: 请求量、响应时间、错误率
- **业务指标**: 在线设备数、飞行时长、任务完成率

### 8.2 日志管理

```
应用日志 → Filebeat → Logstash → Elasticsearch → Kibana
```

### 8.3 告警机制

- **邮件告警**: 严重错误
- **短信告警**: 紧急故障
- **Webhook**: 集成第三方系统

---

## 9. 部署架构

### 9.1 开发环境

```
单机部署:
  - Docker Compose
  - 所有服务在一台机器
```

### 9.2 生产环境

```
高可用部署:
  - 负载均衡 (Nginx)
  - 多实例后端 (3+)
  - 数据库主从复制
  - Redis Sentinel
  - 消息队列集群
```

### 9.3 云原生部署

```
Kubernetes:
  - Deployment (无状态服务)
  - StatefulSet (有状态服务)
  - Service (服务发现)
  - Ingress (入口控制)
  - ConfigMap/Secret (配置管理)
```

---

## 10. 扩展性设计

### 10.1 水平扩展

- 无状态服务可水平扩展
- 数据库读写分离
- 缓存集群
- 消息队列分区

### 10.2 插件机制

```python
# 设备驱动插件
class DeviceDriver(ABC):
    @abstractmethod
    async def connect(self):
        pass
    
    @abstractmethod
    async def send_command(self):
        pass

# 注册插件
driver_registry.register('dji_mavic', DJIMavicDriver)
```

### 10.3 API扩展

- 支持自定义API端点
- Webhook回调
- GraphQL支持

---

## 11. 未来规划

### v1.1
- AI路径规划
- 视觉SLAM
- 边缘计算

### v2.0
- 数字孪生
- 5G网络优化
- 多域协同

---

**文档版本**: 1.0.0  
**最后更新**: 2026-03-11  
**维护者**: SkyMaster架构团队
