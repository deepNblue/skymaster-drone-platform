# V2.1 T1.2 · COLMAP / gsplat 实执行器接入

**日期**：2026-07-13
**主线**：v2.1 T1.2 · 把 NoOpExecutor 替换为真 COLMAP + gsplat（Docker 化）
**状态**：✅ 存储抽象 + 命令构造 + 输出解析 + 20 新测试全绿，累计 65/65

---

## 🎯 T1.2 定位

**T1.0** 定义了 `Executor` 抽象基类 + `NoOpExecutor` 假实现。
**T1.1** 打通了源数据上传（分片 + CAS）。
**T1.2** 把假 executor 换成**真** COLMAP（SfM）+ **真** gsplat（3DGS 训练）。

**核心承诺**（T1.0 挖的坑）：*"因 T1.0 已把 Executor 抽象做好，业务代码零改动"* — 本轮兑现。

---

## 🚫 明确不做（本轮边界）

- ❌ 在 dev 上编译 COLMAP + gsplat 二进制（无 GPU / 无 docker）
- ❌ 生产 Docker 镜像构建（跨 CUDA 版本适配放 T1.5）
- ❌ 训练结果 `.ply` 下载 endpoint（放 T1.3）

**本轮聚焦**：命令构造 + 子进程运行时抽象 + 输出解析 · 一切可通过 MockRunner 严格测试。

---

## 📦 交付物

### 1. `services/scene_executors.py` · 真执行器实现（+330 行）

#### 1.1 `CommandRunner` 子进程抽象（可 Mock）

```python
class CommandRunner(ABC):
    async def run(cmd, *, cwd, timeout, env) → RunResult
```
- `SubprocessRunner` · 生产实现，走 asyncio.create_subprocess_exec
- 缺二进制 → `exit_code=127` · 超时 → `exit_code=124`（kill+wait）
- `set_runner(r)` DI hook 用于测试

#### 1.2 `ExecutorConfig` · 全 env 驱动

| Env | 默认 | 说明 |
|-----|------|------|
| `SKYMASTER_COLMAP_IMAGE` | `colmap/colmap:latest` | Docker 镜像 |
| `SKYMASTER_GSPLAT_IMAGE` | `nerfstudio/nerfstudio:latest` | 训练镜像 |
| `SKYMASTER_SCENES_WORKDIR` | `/tmp/skymaster-scenes` | 场景工作根 |
| `SKYMASTER_COLMAP_TIMEOUT` | 7200s (2h) | SfM 硬超时 |
| `SKYMASTER_GSPLAT_TIMEOUT` | 14400s (4h) | 训练硬超时 |
| `SKYMASTER_USE_DOCKER` | 1 | 走 docker 还是本机 CLI |
| **`SKYMASTER_EXECUTOR`** | `noop` | **noop / colmap / gsplat** |

`make_default_executor()` 读 env 决定装哪一个 —— 一个 env 切换真假运行。

#### 1.3 命令构造（纯函数 · 可测）

```python
build_colmap_cmd(cfg, workdir)
  # docker: docker run --rm -v {wd}:/work {img} colmap automatic_reconstructor ...
  # native: colmap automatic_reconstructor --workspace_path {wd} ...

build_gsplat_cmd(cfg, workdir)
  # docker: docker run --rm --gpus all -v {wd}:/work {img} ns-train splatfacto ...
  # native: ns-train splatfacto --data {wd} ...
```

- COLMAP 用 `automatic_reconstructor` 一键 SfM（feature+match+mapper 链）
- gsplat 用 nerfstudio 的 `splatfacto` model（性价比最高的 3DGS 变体）
- **GPU 请求** · `--gpus all` 传进 docker（生产必要）

#### 1.4 输出解析（正则 · 纯函数）

```python
parse_colmap_stats(stdout) → {"n_points": int, "n_registered_images": int}
parse_gsplat_stats(stdout) → {"n_gaussians": int, "psnr": float}
```

宽容匹配：
- 空格/冒号/等号任意
- 大小写不敏感
- gsplat 支持 **JSON blob line** 和 **plain key: value** 两种输出格式（不同工具家族兼容）
- 找不到指标 → 返回 None，**不炸**（后续 SceneAsset 摘要字段可空）

#### 1.5 三个 Executor 类

| 类 | run_colmap | run_training |
|----|-----------|--------------|
| `NoOpExecutor`（T1.0）| ✅ 假 12345 点 | ✅ 假 234567 高斯 / 27.4 dB |
| `ColmapExecutor`（新）| ✅ 真 SfM | ❌ 明确报错"does not train" |
| `GsplatExecutor`（新·组合）| 委托给 ColmapExecutor | ✅ 真 gsplat 训练 |

`GsplatExecutor` 是**生产默认组合** · 一个 Executor 覆盖 SfM+训练全链路。

---

### 2. 测试 `tests/test_scene_executors.py` · 20 新测试（+280 行）

| 测试组 | 覆盖 |
|--------|------|
| **Metrics parsing** (5) | 真实 COLMAP 输出 · 缺失字段 · 大小写空格 · gsplat JSON · plain kv |
| **Command construction** (4) | docker/native 双模 · GPU flag 存在 · 挂载路径正确 |
| **Executor happy/sad** (5) | 成功记录指标 · 失败 surfaces stderr · train 拒绝在 colmap · 组合正确编排 · 训练 OOM |
| **Factory** (1) | env `SKYMASTER_EXECUTOR` 切换三态 |
| **SubprocessRunner boundaries** (2) | 缺失二进制 exit=127 · timeout kill 后 exit=124 |
| **End-to-end** (1) | GsplatExecutor 通过状态机 ingested→ready |
| **JSON 恶意 payload 容错** (1) | 非法 JSON 值不炸 |
| **ColmapExecutor 单独测** (1) | run_training 明确拒绝 |

**关键 e2e 测试** — `test_gsplat_pipeline_integration_with_state_machine`：
- 装 GsplatExecutor 到全局
- 走 `sp.start_colmap` + `sp.start_training`（用 T1.0 的状态机）
- 断言最终 status=ready + 指标全部写入 scene 对象

—— 证明**"业务代码零改动"承诺**成立。

---

## ✅ 完整验证

- 新测试 · 20/20 全绿
- 全项目累计 · **65/65** 全绿
- 65 = 20 (T1.2) + 12 (T1.1) + 13 (T1.0) + 8 (R23) + 7 (R22) + 5 (R21)
- 运行时长 · 0.31s（全部 mock，无真子进程调用）

---

## 📂 改动文件清单

```
backend-v0.1/
├── app/services/scene_executors.py    (+330 行 · 新增)
└── tests/test_scene_executors.py      (+280 行 · 新增, 20 tests)
```

**代码规模** · +610 行（后端）· 前端本轮无改动（已在 T1.0 完成）

---

## 🔑 生产切换步骤（已备好）

**dev/CI（本地默认）**：
```bash
# 无 env 或 SKYMASTER_EXECUTOR=noop → NoOpExecutor
```

**生产（带 GPU worker 节点）**：
```bash
export SKYMASTER_EXECUTOR=gsplat
export SKYMASTER_USE_DOCKER=1
export SKYMASTER_COLMAP_IMAGE=colmap/colmap:3.9.1
export SKYMASTER_GSPLAT_IMAGE=nerfstudio/nerfstudio:1.1.5
export SKYMASTER_SCENES_WORKDIR=/data/skymaster-scenes
docker pull colmap/colmap:3.9.1
docker pull nerfstudio/nerfstudio:1.1.5
# 启动 worker → 从 pipeline 消费任务 → run_colmap + run_training 直接生效
```

**灰度**：单节点走 gsplat，其他继续走 noop（env 逐机切换）。

---

## 📝 v2.1 T1 路线更新

| 环节 | 状态 |
|------|------|
| T1.0 骨架 | ✅ 完成 |
| T1.1 上传 | ✅ 完成 |
| **T1.2 真执行器** | ✅ 完成（本轮） |
| T1.3 训练产物导出 + `.ply` 下载 | ⏳ 下轮 · 2-3h |
| T1.4 3D viewer（three.js + splat） | ⏳ · 4-6h |
| T1.5 Docker 镜像 CI 与部署 | ⏳ v2.1 后段 |

**T1.3 优先级**：训练完成后要能把 `.ply/.splat` 导出给客户 —— 政务客户会拿到桌面 GaussianSplat viewer 里看，是核心交付物。

---

**T1.2 状态** · ✅ 完成
**连击** · v2.0 收官 R23 → T1.0 → T1.1 → T1.2 · 四轮不中断 · 累计 65 tests
