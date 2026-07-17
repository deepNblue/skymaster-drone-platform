#!/bin/bash
# SkyMaster v0.1 · Sprint 0 · Backend Foundation Agent 启动脚本
# 用于 tmux 单 pane 验证 ClawTeam 模式

set -e

# 1. 修复 node PATH
export PATH="$HOME/.nvm/versions/node/v20.20.1/bin:$PATH"
which node || { echo "❌ node 不在 PATH"; exit 1; }

# 2. 进入工作目录
WORK_DIR=/home/duoduo/projects/skymaster-drone-platform/backend-v0.1
cd $WORK_DIR

# 3. 确保 TASK.md 存在
[ -f TASK.md ] || { echo "❌ TASK.md 不存在"; exit 1; }

# 4. 初始化 PROGRESS.md
cat > PROGRESS.md << 'EOF'
# Sprint 0 · Backend v0.1 进度

## 启动时间
$(date '+%Y-%m-%d %H:%M:%S')

## 阶段进度

EOF

echo "🚀 启动 Claude Agent · 目标：Backend v0.1 骨架"
echo "工作目录: $WORK_DIR"
echo "任务说明: $WORK_DIR/TASK.md"
echo ""
echo "配置："
echo "  ANTHROPIC_BASE_URL=$(python3 -c 'import json; print(json.load(open("/home/duoduo/.claude/settings.json"))["env"]["ANTHROPIC_BASE_URL"])')"
echo "  ANTHROPIC_MODEL=$(python3 -c 'import json; print(json.load(open("/home/duoduo/.claude/settings.json"))["env"]["ANTHROPIC_MODEL"])')"
echo ""
echo "════════════════════════════════════════════"
echo ""

# 5. 拼装 prompt
PROMPT="你是 SkyMaster v0.1 Backend Foundation Engineer。

请仔细阅读 /home/duoduo/projects/skymaster-drone-platform/backend-v0.1/TASK.md 中定义的完整任务，然后按 5 个阶段顺序完成：

1. 项目结构（10分钟）
2. docker-compose.yml（15分钟）
3. Alembic 10张表初始迁移（20分钟）
4. FastAPI 基础接口（20分钟）
5. 冒烟测试（15分钟）

关键要求：
- 每完成一阶段，追加一行到 PROGRESS.md
- 不要启动 docker 服务（用户会手动验证）
- 不要复用 /home/duoduo/projects/skymaster-drone-platform/backend/ 的旧代码
- 完成后停止，不要推进 Sprint 1

参考文档：
- /home/duoduo/projects/skymaster-drone-platform/docs/SDD_v0.1_MVP.md (主要 SDD)
- /home/duoduo/projects/skymaster-drone-platform/docs/PRODUCT_SPEC.md §7

现在开始，先读 TASK.md，然后从阶段 1 开始。"

# 6. 启动 claude（stream-json 便于监控 · full auto）
claude --print --output-format stream-json --verbose \
    --permission-mode bypassPermissions \
    "$PROMPT" 2>&1 | tee agent.log
