# SkyMaster 实战测试指南

## 目录

- [测试环境准备](#测试环境准备)
- [硬件需求](#硬件需求)
- [无人机接入方案](#无人机接入方案)
- [配置步骤](#配置步骤)
- [测试场景](#测试场景)
- [安全须知](#安全须知)

---

## 测试环境准备

### 系统要求

#### 服务器配置

**最低配置（单机测试）**：
```yaml
CPU: 4核（Intel i5/AMD Ryzen 5）
内存: 8GB
存储: 50GB SSD
网络: 100Mbps
操作系统: Ubuntu 20.04 LTS
```

**推荐配置（集群测试）**：
```yaml
CPU: 8核（Intel i7/AMD Ryzen 7）
内存: 16GB
存储: 200GB SSD
网络: 1Gbps
操作系统: Ubuntu 22.04 LTS
```

#### 网络环境

```yaml
局域网:
  - 路由器: 千兆路由器（推荐TP-Link/Netgear）
  - WiFi: 5GHz频段（减少干扰）
  - 带宽: 100Mbps以上
  - 延迟: <10ms

互联网（可选）:
  - 用于远程访问
  - 4G/5G网络支持
  - 公网IP或内网穿透
```

---

## 硬件需求

### 1. 服务器硬件

#### **方案A：PC服务器（推荐）**

```yaml
型号: Dell/HP/Lenovo塔式服务器
配置:
  CPU: Intel Xeon E-2200系列
  内存: 16GB DDR4 ECC
  存储: 500GB SSD
  网络: 千兆网卡
价格: 约5000-8000元
```

#### **方案B：树莓派（低成本）**

```yaml
型号: Raspberry Pi 4B（8GB版）
配置:
  CPU: ARM Cortex-A72 1.5GHz
  内存: 8GB LPDDR4
  存储: 128GB microSD + 外置SSD
  网络: 千兆以太网 + WiFi 5GHz
价格: 约800-1200元
```

#### **方案C：云服务器（灵活）**

```yaml
推荐: 阿里云/腾讯云/AWS
配置:
  CPU: 4核
  内存: 8GB
  存储: 100GB SSD
  带宽: 5Mbps
价格: 约300-500元/月
```

---

### 2. 无人机硬件

#### **入门级（学习/测试）**

##### **PX4飞控无人机**

```yaml
推荐型号: Holybro S500 V2
价格: 约2000-3000元

包含:
  - PX4飞控（Pixhawk 4）
  - 电机: 2216 900KV ×4
  - 电调: 20A ×4
  - 螺旋桨: 1045
  - 机架: S500
  - GPS: mRo GPS u-blox NEO-M8N
  - 遥控器: FlySky FS-i6S
  - 电池: 3S 3000mAh

特点:
  ✅ 开源飞控，完全可控
  ✅ 支持MAVLink协议
  ✅ 适合二次开发
  ✅ 社区支持丰富
```

##### **模拟器（无风险）**

```yaml
推荐: jMAVSim / Gazebo
价格: 免费

特点:
  ✅ 无需真实硬件
  ✅ 安全无风险
  ✅ 支持所有功能测试
  ✅ 适合快速验证
```

#### **进阶级（实际应用）**

##### **ArduPilot飞控无人机**

```yaml
推荐型号: Hexsoon EDU-450
价格: 约4000-6000元

包含:
  - ArduPilot飞控（Cube Orange）
  - 电机: 3110 700KV ×4
  - 电调: 30A ×4
  - GPS: Here3 GPS
  - 遥控器: FrSky X9 Lite
  - 电池: 4S 5000mAh

特点:
  ✅ 功能强大
  ✅ 稳定性高
  ✅ 支持多种传感器
  ✅ 工业级应用
```

##### **大疆DJI无人机（SDK支持）**

```yaml
推荐型号: DJI Matrice 300 RTK
价格: 约50000-80000元

特点:
  ✅ 工业级可靠性
  ✅ 支持DJI SDK
  ✅ 长续航（55分钟）
  ✅ 抗干扰能力强
  ✅ 支持多负载

或选择:
  - DJI Mavic 3 Enterprise（约15000元）
  - DJI Mini 3 Pro（约5000元，需破解）
```

---

### 3. 通信设备

#### **数传电台**

```yaml
推荐: Holybro Transceiver Telemetry Radio V3
价格: 约400-600元
频率: 915MHz / 433MHz
距离: 300m - 10km（视环境）
速率: 57600 bps

连接方式:
  - 飞控端: UART（TELEM端口）
  - 地面站端: USB
```

#### **WiFi模块（短距离）**

```yaml
推荐: ESP32 / ESP8266
价格: 约50-100元
频率: 2.4GHz / 5GHz
距离: 100-300m
速率: 最高150Mbps

优点:
  ✅ 成本低
  ✅ 易于集成
  ✅ 支持OTA更新
```

#### **4G/5G模块（远程）**

```yaml
推荐: Quectel EC20 / EC25
价格: 约200-400元
网络: 4G LTE Cat 4
距离: 无限制（有信号即可）
速率: 下行150Mbps / 上行50Mbps

优点:
  ✅ 超远距离控制
  ✅ 实时视频传输
  ✅ 无需视线距离
```

---

### 4. 辅助设备

#### **地面站电脑**

```yaml
推荐配置:
  CPU: Intel i5 8代以上
  内存: 8GB
  存储: 256GB SSD
  屏幕: 15.6英寸
  价格: 约3000-5000元

推荐型号:
  - ThinkPad E15
  - Dell Latitude 5520
  - HP ProBook 450 G8
```

#### **遥控器**

```yaml
入门级:
  型号: FlySky FS-i6X
  价格: 约300-500元
  通道: 10通道
  协议: AFHDS 2A

进阶级:
  型号: FrSky X9 Lite S
  价格: 约800-1200元
  通道: 24通道
  协议: ACCESS / ACCST

专业级:
  型号: FrSky X12S
  价格: 约2500-3500元
  通道: 32通道
  协议: ACCESS
```

#### **充电设备**

```yaml
推荐: 专业的锂电池充电器
型号: iMAX B6 / ToolkitRC M6
价格: 约200-500元
功能:
  - 支持多种电池类型
  - 平衡充电
  - 快速充电
  - 放电测试
```

---

## 无人机接入方案

### 方案1：PX4飞控接入

#### **硬件连接**

```yaml
连接方式1: USB串口
  飞控 USB端口 → 地面站 USB
  自动识别为: /dev/ttyACM0 (Linux) 或 COM3 (Windows)

连接方式2: 数传电台
  飞控 TELEM1端口 → 数传模块 → USB → 地面站
  波特率: 57600

连接方式3: WiFi数传
  飞控 TELEM1端口 → ESP32模块 → WiFi → 地面站
  协议: UDP 14550端口
```

#### **连接字符串配置**

```bash
# USB连接
serial:/dev/ttyACM0:57600

# 数传电台
serial:/dev/ttyUSB0:57600

# WiFi UDP连接
udp:192.168.1.100:14550

# TCP连接
tcp:192.168.1.100:5760
```

#### **PX4固件配置**

```bash
# 1. 安装QGroundControl
sudo usermod -a -G dialout $USER
# 下载: https://docs.qgroundcontrol.com/master/en/

# 2. 连接飞控，打开QGroundControl

# 3. 配置参数
# MAVLink设置
MAV_0_CONFIG = TELEM1
MAV_0_MODE = Normal
MAV_0_RATE = 1200 (bytes/s)

# 串口设置
SERIAL1_PROTOCOL = MAVLink 2
SERIAL1_BAUD = 57600 8N1

# 4. 保存并重启飞控
```

---

### 方案2：ArduPilot飞控接入

#### **硬件连接**

```yaml
连接方式: 与PX4类似
  - USB串口
  - 数传电台
  - WiFi模块
  - 4G模块
```

#### **连接字符串配置**

```bash
# 与PX4相同格式
serial:/dev/ttyACM0:115200
udp:192.168.1.100:14550
tcp:192.168.1.100:5760
```

#### **ArduPilot固件配置**

```bash
# 1. 安装Mission Planner（Windows）或MAVProxy（Linux）

# 2. 连接飞控

# 3. 配置参数（通过地面站）
# MAVLink设置
SERIAL1_PROTOCOL = 2 (MAVLink 2)
SERIAL1_BAUD = 57 (57600 baud)

# Telemetry设置
TELEM1_BAUD = 57
TELEM1_PROTOCOL = 2

# Heartbeat
ARMING_CHECK = 0 (测试时禁用)

# 4. 保存参数并重启
```

---

### 方案3：大疆DJI无人机接入

#### **SDK接入方式**

```yaml
支持型号:
  - Matrice 300 RTK / 30系列
  - Mavic 3 Enterprise系列
  - Phantom 4 RTK
  - Mini 3 Pro（需破解）

接入方式:
  1. DJI Mobile SDK（手机APP）
  2. DJI Onboard SDK（机载电脑）
  3. DJI Payload SDK（负载接口）
```

#### **配置步骤**

```bash
# 1. 申请DJI开发者账号
网址: https://developer.dji.com/

# 2. 创建应用，获取App ID和App Key

# 3. 配置SkyMaster
# 编辑 .env 文件
DJI_SDK_APP_ID=your_app_id
DJI_SDK_APP_KEY=your_app_key

# 4. 安装DJI SDK依赖
pip install dji-sdk

# 5. 连接DJI无人机
# 使用遥控器连接手机/电脑
# 通过DJI SDK桥接到SkyMaster
```

#### **DJI Bridge配置**

```python
# DJI Bridge 服务配置
# backend/dji_bridge.py

from dji_sdk import DJISDK

class DJIBridge:
    def __init__(self, app_id, app_key):
        self.sdk = DJISDK(app_id, app_key)
        
    async def connect(self, drone_sn):
        """连接DJI无人机"""
        await self.sdk.connect(drone_sn)
        return {
            "drone_id": drone_sn,
            "status": "connected"
        }
        
    async def get_telemetry(self):
        """获取遥测数据"""
        return {
            "latitude": self.sdk.get_latitude(),
            "longitude": self.sdk.get_longitude(),
            "altitude": self.sdk.get_altitude(),
            "battery": self.sdk.get_battery()
        }
```

---

### 方案4：模拟器接入（零成本）

#### **jMAVSim模拟器**

```bash
# 1. 安装Java运行环境
sudo apt install openjdk-11-jdk

# 2. 下载jMAVSim
git clone https://github.com/PX4/jMAVSim.git
cd jMAVSim

# 3. 编译
ant

# 4. 运行模拟器
java -jar jmavsim_run.jar

# 模拟器会自动创建虚拟串口
# UDP: 127.0.0.1:14550
```

#### **Gazebo模拟器（高级）**

```bash
# 1. 安装Gazebo
sudo apt install gazebo9

# 2. 安装PX4 Gazebo插件
git clone https://github.com/PX4/PX4-Autopilot.git
cd PX4-Autopilot
make px4_sitl_default gazebo

# 3. 启动模拟器
make px4_sitl_default gazebo_iris

# 4. 连接地址
# UDP: 127.0.0.1:14550
```

#### **AirSim模拟器（微软）**

```bash
# 1. 安装Unreal Engine
# 下载: https://www.unrealengine.com/

# 2. 下载AirSim
git clone https://github.com/Microsoft/AirSim.git
cd AirSim

# 3. 编译
./setup.sh
./build.sh

# 4. 运行
# 打开Unreal项目，启动仿真

# 5. 连接地址
# UDP: 127.0.0.1:14550
```

---

## 配置步骤

### 步骤1：部署SkyMaster平台

#### **快速部署（Docker）**

```bash
# 1. 安装Docker
curl -fsSL https://get.docker.com | bash

# 2. 安装Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/download/v2.20.0/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# 3. 克隆项目
git clone https://github.com/your-org/skymaster-drone-platform.git
cd skymaster-drone-platform

# 4. 配置环境变量
cp .env.example .env
nano .env
```

#### **编辑 .env 文件**

```bash
# 应用配置
ENVIRONMENT=production
SECRET_KEY=$(openssl rand -hex 32)
JWT_SECRET_KEY=$(openssl rand -hex 32)

# 数据库配置
DATABASE_URL=postgresql://skymaster:your_password@postgres:5432/symaster

# Redis配置
REDIS_URL=redis://redis:6379/0

# MAVLink配置
MAVLINK_DEFAULT_BAUD_RATE=57600
MAVLINK_TIMEOUT=5.0

# 设备配置
DEVICE_MAX_CONNECTIONS=100

# 地图配置（申请Cesium Ion Token）
CESIUM_ION_TOKEN=your_cesium_ion_token

# DJI配置（如果使用）
DJI_SDK_APP_ID=your_app_id
DJI_SDK_APP_KEY=your_app_key
```

#### **启动服务**

```bash
# 1. 启动所有服务
cd docker
docker-compose up -d

# 2. 查看服务状态
docker-compose ps

# 3. 查看日志
docker-compose logs -f backend

# 4. 验证部署
curl http://localhost:8000/health

# 预期输出
{
  "status": "healthy",
  "timestamp": "2026-03-11T12:00:00Z",
  "version": "1.0.0"
}
```

---

### 步骤2：连接无人机

#### **真实无人机连接**

```bash
# 1. 访问Web界面
浏览器打开: http://localhost

# 2. 登录系统
用户名: admin
密码: admin123

# 3. 添加设备
进入"设备" → "添加设备"

填写信息:
  设备ID: drone_001
  设备名称: Test Drone
  设备类型: PX4
  连接方式: serial:/dev/ttyUSB0:57600
  描述: 测试无人机

# 4. 连接设备
点击"连接"按钮
等待状态变为"在线"
```

#### **模拟器连接**

```bash
# 1. 启动模拟器
cd /path/to/jMAVSim
java -jar jmavsim_run.jar

# 2. 添加模拟设备
设备ID: sim_drone_001
连接方式: udp:127.0.0.1:14550

# 3. 连接
点击"连接"
查看遥测数据
```

---

### 步骤3：验证连接

#### **检查遥测数据**

```bash
# 在Web界面查看
设备详情 → 遥测数据

应显示:
  ✅ GPS状态: 3D Fix
  ✅ 卫星数量: 12
  ✅ 飞行模式: STABILIZE
  ✅ 解锁状态: DISARMED
  ✅ 电池电量: 100%
  ✅ 位置: 经纬度、高度
```

#### **测试MAVLink通信**

```bash
# 使用MAVProxy测试
mavproxy.py --master=/dev/ttyUSB0 --baudrate=57600

# 在MAVProxy控制台输入
mode
# 应显示: Mode STABILIZE

arm throttle
# 应显示: ARMED

disarm
# 应显示: DISARMED
```

---

## 测试场景

### 场景1：基础功能测试

#### **测试目标**
- 验证连接稳定性
- 验证遥测数据准确性
- 验证基本控制指令

#### **测试步骤**

```yaml
1. 连接测试
   - 连接无人机
   - 持续观察5分钟
   - 检查是否有断连
   - 记录延迟时间

2. 遥测测试
   - 读取GPS数据
   - 读取姿态数据
   - 读取电池数据
   - 验证数据准确性

3. 控制测试
   - 发送解锁指令
   - 发送上锁指令
   - 发送模式切换
   - 验证响应时间

4. 视频测试（如有摄像头）
   - 打开视频流
   - 检查画质
   - 检查延迟
```

#### **预期结果**

```yaml
连接稳定性:
  - 连接成功率: 100%
  - 平均延迟: <50ms
  - 丢包率: <1%

遥测准确性:
  - GPS精度: <2m
  - 高度精度: <1m
  - 速度精度: <0.5m/s

控制响应:
  - 指令响应时间: <100ms
  - 执行成功率: 100%
```

---

### 场景2：航点飞行测试

#### **测试目标**
- 验证任务规划功能
- 验证任务执行能力
- 验证导航精度

#### **测试准备**

```yaml
场地要求:
  - 开阔场地（无障碍物）
  - 无禁飞区
  - GPS信号良好（卫星>10颗）
  - 天气良好（风速<5m/s）

安全准备:
  - 检查电池电量（>80%）
  - 检查遥控器连接
  - 设置地理围栏
  - 准备应急降落区
```

#### **测试步骤**

```yaml
1. 创建简单航点任务
   航点数量: 3个
   飞行高度: 10m
   飞行速度: 2m/s
   总距离: 约100m

2. 上传任务到无人机
   - 验证任务有效性
   - 上传到飞控
   - 确认上传成功

3. 执行任务
   - 解锁无人机
   - 起飞到悬停高度
   - 开始任务
   - 观察执行过程

4. 监控数据
   - 实时位置
   - 飞行轨迹
   - 航点到达情况
   - 异常告警

5. 完成任务
   - 自动返航
   - 降落
   - 上锁
   - 保存数据
```

#### **数据记录**

```yaml
任务信息:
  任务ID: mission_test_001
  航点数: 3
  计划距离: 100m
  计划时间: 2分钟

执行结果:
  实际距离: 102m
  实际时间: 2分15秒
  航点完成: 3/3
  电池消耗: 15%

精度分析:
  航点1偏差: 0.8m
  航点2偏差: 1.2m
  航点3偏差: 0.5m
  平均偏差: 0.83m

异常事件: 无
```

---

### 场景3：集群编队测试

#### **测试目标**
- 验证多机连接能力
- 验证编队成形
- 验证协同飞行

#### **测试准备**

```yaml
设备准备:
  - 3架以上无人机
  - 每架电量>80%
  - 频率分离（避免干扰）

人员准备:
  - 1名主操作员
  - 3名安全员（每架1名）
  - 1名数据记录员

场地准备:
  - 大型开阔场地
  - 直径>100m
  - 无障碍物
  - 设置安全边界
```

#### **测试步骤**

```yaml
1. 创建集群
   集群ID: swarm_test_001
   成员: drone_001, drone_002, drone_003
   编队类型: V形编队
   间距: 10m

2. 连接所有设备
   - 逐个连接无人机
   - 确认全部在线
   - 检查遥测数据

3. 编队成形
   - 设置编队中心点
   - 启动编队成形
   - 观察成形过程
   - 确认成形完成

4. 编队移动
   - 选择目标位置
   - 执行编队移动
   - 保持队形
   - 监控间距

5. 安全降落
   - 编队返航
   - 依次降落
   - 全机上锁
```

#### **数据记录**

```yaml
编队信息:
  集群大小: 3架
  编队类型: V形
  设定间距: 10m

成形结果:
  成形时间: 45秒
  实际间距: 9.5m - 10.5m
  间距偏差: <0.5m

飞行数据:
  总飞行时间: 5分钟
  平均速度: 3m/s
  电池消耗: 20%

安全事件: 无
```

---

### 场景4：应急响应测试

#### **测试目标**
- 验证失联返航
- 验证低电量保护
- 验证地理围栏

#### **测试场景1：失联返航**

```yaml
1. 无人机飞行到50m距离
2. 关闭地面站数传
3. 观察无人机行为
4. 预期: 20秒后自动返航
5. 恢复通信
6. 记录返航过程
```

#### **测试场景2：低电量保护**

```yaml
1. 设置低电量阈值: 30%
2. 无人机飞行
3. 电量降至30%
4. 预期: 自动返航
5. 观察执行过程
6. 记录电量曲线
```

#### **测试场景3：地理围栏**

```yaml
1. 创建圆形围栏（半径50m）
2. 类型: 禁止离开
3. 无人机飞行
4. 尝试飞出围栏
5. 预期: 触发告警 + 阻止飞行
6. 记录围栏响应
```

---

## 安全须知

### 飞行前检查

#### **设备检查清单**

```yaml
无人机:
  ✅ 螺旋桨完好无损
  ✅ 电机转动顺畅
  ✅ 电池安装牢固
  ✅ GPS天线正常
  ✅ 数传连接正常
  ✅ 遥控器连接正常

地面站:
  ✅ 电脑电量充足
  ✅ 软件运行正常
  ✅ 网络连接稳定
  ✅ 数传连接正常

环境:
  ✅ 天气良好
  ✅ 风速<5m/s
  ✅ 无降雨
  ✅ 无电磁干扰
  ✅ 非禁飞区
```

#### **安全检查**

```yaml
飞行前:
  ✅ 设置地理围栏
  ✅ 设置返航高度
  ✅ 检查电池电量
  ✅ 确认GPS信号
  ✅ 测试遥控器

飞行中:
  ✅ 保持视线距离
  ✅ 持续监控遥测
  ✅ 注意电量消耗
  ✅ 观察天气变化
  ✅ 准备应急操作

飞行后:
  ✅ 检查设备状态
  ✅ 保存飞行数据
  ✅ 检查电池温度
  ✅ 清洁无人机
```

### 应急处理

#### **紧急情况处理**

```yaml
情况1: 无人机失控
  1. 立即切换手动模式
  2. 使用遥控器控制
  3. 紧急降落
  4. 撤离人员

情况2: GPS丢失
  1. 切换到姿态模式
  2. 手动控制返航
  3. 立即降落
  4. 检查GPS模块

情况3: 低电量
  1. 立即返航
  2. 选择安全降落点
  3. 紧急降落
  4. 不要强行飞回

情况4: 通信中断
  1. 保持冷静
  2. 观察无人机
  3. 等待自动返航
  4. 准备手动接管

情况5: 碰撞风险
  1. 立即悬停
  2. 紧急避让
  3. 降落检查
  4. 排查原因
```

### 法律法规

#### **中国无人机法规**

```yaml
实名登记:
  - 所有250g以上无人机
  - 网站: https://uas.caac.gov.cn
  - 需要身份证和无人机信息

飞行许可:
  - 禁飞区: 机场、军事区、政府机关
  - 限飞区: 城市市区、人员密集区
  - 申请: 提前向空管部门申请

飞行限制:
  - 高度: <120m
  - 距离: <500m（视距内）
  - 时间: 白天
  - 天气: 能见度>1km

处罚:
  - 无证飞行: 罚款1000-10000元
  - 禁飞区飞行: 罚款10000-50000元
  - 造成事故: 追究刑事责任
```

---

## 测试报告模板

### 基础信息

```yaml
测试编号: TEST-20260311-001
测试日期: 2026-03-11
测试地点: 北京市朝阳区XX广场
测试人员: 张三、李四、王五
天气情况: 晴，风速2m/s，能见度10km
```

### 设备信息

```yaml
无人机:
  型号: Holybro S500 V2
  飞控: Pixhawk 4 (PX4)
  固件版本: v1.13.2
  电池: 3S 3000mAh

地面站:
  型号: Lenovo ThinkPad E15
  系统: Ubuntu 20.04
  软件: SkyMaster v1.0.0

通信:
  方式: 数传电台
  频率: 915MHz
  距离: 100m
```

### 测试结果

```yaml
连接测试:
  连接成功率: 100%
  平均延迟: 35ms
  丢包率: 0.2%
  结果: ✅ 通过

遥测测试:
  GPS精度: 1.2m
  高度精度: 0.5m
  更新频率: 10Hz
  结果: ✅ 通过

控制测试:
  指令响应: 45ms
  执行成功率: 100%
  结果: ✅ 通过

任务测试:
  航点精度: 0.8m
  任务完成率: 100%
  结果: ✅ 通过
```

### 问题和建议

```yaml
发现问题:
  1. 视频流偶尔卡顿（网络带宽不足）
  2. 电池电压显示略有延迟

改进建议:
  1. 升级到5GHz WiFi
  2. 优化遥测数据缓存
  3. 增加视频流质量自适应

结论:
  SkyMaster平台基础功能正常，
  满足实战测试要求。
  建议优化视频流性能后投入使用。
```

---

## 快速启动检查清单

### 测试前（30分钟）

```bash
□ 检查服务器运行状态
  docker-compose ps

□ 检查网络连接
  ping 192.168.1.100

□ 检查电池电量
  >80%

□ 检查天气
  风速<5m/s

□ 检查GPS信号
  卫星>10颗

□ 检查遥控器
  电量充足

□ 设置地理围栏
  半径100m

□ 准备应急设备
  灭火器、急救包
```

### 测试中

```bash
□ 持续监控遥测数据
□ 注意电池电量
□ 保持视线距离
□ 记录异常情况
□ 准备应急操作
```

### 测试后

```bash
□ 保存飞行数据
□ 检查设备状态
□ 填写测试报告
□ 清洁无人机
□ 充电电池
```

---

## 联系支持

### 技术支持

```yaml
社区支持:
  - GitHub Issues: https://github.com/your-org/skymaster-drone-platform/issues
  - Discord: https://discord.gg/skymaster
  - 论坛: https://community.skymaster.io

商业支持:
  - 邮箱: support@skymaster.io
  - 电话: +86 400-123-4567
  - 工作时间: 周一至周五 9:00-18:00
```

---

**文档版本**: 1.0.0  
**最后更新**: 2026-03-11  
**维护者**: SkyMaster技术团队
