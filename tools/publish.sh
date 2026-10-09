#!/usr/bin/env bash
# ============================================================
# 麦门营养配餐官 · 一键发布脚本
#
# 用途：在你完成 GitHub 登录后，一条命令完成
#   仓库创建 → 首次推送 → workbuddy.md 地址回填 → 提交
#
# 用法：
#   bash tools/publish.sh你的GitHub用户名
#   例：bash tools/publish.sh yourname
#
# 前置条件：
#   1. 已安装 git
#   2. 已配置 GitHub 凭证（二选一）：
#      a) GitHub CLI：gh auth login
#      b) SSH key 已添加到 GitHub
#   3. 已安装 GitHub CLI（可选，若用 SSH 推送则不需要）
# ============================================================

set -euo pipefail

REPO_NAME="mcd-nutrition-planner"
GITHUB_USER="${1:-}"

if [ -z "$GITHUB_USER" ]; then
    echo "用法：bash tools/publish.sh 你的GitHub用户名"
    exit 1
fi

cd "$(dirname "$0")/.."
PROJECT_DIR="$(pwd)"

echo "=============================================="
echo " 麦门营养配餐官 · 发布流程"
echo " 项目目录：${PROJECT_DIR}"
echo " 仓库名称：${REPO_NAME}"
echo " 目标地址：https://github.com/${GITHUB_USER}/${REPO_NAME}"
echo "=============================================="
echo ""

# ---------- 1. 安全检查 ----------
echo "[1/6] 安全检查..."
# 匹配真实 Token 的特征：Bearer 后长串、或用户实际 Token 前缀
# 注意：脚本自身包含此正则，故排除 tools/publish.sh 自身
LEAK=$(grep -rE "Bearer [A-Za-z0-9]{20,}|15vKBEob" \
    --include="*.md" --include="*.json" --include="*.py" . 2>/dev/null \
    | grep -v "tools/publish.sh" || true)
if [ -n "$LEAK" ]; then
    echo "  ❌ 检测到疑似真实 Token："
    echo "$LEAK" | sed 's/^/     /'
    echo "  请先清理后再发布！"
    exit 1
fi
echo "  ✅ 未发现真实 Token"

if [ ! -f "CONTEST_DECLARATION.md" ] || [ ! -f "MCP_INTEGRATION.md" ] || [ ! -f "README.md" ]; then
    echo "  ❌ 缺少参赛必备文件"
    exit 1
fi
echo "  ✅ 必备文件齐备"

# ---------- 2. 离线自检 ----------
echo ""
echo "[2/6] 运行离线自检..."
if command -v python > /dev/null 2>&1; then
    PY=python
elif command -v python3 > /dev/null 2>&1; then
    PY=python3
else
    echo "  ⚠️ 未找到 Python，跳过自检"
    PY=""
fi
if [ -n "$PY" ]; then
    if $PY scripts/nutrition_engine.py > /dev/null 2>&1; then
        echo "  ✅ 引擎自检通过"
    else
        echo "  ❌ 引擎自检失败，请先修复"
        exit 1
    fi
fi

# ---------- 3. 回填仓库地址 ----------
echo ""
echo "[3/6] 回填 workbuddy.md 中的项目地址..."
REPO_URL="https://github.com/${GITHUB_USER}/${REPO_NAME}"
if grep -q "待填（提交时替换为实际 GitHub 仓库地址）" workbuddy.md; then
    # macOS 用sed -i ''，GNU 用 sed -i
    if sed --version > /dev/null 2>&1; then
        sed -i "s|待填（提交时替换为实际 GitHub 仓库地址）|${REPO_URL}|g" workbuddy.md
    else
        sed -i '' "s|待填（提交时替换为实际 GitHub 仓库地址）|${REPO_URL}|g" workbuddy.md
    fi
    echo "  ✅ 已回填：${REPO_URL}"
else
    echo "  ℹ️ 无需回填（可能已填写）"
fi

# ---------- 4. 提交 ----------
echo ""
echo "[4/6] 提交变更..."
git add -A
if git diff --cached --quiet; then
    echo "  ℹ️ 无新变更"
else
    git commit -q -m "docs: 回填仓库地址，补充演示素材"
    echo "  ✅ 已提交"
fi

# ---------- 5. 创建远程仓库 ----------
echo ""
echo "[5/6] 创建 GitHub 远程仓库..."
if git remote get-url origin > /dev/null 2>&1; then
    echo "  ℹ️ origin 已存在：$(git remote get-url origin)"
else
    if command -v gh > /dev/null 2>&1 && gh auth status > /dev/null 2>&1; then
        gh repo create "${REPO_NAME}" --public --source=. --remote=origin --push
        echo "  ✅ 已通过 gh 创建并推送"
    else
        echo ""
        echo "  ⚠️ 未检测到 gh CLI 或未登录"
        echo ""
        echo "  请手动完成以下步骤："
        echo "    1. 在 GitHub 网页新建仓库（名称：${REPO_NAME}，设为 Public，"
        echo "       不要勾选 README/.gitignore/LICENSE）"
        echo "    2. 执行以下命令推送："
        echo ""
        echo "       git remote add origin git@github.com:${GITHUB_USER}/${REPO_NAME}.git"
        echo "       git push -u origin main"
        echo ""
        echo "  （SSH 方式无需 gh。若用 HTTPS，需配置 Personal Access Token）"
        exit 0
    fi
fi

# ---------- 6. 后续提醒 ----------
echo ""
echo "[6/6] 发布完成"
echo "=============================================="
echo " 仓库地址：${REPO_URL}"
echo ""
echo " 接下来请到官方仓库提交报名 Issue："
echo " https://github.com/M-China/mcd-developer-innovation-challenge/issues"
echo ""
echo " Issue 格式："
echo " -----------------------------------------"
echo " 【参赛申请】"
echo " 项目名称：麦门营养配餐官"
echo " 项目地址：${REPO_URL}"
echo " 项目简介：身材管控期也想吃麦当劳？营养配餐官按热量、蛋白质、预算"
echo "           三目标优化具体组合，并明确标注达标率（含真实数据踩坑记录）"
echo " -----------------------------------------"
echo ""
echo " ⏰ 报名截止：2026-10-25 23:59（北京时间）"
echo " 🏆 WorkBuddy 专项：前 100 名 + 提交 workbuddy.md = 3000积分"
echo "=============================================="