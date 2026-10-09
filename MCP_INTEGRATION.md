# MCP_INTEGRATION.md

麦门营养配餐官与麦当劳 MCP Server 的集成说明。

---

## 一、集成概览

| 项 | 值 |
|---|---|
| MCP Server 地址 | `https://mcp.mcd.cn` |
| 传输协议 | Streamable HTTP |
| 协议版本 | `2025-06-18`（服务端仅支持该版本及更早） |
| 鉴权方式 | 请求头 `Authorization: Bearer <MCP_TOKEN>` |
| Token 申请地址 | https://open.mcd.cn/mcp |
| 限流 | 每 Token 每分钟 600 次，超出返回 429 |
| 客户端实现 | `scripts/mcp_client.py`（原生 Python，无第三方依赖） |

### 集成方式选择

本项目提供两种集成方式，Agent 可按环境择优：

**方式 A：MCP Client 原生连接器（推荐）**

在 WorkBuddy / Cursor / Cherry Studio / TRAE 等客户端中配置连接器，Agent 直接调用 MCP 工具，无需运行脚本。

```json
{
  "mcpServers": {
    "mcd-mcp": {
      "type": "streamablehttp",
      "url": "https://mcp.mcd.cn",
      "headers": {
        "Authorization": "Bearer ${MCD_MCP_TOKEN}"
      }
    }
  }
}
```

**方式 B：内置脚本客户端**

`scripts/mcp_client.py` 实现了完整的 Streamable HTTP + SSE 分帧处理，可脱离 MCP Client 独立运行。适用于：

- 批量拉取营养数据做二次分析
- 在 CI / 定时任务中调用
- MCP Client 不可用时的降级方案

---

## 二、实际调用的工具

截至提交，麦当劳 MCP Server 实际提供 **35 个工具**（官方 README 文档列出 24 个，实际多出团餐全链路、抽奖、订单列表等 11 个）。

### 核心链路（必需）

| 工具 | 返回格式 | 在本项目中的用途 |
|---|---|---|
| `list-nutrition-foods` | **toon 紧凑格式**，160 条 | 营养基线数据源，需解析后使用 |
| `query-nearby-stores` | JSON | 定位门店，获取 `storeCode` / `beCode` |
| `query-meals` | JSON | 门店实时菜单与价格 |

### 辅助链路（可选）

| 工具 | 在本项目中的用途 |
|---|---|
| `calculate-price` | 拟选组合的官方价格核算，交叉验证 |
| `query-meal-detail` | 套餐组成与特制选项展开 |
| `available-coupons` | 可领优惠券，辅助预算优化 |
| `auto-bind-coupons` | 一键领券，减少配置步骤 |
| `query-my-account` | 积分余额，可用于积分兑换建议 |
| `campaign-calendar` | 活动日历，避开活动期特殊定价 |
| `now-time-info` | 当前时间，用于推断当前餐次 |

---

## 三、调用流程

```
┌─ 用户自然语言需求
│
▼
┌─ Step 0  建立连接
│    initialize → notifications/initialized
│    协议版本 2025-06-18，请求头携带 Bearer Token
│
▼
┌─ Step 1  营养基线          ← list-nutrition-foods
│    获得 160 条 toon 格式营养数据
│    四层解包 + toon 解析 → 结构化记录
│
▼
┌─ Step 2  建立用户画像
│    从对话提取身高/体重/年龄/性别/活动量/目标/预算/忌口
│    缺失项主动询问，不做假设
│    Mifflin-St Jeor 计算 BMR → TDEE → 单餐预算与蛋白目标
│
▼
┌─ Step 3  实时价格          ← query-nearby-stores → query-meals
│    定位门店取 storeCode/beCode
│    拉取该门店当前可售菜单与真实价格
│    （可选）calculate-price 官方核价
│
▼
┌─ Step 4  三目标优化        ← scripts/nutrition_engine.py::plan()
│    组合搜索：1 主餐 + 0~2 小食 + 0~1 饮料 + 0~1 甜品
│    加权评分：热量 0.42 / 蛋白 0.36 / 预算 0.22 + 标签与钠修正
│    剪枝与去重后返回 Top-K 候选
│
▼
┌─ Step 5  输出报告          ← render_report()
│    推荐组合 + 营养明细 + 达标率 + 价格 + 风险提示
│
▼
└─  可选：用户确认后 create-order 闭环下单
```

---

## 四、关键工程实现

### 4.1 MCP 响应的四层解包

麦当劳 MCP Server 的工具返回**不是纯 JSON**，而是嵌了四层：

```
第 1 层  Markdown 格式的字段说明（含表格、输出模板、示例）
         ↓ "## Original Response" 分隔符
第 2 层  标准 JSON 字符串
         ↓ obj["data"] 仍是字符串
第 3 层  toon 紧凑格式表格
         ↓ 按列名 + 行记录
第 4 层  结构化营养记录
```

**踩坑点**：第一层说明文字中也会出现 `{序号}` 这类占位符，所以不能用"取首个 `{` 到末尾 `}`"的粗暴方式提取。实现采用**括号配对 + 字符串转义感知**的扫描器，从所有候选中选出一个能成功 `json.loads` 且最长的片段。

对应实现：`nutrition_engine.unwrap_mcp_text()` / `parse_tool_response()`

### 4.2 toon 格式解析

`list-nutrition-foods` 为节省 LLM token 使用 toon 紧凑格式而非标准 JSON：

```
[160]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:
  猪柳麦满分,null,1288,308,16,16,24,781,213
  中薯条,null,1210,289,4,12,38,165,18
```

**踩坑点**：字段内容中可能出现逗号，直接 `split(',')` 会错列。实现采用条件策略——逗号数恰好等于列数减一时直接切分，否则从右向左按列数定位分隔符，保住左侧可能含逗号的字段。同时对 `null` 值和缺失数值做容错。

实测结果：**160 条记录 100% 解析成功**，无错行。

对应实现：`nutrition_engine.parse_toon_table()`

### 4.3 数据驱动的阈值标定

钠惩罚阈值经过三次迭代才确定有效，原因见下表：

| 版本 | 基准 | 实测表现 | 结论 |
|---|---|---|---|
| v1 | 800 mg | 82% 餐品惩罚为 0 | 等于 P75，区分度不足 |
| v2 | 1400 mg | 全表 100% 惩罚为 0 | 全表最大 1373 mg，惩罚项静默失效 |
| v3 | 600 mg | 约 25% 餐品吃到惩罚 | **最终采纳** |

官方数据的钠分布：最小 1 mg ｜ P25 80 ｜ 中位 147 ｜ P75 705 ｜ 最大 1373 mg，超800 mg 者占 18.2%。

v2 的教训值得记录：它在纸面上"更符合营养学常识"，但在真实数据下完全不生效，且**不会报错、不会崩溃，只会静默地不起作用**。这是必须用真实数据回归验证的典型案例。

### 4.4 参数差异与踩坑记录

以下参数约束经实测校验，与部分社区转述版本存在差异：

| 工具 | 关键约束 |
|---|---|
| `query-nearby-stores` | `beType` 与 `searchType` 均为**必传**。beType：1=到店，5=得来速；searchType：1=搜索收藏，2=按位置 |
| `query-meals` | 必传 `storeCode` / `orderType` / `beType`；预约场景需额外传 `reservationDate`（格式 `yyyy-MM-dd HH:mm`） |
| `query-meal-detail` | 必传 `storeCode` / `code` / `orderType` / `beType` |
| `calculate-price` | 必传 `storeCode` / `orderType` / `beType` / `items[]` |
| `create-order` | 外送、得来速、团餐场景**必传 `beCode`**；团餐（beType=6）额外必传 `gmServiceCode` |

**最高频踩坑点**：到店自取场景（`orderType=1` 且 `beType=1`）**不要传 `beCode`**，传入会导致调用失败。

### 4.5 速率控制

服务端限流为每 Token 每分钟 600 次。本项目属低频交互场景（单次配餐通常 3～5 次调用），正常使用不会触限。批量拉取菜单时建议请求间隔不低于 100 ms，并实现 429 的退避重试。

---

## 五、业务价值

### 用户侧

把「凭感觉点餐」变成「有据可依的选择」。输出的不只是推荐结果，还包含**达标率**——用户能看到方案离自己的目标还差多少，而不是被一个不容置疑的答案说服。

### 麦当劳侧

- 提升营养信息的可发现性：官方 MCP 已提供 160 条结构化营养数据，但普通用户难以据其决策，本项目把这部分数据的价值真正释放出来
- 优化菜单曝光结构：通过 `calculate-price` 与 `create-order` 打通，将配餐建议直接转化为真实订单
- 呼应官方场景：本项目直接对应官方 README 中提到的"身材管控期也想吃麦当劳"场景

### 生态侧

证明 MCP + Skill 的组合不仅能做"查询转发"，也能承载**真实算法逻辑**。所有核心代码（解析、建模、优化）均不依赖 MCP Client，可离线运行与测试。

---

## 六、免责声明

本项目为独立开发者作品，非麦当劳官方产品。所调用的全部数据均来自麦当劳官方 MCP Server，版权归麦当劳所有。本项目输出的配餐建议仅供参考，不构成医疗、营养或其他专业建议。餐品信息、价格及供应状态以麦当劳官方渠道实时结果为准。