# SkyMaster 模拟器快速启动指南

> **目标**：5分钟内完成SkyMaster + jMAVSim模拟器的完整测试环境搭建

---

## 📋 前置要求

### 系统要求
- **操作系统**: Ubuntu 20.04+ / Windows 10+ / macOS 10.15+
- **内存**: 8GB以上
- **存储**: 10GB可用空间
- **网络**: 稳定的网络连接

### 软件要求
- **Docker** (必须)
- **Docker Compose** (必须)
- **Java 11+** (运行jMAVSim)
- **Git** (克隆项目)

---

## 🚀 快速启动（5步完成）

### Step 1: 安装Docker（如果未安装）

#### Ubuntu/Linux
```bash
# 安装Docker
curl -fsSL https://get.docker.com | bash

# 安装Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/download/v2.20.0/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# 添加当前用户到docker组（避免每次使用sudo）
sudo usermod -aG docker $USER

# 重新登录或执行
newgrp docker

# 验证安装
docker --version
docker-compose --version
```

#### Windows
```powershell
# 下载Docker Desktop
https://www.docker.com/products/docker-desktop

# 安装后重启电脑
# Docker Desktop会自动安装Docker Compose
```

#### macOS
```bash
# 使用Homebrew安装
brew install docker docker-compose

# 或下载Docker Desktop
https://www.docker.com/products/docker-desktop
```

---

### Step 2: 安装Java（运行jMAVSim）

#### Ubuntu/Linux
```bash
# 安装OpenJDK 11
sudo apt update
sudo apt install openjdk-11-jdk -y

# 验证安装
java -version
```

#### Windows
```powershell
# 下载Java 11
https://www.oracle.com/java/technologies/downloads/

# 或使用Chocolatey
choco install openjdk11
```

#### macOS
```bash
# 使用Homebrew安装
brew install openjdk@11

# 配置环境变量
sudo ln -sfn /usr/local/opt/openjdk@11/libexec/openjdk.jdk /Library/Java/JavaVirtualMachines/openjdk-11.jdk
```

---

### Step 3: 部署SkyMaster平台

#### 3.1 克隆项目
```bash
# 克隆SkyMaster项目
cd ~
git clone https://github.com/your-org/skymaster-drone-platform.git
cd skymaster-drone-platform
```

#### 3.2 配置环境变量
```bash
# 复制环境变量模板
cp .env.example .env

# 编辑配置文件（可选，默认配置即可用于测试）
nano .env
```

**.env 关键配置**
```bash
# 应用配置
ENVIRONMENT=development
SECRET_KEY=$(openssl rand -hex 32)
JWT_SECRET_KEY=$(openssl rand -hex 32)

# 数据库配置（Docker会自动创建）
DATABASE_URL=postgresql://skymaster:skymaster@postgres:5432/skymaster

# Redis配置
REDIS_URL=redis://redis:6379/0

# MAVLink配置
MAVLINK_DEFAULT_BAUD_RATE=57600
MAVLINK_TIMEOUT=5.0

# 设备配置
DEVICE_MAX_CONNECTIONS=100
```

#### 3.3 启动SkyMaster服务
```bash
# 进入Docker目录
cd docker

# 启动所有服务（首次启动会下载镜像，约5-10分钟）
docker-compose up -d

# 查看服务状态
docker-compose ps

# 查看日志（检查是否有错误）
docker-compose logs -f backend
```

**预期输出**
```
NAME                COMMAND                  SERVICE             STATUS              PORTS
skymaster-backend   "uvicorn api.v1.main…"   backend             running             0.0.0.0:8000->8000/tcp
skymaster-frontend  "nginx -g 'daemon of…"   frontend            running             0.0.0.0:80->80/tcp
skymaster-postgres  "docker-entrypoint.s…"   postgres            running             0.0.0.0:5432->5432/tcp
skymaster-redis     "docker-entrypoint.s…"   redis               running             0.0.0.0:6379->6379/tcp
```

#### 3.4 验证部署
```bash
# 检查后端健康状态
curl http://localhost:8000/health

# 预期输出
{
  "status": "healthy",
  "timestamp": "2026-03-11T12:00:00Z",
  "version": "1.0.0"
}

# 检查前端
# 浏览器访问: http://localhost
```

---

### Step 4: 安装并运行jMAVSim模拟器

#### 4.1 克隆jMAVSim
```bash
# 克隆jMAVSim项目
cd ~
git clone https://github.com/PX4/jMAVSim.git
cd jMAVSim
```

#### 4.2 编译jMAVSim
```bash
# 安装ant构建工具（如果未安装）
# Ubuntu/Linux
sudo apt install ant -y

# macOS
brew install ant

# Windows（使用Chocolatey）
choco install ant

# 编译jMAVSim
ant

# 预期输出
# BUILD SUCCESSFUL
```

#### 4.3 运行jMAVSim
```bash
# 启动模拟器
java -jar jmavsim_run.jar

# 看到以下输出表示成功
# [SIMULATOR] Starting simulation...
# [MAVLINK] Listening on UDP port 14550
# [QUADROTOR] Vehicle initialized
```

**jMAVSim界面说明**
```
3D视图窗口会显示一架四旋翼无人机
无人机初始位置：(0, 0, 0)
可以观察无人机的姿态变化
```

---

### Step 5: 连接SkyMaster到模拟器

#### 5.1 访问SkyMaster Web界面
```bash
# 浏览器打开
http://localhost

# 默认登录凭据
用户名: admin
密码: admin123
```

#### 5.2 添加模拟无人机
```
1. 登录后，进入"设备管理"页面
2. 点击"添加设备"按钮
3. 填写设备信息:
   - 设备ID: sim_drone_001
   - 设备名称: 模拟无人机1
   - 设备类型: PX4
   - 连接方式: UDP
   - 连接地址: 127.0.0.1:14550
   - 描述: jMAVSim模拟器测试

4. 点击"保存"
5. 点击"连接"按钮
```

#### 5.3 验证连接
```
连接成功后，应显示:
✅ 状态: 在线
✅ GPS: 3D Fix
✅ 卫星数量: 12
✅ 飞行模式: STABILIZE
✅ 解锁状态: DISARMED
✅ 电池: 100%
✅ 位置: 经纬度、高度数据

在3D地图上应能看到无人机图标
```

---

## 🎮 开始测试

### 测试1: 遥测数据监控

#### 步骤
```
1. 在设备列表中点击"sim_drone_001"
2. 查看"遥测数据"面板
3. 观察实时更新的数据:
   - 位置（经纬度、高度）
   - 速度（地速、空速）
   - 姿态（俯仰、横滚、偏航）
   - 电池电量
   - GPS状态
```

#### 预期结果
```
✅ 数据每秒更新10次
✅ 数值在合理范围内
✅ 无延迟或丢包
```

---

### 测试2: 解锁/上锁控制

#### 步骤
```
1. 在设备控制面板，找到"解锁控制"
2. 点击"解锁"按钮
3. 观察jMAVSim窗口，螺旋桨应开始旋转
4. 等待5秒
5. 点击"上锁"按钮
6. 观察螺旋桨停止
```

#### 预期结果
```
✅ 解锁成功，状态变为ARMED
✅ jMAVSim中螺旋桨旋转
✅ 上锁成功，状态变为DISARMED
✅ 螺旋桨停止
```

---

### 测试3: 起飞和降落

#### 步骤
```
1. 切换到"飞行控制"页面
2. 设置起飞高度: 5米
3. 点击"起飞"按钮
4. 观察无人机在jMAVSim中起飞
5. 等待到达悬停高度（约5秒）
6. 点击"降落"按钮
7. 观察无人机自动降落
```

#### 预期结果
```
✅ 无人机平稳起飞
✅ 到达5米高度后悬停
✅ 降落指令执行成功
✅ 降落后自动上锁
```

---

### 测试4: 航点任务

#### 步骤
```
1. 进入"任务规划"页面
2. 在地图上点击3个航点:
   航点1: (39.9042, 116.4074, 10)  # 起点
   航点2: (39.9052, 116.4084, 10)  # 向东100m
   航点3: (39.9042, 116.4074, 10)  # 返回起点

3. 设置任务参数:
   - 飞行高度: 10米
   - 飞行速度: 2m/s
   - 任务类型: 航点飞行

4. 点击"上传任务"
5. 选择"sim_drone_001"
6. 点击"执行任务"
7. 观察无人机按航点飞行
```

#### 预期结果
```
✅ 任务上传成功
✅ 无人机依次飞往航点
✅ 到达每个航点时有提示
✅ 任务完成后自动返航
```

---

### 测试5: 飞行模式切换

#### 步骤
```
1. 在控制面板找到"飞行模式"
2. 依次切换以下模式:
   - STABILIZE (自稳模式)
   - ALTITUDE (高度控制)
   - LOITER (悬停模式)
   - AUTO (自动模式)
   - RTL (返航模式)

3. 每次切换后观察jMAVSim响应
```

#### 预期结果
```
✅ 模式切换成功
✅ 状态显示正确
✅ 无人机响应模式变化
```

---

### 测试6: 紧急停止

#### 步骤
```
1. 让无人机起飞到5米
2. 点击"紧急停止"按钮
3. 观察无人机行为
```

#### 预期结果
```
✅ 无人机立即停止
✅ 进入安全模式
✅ 状态显示异常
```

---

## 📊 性能测试

### 延迟测试
```bash
# 测试指令响应延迟
# 在SkyMaster后端容器中执行
docker exec -it skymaster-backend bash

# 运行延迟测试脚本
python scripts/test_latency.py

# 预期结果
平均延迟: <50ms
最大延迟: <100ms
丢包率: <1%
```

### 稳定性测试
```bash
# 长时间运行测试（30分钟）
python scripts/test_stability.py --duration 1800

# 预期结果
连接保持: 100%
无崩溃: 是
内存使用: <500MB
CPU使用: <30%
```

---

## 🛠️ 故障排查

### 问题1: Docker服务无法启动

#### 症状
```bash
docker-compose up -d
ERROR: Cannot connect to the Docker daemon
```

#### 解决方案
```bash
# 检查Docker服务状态
sudo systemctl status docker

# 如果未运行，启动Docker
sudo systemctl start docker

# 设置开机自启
sudo systemctl enable docker

# 重新尝试
docker-compose up -d
```

---

### 问题2: 端口被占用

#### 症状
```bash
ERROR: Port 80 is already in use
```

#### 解决方案
```bash
# 查看端口占用
sudo lsof -i :80

# 停止占用端口的进程
sudo kill -9 <PID>

# 或修改docker-compose.yml中的端口映射
# 将 "80:80" 改为 "8080:80"
```

---

### 问题3: jMAVSim无法连接到SkyMaster

#### 症状
```
设备连接失败
状态: 离线
```

#### 解决方案
```bash
# 1. 检查jMAVSim是否正在运行
ps aux | grep jmavsim

# 2. 检查UDP端口14550是否监听
netstat -an | grep 14550

# 3. 检查防火墙
sudo ufw status
# 如果开启，允许端口
sudo ufw allow 14550/udp

# 4. 检查SkyMaster后端日志
docker-compose logs backend | grep MAVLink

# 5. 重启服务
docker-compose restart backend
```

---

### 问题4: 数据库连接失败

#### 症状
```bash
backend_1   | ERROR: could not connect to server: Connection refused
```

#### 解决方案
```bash
# 1. 检查PostgreSQL容器状态
docker-compose ps postgres

# 2. 查看PostgreSQL日志
docker-compose logs postgres

# 3. 重启数据库
docker-compose restart postgres

# 4. 重新初始化数据库
docker-compose down -v
docker-compose up -d
```

---

### 问题5: 前端无法访问

#### 症状
```
浏览器访问 http://localhost 显示"无法访问此网站"
```

#### 解决方案
```bash
# 1. 检查前端容器
docker-compose ps frontend

# 2. 检查端口映射
docker port skymaster-frontend

# 3. 查看前端日志
docker-compose logs frontend

# 4. 检查Nginx配置
docker exec skymaster-frontend nginx -t

# 5. 重启前端
docker-compose restart frontend
```

---

## 📝 测试检查清单

### 环境准备
```bash
□ Docker已安装并运行
□ Docker Compose已安装
□ Java 11+已安装
□ Git已安装
□ 网络连接正常
```

### SkyMaster部署
```bash
□ 项目已克隆
□ .env文件已配置
□ Docker容器全部运行
□ 后端健康检查通过
□ 前端可访问
```

### jMAVSim运行
```bash
□ jMAVSim已编译
□ 模拟器启动成功
□ UDP 14550端口监听
□ 3D视图正常显示
```

### 连接测试
```bash
□ 设备已添加
□ 连接成功
□ 遥测数据正常更新
□ GPS状态正常
```

### 功能测试
```bash
□ 解锁/上锁测试通过
□ 起飞/降落测试通过
□ 航点任务测试通过
□ 模式切换测试通过
□ 紧急停止测试通过
```

### 性能测试
```bash
□ 延迟测试通过（<50ms）
□ 稳定性测试通过（30分钟无崩溃）
□ 资源使用正常
```

---

## 🎯 下一步

### 完成基础测试后

#### 1. 高级功能测试
```yaml
- 集群编队飞行
- AI路径规划
- 自动避障
- 数据分析
```

#### 2. 真实硬件测试
```yaml
- 购买PX4飞控无人机
- 连接真实硬件
- 户外飞行测试
```

#### 3. 生产环境部署
```yaml
- 配置SSL证书
- 设置域名解析
- 配置监控告警
- 数据备份策略
```

---

## 📞 获取帮助

### 文档资源
```yaml
官方文档: https://docs.skymaster.io
API文档: http://localhost:8000/docs
jMAVSim文档: https://px4.io/
```

### 社区支持
```yaml
GitHub Issues: https://github.com/your-org/skymaster-drone-platform/issues
Discord: https://discord.gg/skymaster
论坛: https://community.skymaster.io
```

---

## 🎉 恭喜！

如果你完成了所有测试，说明：
- ✅ SkyMaster平台部署成功
- ✅ jMAVSim模拟器运行正常
- ✅ 系统基础功能完善
- ✅ 可以开始高级功能测试

---

**文档版本**: 1.0.0  
**最后更新**: 2026-03-11  
**预计完成时间**: 5-10分钟

**准备好开始了吗？让我们起飞！** 🚀
