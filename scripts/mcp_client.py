#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麦门营养配餐官 · MCP 客户端
McdNutrition Planner - MCP Client

直连麦当劳 MCP Server（Streamable HTTP）。
之所以不直接依赖 MCP Client 的工具注入，是因为本项目需要在任意
Agent / 任意 MCP Client 环境下都能跑，同时支持命令行独立调试。

安全：Token 只从环境变量 MCD_MCP_TOKEN 读取，绝不硬编码、绝不落盘到日志。
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

MCP_URL = os.environ.get("MCD_MCP_URL", "https://mcp.mcd.cn")
TOKEN_ENV = "MCD_MCP_TOKEN"
PROTOCOL_VERSION = "2025-06-18"
RATE_LIMIT_PER_MIN = 600


class McdMcpError(RuntimeError):
    """MCP 调用失败。错误码见官方文档：401 Token 失效/ 429 触发限流。"""


class McdMcpClient:
    def __init__(self, token: str | None = None, url: str | None = None) -> None:
        self.token = token or os.environ.get(TOKEN_ENV, "")
        self.url = url or MCP_URL
        self._session: str | None = None
        self._initialized = False
        if not self.token:
            raise McdMcpError(
                "未找到 MCP Token。请设置环境变量 %s，"
                "申请地址 https://open.mcd.cn/mcp" % TOKEN_ENV
            )

    # ---------- 底层 JSON-RPC ----------

    def _rpc(self, method: str, params: dict[str, Any] | None = None,
             notify: bool = False) -> dict[str, Any] | None:
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if not notify:
            body["id"] = 1
        if params is not None:
            body["params"] = params
        if self._session:
            body["sessionId"] = self._session

        req = urllib.request.Request(
            self.url, data=json.dumps(body).encode("utf-8"), method="POST"
        )
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json, text/event-stream")
        req.add_header("Authorization", "Bearer " + self.token)
        req.add_header("MCP-Protocol-Version", PROTOCOL_VERSION)

        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                sid = resp.headers.get("Mcp-Session-Id")
                if sid:
                    self._session = sid
                raw = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:300]
            except Exception:
                pass
            if e.code == 401:
                raise McdMcpError("401：MCP Token 无效或已过期，请重新申请") from e
            if e.code == 429:
                raise McdMcpError(
                    "429：触发限流（每分钟上限 %d 次请求），请降低频率" % RATE_LIMIT_PER_MIN
                ) from e
            raise McdMcpError("HTTP %s：%s" % (e.code, detail)) from e
        except urllib.error.URLError as e:
            raise McdMcpError("网络错误：%s" % e.reason) from e

        if notify:
            return None

        # Streamable HTTP 可能返回 SSE 分帧，也可能返回纯 JSON
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                line = line[5:].strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        raise McdMcpError("响应不是合法 JSON-RPC：%r" % raw[:200])

    def connect(self) -> None:
        if self._initialized:
            return
        self._rpc("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "mcd-triple-target", "version": "1.0.0"},
        })
        self._rpc("notifications/initialized", {}, notify=True)
        self._initialized = True

    # ---------- 业务方法 ----------

    def list_tools(self) -> list[str]:
        self.connect()
        r = self._rpc("tools/list", {})
        tools = (r or {}).get("result", {}).get("tools", [])
        return [t["name"] for t in tools]

    def call(self, name: str, args: dict[str, Any] | None = None) -> str:
        """调用工具并返回原始文本（交由 nutrition_engine 解包）。"""
        self.connect()
        r = self._rpc("tools/call", {"name": name, "arguments": args or {}})
        if r is None:
            raise McdMcpError("工具 %s 无响应" % name)
        if "error" in r:
            raise McdMcpError("工具 %s 返回错误：%s" % (name, r["error"]))
        result = r.get("result", {})
        if result.get("isError"):
            texts = [c.get("text", "") for c in result.get("content", [])]
            raise McdMcpError("工具 %s 执行失败：%s" % (name, " ".join(texts)[:300]))
        return "\n".join(
            c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"
        )

    # --- 营养与菜单（核心链路）---

    def list_nutrition_foods(self) -> list[dict[str, Any]]:
        from nutrition_engine import load_nutrition_table
        return load_nutrition_table(self.call("list-nutrition-foods"))

    def query_nearby_stores(self, city: str, keyword: str = "",
                            be_type: int = 1) -> dict[str, Any]:
        return {"raw": self.call("query-nearby-stores", {
            "beType": be_type, "searchType": 2,
            "city": city, "keyword": keyword,
        })}

    def query_meals(self, store_code: str, order_type: int = 1,
                    be_type: int = 1, be_code: str | None = None) -> str:
        args: dict[str, Any] = {
            "storeCode": store_code, "orderType": order_type, "beType": be_type}
        if be_code:
            args["beCode"] = be_code
        return self.call("query-meals", args)

    def calculate_price(self, store_code: str, order_type: int, be_type: int,
                        items: list[dict[str, Any]],
                        be_code: str | None = None) -> str:
        args: dict[str, Any] = {
            "storeCode": store_code, "orderType": order_type,
            "beType": be_type, "items": items,
        }
        if be_code:
            args["beCode"] = be_code
        return self.call("calculate-price", args)

    # --- 优惠与账户（辅助链路）---

    def available_coupons(self) -> str:
        return self.call("available-coupons")

    def auto_bind_coupons(self) -> str:
        return self.call("auto-bind-coupons")

    def query_my_account(self) -> str:
        return self.call("query-my-account")

    def campaign_calendar(self, specified_date: str | None = None) -> str:
        args = {"specifiedDate": specified_date} if specified_date else {}
        return self.call("campaign-calendar", args)


# ---------- 命令行入口 ----------

def _cli() -> int:
    cmds = {
        "tools": "列出全部可用 MCP 工具",
        "nutrition": "拉取并解析全量营养表，输出摘要",
        "stores": "查询附近门店  参数：城市 [关键词]",
        "meals": "查询门店菜单    参数：storeCode [orderType] [beType]",
        "price": "价格计算        参数：storeCode 后接 JSON items",
        "coupons": "查看可领取优惠券",
        "account": "查看积分账户",
        "campaign": "查看活动日历",
    }
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print("麦门营养配餐官 · MCP 客户端\n")
        print("用法：python mcp_client.py <命令> [参数]")
        print("需先设置环境变量 %s\n" % TOKEN_ENV)
        for k, v in cmds.items():
            print("  %-10s %s" % (k, v))
        return 0

    c = McdMcpClient()
    cmd = sys.argv[1]
    rest = sys.argv[2:]

    try:
        if cmd == "tools":
            t = c.list_tools()
            print("可用工具 %d 个：" % len(t))
            for x in sorted(t):
                print("  -", x)
        elif cmd == "nutrition":
            rows = c.list_nutrition_foods()
            print("解析成功：%d 条" % len(rows))
            for r in sorted(rows, key=lambda x: -(x.get("protein") or 0))[:10]:
                print("  %-28s %4s kcal 蛋白 %5s g 钠 %6s mg"
                      % (r.get("productName"), r.get("energyKcal"),
                         r.get("protein"), r.get("sodium")))
        elif cmd == "stores":
            if not rest:
                print("用法：stores <城市> [关键词]")
                return 1
            print(c.query_nearby_stores(rest[0], rest[1] if len(rest) > 1 else "")["raw"][:3000])
        elif cmd == "meals":
            if not rest:
                print("用法：meals <storeCode> [orderType] [beType]")
                return 1
            print(c.query_meals(rest[0],
                                int(rest[1]) if len(rest) > 1 else 1,
                                int(rest[2]) if len(rest) > 2 else 1)[:3000])
        elif cmd == "price":
            items = json.loads(rest[1]) if len(rest) > 1 else []
            print(c.calculate_price(rest[0], 1, 1, items)[:2000])
        elif cmd == "coupons":
            print(c.available_coupons()[:2000])
        elif cmd == "account":
            print(c.query_my_account()[:2000])
        elif cmd == "campaign":
            print(c.campaign_calendar(rest[0] if rest else None)[:2000])
        else:
            print("未知命令：%s（用 --help 查看用法）" % cmd)
            return 1
    except McdMcpError as e:
        print("[MCP 错误] %s" % e, file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(_cli())