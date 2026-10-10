#!/usr/bin/env bash
# ============================================================
# 麦门营养配餐官 · 推送脚本
#
# 前置：已把 ~/.ssh/id_ed25519.pub 添加到 GitHub
#       Settings → SSH and GPG keys → New SSH key → Authentication key
#
# 本机环境说明：github.com:443 被封（HTTPS 推送报 502），
#   因此走 ssh.github.com:443 通道，配置见 ~/.ssh/config
#
# 用法：bash tools/push.sh
# ============================================================

set -euo pipefail

REPO_NAME="mcd-nutrition-planner"
GITHUB_USER="yftu"
REPO_URL="git@github.com:${GITHUB_USER}/${REPO_NAME}.git"

cd "$(dirname "$0")/.."
PROJECT_DIR="$(pwd)"

echo "=============================================="
echo " 麦门营养配餐官 · 推送"
echo " 源目录：${PROJECT_DIR}"
echo " 目标：github.com/${GITHUB_USER}/${REPO_NAME}"
echo "=============================================="
echo ""

# ---------- 1. SSH 连通检测 ----------
echo "[1/4] 检测 SSH 连通性..."
SSH_OUT=$(ssh -o StrictHostKeyChecking=no -o ConnectTimeout=15 -T git@github.com 2>&1 || true)
if echo "$SSH_OUT" | grep -q "successfully authenticated\|Welcome"; then
    echo "  ✅ SSH 认证通过"
elif echo "$SSH_OUT" | grep -q "Permission denied"; then
    echo "  ❌ SSH 认证失败——公钥尚未添加到 GitHub"
    echo ""
    echo "  请访问：https://github.com/settings/ssh/new"
    echo "  Title 填：本机 WorkBuddy"
    echo "  Key 粘贴：$(cat ~/.ssh/id_ed25519.pub)"
    echo ""
    exit 1
else
    echo "  ⚠️ 连接异常：${SSH_OUT}"
    echo "  若提示超时，多为当前网络无法连通 ssh.github.com:443，稍后重试。"
    exit 1
fi

# ---------- 2. 安全扫描 ----------
echo ""
echo "[2/4] Token 安全扫描..."
LEAK=$(grep -rE "Bearer [A-Za-z0-9]{20,}|15vKBEob" \
    --include="*.md" --include="*.json" --include="*.py" . 2>/dev/null \
    | grep -v "tools/publish.sh" | grep -v "tools/push.sh" || true)
if [ -n "$LEAK" ]; then
    echo "  ❌ 检测到疑似真实 Token，已中止推送："
    echo "$LEAK" | sed 's/^/     /'
    exit 1
fi
echo "  ✅ 未发现真实 Token"

# ---------- 3. 引擎自检 ----------
echo ""
echo "[3/4] 引擎离线自检..."
if command -v python > /dev/null 2>&1; then PY=python; else PY=python3; fi
if $PY scripts/nutrition_engine.py > /dev/null 2>&1; then
    echo "  ✅ 自检通过"
else
    echo "  ❌ 自检失败"
    exit 1
fi

# ---------- 4. 推送 ----------
echo ""
echo "[4/4] 推送至 GitHub..."
if [ -d ".git" ]; then
    if git remote get-url origin > /dev/null 2>&1; then
        git remote set-url origin "${REPO_URL}"
    else
        git remote add origin "${REPO_URL}"
    fi
else
    git init -q
    git remote add origin "${REPO_URL}"
fi

git add -A
if git diff --cached --quiet; then
    echo "  ℹ️ 无新变更待推送"
else
    git commit -q -m "chore: 发布前检查通过"
fi

git push -u origin HEAD:main
echo "  ✅ 推送完成"

# ---------- 5. 兜底：远程为空时补建 README ----------
NEED_SEED=0
if git ls-remote origin > /dev/null 2>&1; then
    CNT=$(git ls-remote origin | wc -l)
    if [ "$CNT" -eq 0 ]; then NEED_SEED=1; fi
else
    NEED_SEED=1
fi
if [ "$NEED_SEED" -eq 1 ]; then
    echo ""
    echo "  ⚠️ 远程仍为空仓库（GitHub 未接收到提交）"
    echo "  常见原因：仓库初始化时勾选了 README/.gitignore/LICENSE。"
    echo "  补救：删除远程仓库重建（新建时不要勾选任何文件），"
    echo "        或用 https://github.com/new?name=${REPO_NAME} 重建后重跑本脚本。"
fi

echo ""
echo "=============================================="
echo " 仓库地址：https://github.com/${GITHUB_USER}/${REPO_NAME}"
echo ""
echo " 下一步 · 设置仓库描述（提升可发现性）"
echo "   Topics: mcp mcdonalds skill nutrition claude ai"
echo ""
echo " 下一步 · 到官方仓库报名"
echo "   https://github.com/M-China/mcd-developer-innovation-challenge/issues"
echo ""
echo " Issue 正文："
echo " -----------------------------------------"
echo " 【参赛申请】"
echo " 项目名称：麦门营养配餐官"
echo " 项目地址：https://github.com/${GITHUB_USER}/${REPO_NAME}"
echo " 项目简介：身材管控期也想吃麦当劳？本 Skill 按热量、蛋白质、预算"
echo "           三目标优化点餐组合，并明确标注达标率。含 MCP 四层响应"
echo "           解包、toon 格式解析与阈值数据标定的完整实现。"
echo " -----------------------------------------"
echo ""
echo " ⏰ 报名截止：2026-10-25 23:59（北京时间）"
echo "=============================================="