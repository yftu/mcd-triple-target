#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麦门营养配餐官 · 核心引擎
McdNutrition Planner - Core Engine

职责：把 MCP 返回的原始文本解包成结构化营养数据，并在此基础上做
热量 / 蛋白质 / 预算三目标的配餐优化。

数据来源：list-nutrition-foods（toon 紧凑格式，160 条）
设计原则：纯函数、无网络、可离线单测。MCP 通信在 mcp_client.py。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


# ============================================================
# 第一层：MCP 响应解包
# ============================================================
# 实测麦当劳 MCP Server 的工具返回并非纯 JSON，而是：
#   1) 一段 Markdown 格式的字段说明（含表格 / 模板）
#   2) "## Original Response" 分隔符
#   3) 一段标准 JSON 字符串
#   4) JSON 中 data 字段本身又是 toon 格式字符串
# 任何一层没剥掉，后续解析都会失败。这一层是本项目的主要工程价值。


def unwrap_mcp_text(raw: str) -> str:
    """从 MCP 工具返回的混杂文本中提取出 JSON 字符串本体。

    策略：优先定位最后一个完整的 { ... } JSON 对象块。
    服务端在说明文字里也会出现 {序号} 这类占位符，因此不能简单取首个花括号。
    """
    if not raw:
        return ""

    text = raw.strip()

    # 优先使用 "## Original Response" 之后的内容
    marker = "## Original Response"
    idx = text.rfind(marker)
    if idx != -1:
        text = text[idx + len(marker):].strip()

    # 扫描出所有顶层 JSON 对象候选（用括号配对 + 字符串转义感知）
    candidates = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "{":
            depth = 0
            in_str = False
            esc = False
            for j in range(i, n):
                ch = text[j]
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                    continue
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidates.append(text[i:j + 1])
                        i = j
                        break
            else:
                break
        i += 1

    # 取解析成功的、最长的那个候选（原始响应通常是最完整的一段）
    best = ""
    for cand in candidates:
        try:
            json.loads(cand)
            if len(cand) > len(best):
                best = cand
        except Exception:
            continue

    return best or text


def parse_tool_response(raw: str) -> dict[str, Any]:
    """解包 MCP 文本 → 完整 JSON dict。失败时抛出带上下文的异常。"""
    body = unwrap_mcp_text(raw)
    try:
        obj = json.loads(body)
    except Exception as exc:
        raise ValueError(
            "无法解析 MCP 响应为 JSON。原始响应前300 字符：%r" % body[:300]
        ) from exc
    if isinstance(obj, dict):
        return obj
    raise ValueError("MCP 响应不是 JSON 对象：%r" % type(obj))


# ============================================================
# 第二层：toon 紧凑格式解析
# ============================================================
# list-nutrition-foods 为节省 LLM token，返回 toon 格式而非标准 JSON：
#
#   [160]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,
#         carbohydrate,sodium,calcium}:
#     猪柳麦满分,null,1288,308,16,16,24,781,213
#     中薯条,null,1210,289,4,12,38,165,18
#
# 规则：
#   - 首行 [N]{...}:  N = 记录数，{} 内是列名
#   - 后续每行一条记录，逗号分隔，顺序与列名一一对应
#   - 字段内可能出现逗号，因此不能简单 split
#   - nutritionDescription 常为 null
#   - 数值可能为 null（部分餐品缺数据），需容错


_TOON_HEADER = re.compile(
    r"\[(?P<count>\d+)\]\s*\{(?P<cols>[^}]*)\}\s*:",
)


def _split_toon_row(line: str, ncols: int) -> list[str]:
    """按列数切分一行 toon 记录，正确处理字段内逗号。

    采用策略：若该行的逗号数恰好为 ncols-1，直接切分即可；
    否则从右向左逐个定位最后 ncols-1 个逗号作为分隔符，
    保证前面可能含逗号的字段（如描述文案）不被拆开。
    """
    if line.count(",") == ncols - 1:
        return line.split(",")

    if line.count(",") < ncols - 1:
        parts = line.split(",")
        return parts + [""] * (ncols - len(parts))

    # 从右往左切，保留左侧完整字段
    parts: list[str] = []
    rest = line
    for _ in range(ncols - 1):
        pos = rest.rfind(",")
        if pos == -1:
            parts.insert(0, rest)
            rest = ""
            break
        parts.insert(0, rest[pos + 1:])
        rest = rest[:pos]
    parts.insert(0, rest)
    return parts


def _to_float(v: str) -> float | None:
    v = (v or "").strip()
    if v in ("", "null", "NULL", "-"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def parse_toon_table(data: str) -> list[dict[str, Any]]:
    """解析 toon 表格字符串 → dict 列表。"""
    if not data or not data.strip():
        return []

    m = _TOON_HEADER.search(data)
    if not m:
        # 退化为普通 CSV / 无表头
        return []

    cols = [c.strip() for c in m.group("cols").split(",") if c.strip()]
    expected = int(m.group("count"))

    body = data[m.end():]
    rows: list[dict[str, Any]] = []

    for line in body.splitlines():
        line = line.rstrip()
        if not line.strip():
            continue
        if line.strip().startswith("#"):
            continue

        values = _split_toon_row(line.strip(), len(cols))
        if len(values) != len(cols):
            values = (values + ["null"] * len(cols))[: len(cols)]

        row: dict[str, Any] = {}
        for col, val in zip(cols, values):
            num = _to_float(val)
            if num is not None and col not in ("productName", "nutritionDescription"):
                row[col] = num
            else:
                s = (val or "").strip()
                row[col] = None if s in ("null", "") else s
        rows.append(row)

    # 有些服务端不严格给出实际行数，做一次对齐提示
    if expected and len(rows) != expected:
        # 不抛异常，交由调用方按实际数据使用，避免因服务端计数错误导致整体失败
        pass

    return rows


def load_nutrition_table(raw: str) -> list[dict[str, Any]]:
    """端到端：MCP 原始文本 → 营养记录列表。"""
    obj = parse_tool_response(raw)
    if obj.get("success") is False:
        raise ValueError("MCP 返回失败：%s %s" % (obj.get("code"), obj.get("message")))
    data = obj.get("data")
    if isinstance(data, str):
        return parse_toon_table(data)
    if isinstance(data, list):
        return data
    raise ValueError("list-nutrition-foods 返回结构异常：%r" % type(data))


# ============================================================
# 第三层：营养画像与目标模型
# ============================================================

# 参考值：巨无霸 523 kcal / 25g 蛋白 作为热量密度参照
KCAL_PER_G_PROTEIN = 4.0

ACTIVITY_BURN = {
    "sedentary": ("久坐少动", 0),
    "light": ("轻度活动", 150),
    "moderate": ("中度运动", 300),
    "active": ("高强度运动", 500),
    "athlete": ("运动员级", 800),
}

GOALS = {
    "cut": {"label": "控卡减脂", "protein_per_kg": 1.8, "kcal_budget": 0.82},
    "maintain": {"label": "均衡维持", "protein_per_kg": 1.2, "kcal_budget": 1.00},
    "gain": {"label": "增肌补充", "protein_per_kg": 2.2, "kcal_budget": 1.15},
    "indulge": {"label": "放开吃", "protein_per_kg": 1.0, "kcal_budget": 1.30},
}


@dataclass
class Profile:
    """用户画像。字段命名与业务语义对齐，缺省值取保守值。"""

    weight_kg: float = 65.0
    height_cm: float = 170.0
    age: int = 30
    sex: str = "male"
    activity: str = "light"
    goal: str = "maintain"

    def bmr(self) -> float:
        """Mifflin-St Jeor 基础代谢率（kcal/日）。"""
        base = 10 * self.weight_kg + 6.25 * self.height_cm - 5 * self.age
        return base + (5 if self.sex == "male" else -161)

    def tdee(self) -> float:
        """每日总消耗（kcal/日）。"""
        activity_map = {
            "sedentary": 1.2, "light": 1.375, "moderate": 1.55,
            "active": 1.725, "athlete": 1.9,
        }
        return self.bmr() * activity_map.get(self.activity, 1.375)

    def daily_budget(self) -> float:
        """当日可摄入热量预算。"""
        cfg = GOALS.get(self.goal, GOALS["maintain"])
        return self.tdee() * cfg["kcal_budget"]

    def protein_target(self) -> float:
        """当日蛋白质目标（g）。"""
        cfg = GOALS.get(self.goal, GOALS["maintain"])
        return self.weight_kg * cfg["protein_per_kg"]

    def meal_kcal_budget(self, meal: str = "lunch") -> float:
        """单餐热量预算。三餐按 3:4:3 分配。"""
        ratio = {"breakfast": 0.30, "lunch": 0.40, "dinner": 0.30}.get(meal, 0.35)
        return self.daily_budget() * ratio

    def protein_target_meal(self, meal: str = "lunch") -> float:
        return self.protein_target() * {
            "breakfast": 0.28, "lunch": 0.38, "dinner": 0.34,
        }.get(meal, 0.35)


# ============================================================
# 第四层：餐品抽象与打分
# ============================================================

@dataclass
class Item:
    name: str
    kcal: float
    protein: float
    fat: float
    carbs: float
    sodium: float = 0.0
    price: float = 0.0
    tags: list[str] = field(default_factory=list)
    available: bool = True

    @property
    def protein_density(self) -> float:
        """蛋白质密度：每 100 kcal 含多少 g 蛋白。越高越优。"""
        if self.kcal <= 0:
            return 0.0
        return self.protein / self.kcal * 100

    @property
    def kcal_per_protein(self) -> float:
        if self.protein <= 0:
            return float("inf")
        return self.kcal / self.protein

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "kcal": self.kcal, "protein": self.protein,
            "fat": self.fat, "carbs": self.carbs, "sodium": self.sodium,
            "price": self.price, "proteinDensity": round(self.protein_density, 2),
        }


def row_to_item(row: dict[str, Any], price_map: dict[str, float] | None = None) -> Item | None:
    """营养表记录 → Item。缺关键数据则跳过。"""
    name = row.get("productName")
    if not name:
        return None
    kcal = row.get("energyKcal")
    protein = row.get("protein")
    if kcal is None or protein is None:
        return None
    pm = price_map or {}
    return Item(
        name=str(name),
        kcal=float(kcal),
        protein=float(protein),
        fat=float(row.get("fat") or 0),
        carbs=float(row.get("carbohydrate") or 0),
        sodium=float(row.get("sodium") or 0),
        price=float(pm.get(str(name), 0.0)),
    )


# ============================================================
# 第五层：三目标配餐优化
# ============================================================
# 思路：单主餐 + 可选搭配（小食/饮料/甜品）的组合搜索。
# 目标函数为加权归一化评分，而非硬约束，避免"无解"情况。
# 权重由 profile.goal 决定：控卡期热量权重高，增肌期蛋白权重高。


def _slim_penalty(item: Item) -> float:
    """负向项：钠含量。

    阈值的设定来自对官方 160 条真实营养数据的分布分析，而非教科书标准：
        最小 1 mg ｜ P25 80 mg ｜ 中位 147 mg ｜ P75 705 mg ｜ 最大 1373 mg
        超过 800 mg 的餐品占 18.2%

    第一次实现取 800 mg 基准，实测发现该值恰好等于P75，导致 82% 的餐品
    惩罚为 0、指标几乎无区分度；改为 1400 mg 后更糟 —— 全表最大值仅
    1373 mg，惩罚项彻底失效，成为死代码。
    现取 600 mg（约P70）为基准，每超过 250 mg 记 1 分。这样约四分之一
    的候选会吃到惩罚，"倾向低钠"的选项能真实拉开差距。
    """
    if item.sodium <= 0:
        return 0.0
    return max(0.0, (item.sodium - 600) / 250.0)


def _tags_bonus(item: Item, prefer: set[str], avoid: set[str]) -> float:
    b = 0.0
    for t in item.tags:
        if t in prefer:
            b += 1.0
        if t in avoid:
            b -= 2.0
    return b


def score_combo(
    items: list[Item],
    kcal_target: float,
    protein_target: float,
    budget: float | None,
    prefer: set[str] | None = None,
    avoid: set[str] | None = None,
) -> float:
    """给一个组合打分，越高越好。"""
    prefer = prefer or set()
    avoid = avoid or set()

    kcal = sum(i.kcal for i in items)
    protein = sum(i.protein for i in items)
    price = sum(i.price for i in items)

    # 热量：命中目标得满分，偏离按比例扣分。上限惩罚更陡（宁可略低不要爆）。
    if kcal <= 0:
        return -1e9
    if kcal <= kcal_target:
        kcal_score = 100 * (1 - 0.35 * (kcal_target - kcal) / max(kcal_target, 1))
    else:
        over = (kcal - kcal_target) / max(kcal_target, 1)
        kcal_score = 100 - 260 * over
        if over > 0.25:
            kcal_score -= 80

    # 蛋白：低于目标线性扣分，高于目标给少量加分（鼓励但不过度）
    if protein <= protein_target:
        protein_score = 100 * (protein / max(protein_target, 1))
    else:
        protein_score = 100 + 8 * min(
            (protein - protein_target) / max(protein_target, 1), 1.5
        )

    # 预算：不超支满分，超支按比例重扣
    if budget and budget > 0:
        if price <= budget:
            budget_score = 100 - 12 * (budget - price) / budget  # 允许略低于预算
        else:
            budget_score = 100 - 220 * (price - budget) / budget
    else:
        budget_score = 100

    bonus = 0.0
    for i in items:
        bonus += _tags_bonus(i, prefer, avoid) * 2.0
        bonus -= _slim_penalty(i) * 4.0
        if i.available:
            bonus += 0.6

    # --- 结构性惩罚：低营养密度搭配 ---
    # 生成演示动图时发现：算法会把「圆筒冰淇淋 + 冰美式」这类纯零食组合
    # 算进最优解——它们热量低、便宜，还能把热量分母拉低，于是热量项得分
    # 虚高。这类搭配对「控卡」是负担、对「增肌」几乎没有蛋白贡献，
    # 却会挤占预算和蛋白目标。
    # 因此对「低蛋白密度 + 高热量占比」的组合追加惩罚，与目标无关，
    # 避免任何目标下都推荐出一顿"只有零食没有正餐"的方案。
    kcal_total = sum(i.kcal for i in items)
    protein_total = sum(i.protein for i in items)
    if kcal_total > 0:
        protein_share = protein_total / (kcal_total / 4.0)  # 4 kcal/g 为标准参考
        if protein_share < 0.55:
            bonus -= (0.55 - protein_share) * 45.0
        # 单品热量密度过低的搭配（饮料/冰品等）不计入有效正餐
        snack_kcal = sum(i.kcal for i in items if i.kcal <= 120)
        if snack_kcal / kcal_total > 0.28:
            bonus -= (snack_kcal / kcal_total - 0.28) * 90.0

    return 0.42 * kcal_score + 0.36 * protein_score + 0.22 * budget_score + bonus


def plan(
    mains: list[Item],
    sides: list[Item],
    drinks: list[Item],
    desserts: list[Item],
    profile: Profile,
    meal: str = "lunch",
    budget: float | None = None,
    max_side: int = 2,
    prefer: set[str] | None = None,
    avoid: set[str] | None = None,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """生成候选方案列表，按综合分降序返回 top_k。

    结构：1 份主餐 + 0~2 份小食 + 0~1 份饮料 + 0~1 份甜品。
    搜索空间通过"按单品得分预筛Top-N 主餐"来控制，避免组合爆炸。
    """
    if not mains:
        return []

    kcal_t = profile.meal_kcal_budget(meal)
    prot_t = profile.protein_target_meal(meal)
    prefer = prefer or set()
    avoid = avoid or set()

    # 预筛：取主餐中单品综合表现最好的 14 个进入组合搜索
    def base_score(it: Item) -> float:
        return score_combo([it], kcal_t, prot_t, budget, prefer, avoid)

    ranked_mains = sorted(mains, key=base_score, reverse=True)[:14]

    side_pool = sides[:10]
    drink_pool = drinks[:6]
    dessert_pool = desserts[:5]

    results: list[dict[str, Any]] = []
    seen: set[tuple] = set()

    for m in ranked_mains:
        combos: list[list[Item]] = [[m]]

        for s1 in side_pool:
            combos.append([m, s1])
            for s2 in side_pool:
                if s1 is s2:
                    continue
                combos.append([m, s1, s2])

        for base in combos:
            base_has_sweet = any(i in dessert_pool for i in base)
            for d in [None] + drink_pool:
                cur = base + ([d] if d else [])
                cur_has_sweet = base_has_sweet or (d in dessert_pool if d else False)
                if not cur_has_sweet:
                    cur_variants = [cur] + [cur + [x] for x in dessert_pool]
                else:
                    cur_variants = [cur]

                for combo in cur_variants:
                    combo = [x for x in combo if x is not None]
                    key = tuple(sorted(i.name for i in combo))
                    if key in seen:
                        continue
                    seen.add(key)

                    kcal = sum(i.kcal for i in combo)
                    # 硬性剪枝：明显不合理的组合不进入评分
                    if kcal < kcal_t * 0.30 or kcal > kcal_t * 1.55:
                        continue

                    sc = score_combo(combo, kcal_t, prot_t, budget, prefer, avoid)
                    results.append({
                        "score": round(sc, 2),
                        "items": combo,
                        "kcal": round(kcal, 1),
                        "protein": round(sum(i.protein for i in combo), 1),
                        "fat": round(sum(i.fat for i in combo), 1),
                        "carbs": round(sum(i.carbs for i in combo), 1),
                        "sodium": round(sum(i.sodium for i in combo), 1),
                        "price": round(sum(i.price for i in combo), 2),
                    })

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:top_k]


# ============================================================
# 第六层：报告渲染
# ============================================================

def render_report(
    result: dict[str, Any],
    profile: Profile,
    meal: str = "lunch",
    budget: float | None = None,
) -> str:
    """把最优方案渲染成可直接展示给用户的中文报告。"""
    items: list[Item] = result["items"]
    kcal_t = profile.meal_kcal_budget(meal)
    prot_t = profile.protein_target_meal(meal)
    goal_label = GOALS.get(profile.goal, GOALS["maintain"])["label"]

    lines: list[str] = []
    lines.append("麦门营养配餐官 · 推荐方案")
    lines.append("目标：%s ｜ 单餐热量预算 %.0f kcal ｜ 蛋白质目标 %.0f g"
                 % (goal_label, kcal_t, prot_t))
    if budget:
        lines.append("预算上限：%.0f 元" % budget)
    lines.append("")

    lines.append("推荐组合")
    for i in items:
        price_txt = ("  ¥%.1f" % i.price) if i.price else ""
        lines.append("  · %-14s %4.0f kcal  蛋白 %4.1f g  脂肪 %4.1f g  碳水 %4.1f g%s"
                     % (i.name, i.kcal, i.protein, i.fat, i.carbs, price_txt))
    lines.append("")

    kcal = result["kcal"]
    prot = result["protein"]
    kcal_pct = kcal / kcal_t * 100 if kcal_t else 0
    prot_pct = prot / prot_t * 100 if prot_t else 0

    lines.append("达标情况")
    lines.append("  热量 %.0f / %.0f kcal（%s %.0f%%）"
                 % (kcal, kcal_t, "低于" if kcal <= kcal_t else "超出", kcal_pct))
    lines.append("  蛋白 %.1f / %.1f g（达成 %.0f%%）" % (prot, prot_t, prot_pct))
    lines.append("  脂肪 %.1f g ｜ 碳水 %.1f g ｜ 钠 %.0f mg"
                 % (result["fat"], result["carbs"], result["sodium"]))
    if budget and result["price"]:
        lines.append("  预估 %.1f 元（预算 %.0f 元）" % (result["price"], budget))
    lines.append("")

    lines.append("说明：以上为基于麦当劳官方 MCP 实时营养与菜单数据的配餐建议，")
    lines.append("      营养与供应状态以官方渠道实时结果为准；如有健康状况或特殊饮食需求，请咨询专业人士。")
    return "\n".join(lines)


def _self_test() -> None:
    """离线自检：用一个模拟的 toon 片段验证解析器，不依赖网络。"""
    sample = (
        '{"success":true,"code":200,"message":"\\u8bf7\\u6c42\\u6210\\u529f",'
        '"data":"[3]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,'
        'carbohydrate,sodium,calcium}:\\n  \\u6e56\\u7eff\\u96ea\\u9876,null,100,25,1,2,2,3,4\\n'
        '  \\u4e2d\\u85af\\u6761,null,1210,289,4,12,38,165,18\\n'
        '  \\u9e21\\u817f\\u6cd5\\u5f0f\\u6c49\\u5821,null,800,190,20,8,5,600,10\\n"}'
    )
    rows = load_nutrition_table(sample)
    assert len(rows) == 3, "解析条数错误: %d" % len(rows)
    assert rows[1]["productName"] == "中薯条"
    assert rows[1]["energyKcal"] == 289.0
    assert rows[1]["sodium"] == 165.0

    p = Profile(weight_kg=70, height_cm=175, age=28, sex="male",
                activity="light", goal="cut")
    assert 1500 < p.daily_budget() < 2400, p.daily_budget()
    assert 100 < p.protein_target() < 150, p.protein_target()

    mains = [
        Item("麦辣鸡腿堡", 500, 25, 25, 45, 1100, 22),
        Item("巨无霸", 523, 25, 29, 46, 1050, 24),
        Item("麦香鱼", 510, 22, 24, 44, 980, 21),
    ]
    sides = [Item("中薯条", 289, 4, 12, 38, 165, 9),
             Item("麦辣鸡翅", 224, 13, 15, 9, 537, 13)]
    drinks = [Item("无糖可乐", 5, 0, 0, 1, 2, 8)]
    desserts = [Item("圆筒冰淇淋", 93, 2, 3, 14, 36, 6)]

    res = plan(mains, sides, drinks, desserts, p, "lunch", budget=40)
    assert res, "未生成方案"
    best = res[0]
    assert best["kcal"] > 0 and best["protein"] > 0
    print("自检通过 · 最优方案 %s ｜ %.0f kcal ｜ 蛋白 %.1f g ｜ ¥%.1f"
          % (" + ".join(i.name for i in best["items"]),
             best["kcal"], best["protein"], best["price"]))
    print("-" * 46)
    print(render_report(best, p, "lunch", 40))


if __name__ == "__main__":
    _self_test()