# SkyMaster 开发者指南

## 目录

- [开发环境搭建](#开发环境搭建)
- [项目结构](#项目结构)
- [技术栈](#技术栈)
- [代码规范](#代码规范)
- [开发流程](#开发流程)
- [测试指南](#测试指南)
- [调试技巧](#调试技巧)
- [性能优化](#性能优化)
- [贡献指南](#贡献指南)

---

## 开发环境搭建

### 系统要求

- **操作系统**: Linux (Ubuntu 20.04+), macOS 10.15+, Windows 10+ (WSL2)
- **内存**: 最低8GB，推荐16GB
- **存储**: 至少20GB可用空间
- **CPU**: 4核及以上

### 必需软件

#### Python环境

```bash
# 安装Python 3.9+
sudo apt update
sudo apt install -y python3.9 python3.9-venv python3-pip

# 或使用pyenv管理多版本
curl https://pyenv.run | bash
pyenv install 3.9.7
pyenv global 3.9.7
```

#### Node.js环境

```bash
# 安装Node.js 18+
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs

# 或使用nvm
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash
nvm install 18
nvm use 18
```

#### Docker & Docker Compose

```bash
# 安装Docker
curl -fsSL https://get.docker.com | bash

# 安装Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/download/v2.20.0/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# 添加当前用户到docker组
sudo usermod -aG docker $USER
```

#### 数据库

```bash
# PostgreSQL 13+
sudo apt install -y postgresql-13 postgresql-contrib-13

# Redis 6+
sudo apt install -y redis-server
```

### 克隆项目

```bash
# 克隆仓库
git clone https://github.com/your-org/skymaster-drone-platform.git
cd skymaster-drone-platform

# 查看分支
git branch -a

# 切换到开发分支
git checkout develop
```

### 后端环境配置

#### 1. 创建虚拟环境

```bash
cd backend

# 创建虚拟环境
python3.9 -m venv venv

# 激活虚拟环境
source venv/bin/activate  # Linux/macOS
# 或 venv\Scripts\activate  # Windows
```

#### 2. 安装依赖

```bash
# 升级pip
pip install --upgrade pip setuptools wheel

# 安装开发依赖
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

#### 3. 配置环境变量

```bash
# 复制示例配置
cp .env.example .env

# 编辑配置文件
nano .env
```

```bash
# .env
ENVIRONMENT=development
DEBUG=true
DATABASE_URL=postgresql://skymaster:password@localhost:5432/skymaster_dev
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=dev-secret-key-not-for-production
JWT_SECRET_KEY=dev-jwt-secret-key
LOG_LEVEL=DEBUG
```

#### 4. 初始化数据库

```bash
# 创建数据库
createdb skymaster_dev

# 运行迁移
alembic upgrade head

# 导入初始数据
python scripts/seed_data.py
```

#### 5. 启动开发服务器

```bash
# 使用uvicorn
uvicorn api.v1.main:app --reload --host 0.0.0.0 --port 8000

# 或使用启动脚本
./scripts/dev.sh
```

### 前端环境配置

#### 1. 安装依赖

```bash
cd frontend

# 安装npm依赖
npm install
```

#### 2. 配置环境变量

```bash
# 创建环境配置
cp .env.example .env.local

# 编辑配置
nano .env.local
```

```bash
# .env.local
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws
NEXT_PUBLIC_MAP_TOKEN=your-dev-map-token
```

#### 3. 启动开发服务器

```bash
# 开发模式
npm run dev

# 访问 http://localhost:3000
```

### IDE配置

#### VS Code推荐扩展

```json
{
  "recommendations": [
    "ms-python.python",
    "ms-python.vscode-pylance",
    "dbaeumer.vscode-eslint",
    "esbenp.prettier-vscode",
    "ms-azuretools.vscode-docker",
    "GraphQL.vscode-graphql",
    "bradlc.vscode-tailwindcss"
  ]
}
```

#### Python配置 (settings.json)

```json
{
  "python.linting.enabled": true,
  "python.linting.pylintEnabled": true,
  "python.linting.flake8Enabled": true,
  "python.formatting.provider": "black",
  "python.formatting.blackArgs": ["--line-length=100"],
  "editor.formatOnSave": true,
  "python.testing.pytestEnabled": true,
  "python.testing.unittestEnabled": false
}
```

#### ESLint配置 (.eslintrc.js)

```javascript
module.exports = {
  extends: [
    'eslint:recommended',
    'plugin:react/recommended',
    'plugin:@typescript-eslint/recommended',
    'prettier'
  ],
  rules: {
    'react/react-in-jsx-scope': 'off',
    '@typescript-eslint/explicit-module-boundary-types': 'off'
  }
};
```

---

## 项目结构

### 整体结构

```
skymaster-drone-platform/
├── backend/              # 后端代码
│   ├── api/             # API端点
│   ├── core/            # 核心模块
│   ├── models/          # 数据模型
│   ├── schemas/         # Pydantic模式
│   ├── services/        # 业务逻辑
│   ├── tests/           # 测试代码
│   ├── utils/           # 工具函数
│   ├── config.py        # 配置文件
│   └── requirements.txt  # 依赖列表
├── frontend/            # 前端代码
│   ├── src/
│   │   ├── components/  # React组件
│   │   ├── pages/       # 页面
│   │   ├── hooks/       # 自定义Hooks
│   │   ├── services/    # API服务
│   │   ├── stores/      # 状态管理
│   │   ├── utils/       # 工具函数
│   │   └── types/       # TypeScript类型
│   ├── public/          # 静态资源
│   └── package.json     # 依赖配置
├── docker/              # Docker配置
│   ├── docker-compose.yml
│   └── Dockerfile
├── docs/                # 文档
├── scripts/             # 脚本工具
└── tests/               # 集成测试
```

### 后端结构详解

```
backend/
├── api/
│   ├── v1/
│   │   ├── __init__.py
│   │   ├── main.py          # FastAPI应用
│   │   ├── devices.py       # 设备API
│   │   ├── missions.py      # 任务API
│   │   ├── swarm.py         # 集群API
│   │   └── telemetry.py     # 遥测API
│   └── dependencies.py      # 依赖注入
├── core/
│   ├── devices/
│   │   ├── manager.py       # 设备管理器
│   │   └── device.py        # 设备实体
│   ├── mavlink/
│   │   ├── connector.py     # MAVLink连接器
│   │   └── parser.py        # 消息解析
│   ├── missions/
│   │   ├── planner.py       # 任务规划器
│   │   └── executor.py      # 任务执行器
│   ├── swarm/
│   │   ├── controller.py    # 集群控制器
│   │   └── formation.py     # 编队管理
│   ├── safety/
│   │   ├── geofence.py      # 地理围栏
│   │   └── collision.py     # 碰撞检测
│   └── planning/
│       ├── path_planner.py  # 路径规划
│       └── terrain.py       # 地形分析
├── models/
│   ├── device.py            # 设备模型
│   ├── mission.py           # 任务模型
│   ├── swarm.py             # 集群模型
│   └── user.py              # 用户模型
├── schemas/
│   ├── device.py            # 设备模式
│   ├── mission.py           # 任务模式
│   └── user.py              # 用户模式
├── services/
│   ├── auth.py              # 认证服务
│   ├── notification.py      # 通知服务
│   └── analytics.py         # 分析服务
├── tests/
│   ├── unit/                # 单元测试
│   ├── integration/         # 集成测试
│   └── conftest.py          # Pytest配置
└── utils/
    ├── logger.py            # 日志工具
    ├── validators.py        # 验证器
    └── helpers.py           # 辅助函数
```

### 前端结构详解

```
frontend/src/
├── components/
│   ├── common/              # 通用组件
│   │   ├── Button/
│   │   ├── Input/
│   │   └── Modal/
│   ├── map/                 # 地图组件
│   │   ├── Map3D/
│   │   ├── DeviceMarker/
│   │   └── Trajectory/
│   ├── dashboard/           # 仪表盘组件
│   │   ├── TelemetryPanel/
│   │   ├── BatteryGauge/
│   │   └── AttitudeIndicator/
│   └── mission/             # 任务组件
│       ├── WaypointEditor/
│       ├── MissionList/
│       └── MissionTimeline/
├── pages/
│   ├── Dashboard/           # 仪表盘页面
│   ├── Devices/             # 设备页面
│   ├── Missions/            # 任务页面
│   ├── Swarm/               # 集群页面
│   └── Settings/            # 设置页面
├── hooks/
│   ├── useWebSocket.ts      # WebSocket Hook
│   ├── useDevice.ts         # 设备Hook
│   ├── useMission.ts        # 任务Hook
│   └── useMap.ts            # 地图Hook
├── services/
│   ├── api.ts               # API客户端
│   ├── websocket.ts         # WebSocket客户端
│   ├── deviceService.ts     # 设备服务
│   └── missionService.ts    # 任务服务
├── stores/
│   ├── deviceStore.ts       # 设备状态
│   ├── missionStore.ts      # 任务状态
│   ├── swarmStore.ts        # 集群状态
│   └── uiStore.ts           # UI状态
├── types/
│   ├── device.ts            # 设备类型
│   ├── mission.ts           # 任务类型
│   ├── telemetry.ts         # 遥测类型
│   └── api.ts               # API类型
└── utils/
    ├── formatters.ts        # 格式化工具
    ├── validators.ts        # 验证工具
    └── constants.ts         # 常量定义
```

---

## 技术栈

### 后端技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| Python | 3.9+ | 编程语言 |
| FastAPI | 0.100+ | Web框架 |
| SQLAlchemy | 2.0+ | ORM |
| Pydantic | 2.0+ | 数据验证 |
| pymavlink | 2.4+ | MAVLink协议 |
| PostgreSQL | 13+ | 关系数据库 |
| TimescaleDB | 2.0+ | 时序数据库 |
| Redis | 6+ | 缓存/消息队列 |
| Celery | 5.0+ | 异步任务 |
| Alembic | 1.10+ | 数据库迁移 |
| pytest | 7.0+ | 测试框架 |

### 前端技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| React | 18+ | UI框架 |
| TypeScript | 5.0+ | 类型系统 |
| Next.js | 13+ | 应用框架 |
| Ant Design | 5.0+ | UI组件库 |
| Cesium.js | 1.100+ | 3D地球 |
| React Query | 4.0+ | 数据获取 |
| Zustand | 4.0+ | 状态管理 |
| TailwindCSS | 3.0+ | CSS框架 |
| ECharts | 5.0+ | 图表库 |
| Jest | 29+ | 测试框架 |

---

## 代码规范

### Python代码规范

#### 格式化工具

使用 **Black** 进行代码格式化：

```bash
# 安装
pip install black

# 格式化代码
black backend/

# 配置pyproject.toml
[tool.black]
line-length = 100
target-version = ['py39']
include = '\.pyi?$'
```

#### Linting工具

使用 **Flake8** 和 **Pylint**：

```bash
# 安装
pip install flake8 pylint

# 检查代码
flake8 backend/
pylint backend/

# 配置.flake8
[flake8]
max-line-length = 100
exclude = .git,__pycache__,venv
ignore = E203,W503
```

#### 类型提示

```python
# 推荐使用类型提示
from typing import List, Dict, Optional

def get_device(device_id: str) -> Optional[Device]:
    """获取设备信息
    
    Args:
        device_id: 设备ID
        
    Returns:
        设备对象，如果不存在返回None
    """
    return device_manager.get_device(device_id)

def calculate_distance(
    point1: Position, 
    point2: Position
) -> float:
    """计算两点间距离"""
    return geodesic(
        (point1.latitude, point1.longitude),
        (point2.latitude, point2.longitude)
    ).meters
```

#### 文档字符串

```python
def create_mission(
    mission_id: str,
    name: str,
    waypoints: List[Waypoint],
    mission_type: MissionType = MissionType.CUSTOM
) -> Mission:
    """创建新任务
    
    创建一个新的飞行任务，包含指定的航点列表。
    
    Args:
        mission_id (str): 任务唯一标识符
        name (str): 任务名称
        waypoints (List[Waypoint]): 航点列表
        mission_type (MissionType, optional): 任务类型，默认为CUSTOM
        
    Returns:
        Mission: 创建的任务对象
        
    Raises:
        ValueError: 如果mission_id已存在
        ValidationError: 如果航点数据无效
        
    Example:
        >>> waypoints = [Waypoint(...), Waypoint(...)]
        >>> mission = create_mission(
        ...     mission_id="mission_001",
        ...     name="Survey Mission",
        ...     waypoints=waypoints
        ... )
    """
    pass
```

### TypeScript代码规范

#### 格式化配置

使用 **Prettier**：

```json
// .prettierrc
{
  "semi": true,
  "trailingComma": "es5",
  "singleQuote": true,
  "printWidth": 100,
  "tabWidth": 2,
  "useTabs": false
}
```

#### 命名规范

```typescript
// 接口和类型：PascalCase
interface DeviceConfig {
  deviceId: string;
  name: string;
}

type MissionStatus = 'pending' | 'executing' | 'completed';

// 变量和函数：camelCase
const deviceList: Device[] = [];
const getDeviceById = (id: string): Device | undefined => {};

// 常量：UPPER_SNAKE_CASE
const MAX_FLIGHT_ALTITUDE = 120;
const DEFAULT_TIMEOUT = 5000;

// 组件：PascalCase
const DeviceCard: React.FC<DeviceCardProps> = ({ device }) => {
  return <div>{device.name}</div>;
};

// 文件命名
// 组件: DeviceCard.tsx
// 工具: deviceHelpers.ts
// 类型: device.types.ts
// 样式: DeviceCard.module.css
```

#### React组件规范

```typescript
// 组件定义
interface DeviceCardProps {
  device: Device;
  onSelect?: (device: Device) => void;
  className?: string;
}

export const DeviceCard: React.FC<DeviceCardProps> = ({
  device,
  onSelect,
  className
}) => {
  // Hooks放在组件顶部
  const [isExpanded, setIsExpanded] = useState(false);
  const telemetry = useDeviceTelemetry(device.id);
  
  // 事件处理函数
  const handleClick = useCallback(() => {
    onSelect?.(device);
  }, [device, onSelect]);
  
  // 副作用
  useEffect(() => {
    // ...
  }, []);
  
  // 渲染
  return (
    <div className={classNames(styles.card, className)} onClick={handleClick}>
      {/* ... */}
    </div>
  );
};
```

---

## 开发流程

### Git工作流

#### 分支策略

```
main (生产分支)
  └── develop (开发分支)
        ├── feature/device-management
        ├── feature/mission-planner
        └── bugfix/connection-issue
```

#### 提交规范

```bash
# 提交格式
<type>(<scope>): <subject>

<body>

<footer>
```

**类型(type)**:
- `feat`: 新功能
- `fix`: 修复bug
- `docs`: 文档更新
- `style`: 代码格式调整
- `refactor`: 重构
- `test`: 测试相关
- `chore`: 构建/工具链

**示例**:

```bash
feat(device): 添加设备连接状态监控

- 实现实时连接状态检测
- 添加断线重连机制
- 添加状态变化通知

Closes #123
```

#### 开发流程

```bash
# 1. 从develop创建特性分支
git checkout develop
git pull origin develop
git checkout -b feature/new-feature

# 2. 开发和提交
git add .
git commit -m "feat(module): add new feature"

# 3. 推送到远程
git push origin feature/new-feature

# 4. 创建Pull Request
# 在GitHub/GitLab上创建PR

# 5. 代码审查通过后合并
```

---

## 测试指南

### 后端测试

#### 单元测试

```python
# tests/unit/test_device_manager.py
import pytest
from unittest.mock import Mock, AsyncMock
from core.devices.manager import DeviceManager
from core.mavlink.connector import DroneConfig, DroneType

@pytest.fixture
def device_manager():
    """设备管理器fixture"""
    return DeviceManager()

@pytest.mark.asyncio
async def test_register_device(device_manager):
    """测试设备注册"""
    config = DroneConfig(
        drone_id="test_001",
        drone_type=DroneType.PX4,
        connection_string="udp:127.0.0.1:14550"
    )
    
    device_id = await device_manager.register_device(config)
    
    assert device_id == "test_001"
    assert device_manager.get_device("test_001") is not None

@pytest.mark.asyncio
async def test_connect_device_success(device_manager, mocker):
    """测试设备连接成功"""
    # Mock连接器
    mock_connector = AsyncMock()
    mock_connector.connect = AsyncMock(return_value=True)
    mocker.patch(
        'core.devices.manager.MAVLinkConnector',
        return_value=mock_connector
    )
    
    # 注册并连接设备
    config = DroneConfig(...)
    await device_manager.register_device(config)
    success = await device_manager.connect_device("test_001")
    
    assert success is True

def test_get_all_devices(device_manager):
    """测试获取所有设备"""
    devices = device_manager.get_all_devices()
    
    assert isinstance(devices, list)
```

#### 集成测试

```python
# tests/integration/test_mission_api.py
import pytest
from fastapi.testclient import TestClient
from api.v1.main import app

@pytest.fixture
def client():
    """测试客户端"""
    return TestClient(app)

def test_create_mission(client):
    """测试创建任务API"""
    mission_data = {
        "mission_id": "mission_001",
        "name": "Test Mission",
        "mission_type": "custom",
        "waypoints": [
            {
                "waypoint_id": "wp_001",
                "position": {
                    "latitude": 39.9042,
                    "longitude": 116.4074,
                    "altitude": 50
                }
            }
        ]
    }
    
    response = client.post("/api/missions", json=mission_data)
    
    assert response.status_code == 200
    data = response.json()
    assert data['mission_id'] == "mission_001"

def test_get_mission_not_found(client):
    """测试获取不存在的任务"""
    response = client.get("/api/missions/non_existent")
    
    assert response.status_code == 404
```

#### 运行测试

```bash
# 运行所有测试
pytest

# 运行指定测试文件
pytest tests/unit/test_device_manager.py

# 运行指定测试函数
pytest tests/unit/test_device_manager.py::test_register_device

# 生成覆盖率报告
pytest --cov=backend --cov-report=html

# 并行运行测试
pytest -n auto
```

### 前端测试

#### 单元测试

```typescript
// src/components/DeviceCard/DeviceCard.test.tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { DeviceCard } from './DeviceCard';
import { mockDevice } from '@/__mocks__/device';

describe('DeviceCard', () => {
  it('should render device name', () => {
    render(<DeviceCard device={mockDevice} />);
    
    expect(screen.getByText(mockDevice.name)).toBeInTheDocument();
  });
  
  it('should call onSelect when clicked', () => {
    const onSelect = jest.fn();
    render(<DeviceCard device={mockDevice} onSelect={onSelect} />);
    
    fireEvent.click(screen.getByRole('button'));
    
    expect(onSelect).toHaveBeenCalledWith(mockDevice);
  });
  
  it('should display online status', () => {
    render(<DeviceCard device={{ ...mockDevice, status: 'online' }} />);
    
    expect(screen.getByText('在线')).toBeInTheDocument();
  });
});
```

#### Hooks测试

```typescript
// src/hooks/useDevice.test.ts
import { renderHook, waitFor } from '@testing-library/react';
import { useDevice } from './useDevice';
import { deviceService } from '@/services/deviceService';

jest.mock('@/services/deviceService');

describe('useDevice', () => {
  it('should fetch device data', async () => {
    const mockDevice = { id: 'test_001', name: 'Test Drone' };
    (deviceService.getDevice as jest.Mock).mockResolvedValue(mockDevice);
    
    const { result } = renderHook(() => useDevice('test_001'));
    
    await waitFor(() => {
      expect(result.current.device).toEqual(mockDevice);
      expect(result.current.loading).toBe(false);
    });
  });
});
```

#### 运行测试

```bash
# 运行所有测试
npm test

# 运行指定文件
npm test DeviceCard.test.tsx

# 生成覆盖率
npm test -- --coverage

# 监视模式
npm test -- --watch
```

---

## 调试技巧

### 后端调试

#### 使用logging

```python
import logging

logger = logging.getLogger(__name__)

def process_telemetry(device_id: str, data: dict):
    logger.debug(f"Processing telemetry for {device_id}")
    logger.info(f"Telemetry received: {data}")
    
    try:
        # 处理逻辑
        pass
    except Exception as e:
        logger.error(f"Error processing telemetry: {e}", exc_info=True)
```

#### 使用debugger

```python
# 在代码中添加断点
import pdb; pdb.set_trace()

# 或使用ipdb（更友好）
import ipdb; ipdb.set_trace()

# 或使用VS Code调试器
# 在launch.json中配置
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Python: FastAPI",
      "type": "python",
      "request": "launch",
      "module": "uvicorn",
      "args": [
        "api.v1.main:app",
        "--reload"
      ],
      "jinja": true
    }
  ]
}
```

### 前端调试

#### React DevTools

```bash
# 安装React DevTools浏览器扩展
# 使用React Developer Tools检查组件树和props
```

#### Console调试

```typescript
// 使用console方法
console.log('Device data:', device);
console.table(deviceList);
console.time('fetchDevices');
await fetchDevices();
console.timeEnd('fetchDevices');

// 使用debugger
debugger; // 代码会在此处暂停
```

#### VS Code调试

```json
// .vscode/launch.json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Next.js: debug full stack",
      "type": "node-terminal",
      "request": "launch",
      "command": "npm run dev"
    }
  ]
}
```

---

## 性能优化

### 后端优化

#### 数据库优化

```python
# 使用索引
class Device(Base):
    __tablename__ = 'devices'
    
    id = Column(Integer, primary_key=True)
    device_id = Column(String(50), unique=True, index=True)  # 添加索引
    name = Column(String(100))
    
# 批量查询
devices = session.query(Device).filter(
    Device.status == 'online'
).all()

# 使用join避免N+1查询
missions = session.query(Mission).join(Device).filter(
    Device.status == 'online'
).all()
```

#### 异步处理

```python
# 使用Celery处理耗时任务
from celery import Celery

celery_app = Celery('skymaster', broker='redis://localhost:6379/1')

@celery_app.task
def process_flight_log(log_id: str):
    """异步处理飞行日志"""
    log = FlightLog.get(log_id)
    # 处理逻辑
    return {'status': 'completed'}

# 调用异步任务
process_flight_log.delay(log_id='log_001')
```

#### 缓存优化

```python
from functools import lru_cache
import redis

redis_client = redis.Redis(host='localhost', port=6379, db=0)

@lru_cache(maxsize=128)
def get_device_config(device_id: str) -> dict:
    """缓存设备配置"""
    return redis_client.get(f"device:config:{device_id}")

def cache_telemetry(device_id: str, data: dict):
    """缓存遥测数据"""
    redis_client.setex(
        f"telemetry:{device_id}",
        5,  # 5秒过期
        json.dumps(data)
    )
```

### 前端优化

#### 代码分割

```typescript
// 使用动态导入
const DeviceMap = dynamic(() => import('@/components/DeviceMap'), {
  loading: () => <p>Loading...</p>,
  ssr: false
});

// 路由级别分割
const Mission = lazy(() => import('@/pages/Mission'));
```

#### 虚拟列表

```typescript
import { FixedSizeList } from 'react-window';

const DeviceList: React.FC<{ devices: Device[] }> = ({ devices }) => {
  return (
    <FixedSizeList
      height={600}
      itemCount={devices.length}
      itemSize={80}
      width="100%"
    >
      {({ index, style }) => (
        <div style={style}>
          <DeviceCard device={devices[index]} />
        </div>
      )}
    </FixedSizeList>
  );
};
```

#### Memo优化

```typescript
import { memo, useMemo, useCallback } from 'react';

// 使用memo避免不必要渲染
const DeviceCard = memo<DeviceCardProps>(({ device, onSelect }) => {
  return <div>{device.name}</div>;
});

// 使用useMemo缓存计算结果
const sortedDevices = useMemo(() => {
  return devices.sort((a, b) => a.name.localeCompare(b.name));
}, [devices]);

// 使用useCallback缓存函数
const handleSelect = useCallback((device: Device) => {
  onSelect(device);
}, [onSelect]);
```

---

## 贡献指南

### 贡献流程

1. **Fork仓库**
   ```bash
   git clone https://github.com/your-username/skymaster-drone-platform.git
   ```

2. **创建分支**
   ```bash
   git checkout -b feature/your-feature
   ```

3. **编写代码**
   - 遵循代码规范
   - 编写测试
   - 更新文档

4. **提交代码**
   ```bash
   git commit -m "feat(module): add new feature"
   git push origin feature/your-feature
   ```

5. **创建Pull Request**
   - 填写PR模板
   - 关联相关Issue
   - 等待代码审查

### Pull Request检查清单

- [ ] 代码符合项目规范
- [ ] 添加了必要的测试
- [ ] 所有测试通过
- [ ] 更新了相关文档
- [ ] 没有引入新的警告
- [ ] 提交信息清晰明确

### 代码审查标准

- **功能正确性**: 代码是否实现了预期功能
- **代码质量**: 是否遵循最佳实践
- **性能**: 是否有性能问题
- **安全性**: 是否存在安全隐患
- **可维护性**: 代码是否易于理解和维护
- **测试覆盖**: 是否有足够的测试

---

## 常用命令

### 后端命令

```bash
# 启动开发服务器
uvicorn api.v1.main:app --reload

# 运行测试
pytest

# 数据库迁移
alembic revision --autogenerate -m "description"
alembic upgrade head

# 代码格式化
black backend/
isort backend/

# 代码检查
flake8 backend/
pylint backend/
mypy backend/

# 生成文档
pdoc --html api/
```

### 前端命令

```bash
# 启动开发服务器
npm run dev

# 构建生产版本
npm run build

# 运行测试
npm test

# 代码格式化
npm run format

# 代码检查
npm run lint

# 类型检查
npm run type-check

# 分析打包大小
npm run analyze
```

### Docker命令

```bash
# 构建镜像
docker-compose build

# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f

# 进入容器
docker-compose exec backend bash

# 清理资源
docker-compose down -v
```

---

**文档版本**: 1.0.0  
**最后更新**: 2026-03-11  
**维护者**: SkyMaster开发团队
