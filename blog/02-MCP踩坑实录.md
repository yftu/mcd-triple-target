# 麦当劳 MCP 官方文档没说的事：35 个工具、toon 格式，和一段永远不执行的代码

> 项目：https://github.com/yftu/mcd-triple-target
> 三个坑，都不是文档里写的。全部来自实测。

---

## 一、坑一：文档写24 个工具，实际有 35 个

我按官方 README 配好 MCP，跑了 `tools/list` 一数——**35 个**。

官方 README 的「4.1 工具列表」表格里，明确列出的是 **24 个**。差异的 12 个：

```
+ query-lottery-info         + query-party-store
+ draw-lottery               + query-party-store-session
+ query-lottery（抽奖相关）    + party-order-create（团餐下单）
+ query-party-city           + order-list
+ query-party-store-date     + cancel-order
+ query-promotions           + query-my-prizes
+ query-survey-coupon
```

其中**团餐全链路**（`query-party-store` → `query-meal-assistance` → `party-order-create`）文档一个字没提，但它是完整的。

```
query-party-store      查门店是否支持团餐
query-meal-assistance  查该门店的助餐服务
party-order-create     创建团餐订单
```

同时文档里列出的 `mall-create-order-physical`（积分兑换实物）在本次实测中未返回。

**结论**：做 MCP 技术选型时，**以实际 `tools/list` 为准，文档只能当参考**。

---

## 二、坑二：返回不是 JSON，是四层嵌套

这是最耗时间的一个。

我按常规写法解析：

```python
resp = requests.post(url, json=payload)
data = resp.json()["data"]
```

然后发现 `data` 是个**字符串**，不是数组。再解析，又出来一个字符串。

拆开看，返回结构是这样的：

```
┌─ 第 1 层：Markdown 字段说明
│    "## Response Structure
│     - **productName**: 餐品名称 (Type: string)
│     ..."
│
├─ 第 2 层：标准 JSON
│    {"success":true,"code":200,"data":"..."}
│
├─ 第 3 层：toon 紧凑格式（data 字段仍是字符串）
│    "[160]{productName,energyKcal,protein,fat,...}:
│       猪柳麦满分,null,1288,308,16,16,..."
│
└─ 第 4 层：最终结构化数据
     [{productName: 猪柳麦满分, energyKcal: 308, ...}, ...]
```

### 为什么不能直接取 JSON

第 1 层的说明文字里**有占位符**：

```
|序号| 地址ID | 联系人 |配送地址 |
|{序号}|{data.addresses[].addressId}|...
```

所以这种写法会拿到错误的片段：

```python
# ❌ 会命中说明文字里的 {序号}
text[text.index("{"):text.rindex("}") + 1]
```

得用括号配对 + 转义感知扫描：

```python
def unwrap_mcp_text(raw: str) -> str:
    text = raw.strip()
    marker = "## Original Response"
    idx = text.rfind(marker)
    if idx != -1:
        text = text[idx + len(marker):].strip()

    candidates = []
    i, n = 0, len(text)
    while i < n:
        if text[i] == "{":
            depth, in_str, esc = 0, False, False
            for j in range(i, n):
                ch = text[j]
                if in_str:
                    if esc:            esc = False
                    elif ch == "\\":   esc = True
                    elif ch == '"':    in_str = False
                    continue
                if ch == '"':       in_str = True
                elif ch == "{":     depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidates.append(text[i:j + 1])
                        i = j
                        break
            else:
                break
        i += 1

    best = ""
    for cand in candidates:
        try:
            json.loads(cand)
            if len(cand) > len(best):
                best = cand
        except Exception:
            continue
    return best or text
```

逻辑是：从所有括号配对成功的片段里，挑**能 `json.loads` 且最长**的那个。原始响应通常是最完整的一段。

### toon 格式不能直接 split

拿到第 3 层，长这样：

```
[160]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:
  猪柳麦满分,null,1288,308,16,16,24,781,213
  中薯条,null,1210,289,4,12,38,165,18
```

toon 是为了省 token 设计的紧凑格式：**首行 `[N]{列名}` 声明列，下面每行一条记录，逗号分隔。**

看起来 `split(',')` 就够了，但**字段内容里可能有逗号**，会错列：

```python
def _split_toon_row(line: str, ncols: int) -> list[str]:
    # 逗号数恰好匹配则直切
    if line.count(",") == ncols - 1:
        return line.split(",")
    # 否则从右向左按列数反向定位，保住左侧含逗号的字段
    parts, rest = [], line
    for _ in range(ncols - 1):
        pos = rest.rfind(",")
        if pos == -1:
            break
        parts.insert(0, rest[pos + 1:])
        rest = rest[:pos]
    return [rest] + parts
```

实测 **160 / 160 条 100% 解析成功**。

---

## 三、坑三：一段永远不执行的代码

这个最隐蔽。

我给配餐算法加了个"低钠优选"惩罚项，按营养学常识写：

```python
def _slim_penalty(item):
    """成人每日钠建议 <2000mg，单餐不宜超 800mg"""
    return max(0, (item.sodium - 800) / 400)
```

跑完真实数据，我统计有多少餐品吃到惩罚：

```
超过 800mg 的占比：18.2%
```

嗯……82% 不触发。太松了，不够区分。我改成 1400mg（每日建议的七成），听起来更严谨：

```python
return max(0, (item.sodium - 1400) / 300)
```

再统计：

```
超过 1400mg 的占比：0.0%
```

**零。**

我以为统计写错了，回查原始数据：

```
钠分布（160 条真实数据）
最小 1 ｜ P25 80 ｜ 中位 147 ｜ P75 705 ｜ 最大 1373 mg
```

**全表最大 1373 mg。我的阈值 1400 mg。**

这个函数永远不会返回非零值。它是一段死代码，但**没有任何异常提示**——测试全绿、输出格式正常、没有任何地方会报错。

如果我没顺手统计分布，它会一直躺在那，比赛结束都没人发现。

### 改成数据驱动

```python
def _slim_penalty(item):
    """阈值 600mg 来自官方 160 条真实数据的 P70。

    800mg 时惩罚命中率仅 18.2%（恰等于 P75，无区分度）；
    1400mg 时命中率为 0%——高于全表最大值 1373mg，代码永不执行。
    """
    if item.sodium <= 0:
        return 0.0
    return max(0.0, (item.sodium - 600) / 250)
```

| 版本 | 阈值 | 命中率 | 问题 |
|:---:|---:|---:|---|
| v1 | 800 mg | 18.2% | 等于 P75，区分度不足 |
| v2 | 1400 mg | **0%** | **高于全表最大值，死代码** |
| v3 | **600 mg** | ~25% | 采纳 |

**教训**：任何基于"常识"设定的阈值，都必须用真实数据回归验证。常识性数字看起来有依据，反而最危险——因为它让你停止思考。

---

## 四、还有个：加权评分被套利

做演示动画时发现增肌场景推出来这个：

```
· 双层深海鳕鱼堡  485 kcal  蛋白 28 g  ¥22
· 麦乐鸡5块       213 kcal  蛋白 12 g  ¥11
· 冰美式小杯        15 kcal  蛋白  0 g  ¥10   ← 占预算却几乎无营养
· 圆筒冰淇淋93 kcal  蛋白  2 g  ¥6
```

冰美式 + 冰淇淋 占 22 块，只贡献 15 kcal 和 2 g 蛋白。

**不是搜索 bug，是目标函数被套利：**
- 冰淇淋热量低 → 拉低总热量 → **热量项虚高**
- 冰淇淋便宜 → 拉低总花费 → **预算项受益**

加权归一化的加权目标，在无硬约束时天然存在这类结构性套利。修法是加**与目标正交**的约束：

```python
protein_share = protein_total / (kcal_total / 4.0)
if protein_share < 0.55:
    bonus -= (0.55 - protein_share) * 45.0

snack_kcal = sum(i.kcal for i in items if i.kcal <= 120)
if snack_kcal / kcal_total > 0.28:
    bonus -= (snack_kcal / kcal_total - 0.28) * 90.0
```

修完后控卡场景结果完全不变，说明新约束没破坏原有方案。

---

## 五、项目地址

完整代码和踩坑记录，零第三方依赖：

**https://github.com/yftu/mcd-triple-target**

```bash
python scripts/nutrition_engine.py   # 离线自检，无需网络
```

想复现那个死代码 bug，把 `_slim_penalty` 的 600 改成 1400 跑一遍，再打印分布统计就能看到。

**欢迎交流你踩过的 MCP 坑**，尤其是那些"不报错但不起作用"的。

如果这篇有帮助，点个 Star ⭐ 鼓励一下。