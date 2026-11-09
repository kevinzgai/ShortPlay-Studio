# dev 分支 · 续作任务计划（换机接手用）

> 生成：2026-11-09 · 基线分支 `main` · 适用分支 `dev` · **已推送 GitHub（main + dev）** · 历史已剔除示例 PNG
> 本文自包含：**读完即可在另一台机器从 S3 接着做，不需要翻聊天记录。**
> 完整设计依据见 `docs/分步开发路线-移除一键生成.md`（同一分支，已提交）。

---

## 续作提示词（换电脑后直接复制给 AI）

```text
你在 ShortPlay-Studio 项目的 dev 分支上继续开发。开工前先完整读
docs/dev-续作任务计划.md 和 docs/分步开发路线-移除一键生成.md，
不要重新调研架构、不要重做已完成阶段、不要重新讨论已锁定的决策。

【当前状态】
- 代码已推送 GitHub：https://github.com/kevinzgai/ShortPlay-Studio.git，分支 dev（main 是基线分支）。
- S0/S1/S2/S3 已完成：engine.js 的稳定键（sceneStableKey / shotKeyOf / keyShots）、studio.js 的
  S.steps 状态机与旧存档迁移、移除「AI 一键分集 + 分镜」、工作区顺序翻转为
  ①改剧本 ②分集 ③分镜 ④定妆、stepV 存档迁移；S3 分集独立成步（显式 planStep / 可编辑分集表 /
  stale 条 / 二次确认 + byEp 全 stale）。
- S3.5 设置分层（S4 之前插入）：文字模型 / 出图引擎从「生成设置」移出，独立为全局「系统设置」，
  三栏 = 文字模型 / 出图引擎 / 连接与诊断；出图引擎可在界面改并立即生效（engine-config.json）。
  S3 / S3.5 实测见 §3。
- 下一步 = S4「分镜逐集闸门」。S5 定妆消费分镜 / S6 出片归位 / S7 收尾在后面。

【本次只做 S4，照 docs/分步开发路线-移除一键生成.md「阶段 4」的 5 条改动执行】
1. 新增 storyboardStep(epNo)：只请求一集，复用 /api/ai/storyboard（本来按集切片）。
2. 集级状态 steps.shots.byEp[epNo] ∈ idle|running|ready|failed，每集 tab 带状态点与按钮。
3. 合并规则：只替换 shots[].key 属于该集的镜头，其它集原样保留；renumberShots 统一重排镜号。
4. 失败隔离（单集失败不碰其它集）+ 中断恢复（running 归一为 failed，S.shots 落盘）。
5. 新建 tools/verify_shot_gate.mjs 并登记进 tools/verify_all.mjs 的 SUITES。
> S3 把第 2 步的「按规则排分镜 →」留作临时桥接；S4 用逐集闸门替换它。D4：不给「剩余全部」按钮。

【硬约束，违反即返工】
- 四项已锁决策：D1 分集/分镜各为独立 AI 步 + 人工闸门；D2 整步作废 + 显式重跑（不做按场增量）；
  D3 顺序 剧本→分集→分镜→定妆；D4 只有单集闸门，第一版不给「剩余全部」按钮。
- 阶段严格串行，S3 没验收完不许碰 S4；不改 engine.js 的解析/体检/buildStoryboard 规则；
  不新建 AI 接口，复用 /api/ai/plan、/api/ai/storyboard；后端 7 阶段流水线保持休眠不删。
- 本阶段新增脚本必须全绿才进下一阶段；旧脚本若因步骤号变化而红，必须在同阶段内修完，不许挂账。
- 已知缺陷允许保留：重跑会覆盖手工修改，靠二次确认缓解。

【环境与容易踩的坑】
- 服务是 Python 标准库后端 8177：py server.py --no-browser；改 frontend/src 必须 npm run build，
  改 server.py 必须重启 8177。回归：node tools/verify_all.mjs（21 套串行，实测 4m26s）。
- .gitignore 排除 tools/verify_*：这些回归脚本不随仓库走，若新机没有，先从旧机拷 tools/ 整目录，
  并把脚本头部的 playwright-core file:/// 路径与 Chromium executablePath 换成新机实际路径。
  本机（Mac）还额外改了 py→python3、verify_all.mjs 的 py→python3、stage_split 的 fixture 项目 ID，
  且 8177 要带 NO_PROXY=127.0.0.1,localhost 启动（详见 §1 的 Mac 适配清单）。
- engine.js / studio.js / .vue 都是 CRLF，改 .vue 用 Python io.open(..., newline='') + assert count==1
  精确替换；engine.js:918 早有同名 sceneKey(intExt,time,name)，新函数只能叫 sceneStableKey。
- Playwright 用 JS API（allTextContents/innerText），默认有窗口模式 headless:false。
- verify_ai.py 与 verify_parse_progress/resume 已标 PAUSED 并移出 SUITES，别跑旧断言。

【交付要求】
- 先报 3-5 行计划再动手；验证强度默认从简，只有交互/时序/跨层状态才上浏览器脚本。
- 改完跑 verify_all.mjs 并给出逐项结果，用 Conventional Commits 提交（subject 不大写开头）。
- 完成后更新 docs/dev-续作任务计划.md 的阶段进度表，再告诉我下一阶段是什么。
```

---

## 0. 一句话现状

「AI 一键分集 + 分镜」的 7 阶段自动流水线已**休眠**；四个工作区顺序翻转为
**① 改剧本 → ② 分集 → ③ 分镜 → ④ 定妆**。
**S0 / S1 / S2 / S3 / S3.5 已完成**。`verify_all.mjs` 的 SUITES 为 **21 套（原 17 + S3 的 2 + S3.5 的 2）**，
本机实测 **21/21 套全绿**（4m26s）。此前因未配 Key 而红的 3 套，在 `llm-providers.json` 补上后全部转绿，
确认它们确实是环境阻塞而非代码回归。逐项结果见 §3。
**下一步 = S4「分镜逐集闸门」**。第 2 步的「按规则排分镜 →」仍是临时桥接，S4 才换成逐集闸门。

---

## 1. 换机后 5 分钟自检

```bash
git clone https://github.com/kevinzgai/ShortPlay-Studio.git   # 公开仓库，clone 免凭证
cd ShortPlay-Studio
git checkout dev                 # 远程已有 dev，直接切
npm install                     # 或双击 start.bat，它会自动装 + 构建
npm run build
py server.py --no-browser       # 起 8177（服务只用 Python 标准库）
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8177/   # 期望 200
```

- 前端产物在 `dist/`（`server.py` 托管），**改了 `frontend/src` 必须 `npm run build` 才生效**；改 `server.py` 必须重启 8177。
- 开发态：`py server.py --no-browser` + `npm run dev --prefix frontend`（5173 代理 /api 到 8177）。
- 离线模式 `?ai=0`：强制规则引擎 + 不发任何模型请求，排查 UI 时优先用。
- **推送凭证**：本机 `origin` 走 SSH（`git@github.com:...`），密钥 `~/.ssh/id_ed25519_github`。只 clone / 读代码不需要配置；要 push 就得在新机配自己的 SSH 公钥，或改用 HTTPS + PAT。

### 回归（重要：脚本不在 git）

```bash
node tools/verify_all.mjs        # 21 套串行（原 17 + S3 的 2 + S3.5 的 2），实测 4m26s
node tools/verify_all.mjs assets # 只跑名字含 assets 的
```

`.gitignore` 有 `tools/verify_*`，**全部 31 个回归脚本不随仓库走**。换机后从旧机器拷整个 `tools/` 目录，并替换其中两处本机绝对路径（脚本头部）：

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
| **S4 分镜逐集闸门** | ⬜ **下一步** | 核心，`storyboard()` 本来按集切片；替换第 2 步的临时桥接 |
| S5 定妆消费分镜 | ⬜ | 分组视图才有数据 |
| S6 出片归位（可选） | ⬜ | frames 挪到第 4 步末尾，不做就在 README 写已知限制 |
| S7 收尾 | ⬜ | 休眠流水线注释、README、套件登记 |

**依赖严格串行**：S2 定死步骤号 → S3 定死集号 → S4 依赖集号 → S5 依赖镜头。不许跳步。
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

---

## 5. 关键代码坐标（别重新找）

| 位置 | 说明 |
|---|---|
| `frontend/src/lib/engine.js` | `sceneStableKey` / `keyScenes` / `shotKeyOf` / `keyShots`；`parseScript`→`scenes[].key`，`renumberShots`→`shots[].key` |
| `engine.js:918` | **早有同名 `sceneKey(intExt,time,name)`（资产去重键）**，新函数必须叫 `sceneStableKey`，改名回去会 `SyntaxError` |
| `frontend/src/stores/studio.js` | `defaultSteps()`、`normalizeSteps()`（旧 `S.stale` 字符串→stale）、`hydrate()` 的 `keyShots` 补键与 `stepV` 迁移、`markStale()` |
| `studio.js` `projectData()` / `blankProjectData()` | 写 `stepV = 2`；`hydrate()` 对无 `stepV` 的旧项目把 step 3↔4 换回来（29 个旧存档靠它才不落错工作区） |
| `studio.js` `doGenerate()` | **临时桥接** `localGenerate()`；S4 用逐集闸门替换，别当成最终形态 |
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
| `tools/verify_*`（26 个 `verify_*.mjs`） | `.gitignore` 明确排除「硬编码本机路径」 | 拷 `tools/` 整目录 + 按 §1 的 Mac 适配清单改路径 / 命令 / fixture |
| `tools/verify_all.mjs`（19 套 SUITES） | 原 17 套已从旧机同步，另登记 S3 新增 2 套 | 见 §3；换机后同样把新增脚本一起拷 |
| `projects/p_fixture_stage_split` | `verify_stage_split.mjs` 需要「含分镜的既有项目」，旧机 fixture 未随仓库迁移 | 用 `engine.js` 造一个 23 镜项目，字段要点见 §1 |
| `llm-config.bat` / `llm-providers.json` / `.env*` | **含真实 API Key，禁止提交** | 在新机按 README 第 49 行说明重建；万相 key 走这里。**本机缺这个 → 3 套 AI 资产用例被按钮闸门挡住** |
| `projects/`（29 个真实项目） | 本机运行数据 | 不迁移也能开发；要测旧存档迁移就拷几个 `project.json` |
| `dist/` | 构建产物 | `npm run build` 重新生成 |
| `examples/assets/`（本机 71M 测试图） | 运行时出图产物、体积过大 | 已加入 `.gitignore`；历史里的 51 张示例图也已剔除，新机跑出图时自动生成 |
| `screenshots/`、`.tts/`、`.workbuddy/` | 运行/个人数据 | 忽略 |
| `MIGRATION.md` | 含本机绝对路径的运维记录 | 忽略 |
| `~/.ssh/id_ed25519_github` | 本机 GitHub 专用私钥，禁止外传 | 新机另生成一对，把公钥加到 GitHub 账号 |

---

## 7. 分支与提交状态

- 本地分支 **`dev`**（从基线分支 `main` 新建），含 S0/S1/S2/S3 全部代码改动、`README.md` 同步、`docs/` 两份文档、三份 `tools/baseline-*.txt`。S3 以 Conventional Commits 提交（subject 小写开头），验证脚本按 `.gitignore` 不入库。
- **✅ 已推送到 `github.com:kevinzgai/ShortPlay-Studio.git`**（2026-11-09）：`dev` 与 `main` 均已推送，`dev` 已设 upstream 跟踪 `origin/dev`。用 `git ls-remote --heads origin` 核对。
- **⚠️ 2026-11-09 做过一次历史重写**（剔除 51 张示例 PNG，仓库 47.6 MB → 约 1 MB）：**所有旧 commit hash 全部失效**，本文不再写死 hash，以远程当前值为准；桌面 bundle / patch 也已按新历史重导。
- `origin` 使用 **SSH**：`git@github.com:kevinzgai/ShortPlay-Studio.git`。本机 `~/.ssh/config` 的 `Host github.com` 段指向专用密钥 `~/.ssh/id_ed25519_github`（`IdentitiesOnly yes`）。
- **坑**：本机原有的 `~/.ssh/id_rsa` 是绑定 `wd-hub` 仓库的 Deploy Key，`ssh -T git@github.com` 会显示 `Hi kevinzgai/wd-hub!` 看似认证成功，但推这个仓库报 `Permission ... denied to deploy key`。GitHub 不允许同一把 deploy key 复用到别的仓库，别再拿旧密钥试。
- 新机 clone 用 HTTPS 即可（免凭证）；要 push 就配自己的 SSH 公钥，或改用 HTTPS + PAT。

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

- S2 刻意偏离计划两处：① `planOnly()` **已在 S3 拆成 `planStep()`（显式按钮）**；② `doGenerate()` 降级为离线规则而非彻底禁用（否则 S2→S4 之间排不出镜头、5 个脚本失去可测路径）。
- S3 起 `localGenerate()` 不再重算分集（沿用第 2 步已确认的方案），避免临时桥接把手调结果悄悄覆盖；S4 换成逐集闸门后这条桥接即可移除。
- 本机（Mac）`npm` 镜像源 500、官方源不通，`vue` / `vite` 依赖是从本机其它工程的 pnpm 目录复制补齐的；`npm run build` 已跑通，换机仍按 §1 正常 `npm install`。
- 本机 macOS 有 `127.0.0.1:7877` 系统代理，8177 不带 `NO_PROXY=127.0.0.1,localhost` 启动时，Python `urllib` 会把 ComfyUI 8188 探测带成 502；带 `NO_PROXY` 重启后 `/api/comfy/status` online=true（ComfyUI 0.34.2），`verify_comfy_ui.mjs` 26/26 全绿。
- 本机未配 `llm-providers.json`，`/api/config` 的 `llm:false` 使 `#build-assets` / `.ap-fill` 置灰，3 套 AI 资产用例无法跑（环境阻塞，非 S3 代码回归）；补齐模型 Key 后重跑即可，见 §3。
- D2 的「重跑覆盖手工修改」尚未解决，靠二次确认缓解；真正合并要等按场增量（键已埋好）。
- S6 不做的话，第 3 步看到的提示词可能缺资产描述，需在 README「已知限制」写明。
- 本地规范化依赖空行补场号；PDF 导入不支持。
- `verify_parse_progress.mjs` / `verify_parse_resume.mjs` 不在 SUITES 内，S2 后是死脚本，S4 一并处置。
