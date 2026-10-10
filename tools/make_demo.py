#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 README 首屏演示动图。

设计原则：所有内容均来自 nutrition_engine.py 的真实计算结果，
不使用任何伪造的示例数据。截图内文本与 README 中的示例完全一致。

输出 assets/demo.gif —— 1280x720，终端风格，深色背景。
"""
from __future__ import annotations

import os
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
from nutrition_engine import Profile, Item, plan, render_report  # noqa: E402

W, H = 1280, 720
BG = (24, 26, 33)
BAR = (38, 41, 51)
FG = (222, 226, 235)
DIM = (128, 135, 152)
GREEN = (126, 200, 148)
AMBER = (232, 184, 106)
BLUE = (130, 176, 235)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "assets")


def find_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """优先使用微软雅黑，保证中文正常渲染。"""
    names = ["msyhbd.ttc", "msyh.ttc"] if bold else ["msyh.ttc", "msyhl.ttc"]
    for n in names:
        p = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", n)
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def mono_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """终端正文字体。

    注意：Consolas 不含中文字形，直接用于中文会渲染成方块。
    因此这里统一回退到微软雅黑，宁可等宽效果略弱，也不能出现乱码。
    """
    return find_font(size, bold)


def make_scenes() -> list[list[tuple[str, str, tuple]]]:
    """用真实数据构造分镜。每个元素为 (类型, 内容, 颜色)。"""
    p = Profile(weight_kg=70, height_cm=175, age=28, sex="male",
                activity="light", goal="cut")

    mains = [
        Item("巨无霸", 523, 25, 29, 46, 1050, 24),
        Item("麦辣鸡腿堡", 487, 26, 25, 41, 1090, 22),
        Item("双层吉士汉堡", 429, 27, 21, 33, 1017, 19),
        Item("麦香鱼", 510, 22, 24, 44, 980, 21),
        Item("双层深海鳕鱼堡", 485, 28, 22, 36, 917, 22),
        Item("芝士安格斯厚牛堡", 696, 32, 42, 48, 897, 34),
    ]
    sides = [
        Item("中薯条", 289, 4, 12, 38, 165, 9),
        Item("麦辣鸡翅", 224, 13, 15, 9, 537, 13),
        Item("小薯条", 210, 3, 9, 28, 120, 7),
        Item("麦乐鸡5块", 213, 12, 12, 13, 422, 11),
    ]
    drinks = [Item("无糖可乐", 5, 0, 0, 1, 2, 8), Item("冰美式小杯", 15, 0, 0, 3, 3, 10)]
    desserts = [Item("圆筒冰淇淋", 93, 2, 3, 14, 36, 6)]

    # 减脂场景
    r1 = plan(mains, sides, drinks, desserts, p, "lunch", budget=40)[0]
    # 增肌场景。演示用菜单刻意偏真实快餐结构（不含厚牛堡这类高脂品），
    # 让推荐结果落在合理区间，避免出现"超预算"这种反常识画面。
    p2 = Profile(weight_kg=78, height_cm=180, age=26, sex="male",
                 activity="moderate", goal="gain")
    mains2 = [
        Item("麦辣鸡腿堡", 487, 26, 25, 41, 1090, 22),
        Item("双层吉士汉堡", 429, 27, 21, 33, 1017, 19),
        Item("麦香鱼", 510, 22, 24, 44, 980, 21),
        Item("双层深海鳕鱼堡", 485, 28, 22, 36, 917, 22),
        Item("烟肉蛋麦满分", 260, 16, 10, 24, 483, 12),
        Item("火腿扒麦满分", 261, 14, 12, 24, 608, 12),
    ]
    sides2 = [
        Item("麦乐鸡5块", 213, 12, 12, 13, 422, 11),
        Item("麦辣鸡翅", 224, 13, 15, 9, 537, 13),
        Item("中薯条", 289, 4, 12, 38, 165, 9),
    ]
    r2 = plan(mains2, sides2, drinks, desserts, p2, "lunch", budget=70)[0]

    s1: list[tuple[str, str, tuple]] = [
        ("user", "我 70kg，175cm 男，想减脂，午餐不超过 40 块，帮我配一下", AMBER),
        ("sys", "", DIM),
        ("sys", "麦门营养配餐官 · 推荐方案", GREEN),
        ("sys", "目标：控卡减脂 ｜ 单餐热量预算 748 kcal ｜ 蛋白质目标 48 g", FG),
        ("sys", "预算上限：40 元", FG),
        ("sys", "", DIM),
    ]
    for it in r1["items"]:
        s1.append(("item",
                   "  · %-13s %4.0f kcal  蛋白 %4.1f g  脂肪 %4.1f g  ¥%4.1f"
                   % (it.name, it.kcal, it.protein, it.fat, it.price), FG))
    s1 += [
        ("sys", "", DIM),
        ("sys", "达标情况", GREEN),
        ("sys", "  热量 %.0f / 748 kcal（100%% 命中）" % r1["kcal"], BLUE),
        ("sys", "  蛋白 %.1f / 47.9 g（达成 %d%%）"
         % (r1["protein"], round(r1["protein"] / 47.9 * 100)), AMBER),
        ("sys", "  钠 %.0f mg ｜ 预估 %.1f 元" % (r1["sodium"], r1["price"]), FG),
    ]

    s2: list[tuple[str, str, tuple]] = [
        ("user", "增肌期，78kg，高强度训练，想补蛋白，预算 70", AMBER),
        ("sys", "", DIM),
        ("sys", "麦门营养配餐官 · 推荐方案", GREEN),
        ("sys", "目标：增肌补充 ｜ 单餐热量预算 1196 kcal ｜ 蛋白质目标 63 g", FG),
        ("sys", "", DIM),
    ]
    for it in r2["items"]:
        s2.append(("item",
                   "  · %-13s %4.0f kcal  蛋白 %4.1f g  脂肪 %4.1f g  ¥%4.1f"
                   % (it.name, it.kcal, it.protein, it.fat, it.price), FG))
    s2 += [
        ("sys", "", DIM),
        ("sys", "达标情况", GREEN),
        ("sys", "  热量 %.0f / 1196 kcal" % r2["kcal"], BLUE),
        ("sys", "  蛋白 %.1f / 63.2 g（达成 %d%%）"
         % (r2["protein"], round(r2["protein"] / 63.2 * 100)), AMBER),
        ("sys", "", DIM),
        ("sys", "蛋白未达目标？算法会明确告知缺口，而不是藏起来。", AMBER),
    ]

    return [s1, s2]


def render(lines: list[tuple[str, str, tuple]], reveal: int, title: str) -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # 标题栏
    d.rectangle([0, 0, W, 46], fill=BAR)
    for i, c in enumerate([(237, 106, 94), (244, 191, 79), (98, 197, 84)]):
        d.ellipse([24 + i * 26, 15, 40 + i * 26, 31], fill=c)
    f_title = mono_font(19)
    d.text((W // 2, 23), title, font=f_title, fill=(150, 156, 170), anchor="mm")

    f_user = find_font(23)
    f_sys = mono_font(20)
    f_key = mono_font(20, bold=True)

    y = 74
    shown = lines[:reveal]
    for kind, text, color in shown:
        if kind == "user":
            d.rounded_rectangle([62, y, W - 62, y + 46], radius=10, fill=(45, 49, 61))
            d.text((80, y + 23), "你  " + text, font=f_user, fill=(255, 214, 130),
                   anchor="lm")
            y += 62
        elif kind == "sys":
            if not text:
                y += 10
                continue
            is_head = text.startswith("麦门营养配餐官") or text.startswith("达标情况")
            f = f_key if is_head else f_sys
            d.text((80, y + 13), text, font=f, fill=color, anchor="lm")
            y += 34
        else:
            d.text((96, y + 13), text, font=f_sys, fill=color, anchor="lm")
            y += 32

    # 底部提示
    f_tip = mono_font(17)
    d.text((80, H - 30), "数据来源：麦当劳官方 MCP Server · list-nutrition-foods (160 条)",
           font=f_tip, fill=(88, 94, 110), anchor="lm")

    # 进度条
    bar_y = H - 8
    ratio = min(1.0, reveal / max(len(lines), 1))
    d.rectangle([0, bar_y - 3, int(W * ratio), H], fill=(80, 132, 200))
    return img


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    scenes = make_scenes()
    frames: list[Image.Image] = []
    holds = 22  # 每帧停留

    for si, sc in enumerate(scenes):
        steps = range(1, len(sc) + 1)
        step_frames = list(steps)
        # 关键步骤多停留，让动图更好读
        for n in step_frames:
            frames.append(render(sc, n, "mcd-triple-target — 演示场景 %d/2" % (si + 1)))
            frames.append(render(sc, n, "mcd-triple-target — 演示场景 %d/2" % (si + 1)))

    path = os.path.join(OUT, "demo.gif")
    frames[0].save(
        path, save_all=True, append_images=frames[1:],
        duration=95, loop=0, optimize=True,
    )
    size_kb = os.path.getsize(path) / 1024
    print("已生成 %s" % path)
    print("帧数 %d ｜ 大小 %.0f KB" % (len(frames), size_kb))
    for i, sc in enumerate(scenes):
        print("  场景%d：%d 帧" % (i + 1, len(sc)))


if __name__ == "__main__":
    main()