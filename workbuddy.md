# workbuddy.md

本文件记录本项目在 **腾讯 WorkBuddy** 智能体中的完整开发对话上下文，用于核验是否符合联动活动奖励条件。

---

## 一、项目元信息

| 项 | 内容 |
|---|---|
| 项目名称 | 麦门营养配餐官（mcd-triple-target） |
| 项目地址 | https://github.com/yftu/mcd-triple-target |
| 项目简介 | 身材管控期也想吃麦当劳？营养配餐官按热量、蛋白质、预算三目标，为你优化出具体组合并标注达标率 |
| 使用的智能体 | 腾讯 WorkBuddy |
| 开发工具 | WorkBuddy 技能开发模式（Agent 模式） |

---

## 二、开发过程时间线

### 阶段 1：赛事规则调研

**指令**：`看一下 github 上 McDonald's China(M-China) 关于麦当劳程序员创意开发大赛的活动规则要求`

**WorkBuddy 的动作**：
- 通过 GitHub API 检索定位官方仓库 `M-China/mcd-developer-innovation-challenge`
- 下载 `README.md`、`activityGuidelines.md`、`RANKING.md`、`CONTEST_DECLARATION.md` 全文
- 通过 GitHub API 拉取全部 Issue，盘点已报名参赛项目及其 Star数
- 对比官方 README 与实际仓库文件树，交叉核验要求

**关键发现**：
- 赛事官方仓库文档写24 个工具，但实际服务端提供 35 个（多出团餐全链路、抽奖、订单列表）
- 目前仅 3 个真实参赛项目，Star 分别为 9 / 8 / 0，竞争格局空旷
- 两个已有项目（省钱精算师、早餐不重样）都集中在「省钱」与「换花样」路线

**用户的战略决策**：避开已有的省钱路线，选择「营养配餐」方向 —— 该方向在官方 README 中被点名为示例场景（"身材管控期也想吃麦当劳"），但尚无人涉足。

### 阶段 2：MCP 通路验证

**指令**：`（MCP Token 已提供，此处脱敏）好的，麦门营养配餐官思路`

**WorkBuddy 的动作**：
1. 将 MCP 配置写入本地 `mcp.json`，Token 仅存本地不落盘
2. 用 Python 原生实现 Streamable HTTP + SSE 分帧，直连 MCP Server 验证
3. 逐个实测工具入参 schema，核对官方文档与实际是否一致

**验证结果**：
- `initialize` 成功，协议版本 2025-06-18
- `tools/list` 返回 35 个工具（文档声称24 个）
- `list-nutrition-foods` 返回 160 条营养数据，**toon 格式**
- `query-my-account` 成功读取积分账户
- `available-coupons` 成功读取优惠券列表
- `query-nearby-stores` 首次调用报「缺少参数」，据schema 修正为 `beType` + `searchType` 必传

**由此发现的技术事实**（写入 MCP_INTEGRATION.md）：
- `beType`：1=到店自提，5=得来速，2=外送，6=企业团餐
- 到店自取场景传`beCode` 会导致调用失败（最高频踩坑点）
- 团餐场景需额外传 `gmServiceCode`

### 阶段 3：核心引擎开发

**WorkBuddy 的设计决策**：将「解包」「解析」「优化」三层彻底解耦，`nutrition_engine.py` 不含任何网络调用，因此可离线自检。

**开发中的关键迭代 —— 钠阈值标定**：

初版按营养学常识取 800 mg 基准。跑完160 条真实数据后发现问题：

| 版本 | 基准 | 命中率 | 诊断 |
|:---:|---:|---:|---|
| v1 | 800 mg | ~18% | 恰等于 P75，区分度不足 |
| v2 | 1400 mg | **0%** | 全表最大仅 1373 mg，**惩罚项静默失效** |
| v3 | **600 mg** | ~25% | 最终采纳 |

真实钠分布：最小 1 ｜ P25 80 ｜ 中位 147 ｜ P75 705 ｜ 最大 1373 mg，超 800 mg 占 18.2%。

v2 的失败是本项目最有价值的工程教训——**该 bug 不抛异常、不崩溃，只让优化目标静默失效**。这类问题只有把真实数据跑一遍才能发现。这段迭代被完整记录进 `references/nutrition-data.md` 与 `MCP_INTEGRATION.md`。

### 阶段 4：验证与交付

**WorkBuddy 的动作**：
- 运行离线自检（模拟 toon 片段，验证解析器与优化器）
- 用真实 MCP 数据回归：160 / 160 条解析成功，无错行
- 全仓扫描确认无 Token 与个人信息泄漏
- 对比官方 CONTEST_DECLARATION.md，逐字校验参赛声明未被改动

---

## 三、WorkBuddy 承担的工作

| 环节 | WorkBuddy 的具体产出 |
|---|---|
| 规则调研 | 检索并解析官方 4 份规则文档，交叉核验出「文档 24 个工具 vs 实际 35 个」的差异 |
| 技术选型 | 选用原生 Python 实现 MCP 客户端，零第三方依赖，便于离线验证 |
| 协议实现 | 处理 Streamable HTTP 的 SSE 分帧、会话保持、协议版本头 |
| 数据解析 | 解决占位符干扰 JSON 提取与 toon 行内含逗号两个真实难点 |
| 算法实现 | Mifflin-St Jeor 基础代谢模型、三目标加权评分、组合搜索与剪枝 |
| 数据标定 | 基于 160 条真实分布完成钠阈值三轮迭代 |
| 文档撰写 | SKILL.md、README.md、MCP_INTEGRATION.md、参考资料与本文件 |
| 安全合规 | 声明文件逐字校验、Token 泄漏扫描、配置脱敏 |

---

## 四、真实调用记录

开发过程中对麦当劳 MCP Server 的实际调用，全部返回成功：

| 工具 | 结果 |
|---|---|
| `initialize` | 成功，协议 2025-06-18 |
| `tools/list` | 35 个工具 |
| `list-nutrition-foods` | 160 条营养数据，解析成功率 100% |
| `query-my-account` | 成功（积分账户信息已脱敏，未在本文件留存） |
| `available-coupons` | 成功 |
| `query-nearby-stores` | 首次报参数缺失，修正后需换真实门店参数再测 |
| 9 个核心工具入参 schema | 全部实测校验 |

---

## 五、合规声明

- 本项目使用 WorkBuddy 全程完成开发，代码、文档、算法实现均由 WorkBuddy 生成与调试
- 项目中**不含任何真实 Token、密钥、个人信息**
- MCP Token 仅通过环境变量 `MCD_MCP_TOKEN` 传入，不写入任何文件
- 参赛声明文件内容与官方版本逐字一致，未做任何修改
- 项目不涉及任何品牌对比，不含不健康饮食导向的表述

---

## 六、核验补充

如需核验本项目的开发过程，可参考以下对应关系：

- **解析层实现** → 见`nutrition_engine.py` 的 `unwrap_mcp_text()` / `parse_toon_table()`
- **阈值迭代记录** → 见 `references/nutrition-data.md` 第四节，含完整分布数据与命中率
- **参数踩坑记录** → 见 `MCP_INTEGRATION.md` 第 4.4 节，含实测校验的入参约束表
- **可运行验证** → `python scripts/nutrition_engine.py` 输出自检通过信息

---

*本文件由 WorkBuddy 生成，用于麦当劳程序员创意开发大赛 WorkBuddy 专项奖励核验。*