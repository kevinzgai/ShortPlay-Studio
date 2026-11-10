# LangChain 接入技术方案（初稿 v0.1）

> 状态：**初稿，待评审**。本文档由 2026-11-11 拷问式评审收敛的共识起草，最终方案以项目 owner 确认为准。
> 关联文档：`docs/资产与分镜自动分解-系统设计.md` §5.3（旧决策，本文推翻之）。

---

## 0. 决策变更记录

| 日期 | 变更 | 内容 |
|---|---|---|
| 2026-11-11 | **推翻** | §5.3「暂不引入 LangChain/LangGraph」决策被明确推翻 |
| 2026-11-11 | **新立** | 采用**两步绞杀者模式**接入：现有 `llm_json.py` 抽象层是唯一替换接缝 |
| 2026-11-11 | **修订** | owner 拍板：步骤一立即执行；步骤二（LangGraph）挂触发器待命不排期，触发条件见 §5 |

推翻动机（评审确认的三条）：
1. **可观测**：现状 LLM 调用零记录，出问题只能靠用户口述复现；需要 `llm_calls` 表落库。
2. **流式**：SSE 基础设施已有（`/api/parse/events`），但 LLM 层是 urllib 一次性阻塞读，接不了 token 流。
3. **skill 和工具后续开发好维护**：角色注册表 + Agent 工作台要长出工具调用、评审回环，自研编排撑不住，LangGraph 的状态机/检查点是现成轮子。

---

## 1. 目标 / 非目标

**目标（按优先级）**

| # | 目标 | 验收标准 |
|---|---|---|
| G1 | LLM 调用全链路落库可查 | 每次调用在 `llm_calls` 表留一行：调用方、模型、耗时、成败、token 用量 |
| G2 | 现有 26 套回归全部绿 | 每一步实施后 `tools/verify_*.mjs` 26/26 通过 |
| G3 | 报错语义逐字不变 | 「NO_KEY」「模型输出被截断（max_tokens=%d 不够用）…」等中文报错原样 |
| G4 | 为工具调用/评审回环铺路 | LangGraph 状态机就位后，加「评估 Agent 打回」只需加节点不动拓扑 |
| G5 | 流式输出通道打通 | 单步接口可切 token 流（第三步做） |

**非目标（明确不做）**

| # | 非目标 | 理由 |
|---|---|---|
| N1 | 不用 `with_structured_output` | 网关背后 13 家模型 tool_calls 支持参差不齐；自研 `extract_json` 已是事实标准 |
| N2 | 第一步就上流式 | 流式后置到第三步，先保回归绿 |
| N3 | 不改前端编排 | `ai.js` 浏览器/Node 共用 ESM 串行链原样保留 |
| N4 | 不动逐集降级语义 | 每集失败独立降级、整体失败全本地出结果——LangGraph 只管「顺序」，不管「重试策略」 |

---

## 2. 三条铁律（评审锁死，实施中不可破）

1. **`extract_json` / `repair_json` 逐字保留**：不重写、不「顺手优化」，连注释一起原样搬。这是 13 家模型脏 JSON 的兼容层，26 套回归 indirectly 依赖它的行为。
2. **`with_structured_output` 不作依赖项**：任何 Pydantic schema 校验只做**旁路告警**（记 `llm_calls.schema_ok=0`），不做硬失败。
3. **每步一提交、26 回归放行**：任一步回归挂了，回滚单个 commit 即回到上一步，不留半吊子状态。

---

## 3. 选型与依赖

| 依赖 | 版本（2026-11-05 PyPI） | 角色 |
|---|---|---|
| `langchain-core` | **1.7.6** | 消息类型 / callback 契约（直接 import，故列为直接依赖） |
| `langchain-openai` | **1.7.4** | `ChatOpenAI`，OpenAI 兼容网关统一接入 |
| `langgraph` | （1.2.20，**暂不引入**） | 步骤二依赖，随触发器达成再加入（见 §5 排期修订） |

- **不引入** `langchain` 全家桶（1.4.9）：create_agent/middleware 那层我们不用，角色注册表继续自己的。
- Python ≥ 3.10（本机 3.13.12 ✅）。
- **部署形态变更**：从「零第三方依赖、python.exe 直接跑」→「venv + requirements.txt（3 个直接依赖）」。`start.bat` / `start-mac.command` 增加 venv 引导段（见 §5 步骤一）。
- 已知上游动态（2026-11-04 发布）：`with_structured_output` 拒答行为变更为 `ModelRefusalError`——**不影响我们**（N1 本来就不用它），记录备查。

**为什么 `langchain-openai` 而不是继续 urllib**：网关侧的重试、超时、streaming（第三步）、token 用量统计是现成的；自己续写 urllib 版本等于维护第四套协议代码。

---

## 4. 目标架构

```
┌─ app/web/ 路由表（不动）────────────────────────┐
│  /api/ai/plan · /api/ai/storyboard · /api/agents/run … │
└──────────────────┬─────────────────────────────┘
                   ▼
┌─ app/services/ 业务层（签名不变，只换 import）──┐
│  parse_task.py · assets.py · agents.py          │
└──────────────────┬─────────────────────────────┘
                   ▼
┌─ app/services/llm_gateway.py（新 · 唯一出口）───┐
│  call_llm(system,user,…) -> (content, model)    │   ← 同签名替换
│  call_llm_json(system,user,key,…) -> (data,model)│  ← 语义逐字保留
│  内部：ChatOpenAI + LlmCallsHandler(落库)        │
└───────┬──────────────────────┬──────────────────┘
        ▼                      ▼
┌─ llm_json.py 保留 ─┐  ┌─ SQLite data/llm_calls.db ─┐
│ extract_json        │  │ llm_calls 表（§6）           │
│ repair_json         │  └────────────────────────────┘
│（逐字保留，被       │
│  gateway import）   │
└─────────────────────┘
```

- **`llm_json.py` 不删**：`extract_json`/`repair_json` 是纯函数，gateway import 它们；`call_llm`/`call_llm_json` 在 gateway 落地后从 llm_json 里改为转发行（绞杀第一步），第二步结束后再降级为 `from .llm_gateway import *` 的兼容垫片。
- **`llm_store.py` 不动**：多 provider 运行时切换、脱敏逻辑是资产，gateway 每次调用实时读 `llm_settings()`，provider 切换即刻生效（与现状一致）。

### 兼容性契约（gateway 必须逐字保住的清单）

| 现状行为 | gateway 对应实现 |
|---|---|
| `call_llm` 返回 `(content, model)` 二元组 | 同 |
| 未配 Key 抛 `RuntimeError("NO_KEY")` | 同 |
| HTTP 错误 → `RuntimeError("模型服务返回 %s：%s")` | ChatOpenAI 异常捕获后翻译成同格式 |
| 连不上/超时 → `RuntimeError("连不上模型服务或请求超时：%s")` | 同 |
| `finish_reason == "length"` → 截断中文报错（含加大 SHORTPLAY_LLM_MAX_TOKENS 提示） | 同（从 `response_metadata` 取 finish_reason） |
| 只吐思考不吐答案 → reasoning_content 专用报错 | 网关兼容：检查 `additional_kwargs.reasoning_content` |
| `call_llm_json` 修补→重试一次的顺序与重试 system 追加文案 | **逐字保留**，含「引用台词改用中文书名号」 |
| temperature=0.3、user 消息 36000 字符截断 | 同 |

---

## 5. 实施步骤（两步绞杀 + 流式后置）

> **排期修订（2026-11-11 owner 拍板）**：步骤一立即执行；**步骤二不排期、挂触发器待命**。触发条件（二选一先到）：
> a) P3「评估 Agent 打回」的打回条件 + 收敛条件定义清楚；
> b) 第二个需要工具循环的 skill 立项。
> 理由：可观测与流式不绑定 LangGraph，步骤一即兑现；LangGraph 独有价值（状态机/断点续跑/条件边）在评审回环定义清楚前只有成本没有收益。触发达成前，直接依赖仅 langchain-core + langchain-openai 两个。

### 步骤一：绞杀第一步 —— gateway 落地 + llm_calls 落库（G1/G2/G3）

1. **venv 引导**：新增 `requirements.txt`（**2 个直接依赖**，钉版本；langgraph 待触发器达成再加入）；`start.bat` 加
   `py -m venv .venv` + `.venv\Scripts\python -m pip install -r requirements.txt`，
   启动改 `.venv\Scripts\python server.py`；`start-mac.command` 同理。仓库 `.gitignore` 加 `.venv/`。
2. **建表**：`app/config/db.py` 新增 SQLite 初始化（`data/llm_calls.db`，WAL 模式，见 §6）。
3. **写 gateway**：`app/services/llm_gateway.py`。落库采用**函数级埋点**（`call_llm` 返回前/异常时写表）而非 `BaseCallbackHandler`——绞杀保证 `call_llm` 是唯一出口，函数埋点等价于全链路埋点，且避免 handler 与各家网关 usage 字段差异的解析泥潭；`call_path` v1 自动取调用方模块名（`sys._getframe` 回溯），role 级粒度留待调用方显式传入。
4. **切流量**：`parse_task.py` / `assets.py` / `agents.py` 的 `from app.services.llm_json import call_llm_json` 改为从 gateway import——**三个文件各改一行 import，调用行零改动**。
5. **回归放行**：26 套 `tools/verify_*.mjs` 全绿 → 提交。挂了 → revert 本提交，回到纯 stdlib。

### 步骤二：绞杀第二步 —— LangGraph 状态机接管编排（G4）【触发器待命，未排期】

1. 把 `parse_task.py` 休眠保留的 7 阶段流水线改造为 `StateGraph`：节点 = 现有阶段函数，状态 = 快照 dict（沿用 `/api/parse/state` 的结构）。
2. **降级语义显式保留**：每个节点内部自带 try/except + 降级产出；LangGraph 不配自动重试（`retry_policy` 不用），避免与「逐集降级」打架。
3. SQLite checkpointer（复用 `llm_calls.db` 或独立 `checkpoint.db`）→ 断点续跑替代现有 since 续传的手工簿记。
4. 角色注册表（`agents.py` ROLES）包一层 `add_node` 适配器：注册即成节点，为将来「评估 Agent 打回」的条件边铺路。
5. 回归放行 → 提交。

### 步骤三：流式（G5，后置）

- gateway 加 `stream_llm(system, user, …)` 生成器（`ChatOpenAI.stream` / `astream`）；
- 复用 `/api/parse/events` 的 SSE 通道推 `delta` 事件；
- 前端按需消费，不消费则后端聚完整 JSON 仍走 `call_llm_json`——**两条路并存，流式不是替换**。

### 明确不做的一步

- ❌ 「把单步接口 /api/ai/* 全部搬进 LangGraph」：单步调用没有状态，套图是负收益；只搬有阶段/断点诉求的流水线。

---

## 6. `llm_calls` 表结构

```sql
CREATE TABLE IF NOT EXISTS llm_calls (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  ts               TEXT    NOT NULL,  -- ISO8601 本地时间
  call_path        TEXT    NOT NULL,  -- 业务标识：parse_task.adapt / assets.fill / agents.run:<role>
  provider_id      TEXT    NOT NULL,  -- llm-providers.json 的 provider id
  base_url         TEXT    NOT NULL,
  model            TEXT    NOT NULL,
  attempt          INTEGER NOT NULL DEFAULT 1,  -- 第几次尝试（2 = JSON 修补后的重试）
  ok               INTEGER NOT NULL,            -- 1 成功 0 失败
  latency_ms       INTEGER,
  prompt_chars     INTEGER,                     -- 只记字符数，不记原文
  completion_chars INTEGER,
  finish_reason    TEXT,                        -- stop / length / …
  prompt_tokens    INTEGER,                     -- 上游 usage，有则记
  completion_tokens INTEGER,
  total_tokens     INTEGER,
  error            TEXT                         -- 失败原因，截 200 字
);
CREATE INDEX IF NOT EXISTS idx_llm_calls_ts ON llm_calls(ts);
```

隐私红线（沿用现有设计原则）：**不存 prompt/completion 原文、不存 apiKey**，只存字符数与用量。

---

## 7. 回滚策略

| 场景 | 动作 |
|---|---|
| 步骤一回归挂 | revert 单 commit；venv 留着不影响（未 import 即不生效） |
| 步骤二回归挂 | revert 单 commit，gateway 已验证无风险可独立存活 |
| 上游版本破坏行为 | requirements 钉死版本；升级前先跑 26 回归 |
| `llm_calls` 表写坏拖垮主流程 | handler 全部 try/except 包裹，**落库失败只打 stderr，绝不让业务调用失败** |

---

## 8. 风险与对策

| 风险 | 等级 | 对策 |
|---|---|---|
| 网关对 langchain-openai 的兼容参差（13 家模型） | 高 | 步骤一上线后逐家跑一轮真实调用冒烟；异常翻译层保证报错格式不漏 |
| 上游周更节奏快（langgraph 1.2.x 每周 patch） | 中 | 钉版本 + 升级跑回归；不追 beta 特性 |
| 部署特性丢失（「无 pip install」没了） | 中 | 已在评审中接受；venv 引导做进 start 脚本，用户无感 |
| LangGraph 状态序列化与现有快照结构冲突 | 中 | 步骤二状态 dict 直接复用 `/api/parse/state` 结构，不发明新结构 |
| callback 落库在高频调用下的 IO 争用 | 低 | 单写连接 + WAL；QPS 本项目场景极低 |

---

## 9. 与 C 阶段（换 FastAPI）的关系

**解耦，无先后依赖**。gateway 层对宿主无感知：stdlib `SimpleHTTPRequestHandler` 下先落地验证，FastAPI 替换只动 `app/main.py:run()`（`main.py` 注释里本就预留了这一步）。两者可独立排期；若 C 阶段先行，gateway 步骤一照常执行。

---

## 10. 待 owner 确认的开放点

| # | 问题 | AI 建议 |
|---|---|---|
| Q1 | requirements 是否连传递依赖一起钉（pip freeze 全量） | 钉全量（freeze），升级走显式流程 |
| Q2 | `llm_calls.db` 放 `data/` 还是项目根 | `data/`，与现有本地数据目录惯例一致 |
| Q3 | 步骤二是否连 Agent 工作台（`/api/agents/run`）一起接管 | 不接管：工作台单次调用无状态，只搬流水线 |
| Q4 | token 用量要不要做前端展示页 | 先落库，展示页等有真实排查需求再做 |
