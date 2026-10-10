#!/usr/bin/env bash
# ============================================================
# 验证仓库 Description / Topics 是否设置成功
#
# 本机环境说明：github.com 网页被封（443），但 api.github.com /
# raw.githubusercontent.com / codeload.github.com 可通。
# 未认证 GitHub API 限流仅 60 次/小时，脚本自带等待重试逻辑。
# ============================================================

set -uo pipefail

REPO="${1:-yftu/mcd-triple-target}"
PY="C:/Users/Tuyufeng/.workbuddy/binaries/python/versions/3.13.12/python.exe"

echo "=============================================="
echo " 仓库设置核查：${REPO}"
echo "=============================================="
echo ""

# 直接用浏览器方式访问会失败，故用 Python urllib 走可用通道
"$PY" - "$REPO" << 'PYEOF'
import json, sys, time, urllib.request, urllib.error

repo = sys.argv[1]


def fetch(url):
    req = urllib.request.Request(
        url, headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/vnd.github+json",
        })
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.read().decode("utf-8", "replace")
    except Exception as e:
        return json.dumps({"message": str(e)})


def main():
    url = "https://api.github.com/repos/%s" % repo

    # 限流时等待重置
    for attempt in range(1, 4):
        raw = fetch(url)
        try:
            d = json.loads(raw)
        except Exception:
            print("  ⚠️ 响应无法解析（网络问题），重试中...")
            time.sleep(5)
            continue

        if "rate limit" not in str(d.get("message", "")).lower():
            break

        import datetime
        rl = fetch("https://api.github.com/rate_limit")
        try:
            reset = json.loads(rl)["resources"]["core"]["reset"]
        except Exception:
            reset = int(time.time()) + 120
        wait = reset - int(time.time()) + 10
        if wait > 1800 or wait < 0:
            print("  ⏳ 未认证 API 已限流，需等待约 %.0f 分钟" % (max(wait, 0) / 60))
            print("")
            print("  替代方案（不依赖 API）：")
            print("    直接在浏览器打开：https://github.com/%s" % repo)
            print("    看右侧 About 区域是否有标签显示")
            print("")
            print("  或设置 Personal Access Token 后重试：")
            print("    https://github.com/settings/tokens/new")
            print("    勾选 public_repo 权限即可（只读公开信息其实不需要，")
            print("    但可获得 5000 次/小时的认证额度）")
            return
        print("  ⏳ 触发限流，等待 %d 秒后重试（第 %d 次）..." % (wait, attempt))
        time.sleep(wait)

    if "full_name" not in d:
        print("  ❌ 读取失败：%s" % str(d.get("message"))[:120])
        return

    print("  仓库     : %s" % d["full_name"])
    print("  可见性   : %s" % d.get("visibility"))
    print("  描述     : %s" % (d.get("description") or "(未设置)"))
    print("")
    topics = d.get("topics") or []
    print("  Topics   : %s" % ("、".join(topics) if topics else "(未设置)"))

    # 校验
    print("")
    print("  " + "-" * 44)
    ok_desc = bool(d.get("description"))
    ok_top = len(topics) > 0
    print("  Description : %s" % ("✅ 已设置" if ok_desc else "❌ 未设置"))
    print("  Topics      : %s" % ("✅ 已设置（%d 个）" % len(topics) if ok_top else "❌ 未设置"))
    print("  Star        : %d" % d.get("stargazers_count", 0))
    if d.get("stargazers_count", 0) == 0:
        print("")
        print("  ⚠️  Star 为 0 将无法进入排行榜（规则要求 Star>0）")
    print("  " + "-" * 44)

    if ok_desc and ok_top:
        print("")
        print("  ✅ 基础设置已完整，可进行Star 运营")
    else:
        print("")
        print("  📌 缺失项需补齐：")
        if not ok_desc:
            print("     · Description →仓库主页右侧 About 区铅笔图标")
        if not ok_top:
            print("     · Topics      → 同一位置，点 Add a topic 逐个添加")
            print("       建议：mcp mcdonalds skill nutrition ai")


main()
PYEOF

echo ""
