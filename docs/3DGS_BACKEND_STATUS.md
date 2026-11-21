# 3DGS 重建后端 — 真实验证状态与收口说明

> 2026-11-21 · 对应 develop 分支本轮收口。本文纠正历史上「已完成 70%」的模糊口径，
> 用**代码事实 + 本机实测**说明哪些链路是真通的、哪些仍是 mock，以及如何切真训练。

## 一、结论速览

| 环节 | 真实状态 | 本机可验 |
|---|---|---|
| Executor 选择开关 | ✅ 统一（本轮修复） | ✅ |
| COLMAP SfM（稀疏重建） | ✅ 真二进制，`automatic_reconstructor` | ✅ 已跑通 |
| 训练（gsplat/nerfstudio） | ⚠️ 命令构造真实，默认 mock；真训练需 nerfstudio 环境 | ❌ 本机版本冲突 |
| 产物自动注册（.ply/.splat → CAS → 可下载） | ✅ 本轮新增 | ✅ 合成 ply 已验 |
| 作业队列 / worker | ⚠️ 骨架（stub），未与本链路接线 | — |

一句话：**COL MAP 真跑通、产物闭环真跑通、真训练卡在 nerfstudio 依赖版本，已留好切换开关。**

## 二、本轮修复的真实 Bug

**executor 开关错位**（历史遗留，导致设了 env 也不生效）：

- `main.py` 读 `SKYMASTER_REAL_GS_EXECUTORS`（布尔），
- `scene_executors.make_default_executor()` 读 `SKYMASTER_EXECUTOR`（模式字符串），
- 生产装配只走 `main.py`，所以文档里写的 `SKYMASTER_EXECUTOR=gsplat` **从未生效**。

修复：统一到 `scene_executors.resolve_executor_mode()`，优先级：

1. `SKYMASTER_EXECUTOR`（显式：noop / colmap / gsplat / gsplat4d）
2. `SKYMASTER_REAL_GS_EXECUTORS`（legacy 布尔，true → gsplat，配合 `SKYMASTER_SCENE_KIND_DEFAULT=4dgs` → gsplat4d）
3. `config/scene_3dgs.json` 的 `executor.mode`（默认 noop）

`main.py` 与工厂现在都调这一个函数；`_real_gs_executors_enabled()` 退化为布尔 shim。

## 三、配置驱动

`backend/config/scene_3dgs.json`（可用 `SKYMASTER_SCENE_CONFIG` 覆盖）：

- `executor` — 模式、env 名、别名、默认场景类型
- `runtime` — workdir、docker 镜像、超时、docker 开关（默认 **false**，本机无 Docker）
- `commands` — colmap / gsplat / gsplat4d 的命令参数
- `artifacts` — 产物自动注册开关、glob、按扩展名映射 kind、大小上限

敏感/运行时值仍以环境变量为准；配置文件只放默认值与业务规则。

## 四、本机实测

### 4.1 COLMAP 稀疏重建 — ✅ 通过

```
环境：COLMAP 3.9.1 (CPU build)，WSL Ubuntu 24.04
夹具：scripts/gen_colmap_fixture.py 生成 12 张合成多视角棋盘格图（确定性 seed，无网络）
命令：colmap automatic_reconstructor --workspace_path ... --image_path ... --sparse 1 --dense 0
结果：sparse/0/{cameras,images,points3D}.bin 全部产出，25 个 3D 点，2 张图配准
测试：SKYMASTER_TEST_REAL_COLMAP=1 pytest tests/test_scene_real_colmap.py  → 2 passed
```

`test_scene_real_colmap.py` 默认跳过（需 `colmap` 二进制），CI 不会因缺二进制而红。

### 4.2 真 3DGS 训练 — ❌ 本机版本冲突，保持 mock

```
本机：Python 3.12.3 / torch 2.10.0+cu128 (CUDA 可用) / gsplat 1.5.3 / RTX 5070 12GB
nerfstudio 1.1.5 的 PyPI 元数据硬约束：gsplat==1.4.0
Dockerfile.gpu-worker 声明：torch 2.4.0+cu124 + nerfstudio 1.1.5
冲突：装 nerfstudio 会强降 gsplat 1.5.3→1.4.0，且 torchvision 需匹配更老的 torch；
      系统 Python 3.12 受 PEP668 保护、无 venv/ensurepip，无法干净隔离安装。
```

结论：不在本机强行安装以免破坏现有 torch/cuda。真训练链路保持「命令构造真实 +
默认 NoOp」，通过配置开关在具备 GPU worker 镜像的环境启用。

## 五、产物自动注册闭环（本轮新增）

训练成功后不再「只写本地文件」，而是：

1. `ExecResult.artifact_paths` — executor 成功后扫描输出目录（`artifacts.output_globs`）填产物路径；
2. `scene_artifacts_service.register_produced_artifacts()` — 流式写入 CAS（复用
   `object_storage.stage_chunk/assemble`，1 MiB 分块）、按 sha256 幂等、建 `SceneAsset`
   行（`uploaded_by=NULL` 表示系统产物）；
3. `scene_pipeline.start_training()` 转 `ready` 前调用，结果摘要写入 `scene.meta.training_artifacts`；
4. 前端既有产物列表 / `GET /scenes/{id}/assets/{aid}/download` 自动可见可下载。

失败降级：注册异常不会把已成功的训练翻成 `failed`（记 log + `meta.errors`）。
测试：`tests/test_scene_artifacts_service.py`（10 passed，含幂等/跳过大文件/损坏降级/pipeline 集成）。

## 六、如何在有 GPU worker 的环境切真训练

```bash
# 方案 A — 用nerfstudio GPU 镜像（Dockerfile.gpu-worker，已锁 torch2.4/cu124 + gsplat1.4）
export SKYMASTER_EXECUTOR=gsplat          # 或 gsplat4d / colmap
export SKYMASTER_USE_DOCKER=1             # 用镜像，避免污染宿主机 Python
export SKYMASTER_GSPLAT_IMAGE=nerfstudio/nerfstudio:latest

# 方案 B — 原生安装（需匹配 gsplat==1.4.0，建议在专用 venv/python3.10-3.11）
export SKYMASTER_EXECUTOR=gsplat
export SKYMASTER_USE_DOCKER=0
```

4DGS 追加 `SKYMASTER_SCENE_KIND_DEFAULT=4dgs`（legacy 路径）或直接 `SKYMASTER_EXECUTOR=gsplat4d`。

真训练时长：nerfstudio `splatfacto` 默认 30000 iterations，1000 图 @A100 目标 P95 < 30min
（见 PRODUCT_SPEC）；本机未实测，不在本轮承诺。

## 七、仍未接线 / 历史欠账（诚实清单）

- `gpu_worker.py` 三个 executor 仍是 `sleep(2)` 假数据，`enqueue()` 没有业务调用点；
- `docker-compose.yml` 没有 worker 服务，仅 K8s 清单声明；
- 主栈 `sim.py` 的 HTTP 命令旁路为 3 机演示保留，与本项目 MAVLink 双向链路是两条路；
- 真训练产物 → `.ply` 导出依赖 nerfstudio 自己的 `ns-export`，本轮产物注册验证用的是合成 ply；
- 旧文档（V2_1_T1_2/T1_5、V2.0_ROADMAP、PRODUCT_SPEC）口径写「已完成」，其完成定义是
  API + 状态机 + mock 测试 + viewer，不含真训练；以本文为准。
