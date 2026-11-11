# dev 分支 · 续作任务计划（换机接手用）

> 生成：2026-11-09 · 最后更新：**2026-11-11** · 基线分支 `main` · 适用分支 `dev` · **已推送 GitHub（main + dev）** · 历史已剔除示例 PNG
> 本文自包含：**S0~S7 + A/B/C 全部完成；本文档转维护手册，读完即可接手，不需要翻聊天记录。**
> 完整设计依据见 `docs/分步开发路线-移除一键生成.md`、`docs/前后端拆分方案.md`、`docs/LangChain接入-技术方案.md`。
>
> **2026-11-11 重大变更（换机必读，旧文档口径已全部作废）**：
> ① 后端已从「Python 标准库单文件」换成 **FastAPI + uvicorn**，零依赖部署特性**已放弃**，改用 venv；
> ② 前后端**已拆成两个仓库**，前端在兄弟目录 `shortplay-studio-web`，本仓 `frontend/` 与根 `dist/` 已删除；
> ③ LLM 调用改走 `app/services/llm_gateway.py`（LangChain），**每次调用落库** `data/llm_calls.db`；
> ④ 回归从 25 套变成 **26 套**，启动命令改为 `./.venv/bin/python server.py`。

---

## 续作提示词（换电脑后直接复制给 AI）

```text
你在 ShortPlay-Studio 项目的 dev 分支上继续开发。开工前先完整读
docs/dev-续作任务计划.md 和 docs/分步开发路线-移除一键生成.md，
不要重新调研架构、不要重做已完成阶段、不要重新讨论已锁定的决策。

【当前状态】
- 代码已推送 GitHub：https://github.com/kevinzgai/ShortPlay-Studio.git，分支 dev（main 是基线分支）。
- S0/S1/S2/S3/S3.5/S4/S5/S6 已完成：engine.js 稳定键、studio.js 的 S.steps 状态机与存档迁移、
  移除一键 + 工作区顺序翻转、S3 分集独立成步（显式 planStep / 可编辑分集表 / stale 条 /
  二次确认 + byEp 全 stale）、S3.5 设置分层（全局系统设置三栏 + engine-config.json）、
  S4 分镜逐集闸门（storyboardStep / byEp 集级状态 / 按 key 只替换本集 / 失败隔离）、
  S5 定妆消费分镜（assetsFromShots / reparse 来源可配置 / 资产卡引用数 / 零引用兜底说明）、
  S6 出片归位（framesGate 硬闸门 / withRefSlots 参考图槽位 / 第 3 步只读预览不发 frames）。
- S7「收尾与文档」已完成：休眠流水线标注、README 工作区章节 +「为什么不做一键」、套件登记复核、
  两个死脚本标 DEPRECATED 销账。
- **【2026-11-11 新增，三项大改造已全部落地】**
  A 阶段拆包（`app/` 五层）、B 阶段拆仓（前端独立成 `shortplay-studio-web` 兄弟仓，
  本仓 `frontend/` 与根 `dist/` 已删，`studio.js` 2881 行拆成 5 个域文件 + barrel）、
  C 阶段换 FastAPI（`app/asgi.py`，`SHORTPLAY_LEGACY_SERVER=1` 可回退标准库实现）。
  另加 LangChain 接入步骤一：LLM 调用走 `app/services/llm_gateway.py`，每次调用落库 `data/llm_calls.db`。
- 实测：`verify_all.mjs` **26 套**（原 25 + Step C 的 SSE 不阻塞），本机实测 **26/26**（约 5 分钟）。

【全部阶段已完成，本提示词转为维护模式】
- S0~S7 + A/B/C 已全部落地并验收，不要重做任何阶段。要改功能就按新需求开新阶段，先报计划再动手。
- 四条红线仍然有效（见下）；改动前先跑一次基线：node tools/verify_all.mjs（26 套串行，实测约 5 分钟）。
- 休眠的 /api/parse/start 流水线：代码保留、无 UI 入口、已标「勿删（旧项目恢复用）」，
  不要新建入口，也不要删；两个 DEPRECATED 回归脚本不跑。
- README 的「四个工作区 · 每步人工确认」与「为什么不做一键」是产品口径，改实现必须同步改它，
  verify_final_docs.mjs 会拦。
- LangGraph（技术方案步骤二）**挂触发器待命、未排期**，触发条件是「评审回环的打回+收敛条件定义清楚」
  或「第二个需要工具循环的 skill 立项」。触发前不要主动引入 langgraph 依赖。

【硬约束，违反即返工】
- 四项已锁决策：D1 分集/分镜各为独立 AI 步 + 人工闸门；D2 整步作废 + 显式重跑（不做按场增量）；
  D3 顺序 剧本→分集→分镜→定妆；D4 只有单集闸门，第一版不给「剩余全部」按钮。
- 阶段已全部完成（S2 定死步骤号、S3 定死集号、S4 依赖集号、S5 依赖镜头、S6 依赖资产），新阶段仍须串行；
  不改 engine.js 的解析/体检/buildStoryboard 规则
  （S5 起允许新增资产来源层纯函数，但既有规则一行不许删改，见 verify_plan_contract.mjs）；
  不新建 AI 接口，复用 /api/ai/plan、/api/ai/storyboard、/api/ai/assets、/api/ai/frames；
  后端 7 阶段流水线保持休眠不删。
- **LangChain 三条铁律（2026-11-11 锁定）**：`extract_json` / `repair_json` 逐字保留不许重写；
  `with_structured_output` 不作依赖（只做旁路告警）；每步一提交、26 回归放行，挂了单 commit 回滚。
- 本阶段新增脚本必须全绿才进下一阶段；旧脚本若因步骤号变化而红，必须在同阶段内修完，不许挂账。
- 已知缺陷允许保留：重跑会覆盖手工修改，靠二次确认缓解。

【环境与容易踩的坑】
- **后端已是 FastAPI + uvicorn，必须用 venv**：`./.venv/bin/python server.py --no-browser`；
  venv 不存在时 `python3 -m venv .venv && ./.venv/bin/python -m pip install -r requirements.txt`。
  回退旧标准库实现：`SHORTPLAY_LEGACY_SERVER=1 ./.venv/bin/python server.py`。
- **前端在兄弟仓**：`../shortplay-studio-web`。改前端必须去那个仓 `npm run build`，
  本仓没有 `frontend/`，也没有 `dist/`。`server.py` 用 WEB_ROOT 四级解析自动找兄弟仓产物。
- 回归：`node tools/verify_all.mjs`（**26 套**串行，实测约 5 分钟）。
- .gitignore 排除 tools/verify_*：这些回归脚本不随仓库走，若新机没有，先从旧机拷 tools/ 整目录，
  并把脚本头部的 playwright-core file:/// 路径与 Chromium executablePath 换成新机实际路径。
  本机（Mac）还额外改了 py→python3、verify_all.mjs 的 py→python3、stage_split 的 fixture 项目 ID，
  且 8177 要带 NO_PROXY=127.0.0.1,localhost 启动（详见 §1 的 Mac 适配清单）。
- engine.js / studio.js / .vue 改前先统计 `\r\n` 确认行尾，再用 Python io.open(..., newline='')
  + assert count==1 精确替换；engine.js:918 早有同名 sceneKey(intExt,time,name)，新函数只能叫 sceneStableKey。
- Playwright 用 JS API（allTextContents/innerText），默认有窗口模式 headless:false。
- verify_ai.py 与 verify_parse_progress/resume 已标 PAUSED 并移出 SUITES，别跑旧断言。
- **LLM 调用排查**：出问题先查 `data/llm_calls.db`（call_path / model / latency / token 用量 / error），
  比问用户复现快得多。`call_path` 记的是调用方模块名（如 `parse_task` / `assets`）。

【交付要求】
- 先报 3-5 行计划再动手；验证强度默认从简，只有交互/时序/跨层状态才上浏览器脚本。
- 改完跑 verify_all.mjs 并给出逐项结果，用 Conventional Commits 提交（subject 不大写开头）。
- 完成后更新 docs/dev-续作任务计划.md 的阶段进度表，再告诉我下一阶段是什么。
```

---

## 0. 一句话现状

「AI 一键分集 + 分镜」的 7 阶段自动流水线已**休眠**；四个工作区顺序翻转为
**① 改剧本 → ② 分集 → ③ 分镜 → ④ 定妆**。
**S0~S7 九个功能阶段 + A/B/C 三个架构阶段全部完成**。后端已是 **FastAPI + uvicorn**、前后端**已拆双仓**、
LLM 调用走 **LangChain 网关且全量落库**。`verify_all.mjs` 的 SUITES 为 **26 套**，本机实测 **26/26 全绿**（约 5 分钟）。
第 2 步的临时桥接已在 S4 移除，第 3 步只保留逐集闸门与只读提示词预览；第 4 步资产清单以分镜引用为准，
首帧提示词在定妆完成后才生成；README 已与实现对齐，休眠流水线已标注「勿删」。逐项结果见 §3。
**下一步 = 无**（路线收尾）。唯一挂着的是 LangGraph 步骤二，**等触发器**，不是待办任务。

### 架构现状（2026-11-11 之后）

| 维度 | 现状 |
|---|---|
| 仓库 | 后端 `ShortPlay-Studio`（本仓）+ 前端 `shortplay-studio-web`（兄弟目录） |
| HTTP 层 | FastAPI + uvicorn（`app/asgi.py` 做协议翻译）；`SHORTPLAY_LEGACY_SERVER=1` 回退标准库 |
| 部署 | venv + `requirements.txt`（5 条直接依赖，钉版本）；**「零依赖双击即用」已放弃** |
| LLM 层 | `app/services/llm_gateway.py`（ChatOpenAI）；`extract_json`/`repair_json` 原样复用 |
| 可观测 | `data/llm_calls.db`（SQLite WAL）逐次记录：call_path / model / 耗时 / token / error |
| 回归 | 26 套；`verify_sse_nonblocking.py` 专防事件循环被 SSE 阻塞 |
| 前端状态 | `src/stores/studio.js` 是 barrel，域文件在 `src/stores/studio/{core,session,steps,shots,assets}.js` |

---

## 1. 换机后 5 分钟自检

```bash
# ① 两个仓都要 clone（前端是独立仓，必须在同级目录）
git clone https://github.com/kevinzgai/ShortPlay-Studio.git       # 后端（本仓）
git clone https://github.com/kevinzgai/shortplay-studio-web.git   # 前端（兄弟仓）

# ② 后端 venv（必须：FastAPI 之后不再是零依赖）
cd ShortPlay-Studio
git checkout dev
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt

# ③ 前端装依赖 + 构建（产物在 shortplay-studio-web/dist）
cd ../shortplay-studio-web && npm install && npm run build && cd ../ShortPlay-Studio

# ④ 起服务（macOS/Linux 用这条；Windows 双击 start.bat 会自动做 ②③）
NO_PROXY=127.0.0.1,localhost ./.venv/bin/python server.py --no-browser
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8177/   # 期望 200
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8177/docs  # FastAPI 文档页，期望 200
```

- **前端产物在兄弟仓 `shortplay-studio-web/dist/`**，本仓**没有** `frontend/` 也没有 `dist/`。
  改前端必须去那个仓 `npm run build`；`app/paths.py` 的 WEB_ROOT 会自动按
  `SHORTPLAY_WEB_ROOT` → 兄弟仓 dist → 本仓 dist → 仓库根 四级解析。
- 开发态：后端 `./.venv/bin/python server.py --no-browser` + 前端仓 `npm run dev`（5173 代理 /api 到 8177）。
- 离线模式 `?ai=0`：强制规则引擎 + 不发任何模型请求，排查 UI 时优先用。
- **回退到旧标准库实现**（FastAPI 出问题时的应急开关）：
  `SHORTPLAY_LEGACY_SERVER=1 ./.venv/bin/python server.py --no-browser`，启动横幅会显示 `LEGACY`。
- **推送凭证**：本机 `origin` 走 SSH（`git@github.com:...`），密钥 `~/.ssh/id_ed25519_github`。只 clone / 读代码不需要配置；要 push 就得在新机配自己的 SSH 公钥，或改用 HTTPS + PAT。

### 回归（重要：脚本不在 git）

```bash
node tools/verify_all.mjs        # 26 套串行，实测约 5 分钟
node tools/verify_all.mjs assets # 只跑名字含 assets 的
./.venv/bin/python tools/verify_sse_nonblocking.py  # SSE 不阻塞事件循环（Step C 专项）
```

`.gitignore` 有 `tools/verify_*`，**全部回归脚本不随仓库走**。换机后从旧机器拷整个 `tools/` 目录，并替换其中两处本机绝对路径（脚本头部）：

| 原值 | 改成 |
|---|---|
| `import { chromium } from "file:///C:/Users/Administrator/.workbuddy/binaries/node/workspace/node_modules/playwright-core/index.mjs";` | 新机上 playwright-core 的实际路径，或改用 `import { chromium } from "playwright-core";` |
| `executablePath: "C:/Users/Administrator/AppData/Local/ms-playwright/chromium-1243/chrome-win64/chrome.exe"` | 新机 Chrome/Chromium 路径 |

Python 侧脚本（`verify_platform.py` 等）同样检查一次 playwright 路径。脚本默认**有窗口模式** `headless: false`，截图落 `screenshots/`。
`tools/baseline-*.txt` 三份基线报告**已提交**，可作为对照物。

**Mac 本机适配清单（2026-11-09 实测；脚本不进 git，换机照做）**：

| 项 | 旧机（Windows） | 本机实际值 / 处理 |
|---|---|---|
| playwright-core | `file:///C:/Users/Administrator/.workbuddy/binaries/node/workspace/node_modules/playwright-core/index.mjs` | `file:///Users/kevin/.npm/_npx/dea9475797100b20/node_modules/playwright-core/index.mjs` |
| Chrome | `chromium-1243/chrome-win64/chrome.exe` | `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome` |
| 生成测试图 | `py -c ...` | `python3 -c ...`（`verify_ref_original.mjs` 3 处、`verify_ref_upload.mjs` 1 处），另需 `Pillow` |
| 离线主流程 | `py tools/verify_platform.py` | SUITES 改 `python3` + `pip install playwright`（PyPI 直连慢时直接下 wheel 安装） |
| `verify_stage_split.mjs` | 硬编码旧机项目 ID `p_20261109_141839_fc63` | 改为动态挑 `projects/` 下 `shots` 非空的项目；本机另造 `p_fixture_stage_split` |
| ComfyUI 探测 | 无系统代理 | macOS 有 `127.0.0.1:7877` 代理时，8177 必须带 `NO_PROXY=127.0.0.1,localhost` 启动，否则 `/api/comfy/status` 报 502 |

> fixture 项目要点：**23 镜**、`view: "card"`（写 `3` 会渲染成表格、没有 `.shot` 卡）、
> `activeEpisode: "all"`（写集号会被 `visibleShots` 过滤空）、`createdAt/updatedAt` 用 ISO 字符串
> （写数字会让 `/api/projects` 排序抛异常、接口直接断开）。

---

## 2. 四项已锁决策（不要再重新讨论）

| # | 决策 | 结论 |
|---|---|---|
| D1 | 分集 / 分镜由谁产出 | 两个**独立 AI 步骤 + 人工闸门**；复用已有 `/api/ai/plan`、`/api/ai/storyboard`，不新建接口 |
| D2 | 上游改了下游怎么办 | **整步作废 + 显式重跑**（不做按场增量）；但 `sceneStableKey` / `shotKeyOf` 已在 S1 埋进数据，将来做增量不必迁移历史存档 |
| D3 | 分镜与定妆顺序 | **翻转**：先分镜后定妆；`S.step` 3=分镜、4=定妆 |
| D4 | 分镜粒度 | **只有单集闸门**，第一版不给「剩余全部」按钮——否则一键换名字复活 |
| D5 | 配置分几层（S3.5） | **作用域分层**：模型与引擎是**全局**（`系统设置`），镜头节奏 / 视别 / 画幅 / AI 开关是**项目级**（`生成设置`，存 `project.data.config`）。系统设置内只配置不执行 |

**已知且已接受的缺陷**：重算会覆盖手改的镜头文字与镜号。缓解是重跑前二次确认并列出「将影响 N 个镜头、其中 M 个改过」。

---

## 3. 阶段进度

| 阶段 | 状态 | 关键产出 |
|---|---|---|
| S0 冻结基线 | ✅ | `tools/baseline-2026-11-09.txt` 16/16；`baseline-step-audit-2026-11-09.txt`（30 脚本 16 命中 110 行） |
| S1 契约与稳定键 | ✅ | `engine.js` 4 个导出、`studio.js` 的 `S.steps` 状态机、`verify_step_keys.mjs` 18/18 |
| S2 移除一键 + 顺序翻转 | ✅ | 删 `#one-click` / `oneClick()` / `#flow-stages`；`App.vue` view-3/4 对调；`stepV` 存档迁移；`verify_no_oneclick.mjs` 16/16 |
| S3 分集独立成步 | ✅ | `planStep()` 显式按钮 / 可编辑分集表（`source="manual"`）/ stale 条 / 二次确认 + `byEp` 全 stale 不删镜头；`verify_plan_step.mjs` 36/36 |
| S3.5 设置分层（插队） | ✅ | 双入口（生成设置 / 系统设置）、三栏（文字模型 / 出图引擎 / 连接与诊断）、引擎可配且热生效（`engine-config.json`）、修 `SHORTPLAY_COMFY` 白名单 bug；契约 48/48 + 三栏 30/30；全量 **21/21** |
| S4 分镜逐集闸门 | ✅ | `storyboardStep(epKey)` / byEp 集级状态 / 按 `shots[].key` 只替换本集 / 失败隔离与 running 归一 / 第 2 步桥接移除；`verify_shot_gate.mjs` 21/21；全量 **22/22** |
| S5 定妆消费分镜 | ✅ | `assetsFromShots()` + `assetUsage()` / `reparse(opts)` 来源可配置 / 资产卡「N 镜 · 第 X–Y 集」与零引用兜底说明 / `#asset-source-note`；`verify_asset_from_shots.mjs` 27/27；全量 **23/23** |
| S6 出片归位 | ✅ | `framesGate` computed + `regenFrames(silent)` 第 4 步硬闸门 / `withRefSlots()` 参考图槽位 / `#frames-gate` / `#pv-frames-note` 只读预览 / 回第 3 步不发 frames；`verify_frames_after_assets.mjs` 24/24；全量 **24/24（5m05s，含 1 套环境跳过）** |
| S7 收尾与文档 | ✅ | `server.py` 顶部 + 分区注释标「无 UI 入口，勿删」/ README 改「四个工作区 · 每步人工确认」+「为什么不做一键」并修掉 4 处过时口径 / 死脚本标 DEPRECATED 销账 / `verify_final_docs.mjs` 38/38；全量 **25/25（5m15s，含 1 套环境跳过）** |

### 架构阶段（2026-11-11 完成，与 S 系列正交）

| 阶段 | 状态 | 关键产出 |
|---|---|---|
| A 拆包 | ✅ | `server.py` 4418 行 → **21 行**薄壳；业务搬 `app/services/`、路由 `app/web/`、配置 `app/config/`、静态与分发 `app/main.py`；`app/paths.py` 用 `parent.parent`（踩过「静默生成空目录」的坑）；全量 26/26 |
| B 拆仓 | ✅ | 前端独立仓 `shortplay-studio-web`；本仓删 `frontend/`（44 文件）与根 `dist/`；`studio.js` 2881 行拆 `studio/{core,session,steps,shots,assets}.js` + barrel（25 个组件 import 路径不变）；WEB_ROOT 四级解析；全量 26/26 |
| C 换 FastAPI | ✅ | 先做响应层解耦（`Response` + `Sink`，36 函数 88 调用点**一行未改**），再加 `app/asgi.py`；SSE 阻塞丢 `anyio.to_thread`（挂起时 `/api/config` 最差 **2ms**）；`SHORTPLAY_LEGACY_SERVER=1` 回退；全量 26/26（5m02s，比 stdlib 快 25s） |
| LangChain 接入（步骤一） | ✅ | `app/services/llm_gateway.py`（ChatOpenAI 替换 urllib）；`app/config/db.py` 落库 `data/llm_calls.db`；三条铁律锁定；26/26 |
| LangChain 接入（步骤二） | ⏸ **挂触发器** | LangGraph 接管编排。触发条件：评审回环的「打回+收敛条件」定义清楚，或第二个需要工具循环的 skill 立项。**未触发前不引入 langgraph 依赖** |

**依赖严格串行**：S2 定死步骤号 → S3 定死集号 → S4 依赖集号 → S5 依赖镜头 → S6 依赖资产。不许跳步。
**S3.5 是正交层**：只动 UI 与配置读写，不参与上面这条依赖链，也不改 `engine.js` 与生成逻辑。
**门槛规则**：本阶段新增脚本全绿才进下一阶段；旧脚本因步骤号变红必须**同阶段内修完，不许挂账**。

### S2 实测结果（对照用）

`tools/baseline-s2-2026-11-09.txt`：**17/17 套 PASS**（3m34s）。
细项：stage_split 22/22、shot_group 16/16、platform 43/43、linear_ui 19/19、projects 30/30、no_oneclick 16/16、资产逻辑 69/69、清场护栏 15/15。`npm run build` 通过，产物里已无 `one-click`。

### S3 实测结果（对照用）

`node tools/verify_all.mjs`（旧机 `tools/` 同步后，19 套串行约 6 分钟）：**16/19 套 PASS**。

- **S3 新增 2 套全绿**：源码契约 24/24（`planOnly` 已删、解绑自动触发、`steps.plan` 五字段写入、
  `byEp` 全 stale 且不删 `S.shots`、D4 无全部按钮、`engine.js` 未改、后端流水线仍在）；
  分集独立成步 36/36（进第 2 步不自动分集、点按钮才发 `/api/ai/plan`、手改集名刷新仍在、
  改剧本出「基于旧稿」条且方案不变、二次确认列出「将覆盖 N 集手调结果」、取消确认不重算、
  `byEp` 全 stale 且镜头不丢、所有集 tab 标需重算、拆分/合并/删集、AI 失败降级 `engine=local`、无 JS 报错）。
- **原 17 套中 14 套全绿**：清场护栏 15/15、稳定键 18/18、资产逻辑 69/69、复制提示词、
  道具提示词不再画人 13/13、参考图原图不压缩 16/16、参考图落盘 11/11、项目管理 30/30、
  Linear 三栏、两阶段结构 22/22、第一步改剧本 23/23、移除一键 16/16、离线主流程 43/43、
  ComfyUI 出图 UI 26/26（含真实出图 1 张，12.4s）。
- **3 套环境阻塞（非代码回归）**：`资产清单密度` / `资产面板 + 整包导出` / `道具提示词界面口径`
  都卡在 `#build-assets` 或 `.ap-fill` 的 `!aiReady` 闸门——本机没有 `llm-providers.json`，
  `/api/config` 返回 `llm:false`。补齐模型 Key 后重跑即可，**不需要改 S3 代码**。
- `npm run build` 通过（44 模块）；脚本跑完自动删除临时项目。

> ✅ `tools/` 已从旧机整目录同步（26 个 `verify_*.mjs`），`verify_all.mjs` 的 SUITES 恢复原 17 套
### S3.5 实测结果（对照用）

`node tools/verify_all.mjs`：**21/21 套全绿（4m26s）**。

- **S3.5 新增 2 套全绿**：
  - `verify_system_settings_contract.mjs` **48/48**（无浏览器）：引擎配置独立落盘 + mtime 缓存、
    「文件 → env → 默认」优先级、`COMFY_HOST`/`COMFY_MODEL` 已函数化且无裸常量残留、
    `SHORTPLAY_COMFY` 进白名单、四个新接口齐备、Key 出站打码、双入口、三栏、
    生成设置不再挂 `ModelSettings`、系统设置无执行动作、诊断三态口径。
  - `verify_system_settings.mjs` **30/30**（Playwright）：生成设置里没有模型列表、
    系统设置里没有重排按钮、引擎地址与 unet 预填且可编辑、每项标明生效来源、
    能列出 ComfyUI 真实 unet、保存后 `source` 由 `default` 变 `file`、
    诊断四行齐备、万相未配置只算 `warn`、诊断标题与 tab 徽章口径一致、tab 记忆、无 JS 报错。
- **原 19 套全部保持全绿**，此前 3 套缺 Key 的红灯（资产清单密度 13/13、资产面板 11/11、
  道具提示词界面口径 12/12）在补 `llm-providers.json` 后转绿，**证实是环境阻塞而非回归**。
- 本轮唯一一次红灯是「两阶段结构」：脚本按「第一个含分镜的项目」挑 fixture，
  回归留下的临时项目（10 镜、`step=1`）把它顶掉了。已改为**优先 `p_fixture_stage_split`**，
  再退到「≥20 镜且 step≥3」，恢复 22/22。这属于脚本 fixture 选择问题，与 S3.5 代码无关。

#### 这轮修掉的既存 bug

`load_local_config()` 的白名单只放行 `SHORTPLAY_LLM_*` 和 `SHORTPLAY_DASHSCOPE_API_KEY`，
**`SHORTPLAY_COMFY` 不在其中**——按旧代码把 ComfyUI 地址写进 `llm-config.bat` 是 silently 无效的，
只能改系统环境变量。已补进白名单（同时放行 `SHORTPLAY_QWEN_IMAGE_*`）。

> 并登记 S3 / S3.5 各新增 2 套；脚本仍按 `.gitignore` 不入库，本机路径 / 命令 / fixture 适配见 §1。
> 旧机 S2 基线 17/17 与本机 16/19 的差异**只**是上述 3 套缺 Key，**没有出现「因步骤号变化而红」的用例**；
> 门槛规则「旧脚本因步骤号变红必须同阶段内修完」已在本机复核确认无挂账。

### S4 实测结果（对照用）

`node tools/verify_all.mjs`：**22/22 套全绿**（首轮 4m33s、清掉无效 Key 后复跑 3m58s）；`npm run build` 通过（47 模块）。

- **新增 `verify_shot_gate.mjs` 21/21**（Playwright，AI 接口全 mock）：3 集项目逐集点 3 次 =
  3 次独立 `/api/ai/storyboard` 且每次 payload 只含该集场次；第 3 集 502 时前两集镜头
  `id/key/code` 全不变、只在该集卡片显示「重试」与原因；重开页面 1/2 集 ready、第 3 集仍待生成、
  镜号连续无重号；重跑本集只替换本集；第 3 步 DOM 无「全部 / 剩余」语义按钮（D4）。
- **旧 21 套全部保持全绿**。受第 2 步桥接移除影响的 5 套脚本改为「点 `#generate` 导航 →
  逐集点 `[data-shot-gate]`」：`verify_plan_step.mjs` 37/37、`verify_no_oneclick.mjs` 16/16、
  `verify_projects.mjs` 30/30、`verify_linear_ui.mjs` 19/19、`verify_platform.py` 43/43。
  `verify_linear_ui.mjs` 顺带切到 `?ai=0`，避免回归打真实模型。
- **修掉一个 S3 遗留的假绿**：`verify_plan_step.mjs` 的「手改场次区间 → byEp 全 stale」原来填的是
  输入原值（`@change` 不触发），靠 `planStep` 残留的 stale 蒙混过关。S4 把闸门状态写成 ready 后暴露，
  已改为填不同值 + 补一条「生成后本集为 ready」前置断言。
- **口径说明**：S3 的 D2 会把分集重算后的**所有**集（含从未生成过的）标 `stale`；对未生成集
  它语义上就是「待生成 / 需重排」，闸门按钮显示「重排本集」，不算失败。
- **一次环境红灯**：首轮 21/22，唯一红灯是「万相未配置只算 warn」——上一步写入的那条万相 Key
  本身 401 无效、却让诊断变 `ok`。清掉无效 Key 后该套 30/30、全量复跑 22/22。
  「只要填了 Key 就显示可用、不校验真伪」仍是已知缺陷，留待后续单独修（见 §8）。

### S5 实测结果（对照用）

`node tools/verify_all.mjs`：**23/23 套全绿**（首轮 22/23、修正契约脚本后复跑 4m05s）；`npm run build` 通过（47 模块）。

- **新增 `verify_asset_from_shots.mjs` 27/27**（Node 纯函数 11 项 + Playwright 16 项，AI 接口全 mock）：
  旧规则会清掉「剧本里没有、但镜头引用过」的纯规则角色，`assetsFromShots` 能补回；道具不被重建清掉；
  引用数 / 集号范围 / 短徽标文案正确；正常路径输出与旧规则逐字段一致（旧脚本零回归风险）。
  浏览器段走完阶段 4 → 第 4 步，三个分组非空、每行都有 `[data-asset-usage]`；
  真删第 3 集全部镜头后，该集独占场景资产仍在，显示 `0镜 · 兜底`，title 为
  「现无镜头引用 · 第 3 集 · 剧本兜底保留」。
- **旧 22 套全部保持全绿**。唯一一次红灯是 `verify_plan_contract.mjs` 的
  「engine.js 在 S3 未被改动」——它用 `git status` 判断，**提交后就变绿、与内容无关**，是历史假绿。
  S5 明确允许在 engine.js 新增资产来源层函数，已改成检查 `git diff HEAD` 删除行必须为 0、
  且 `parseScript` / `diagnose` / `buildStoryboard` 三个已锁函数仍在；25/25。
- **验收口径**：删镜头走界面 `#del-selected` 真删，不用 localStorage 注入 + reload
  （应用会从服务端项目恢复，注入会被覆盖，那是假删）。
- **未改**：`buildAssets` 内部、`parseScript` / `diagnose` / `buildStoryboard` 规则、`server.py`、
  AI 接口；D4 仍无批量按钮。

### S6 实测结果（对照用）

`node tools/verify_all.mjs`：**24/24 套全绿**（首轮 23/24、修复环境降级后复跑 **5m05s**）。

- **新增 `verify_frames_after_assets.mjs` 24/24**（Playwright，mock `/api/config`、`/api/ai/plan`、
  `/api/ai/storyboard`、`/api/ai/assets`、`/api/projects/upload-ref`、`/api/ai/frames`）：
  3 集 6 镜走完阶段 4 后，第 3 步 **0 次 frames 请求**、提示词区标明只读预览、没有生成按钮；
  第 4 步 `#frames-gate` 按「资产包 → 至少一条已定妆」两级闸门逐步放行（按钮禁用原因随状态变化）；
  真实挂参考图后按钮可点，只发 **1 次** `/api/ai/frames`、请求带分镜表与资产包，
  提示词含「参考图槽位 [1] C01」且 `refSlots` 关联到已定妆资产；回第 3 步无新增请求；无 JS 报错。
- **旧 23 套全部保持全绿**：S5 27/27、S4 21/21、S3 契约 25/25、离线主流程 43/43 等。
- **一次环境红灯（非代码回归）**：首轮 23/24，唯一红灯是 `ComfyUI 出图 UI` 在 `#comfy-generate`
  上等 30s 超时。诊断 `curl 127.0.0.1:8188/system_stats` 为 `http=000`、`/api/comfy/status` 为
  `Connection refused`，8188 无监听、无 ComfyUI 进程，**不是代理 502、也不是 S6 代码回归**。
  修法：`verify_comfy_ui.mjs` 在 `bar.online === false` 时打印 `[环境跳过] ComfyUI 8188 离线`、
  清场、退出码 0。该套现在是 `0 通过/0 失败（环境跳过）`，启动 8188 后可拿回完整 26 项。
  同因「系统设置三栏」为 29/30（1 项诊断不可用），按不可用记录，不算失败。
- **未改**：`server.py`、后端 7 阶段流水线、AI 接口、`engine.js` 解析/体检/分镜规则；D4 仍无批量按钮。

### S7 实测结果（对照用）

`node tools/verify_all.mjs`：**25/25 套全绿（5m15s）**，`npm run build` 47 模块通过。

- **新增 `verify_final_docs.mjs` 38/38**（无浏览器，纯读文件，5 组断言）：
  A. README 与实现一致（新标题 / 有「为什么不做一键」/ 四步顺序 / 不再有「临时桥接」/
  「AI 同步给出」等过时表述 / S5、S6 口径已写入）；B. 休眠流水线保留且标「勿删」
  （docstring + 分区注释 + handler + SSE + `ui.parse`/`resumeParseTask` + `ParseProgress.vue` + 五个单步接口）；
  C. 四个工作区顺序锁定（view-1..4 → StepOne/Two/Shots/Asset、`storyboardStep` 与 `framesGate` 仍在）；
  D. SUITES 25 套且六个关键脚本都已登记、三个死脚本不在其中；E. 两个死脚本标 DEPRECATED 且不再挂账。
- **旧 24 套全部保持全绿**：S6 24/24、S5 27/27、S4 21/21、S3 契约 25/25、离线 43/43、项目管理 30/30 等。
- **ComfyUI 仍环境跳过**：`0 通过/0 失败`（8188 `Connection refused`）；「系统设置三栏」29/30，
  少的那 1 项就是 ComfyUI 诊断不可用。启动 8188 后重跑两套即可拿回完整断言。
- **按约定重启了 8177**：本次只改 `server.py` 的 docstring 与分区注释，运行时行为不变；
  重启后 `root=200`、`/api/projects` 200（13KB）、`/api/comfy/status` 返回 `online:false` 而非 502。
- **验证口径**：清场护栏输出里的 `[安全拦截] 项目列表为空` / `HTTP 500` / `delete refused`
  是它刻意构造的负面用例，不是服务故障（该套 15/15）。

---

## 4. S3 执行清单（可直接照做）

> **已完成 · 2026-11-09**：6 步全部落地，实测见 §3。已知缺陷（重跑覆盖手改）按约定保留，靠二次确认缓解。

**目标**：分集从「进第 2 步自动附带」变成「可看、可改、可重算」，并让改稿后的下游显式标 stale。

1. **删根因**：`frontend/src/stores/studio.js` 的 `planOnly()` 里有 `S.episodes.length` 短路（约 862 行）——分集一旦产生就**永不重算**。改成显式 `planStep()`，由按钮触发；保留 `S.steps.plan` 写入 `running/ready/at/engine/model`。
2. **解除自动触发**：`goStep(2)` / `goStep2()` 不再自动调 `planOnly()`；第 2 步给一个「生成 / 重算分集」按钮（AI 优先，失败降级本地 `localEpisodes`）。
3. **分集表可编辑**：改集名、`sceneFrom/sceneTo`、拆分/合并/删集；编辑后标 `episodes[].source = "manual"`。
4. **stale 提示**：改剧本 → `steps.plan.status = "stale"`，第 2 步顶部条「剧本改过，现有分集基于旧稿」+「重算分集」；不点就保留旧方案。
5. **下游连带作废**：重算确认框列出「将覆盖 N 集手调结果」；确认后把 `steps.shots.byEp` 全置 `stale`，**不删 `S.shots`**（镜头仍在表里可见，等 S4 逐集重跑）。
6. **验收脚本**：新建 `tools/verify_plan_step.mjs`，登记进 `verify_all.mjs` 的 SUITES。

**完成标准**
- 改剧本 → 第 2 步出 stale 条；点重算才发 `/api/ai/plan`；不点则显示「基于旧稿」且方案不变。
- 手改一集场次区间 → 刷新仍在（`episodes` 在 `PERSIST_KEYS` 内）。
- 分集变更后第 3 步所有集标「需重算」，已生成镜头不丢。
- `verify_plan_step.mjs` + `verify_platform.py` 全绿，且 `verify_all.mjs` 不低于 17/17。

### S4 执行清单（已完成 · 2026-11-10）

**目标**：第 3 步按集生成，每集出完即停，失败隔离；第 2 步的临时桥接下掉。

1. `storyboardStep(epKey)`：复用 `AI.storyboard`（本来按集切片），一次只请求一集；
   未分集时整部片子是一个隐式闸门 `key="all"`（集号 0，保持全局镜号）。
2. `steps.shots.byEp[key] ∈ idle|running|ready|stale|failed` + `steps.shots.errors[key]`；
   `StepShots.vue` 每集一张卡（状态点 / 三态按钮 / 失败原因），`episodeTabs` 加状态点。
3. 合并：按 `shots[].key` 的 `e{集号}-` 前缀只剔除本集镜头（旧数据退回 `episode` 字段），
   插回原集位置后 `E.renumberShots(merged, S.episodes)` 统一重排镜号与稳定键。
4. 失败隔离：AI 失败只写 `failed` + 原因，不降级覆盖、不弹全屏遮罩；`hydrate()` 把 `running`
   归一为 `failed` 并给出「上次生成被中断」提示；旧存档有镜头但无 byEp 时按每集是否已有镜头推断。
5. `tools/verify_shot_gate.mjs` 登记 SUITES（21 → 22 套）；5 个旧脚本按新链路改写。

**硬约束复核**：未改 `engine.js`；未新建 AI 接口（只调 `/api/ai/storyboard`）；
后端 7 阶段流水线仍休眠；D4 无任何批量按钮；`npm run build` 通过。

### S5 执行清单（已完成 · 2026-11-10）

**目标**：资产清单以分镜引用为准，剧本只兜底；删镜头不牵连资产。

1. `engine.js` 新增 `shotRefIds()` / `assetUsage()` / `assetsFromShots()` 三个纯函数并导出；
   `buildAssets(parsed, prev)` 内部一行未动，正常路径输出逐字段一致。
2. `studio.js` 的 `reparse(opts)` 可配置资产来源（默认 `shots`，`{ assetsFrom: "script" }` 退回旧行为）；
   新增 `assetUsage` computed，给零引用资产按 `sceneNos` 换算集号、生成 orphan 说明。
3. `AssetPanel.vue` 的 `.ap-row` 加行内短徽标（行高必须 ≤36px，见 `verify_asset_layout.mjs`）、
   分组卡加完整文案；`assets.css` 加 `.ap-row-us` / `.ap-shot-us` 与琥珀色 orphan；
   `StepAsset.vue` 加 `#asset-source-note` 说明条。
4. `tools/verify_asset_from_shots.mjs` 登记 SUITES（22 → 23 套）；
   `verify_plan_contract.mjs` 的过期断言改为真契约。

**硬约束复核**：`engine.js` 的 diff 为「0 删除 / 77 新增」，全部落在资产来源层；
未新建 AI 接口；后端 7 阶段流水线仍休眠；D4 无批量按钮；`npm run build` 通过。

### S6 执行清单（已完成 · 2026-11-10）

**目标**：首帧提示词必须在资产定妆之后生成，第 3 步不再用空参考图算提示词。

1. `studio.js` 新增 `framesGate` computed（条件：`S.step === 4` + 有镜头 + 有 `assetPack` +
   至少一条资产挂了参考图或出图），并把 `regenFrames(silent)` 改成第 4 步硬闸门：
   非第 4 步直接返回并提示「第 3 步只有只读预览」；silent 首次生成在闸门未放行时静默跳过。
2. `withRefSlots()` 把服务端回包里的 `refAssets` 编号关联回已定妆资产，写成
   `refSlots` 与「参考图槽位：[1] C01 …」追加到提示词末尾，供第 4 步 chip 展示。
3. UI：`StepAsset.vue` 加 `#frames-gate` / `#frames-gate-reason` / `#generate-frames` / `#frames-slots`；
   `PreviewPanel.vue` 加 `#pv-frames-note` 只读说明；`styles.css` 加 `.fg-*` 并在打印样式里隐藏闸门卡。
4. `tools/verify_frames_after_assets.mjs` 登记 SUITES（23 → 24 套）；
   `tools/verify_comfy_ui.mjs` 补 8188 离线环境跳过。

**硬约束复核**：`/api/ai/frames` 仍是既有单步接口、未新建 AI 接口；`server.py` 与后端 7 阶段流水线未改；
`engine.js` 的解析 / 体检 / 分镜规则未动；D4 无批量按钮。

### S7 执行清单（已完成 · 2026-11-10）

**目标**：README 与实现一致，休眠流水线处置明确，套件登记不留挂账。

1. `server.py`：顶部 docstring 第 10 项改成「【休眠保留 · 无 UI 入口，勿删（旧项目恢复用）】」
   并说明当前主流程；分区注释同样加一条。**代码一行未删**。
2. `README.md`：章节标题改「二、四个工作区 · 每步人工确认」，表格改成「序 / 工作区 / 人工确认什么 / 产出」，
   新增「为什么不做一键」小节；同时修掉 4 处过时口径（临时桥接、AI 同步给出分集方案卡、
   第 3 步「最终提示词」、死脚本 16/16 与 14/14 的现状）。
3. `verify_all.mjs`：复核 6 个关键脚本已登记，注释从「S4 接入后再重写」改为 S7 销账口径；
   新增第 25 套 `verify_final_docs.mjs`。
4. 两个死脚本：头部由 `PAUSED (S2)` 改为 `DEPRECATED (S7 已销账)`，写明「不重写、不删除」的理由
   与「不在 SUITES 内，勿作为回归跑」。**文件保留**，供旧项目恢复排查。

**硬约束复核**：未改任何生成逻辑；`engine.js` / `studio.js` / AI 接口 / 后端流水线全部未动；
D4 无批量按钮；`npm run build` 通过。

---

## 5. 关键代码坐标（别重新找）

> **注意路径前缀**：2026-11-11 拆仓后，前端文件全部在**兄弟仓** `../shortplay-studio-web/` 下，
> 下表里写 `frontend/src/...` 的历史条目实际路径为 `../shortplay-studio-web/src/...`。
> `studio.js` 已拆域，历史条目里说「`studio.js` 的某函数」现在在 `src/stores/studio/<域>.js` 里
> （barrel 仍导出同名符号，`import { xxx } from "./stores/studio.js"` 照旧可用）。

### 架构层（2026-11-11 新增）

| 位置 | 说明 |
|---|---|
| `server.py` | **21 行薄壳**，只剩 `from app.main import run`。改启动逻辑别在这改 |
| `app/main.py` | 装配层：`Handler` / `StudioServer` / `run()` / 横幅。`run()` 里 `SHORTPLAY_LEGACY_SERVER=1` 走旧 stdlib 实现 |
| `app/asgi.py` | **FastAPI 应用**：只做协议翻译（Sink 收 `Response` → Starlette），含 SSE 线程池防阻塞、静态托管、404 口径 |
| `app/web/responses.py` | **响应原语**：`Response`（纯数据）+ `Sink`（假 handler，`wfile` 主动抛错）+ `_emit` 双模式投递。**路由层能脱离 socket 测就靠它** |
| `app/web/routes_get.py` / `routes_post.py` / `agent_routes.py` | 三张路由表。签名仍是 `fn(h)` / `fn(h, payload)`，**没改成 FastAPI 路由函数**（有意为之：换框架零改动） |
| `app/services/llm_gateway.py` | **LLM 唯一出口**：`call_llm` / `call_llm_json`，同签名替换旧 urllib 版；报错文案逐字兼容 |
| `app/services/llm_json.py` | `extract_json` / `repair_json` **一字不许改**（铁律），gateway 直接 import 复用 |
| `app/config/db.py` | `llm_calls` 表（SQLite WAL）。只存字符数与 token，**不存 prompt 原文与 Key**；写失败只打 stderr |
| `app/paths.py` | `ROOT` 必须 `parent.parent`；`WEB_ROOT` 四级解析（环境变量→兄弟仓 dist→本仓 dist→仓库根） |
| `requirements.txt` | 5 条直接依赖钉版本：langchain-core / langchain-openai / fastapi / uvicorn（+ 传递依赖） |
| `../shortplay-studio-web/src/stores/studio.js` | barrel，5 行 `export *`；域文件在 `studio/{core,session,steps,shots,assets}.js` |
| `tools/verify_sse_nonblocking.py` | Step C 专项：SSE 挂起期间 `/api/config` 必须 < 500ms |

### 业务层（历史条目，路径见上方提示）

| 位置 | 说明 |
|---|---|
| `frontend/src/lib/engine.js` | `sceneStableKey` / `keyScenes` / `shotKeyOf` / `keyShots`；`parseScript`→`scenes[].key`，`renumberShots`→`shots[].key` |
| `engine.js:918` | **早有同名 `sceneKey(intExt,time,name)`（资产去重键）**，新函数必须叫 `sceneStableKey`，改名回去会 `SyntaxError` |
| `frontend/src/stores/studio.js` | `defaultSteps()`、`normalizeSteps()`（旧 `S.stale` 字符串→stale）、`hydrate()` 的 `keyShots` 补键与 `stepV` 迁移、`markStale()` |
| `studio.js` `projectData()` / `blankProjectData()` | 写 `stepV = 2`；`hydrate()` 对无 `stepV` 的旧项目把 step 3↔4 换回来（29 个旧存档靠它才不落错工作区） |
| `studio.js` `storyboardStep()` | **S4 逐集闸门**：一次只请求一集，按 `shots[].key` 只替换本集；未分集用隐式 `all` 闸门 |
| `studio.js` `doGenerate()` / `localGenerate()` | 第 2 步的临时桥接已在 S4 移除；现在只服务于生成设置的「按当前参数重排（本地规则）」与 stale 条，不再是主路径 |
| `StepShots.vue` `#shot-gates` | 每集一张卡，`[data-shot-gate]` 是回归脚本的稳定钩子；D4 无批量按钮 |
| `engine.js` `assetsFromShots()` / `assetUsage()` | **S5**：前者以 shots 引用为准补回资产、剧本只兜底；后者统计「N 镜 / 第 X–Y 集」。都不碰 `buildAssets` 内部 |
| `studio.js` `reparse(opts)` / `assetUsage` computed | **S5**：资产来源可配置（`{ assetsFrom: "script" }` 退回旧行为）；零引用资产按 `sceneNos` 换算集号给 orphan 说明 |
| `AssetPanel.vue` `[data-asset-usage]` / `StepAsset.vue` `#asset-source-note` | **S5**：列表短徽标（行高 ≤36px）+ 分组卡完整文案 + 第 4 步来源说明条，回归脚本的稳定钩子 |
| `studio.js` `framesGate` / `regenFrames(silent)` | **S6**：第 4 步硬闸门；静默重算在闸门未放行时不发请求，非第 4 步直接返回 |
| `studio.js` `withRefSlots()` | **S6**：`refAssets` → `refSlots`，把「参考图槽位」追加进首帧提示词 |
| `StepAsset.vue` `#frames-gate` / `PreviewPanel.vue` `#pv-frames-note` | **S6**：定妆后的生成按钮与槽位 chip / 第 3 步只读预览说明，回归脚本的稳定钩子 |
| `README.md` 二章 +「为什么不做一键」 | **S7**：产品口径正文；改实现必须同步改它，`verify_final_docs.mjs` 会拦 |
| `server.py` 顶部 docstring 第 10 项 / 分区注释 | **S7**：休眠流水线「无 UI 入口，勿删（旧项目恢复用）」，代码保留 |
| `tools/verify_final_docs.mjs` | **S7**：无浏览器契约（README 一致 / 流水线保留 / 顺序锁定 / SUITES 登记 / 死脚本销账） |
| `frontend/src/lib/ai.js:140-148` | `storyboard(script, parsed, ep, config)` **本来就按集切片**（`ep.sceneFrom..sceneTo` + `E.scriptSlice`），`AI.run` 是 `episodes.forEach` 逐集调 → S4 零架构成本 |
| `server.py` | `/api/parse/start` 7 阶段流水线**代码保留、无 UI 入口**；`resumeParseTask` 也留着（旧项目刷新不炸）。单步接口 `/api/ai/{adapt,plan,storyboard,assets,frames}` 全部可用 |
| `frontend/src/App.vue` | `view-3` 挂 StepShots，`view-4` 挂 StepAsset |
| `STEPS` / `goStep(4)` 闸门 | 无镜头时提示「先在第 3 步排分镜，再来定妆」 |

### 踩过的坑（照抄可省一小时）

- **CRLF**：`engine.js` / `studio.js` / `.vue` 均为 CRLF。改 `.vue` 用 Python `io.open(..., newline='')` + `assert count==1` 精确替换，别用 sed。`studio.js` 里两处 `S.stale = ""; S.step = 3;` 缩进不同（一处 4 空格、一处 2 空格），批量替换要分两条。
- **Python heredoc 吞 `\n`**：`bits.join("\n")` 会变成跨行字符串；改用 `String.fromCharCode(10)` 或直接写 `chr(10)`。
- **Git Bash `/tmp` ≠ Windows Python 路径**：跨两者传路径用 `cygpath -w`。
- **Playwright JS API**：是 `allTextContents()` / `innerText()`；`all_inner_texts()` 是 Python 版。
- **假绿**：`verify_ai.py` 曾 28/32 却返回退出码 0，被 `verify_all` 算成 PASS。它连同 `verify_parse_progress.mjs`、`verify_parse_resume.mjs` 已标 **PAUSED** 并从 SUITES 摘除，S4 接入逐集 AI 后按新流程重写，别直接跑旧断言。
- **深链接跳不通先确认 URL/标题**，否则三个页面测的都是首页。

---

## 6. 本机才有的东西（不进 git，换机要自备）

| 路径 | 原因 | 换机怎么办 |
|---|---|---|
| `tools/verify_*`（本机 32 个 `verify_*.mjs` + 若干 `.py`，含 PAUSED 死脚本与新增的 `verify_sse_nonblocking.py`） | `.gitignore` 明确排除「硬编码本机路径」 | 拷 `tools/` 整目录 + 按 §1 的 Mac 适配清单改路径 / 命令 / fixture |
| `tools/verify_all.mjs`（**26 套** SUITES） | 25 套 + Step C 的 SSE 不阻塞 1 套 | 见 §3；换机后同样把新增脚本一起拷 |
| `projects/p_fixture_stage_split` | `verify_stage_split.mjs` 需要「含分镜的既有项目」，旧机 fixture 未随仓库迁移 | 用 `engine.js` 造一个 23 镜项目，字段要点见 §1 |
| `llm-config.bat` / `llm-providers.json` / `.env*` | **含真实 API Key，禁止提交** | 在新机按 README 第 49 行说明重建（只需 LLM 那条；万相 key 可选、2026-11-11 起不用管）。**本机缺这个 → 3 套 AI 资产用例被按钮闸门挡住** |
| **`.venv/`**（Python 虚拟环境） | 平台相关，不可跨机复制 | **必装**：`python3 -m venv .venv && ./.venv/bin/python -m pip install -r requirements.txt`。FastAPI 之后不再是零依赖 |
| **`data/llm_calls.db`**（LLM 调用台账） | 本机运行数据，`.gitignore` 排除 | 不用迁移：首次调用自动建表。要带历史排查就拷这个文件 |
| `projects/`（29 个真实项目） | 本机运行数据 | 不迁移也能开发；要测旧存档迁移就拷几个 `project.json` |
| `shortplay-studio-web/dist/` | 构建产物，在**兄弟仓**里 | 去前端仓 `npm install && npm run build` 重新生成。**本仓已无 `dist/`** |
| `examples/assets/`（本机 71M 测试图） | 运行时出图产物、体积过大 | 已加入 `.gitignore`；历史里的 51 张示例图也已剔除，新机跑出图时自动生成 |
| `screenshots/`、`.tts/`、`.workbuddy/` | 运行/个人数据 | 忽略 |
| `MIGRATION.md` | 含本机绝对路径的运维记录 | 忽略 |
| `~/.ssh/id_ed25519_github` | 本机 GitHub 专用私钥，禁止外传 | 新机另生成一对，把公钥加到 GitHub 账号 |

---

## 7. 分支与提交状态

- 本地分支 **`dev`**（从基线分支 `main` 新建），含 S0/S1/S2/S3 全部代码改动、`README.md` 同步、`docs/` 两份文档、三份 `tools/baseline-*.txt`。S3 以 Conventional Commits 提交（subject 小写开头），验证脚本按 `.gitignore` 不入库。
- **✅ 已推送到 `github.com:kevinzgai/ShortPlay-Studio.git`**（2026-11-09）：`dev` 与 `main` 均已推送，`dev` 已设 upstream 跟踪 `origin/dev`。用 `git ls-remote --heads origin` 核对。
- **✅ 2026-11-10 已推送**：S3.5~S7 的 12 个提交（`feat(settings)` / `style(settings)` / `feat(plan)` / `feat(shots)` / `feat(assets)` / `feat(frames)` 及各阶段 `docs(plan)`）已推到 `origin/dev`，本地与远程同步。换机 clone 后用 `git log --oneline origin/dev..HEAD` 核对，正常应为空。
- **✅ 2026-11-11 已推送（架构三阶段 + LangChain）**：A 拆包 / B 拆仓 / C 换 FastAPI /
  LangChain 步骤一 全部推到 `origin/dev`。**前端仓 `shortplay-studio-web` 是独立仓库，也在 `dev` 分支，
  换机要单独 clone**（见 §1）。两个仓的提交互不依赖，先 clone 哪个都行。
- 入库范围提醒：`tools/verify_*`、`engine-config.json`、`llm-providers.json`、`.venv/`、`data/`
  按 `.gitignore` **不入库**。clone 下来没有回归脚本、没有本机密钥、没有 venv、没有调用台账，
  需按 §1 自行同步与安装。
- **⚠️ 2026-11-09 做过一次历史重写**（剔除 51 张示例 PNG，仓库 47.6 MB → 约 1 MB）：**所有旧 commit hash 全部失效**，本文不再写死 hash，以远程当前值为准；桌面 bundle / patch 也已按新历史重导。
- `origin` 使用 **SSH**：`git@github.com:kevinzgai/ShortPlay-Studio.git`。本机可用密钥是 **`~/.ssh/id_ed25519`**（`ssh -T git@github.com` 应回 `Hi kevinzgai!`）。
  **2026-11-10 实测补充**：当时 remote 曾被配成 HTTPS，`git push` 会 `Operational timed out` / `could not read Username`（本机没缓存 HTTPS 凭证），改回 SSH 后一次推成功。若再遇到推不上，先 `git remote get-url origin` 确认协议。
- **坑**：`~/.ssh/id_rsa` 曾是绑定 `wd-hub` 仓库的 Deploy Key，`ssh -T git@github.com` 会显示 `Hi kevinzgai/wd-hub!` 看似成功，推本仓库却报 `Permission denied to deploy key`。GitHub 不允许同一把 deploy key 复用到别的仓库；本机现在也**没有** `id_rsa` 了，别再按旧文档找它。
- 新机 clone 用 HTTPS 即可（只读免凭证）；**要 push 必须走 SSH** 并配自己的公钥，或显式用 HTTPS + PAT（本机 `osxkeychain` 没有存 PAT，所以 HTTPS 直接推会失败）。

### 离线兜底：桌面交接包（仍保留，非必需）

`Desktop/ShortPlay-dev-handoff/` 内有若干 patch + 1 个 bundle（含重写后的完整 dev 历史，`git bundle verify` 通过）。只有在不方便联网、想完全离线迁移时才需要：

```bash
git clone /path/to/ShortPlay-dev.bundle ShortPlay-Studio -b dev
cd ShortPlay-Studio
git remote set-url origin git@github.com:kevinzgai/ShortPlay-Studio.git
```

> 交接包在**最后一次提交后重新导出**，含 dev 上全部提交。若旧机又追加提交，重跑
> `git format-patch main..dev -o <目录>` 与 `git bundle create <目录>/ShortPlay-dev.bundle dev`。
> 补丁/bundle 只含 git 跟踪的文件，`tools/verify_*` 回归脚本仍需按 §1 单独拷贝。
> `.gitignore` 的 `tools/verify_*` 策略**未改动**：S3 起新增的验收脚本也要按 §1 手工同步到新机。

---

## 8. 未决 / 已知限制

### 当前真正待办（2026-11-11）

| # | 项 | 状态 | 说明 |
|---|---|---|---|
| 1 | LangGraph 步骤二（接管流水线编排） | ⏸ **等触发器，不是待办** | 触发条件二选一：评审回环的「打回+收敛条件」定义清楚，或第二个需要工具循环的 skill 立项。触发前不引入 langgraph 依赖 |
| 2 | 「零依赖双击即用」已放弃 | ⚠️ 已接受的代价 | FastAPI 之后必须 venv。`start.bat` / `start-mac.command` 已做自动引导，venv 缺失时回退系统 Python（AI 调用不可用但服务能起） |
| 3 | D2 重跑覆盖手工修改 | ⚠️ 已知限制 | 靠二次确认缓解；真正合并要等按场增量（键已埋好） |
| 4 | 本地规范化依赖空行补场号；PDF 导入不支持 | ⚠️ 已知限制 | 未排期 |

### 已注销（核查后确认不用做，别再当遗留任务跟）

| 项 | 结论 |
|---|---|
| ~~万相有效 Key / 只判有没有填不判真伪~~ | **2026-11-11 用户明确注销**。它是 ComfyUI 之外的可选备用引擎，默认引擎是 `comfy`；`qwenKey` 为空时诊断只降级为 `warn`，不影响主流程与回归 |
| ~~新建项目道具分组默认空~~ | **2026-11-11 核查结案，不是缺陷**。① AI 分解路径道具完整（实测产出 3 个）；② 只有离线引擎 `engine.js:1069` 的 props 只继承不推断，属有意设计（道具名无可靠正则特征）；③ 绑定链路正常（fixture 44 镜中 8 镜正确绑定） |

### 历史限制（保留供溯源）

- S2 刻意偏离计划两处：① `planOnly()` **已在 S3 拆成 `planStep()`（显式按钮）**；② `doGenerate()` 降级为离线规则而非彻底禁用（否则 S2→S4 之间排不出镜头、5 个脚本失去可测路径）。
- S3 起 `localGenerate()` 不再重算分集；**S4 已移除第 2 步的临时桥接**（`#generate` 只导航到第 3 步），`localGenerate()` 仅保留给生成设置的本地重排入口。
- 本机（Mac）`npm` 镜像源 500、官方源不通，`vue` / `vite` 依赖是从本机其它工程的 pnpm 目录复制补齐的；`npm run build` 已跑通，换机仍按 §1 正常 `npm install`。
- 本机 macOS 有 `127.0.0.1:7877` 系统代理，8177 不带 `NO_PROXY=127.0.0.1,localhost` 启动时，Python `urllib` 会把 ComfyUI 8188 探测带成 502；带 `NO_PROXY` 重启后 `/api/comfy/status` online=true。
- **ComfyUI 8188 会掉线**（2026-11-11 实测：跑回归中途从在线变成 `Connection refused`）。掉线时 `verify_comfy_ui.mjs` 环境跳过、`系统设置三栏` 掉 1 项、并发测试 C 段失败（A/B 段 40/40 仍过）。**这是环境问题不是代码回归**，把 ComfyUI 拉起来重跑即可。
- D2 的「重跑覆盖手工修改」尚未解决，靠二次确认缓解；真正合并要等按场增量（键已埋好）。
- S6 已完成：第 3 步是只读预览、不会用空参考图算提示词；首帧提示词统一在第 4 步定妆后生成。
- **S5 起 engine.js 允许新增资产来源层函数**：`verify_plan_contract.mjs` 不再用「git status 干净」判断（那是假绿），
  改为检查 `git diff HEAD` 删除行必须为 0 + 三个已锁函数仍在。若将来要删改既有规则，这条会先红。
- ~~**道具分组的新建项目默认仍为空**：`buildAssets` 的 props 只从 prev 继承，S5 的验收脚本通过界面 `#add-prop`
  加一条道具来代表「资产分解后」的状态；若要「走完阶段 4 就自动有道具」，需另开阶段补一条道具推断规则。~~
  **→ 2026-11-11 核查后结案（不是缺陷，无需改代码）**：
  ① **AI 分解路径道具完整**——实测《鬼婚逃命》真实调用产出 3 个道具（红绳玉佩 / 黄纸铜钱 / 黄铜罗盘），
  `agents/prompts/assets.md` 的 props schema 与 `assets.py:140` 的解析完全对得上；
  ② **只有离线规则引擎**（`engine.js:1069`）的 props 是 `((prev && prev.props) || []).slice()`——只继承不推断，
  这是**有意设计**：道具名没有像人名那样的动词模式可依据，正则硬猜只会产出噪声道具污染面板；
  ③ **绑定链路本身正常**——`p_fixture_stage_split` 实测 44 镜中 8 镜正确绑定（「热咖啡」绑到 8 个出现它的镜头）。
  结论：走 AI 分解自然就有道具，离线模式保持「不猜」，此条不再跟进。
- **死脚本已销账（S7）**：`verify_parse_progress.mjs` / `verify_parse_resume.mjs` / `verify_ai.py` 标 **DEPRECATED**，
  不在 SUITES；不重写也不删除（被测对象无 UI 入口，逐集链路由 S4/S5/S6 覆盖），保留供旧项目恢复排查。
- ~~**万相 Key 只判「有没有填」不判真伪**：`qwen_image_status()` / `engine_probe("qwen")` 让无效 Key 也显示「可用」，实际出图 401。2026-11-10 实测发现，尚未修；修时建议用不计费的 `/compatible-mode/v1/models` 做真实鉴权探测，并同步系统设置契约脚本。~~
  **→ 2026-11-11 用户明确注销：万相不用管**。可选备用引擎，非主链路，此条不再跟进（代码保持现状）。
- **本机 ComfyUI 8188 当前离线**（2026-11-10 S6 全量时）：`verify_comfy_ui.mjs` 已做环境降级，
  打印 `[环境跳过]` 并以 0 通过/0 失败退出；`系统设置三栏` 因此是 29/30（1 项诊断不可用）。
  启动 8188 后重跑这两套可拿回完整断言，**不需要改代码**。
- ~~**万相有效 Key 仍未提供**：`engine-config.json` 的 `qwenKey` 为空；用户提供新 Key 后需重新
  `/api/engine/config` 写入并用 `/api/comfy/generate` 实出一张图验证（`/api/engine/test` 不做鉴权探测）。~~
  **→ 2026-11-11 用户明确注销：万相不用管**，不再等待 Key，也不需要做真伪探测。
