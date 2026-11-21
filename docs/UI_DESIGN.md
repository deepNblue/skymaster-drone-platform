# SkyMaster UI Design System v0.1

- **版本**：v0.1-draft · 2026-07-09
- **主题定位**：**军工黑客风 · 暗黑独占 · 无浅色模式**
- **技术栈**：React 18 + Next.js 14 + Ant Design 5（dark algorithm）+ TailwindCSS + Framer Motion + Three.js + Cesium
- **风格锚点**：Palantir Gotham × Boston Dynamics × 军用指挥中心 × 终端黑客

---

## 一、设计原则

| # | 原则 | 说明 |
|---|---|---|
| 1 | **黑得深沉** | 底色 `#0d1117`，不用纯黑 `#000`（视觉过硬） |
| 2 | **绿得冷峻** | 主色 `#39ff14` 荧光绿，仅用于关键数据 / 主操作 / 激活态，禁止大面积铺 |
| 3 | **数据即艺术** | 每一个数字都有跳动 / 流动 / 微光动效 |
| 4 | **玻璃穿透** | 面板半透明 + 背景模糊，透出后方 3D 地球 / 粒子 |
| 5 | **无霓虹辉光** | 明确禁用外发光 (`box-shadow: 0 0 20px #xx`) 等发光装饰 |
| 6 | **军工冷静** | 少曲线、多直角 / 45° 切角，等宽字体优先 |
| 7 | **动效克制** | 动效必须服务信息，禁止装饰性动画 |

---

## 二、色彩系统

### 2.1 基础色板

| Token | HEX | 用途 |
|---|---|---|
| `--bg-base` | `#0d1117` | 页面底色 |
| `--bg-elevated-1` | `#161b22` | 一级容器（导航、侧栏） |
| `--bg-elevated-2` | `#1c2128` | 二级容器（卡片、面板） |
| `--bg-glass` | `rgba(22,27,34,0.6)` | 玻璃拟态面板 |
| `--border-primary` | `#30363d` | 主边框 |
| `--border-subtle` | `#21262d` | 次要边框 |
| `--text-primary` | `#e6edf3` | 主文字 |
| `--text-secondary` | `#8b949e` | 次要文字 |
| `--text-tertiary` | `#6e7681` | 弱化文字 |

### 2.2 品牌 & 数据色

| Token | HEX | 用途 |
|---|---|---|
| `--accent-primary` | `#39ff14` | 主色（荧光绿），激活/关键数据 |
| `--accent-primary-dim` | `#26a806` | 主色暗态（hover/disabled） |
| `--accent-cyan` | `#00ffff` | 遥测辅助色（速度/信号） |
| `--accent-amber` | `#ffb000` | 警告级数据（电量低/信号弱） |
| `--accent-red` | `#ff3838` | 危险/错误 |
| `--accent-purple` | `#b967ff` | AI/Copilot 输出标识 |
| `--accent-blue` | `#4c9aff` | 链接/次要操作 |

### 2.3 状态色

| 状态 | HEX | 使用 |
|---|---|---|
| Success | `#39ff14` | 完成、连接、就绪 |
| Warning | `#ffb000` | 电量 20-40%、信号弱 |
| Danger | `#ff3838` | 电量 <20%、失联、GPS 丢失 |
| Info | `#4c9aff` | 提示、消息 |
| Disabled | `#484f58` | 禁用态 |

### 2.4 数据可视化色板（ECharts）

```js
export const CHART_COLORS = [
  '#39ff14',  // 主：绿
  '#00ffff',  // 副：青
  '#ffb000',  // 警：琥珀
  '#ff3838',  // 危：红
  '#b967ff',  // AI：紫
  '#4c9aff',  // 蓝
  '#ff6b9d',  // 粉
  '#00e5a1',  // 翠
];
```

---

## 三、字体系统

### 3.1 字体族

```css
--font-sans:    'Inter', 'HarmonyOS Sans SC', system-ui, sans-serif;
--font-mono:    'JetBrains Mono', 'Fira Code', 'SF Mono', monospace;
--font-display: 'Rajdhani', 'Orbitron', 'HarmonyOS Sans SC', sans-serif;
```

**使用规则**：
- 正文 → `--font-sans`
- **所有数字、坐标、代码、日志 → `--font-mono`**（等宽是军工风灵魂）
- 大标题、面板标题、指挥中心大屏 → `--font-display`

### 3.2 字号阶梯

| Token | 大小 | 行高 | 用途 |
|---|---|---|---|
| `--fs-display` | 40px | 1.2 | 首屏大标题 |
| `--fs-h1` | 28px | 1.3 | 页面标题 |
| `--fs-h2` | 22px | 1.4 | 卡片标题 |
| `--fs-h3` | 18px | 1.4 | 分组标题 |
| `--fs-body` | 14px | 1.6 | 正文 |
| `--fs-caption` | 12px | 1.5 | 辅助文字 |
| `--fs-mono-lg` | 32px | 1.0 | 大数字（速度/高度/电量） |
| `--fs-mono-md` | 18px | 1.2 | 中数字 |
| `--fs-mono-sm` | 12px | 1.4 | 日志、坐标 |

---

## 四、视觉元素

### 4.1 玻璃拟态 Glassmorphism ✅

```css
.glass-panel {
  background: rgba(22, 27, 34, 0.6);
  backdrop-filter: blur(20px) saturate(180%);
  -webkit-backdrop-filter: blur(20px) saturate(180%);
  border: 1px solid rgba(48, 54, 61, 0.6);
  border-radius: 4px;  /* 军工风：小圆角 */
  padding: 16px;
}
```

**规则**：
- 所有主面板（遥测、地图 HUD、任务栏）必须半透明玻璃
- 后方必须有可透视内容（3D 地球或粒子背景）
- 边框 `1px` 灰色，不发光

### 4.2 3D 地球背景 Cesium ✅

**场景配置**：
- 使用 Cesium World Terrain（免费黑夜配色）
- 地球图层切换：暗色卫星 / 线框 / 热力
- 摄像机默认俯视中国，缓慢自转（0.02 rad/s）
- 全屏 z-index=0，UI 层 z-index≥1

**性能规则**：
- 无飞行任务时，帧率降至 15fps
- 移动端自动禁用，退化为静态截图 + 粒子

### 4.3 粒子动态背景 ✅

**方案**：`tsParticles` v3
- 密度：40 个粒子 / 1000×1000px
- 粒子色：`#39ff14`（透明度 0.15）
- 连线：≤120px 间距内连线，透明度 0.05
- 交互：鼠标 hover 排斥半径 100px
- 只在无 Cesium 地球的页面使用（登录页、模型市场、社区）

### 4.4 数据流线条 ✅

**用于**：
- 侧栏导航 hover 时右侧扫过一道流光
- 面板边框沿边扫描线（Data Flow Border）
- 全屏顶部 4px 高进度条（数据加载中）

```css
@keyframes dataFlow {
  0%   { background-position: -200% 0; }
  100% { background-position: 200% 0; }
}
.data-flow-border {
  background: linear-gradient(90deg, transparent, #39ff14, transparent);
  background-size: 50% 100%;
  animation: dataFlow 3s linear infinite;
}
```

### 4.5 全息投影感 Hologram ✅

**用于**：
- 无人机 3D 模型（Three.js）
- Vision AI 识别框
- Copilot 输出弹层

**实现**：
- 半透明 + 45° 扫描线纹理
- 边缘轻微色差（RGB 分离 1px）
- 顶部/底部渐入渐出 mask
- 无外发光

```css
.hologram {
  background: repeating-linear-gradient(
    0deg,
    rgba(57, 255, 20, 0.03) 0px,
    rgba(57, 255, 20, 0.03) 2px,
    transparent 2px,
    transparent 4px
  );
  mask-image: linear-gradient(to bottom, transparent, black 10%, black 90%, transparent);
}
```

### 4.6 明确禁用清单 ❌

- 霓虹辉光（`box-shadow: 0 0 Xpx neon`）
- 渐变按钮（Bootstrap 风）
- 3D 立体阴影（Material 风）
- 大圆角（≥16px）
- 装饰性弹跳/摇摆动画
- 彩虹渐变

---

## 五、Ant Design 5 主题配置

### 5.1 全局 Token

```ts
// theme.ts
import { theme } from 'antd';

export const skymasterDarkTheme = {
  algorithm: theme.darkAlgorithm,
  token: {
    colorPrimary: '#39ff14',
    colorSuccess: '#39ff14',
    colorWarning: '#ffb000',
    colorError:   '#ff3838',
    colorInfo:    '#4c9aff',
    colorBgBase:  '#0d1117',
    colorTextBase:'#e6edf3',
    borderRadius: 4,
    fontFamily:   'Inter, HarmonyOS Sans SC, sans-serif',
    fontSize:     14,
    wireframe:    false,
  },
  components: {
    Layout:   { headerBg: '#161b22', siderBg: '#161b22', bodyBg: '#0d1117' },
    Menu:     { darkItemBg: 'transparent', darkItemSelectedBg: 'rgba(57,255,20,0.1)', darkItemSelectedColor: '#39ff14' },
    Button:   { primaryShadow: 'none', defaultBorderColor: '#30363d' },
    Card:     { colorBgContainer: 'rgba(22,27,34,0.6)', colorBorderSecondary: '#30363d' },
    Table:    { headerBg: '#161b22', rowHoverBg: 'rgba(57,255,20,0.05)' },
    Input:    { colorBgContainer: '#0d1117', activeBorderColor: '#39ff14' },
    Progress: { defaultColor: '#39ff14' },
  },
};
```

### 5.2 主要组件覆写

- **Button primary**：绿底黑字，hover 无外发光只加深底色
- **Table**：斑马纹关闭，仅顶部边框 + 行 hover 高亮 5% 主色
- **Menu**：激活项左侧 3px 主色竖条 + 5% 主色底
- **Modal**：玻璃拟态背板，遮罩 `rgba(0,0,0,0.7)` + blur 6px
- **Notification**：右下角滑入，无阴影，仅左边框 3px 状态色

---

## 六、布局与结构

### 6.1 标准页面骨架

```
┌────────────────────────────────────────────┐
│ Top Bar 48px  ▓Logo▓ [Search] [User] [🔔]  │
├──────┬─────────────────────────────────────┤
│      │                                     │
│Sider │        Main Content Area            │
│ 240  │        (Cesium / Glass Panels)      │
│  or  │                                     │
│  60  │                                     │
│      │                                     │
├──────┴─────────────────────────────────────┤
│ Status Bar 28px  ● 12机在线  ⚡5.6TB  🌐OK │
└────────────────────────────────────────────┘
```

- 顶部栏 48px、状态栏 28px、侧栏 240px（可收起 60px）
- 状态栏是**军工感灵魂**：等宽字体 + 实时跳动数字 + 三色圆点

### 6.2 核心页面首屏

| 页面 | 主视觉 |
|---|---|
| **登录页** | 全屏 3D 地球 + 粒子 + 中央玻璃登录卡 + 底部滚动"系统就绪" |
| **总览 Dashboard** | 全屏 Cesium + 无人机图标脉冲 + 四角玻璃面板（在线/任务/告警/AI） |
| **任务规划** | 60% 地图 + 40% 右侧参数面板（玻璃 + 折叠区块） |
| **实时监控** | 3×3 网格视频墙 + 顶部机队栏 + 右侧遥测面板 |
| **集群编队** | 全屏 Three.js 编队 3D 视图 + 底部时间轴 |
| **模型市场** | 卡片瀑布流 + 粒子背景，卡片 hover 出现全息投影效果 |
| **Copilot** | 右侧滑出抽屉 40% 宽 + 全息紫色边框 + 打字机效果 |

---

## 七、微交互与动效

### 7.1 动效原则

- **持续时间**：hover 150ms / 状态切换 300ms / 页面切换 500ms
- **缓动**：`cubic-bezier(0.4, 0, 0.2, 1)` (Material Standard)
- **禁用**：`prefers-reduced-motion` 自动降级
- **强制**：任何 loading > 1s 必须有明确进度

### 7.2 数字跳动 CountUp

大数字（速度/高度/电量）变化时 300ms 平滑滚动到新值（`react-countup`）。

### 7.3 侧栏 hover 流光

菜单项 hover 时，右侧 4px 主色条从上到下扫过 200ms。

### 7.4 无人机图标脉冲

地图上的每架无人机图标：
- 静态：绿点 4px
- 呼吸：外圈半透明绿 `10px → 20px` 循环 2s
- 告警：切换为红色 + 加速呼吸至 0.5s

### 7.5 Copilot 打字机

AI 输出以 30 char/s 逐字显示，光标闪烁 `▊`，紫色。

---

## 八、图标系统

- **主图标库**：Ant Design Icons（线性风格，已适配暗色）
- **无人机/设备图标**：自定义 SVG，均为线性 1.5px 描边
- **警戒图标**：单色 + 微动画（闪烁频率 1Hz）
- **禁止使用**：填充图标、彩色 emoji、拟物图标

---

## 九、可访问性 & 性能

### 9.1 对比度
- 主文字 vs 底色：`#e6edf3` on `#0d1117` = **17.3:1** ✅ AAA
- 次文字 vs 底色：`#8b949e` on `#0d1117` = **6.4:1** ✅ AA
- 主色 vs 底色：`#39ff14` on `#0d1117` = **13.8:1** ✅ AAA

### 9.2 性能预算
- 首屏 LCP < 2.5s
- Cesium 初始化 < 3s（懒加载）
- 玻璃拟态元素数 ≤ 8 个/屏（避免 GPU 过载）
- 粒子密度自适应（低端设备降至 20 粒子）

### 9.3 键盘导航
- 所有可交互元素 Tab 可达
- 焦点态：2px 主色实线外框（不用光晕）
- 快捷键：`?` 帮助 / `/` 搜索 / `Esc` 退出

---

## 十、实施路线（对齐 §10 Roadmap）

| 版本 | UI 里程碑 |
|---|---|
| v0.1 MVP | 主题 token 落地 + AntD dark 覆写 + 5 个核心页面 |
| v0.5 Beta | 玻璃拟态 + Cesium 全屏 + 数字动效 + 状态栏 |
| v1.0 GA | 全息投影组件库 + 移动响应 + i18n（中/英） |
| v2.0 | Copilot 抽屉 + 模型市场卡片 + 社区页 |
| v2.1 | 3DGS 展厅 + WebGPU 加速 + 大屏模式（4K/8K） |

---

## 附录 A · 参考截图 mockup 描述（首屏 Dashboard）

```
[背景层] 全屏 Cesium 中国夜景 → 缓慢自转 → 城市灯光颗粒感
[粒子层] 40 个绿色粒子 + 淡连线
[顶部栏] SkyMaster ▎ 深度搜索 [_______] 🔔3 👤duoduo
[左侧栏] ▎总览 · 设备 · 任务 · 直播 · 集群 · AI · 报备 · 数据
[主区左上] 玻璃卡：在线无人机 [12 / 15]  🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢
[主区右上] 玻璃卡：今日任务 [7 完成 / 2 进行 / 1 待批]
[主区左下] 玻璃卡：告警 [1 高 / 3 中 / 5 低]  最新告警行
[主区右下] 玻璃卡：AI Copilot [紫色小图标] "3 分钟前生成了..."
[中央]     Cesium 地球上 12 个绿点脉冲 + 1 个红点闪烁
[状态栏]   ● 12在线  ⚡5.6TB  🌐OK  💾92%  🕐01:45:32 UTC+8
```

---

**下一步**：
1. 招 1 名 UI Designer 出高保真 Figma
2. 前端组落地主题 Token + 5 个核心页面 mockup 实现
3. 建立 Storybook 组件库
4. UI 评审 → Beta 版试点用户 dogfood

🐈
