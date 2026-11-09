# dev 分支 · 续作任务计划（换机接手用）

> 生成：2026-11-09 · 基线 `bf5e410`（main）· 适用分支 `dev` · **已推送 GitHub（main + dev）**
> 本文自包含：**读完即可在另一台机器从 S3 接着做，不需要翻聊天记录。**
> 完整设计依据见 `docs/分步开发路线-移除一键生成.md`（同一分支，已提交）。

---

## 续作提示词（换电脑后直接复制给 AI）

```text
你在 ShortPlay-Studio 项目的 dev 分支上继续开发。开工前先完整读
docs/dev-续作任务计划.md 和 docs/分步开发路线-移除一键生成.md，
不要重新调研架构、不要重做已完成阶段、不要重新讨论已锁定的决策。

【当前状态】
- 代码已推送 GitHub：https://github.com/kevinzgai/ShortPlay-Studio.git，分支 dev（main 是基线 bf5e410）。
- S0/S1/S2 已完成：engine.js 的稳定键（sceneStableKey / shotKeyOf / keyShots）、studio.js 的
  S.steps 状态机与旧存档迁移、移除「AI 一键分集 + 分镜」、工作区顺序翻转为
  ①改剧本 ②分集 ③分镜 ④定妆、stepV 存档迁移。全量回归 17/17 套 PASS。
- 唯一待办起点 = S3「分集独立成步」。S4 逐集闸门 / S5 定妆消费分镜 / S6 出片归位 / S7 收尾在后面。

【本次只做 S3，照 docs/dev-续作任务计划.md §4 的 6 步执行】
1. 删掉 studio.js 中 planOnly() 里的 S.episodes.length 短路（分集永不重算的根因），改成显式
   planStep()，由按钮触发，并写 S.steps.plan 的 running/ready/at/engine/model。
2. goStep(2) / goStep2() 不再自动调 planOnly()；第 2 步给「生成 / 重算分集」按钮，AI 优先、失败降级本地。
3. 分集表可编辑：集名、sceneFrom/sceneTo、拆分/合并/删集；编辑后标 episodes[].source = "manual"。
4. 改剧本 → steps.plan.status = "stale"，第 2 步出「基于旧稿」提示条 + 「重算分集」；不点就保留旧方案。
5. 重算前二次确认并列出「将覆盖 N 集手调结果」；确认后把 steps.shots.byEp 全置 stale，
   但不删 S.shots（镜头仍在表里，等 S4 逐集重跑）。
6. 新建 tools/verify_plan_step.mjs 并登记进 tools/verify_all.mjs 的 SUITES。

【硬约束，违反即返工】
- 四项已锁决策：D1 分集/分镜各为独立 AI 步 + 人工闸门；D2 整步作废 + 显式重跑（不做按场增量）；
  D3 顺序 剧本→分集→分镜→定妆；D4 只有单集闸门，第一版不给「剩余全部」按钮。
- 阶段严格串行，S3 没验收完不许碰 S4；不改 engine.js 的解析/体检/buildStoryboard 规则；
  不新建 AI 接口，复用 /api/ai/plan、/api/ai/storyboard；后端 7 阶段流水线保持休眠不删。
- 本阶段新增脚本必须全绿才进下一阶段；旧脚本若因步骤号变化而红，必须在同阶段内修完，不许挂账。
- 已知缺陷允许保留：重跑会覆盖手工修改，靠二次确认缓解。

【环境与容易踩的坑】
- 服务是 Python 标准库后端 8177：py server.py --no-browser；改 frontend/src 必须 npm run build，
  改 server.py 必须重启 8177。回归：node tools/verify_all.mjs（串行约 3-4 分钟）。
- .gitignore 排除 tools/verify_*：这 29 个回归脚本不随仓库走，若新机没有，先从旧机拷 tools/ 整目录，
  并把脚本头部的 playwright-core file:/// 路径与 Chromium executablePath 换成新机实际路径。
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
**S0 / S1 / S2 已完成**，全量回归 **17/17 套 PASS**。
**下一步 = S3「分集独立成步」**。当前第 2 步的「按规则排分镜 →」是临时桥接，S4 才换成逐集闸门。

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
node tools/verify_all.mjs        # 17 套串行，约 3–4 分钟
node tools/verify_all.mjs assets # 只跑名字含 assets 的
```

`.gitignore` 有 `tools/verify_*`，**全部 29 个回归脚本不随仓库走**。换机后从旧机器拷整个 `tools/` 目录，并替换其中两处本机绝对路径（脚本头部）：

| 原值 | 改成 |
|---|---|
| `import { chromium } from "file:///C:/Users/Administrator/.workbuddy/binaries/node/workspace/node_modules/playwright-core/index.mjs";` | 新机上 playwright-core 的实际路径，或改用 `import { chromium } from "playwright-core";` |
| `executablePath: "C:/Users/Administrator/AppData/Local/ms-playwright/chromium-1243/chrome-win64/chrome.exe"` | 新机 Chrome/Chromium 路径 |

Python 侧脚本（`verify_platform.py` 等）同样检查一次 playwright 路径。脚本默认**有窗口模式** `headless: false`，截图落 `screenshots/`。
`tools/baseline-*.txt` 三份基线报告**已提交**，可作为对照物。

---

## 2. 四项已锁决策（不要再重新讨论）

| # | 决策 | 结论 |
|---|---|---|
| D1 | 分集 / 分镜由谁产出 | 两个**独立 AI 步骤 + 人工闸门**；复用已有 `/api/ai/plan`、`/api/ai/storyboard`，不新建接口 |
| D2 | 上游改了下游怎么办 | **整步作废 + 显式重跑**（不做按场增量）；但 `sceneStableKey` / `shotKeyOf` 已在 S1 埋进数据，将来做增量不必迁移历史存档 |
| D3 | 分镜与定妆顺序 | **翻转**：先分镜后定妆；`S.step` 3=分镜、4=定妆 |
| D4 | 分镜粒度 | **只有单集闸门**，第一版不给「剩余全部」按钮——否则一键换名字复活 |

**已知且已接受的缺陷**：重算会覆盖手改的镜头文字与镜号。缓解是重跑前二次确认并列出「将影响 N 个镜头、其中 M 个改过」。

---

## 3. 阶段进度

| 阶段 | 状态 | 关键产出 |
|---|---|---|
| S0 冻结基线 | ✅ | `tools/baseline-2026-11-09.txt` 16/16；`baseline-step-audit-2026-11-09.txt`（30 脚本 16 命中 110 行） |
| S1 契约与稳定键 | ✅ | `engine.js` 4 个导出、`studio.js` 的 `S.steps` 状态机、`verify_step_keys.mjs` 18/18 |
| S2 移除一键 + 顺序翻转 | ✅ | 删 `#one-click` / `oneClick()` / `#flow-stages`；`App.vue` view-3/4 对调；`stepV` 存档迁移；`verify_no_oneclick.mjs` 16/16 |
| **S3 分集独立成步** | ⬜ **下一步** | 见 §4 |
| S4 分镜逐集闸门 | ⬜ | 核心，`storyboard()` 本来按集切片 |
| S5 定妆消费分镜 | ⬜ | 分组视图才有数据 |
| S6 出片归位（可选） | ⬜ | frames 挪到第 4 步末尾，不做就在 README 写已知限制 |
| S7 收尾 | ⬜ | 休眠流水线注释、README、套件登记 |

**依赖严格串行**：S2 定死步骤号 → S3 定死集号 → S4 依赖集号 → S5 依赖镜头。不许跳步。
**门槛规则**：本阶段新增脚本全绿才进下一阶段；旧脚本因步骤号变红必须**同阶段内修完，不许挂账**。

### S2 实测结果（对照用）

`tools/baseline-s2-2026-11-09.txt`：**17/17 套 PASS**（3m34s）。
细项：stage_split 22/22、shot_group 16/16、platform 43/43、linear_ui 19/19、projects 30/30、no_oneclick 16/16、资产逻辑 69/69、清场护栏 15/15。`npm run build` 通过，产物里已无 `one-click`。

---

## 4. S3 执行清单（可直接照做）

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
| `tools/verify_*`（29 个脚本） | `.gitignore` 明确排除「硬编码本机路径」 | 拷 `tools/` 整目录 + 按 §1 改两处路径 |
| `llm-config.bat` / `llm-providers.json` / `.env*` | **含真实 API Key，禁止提交** | 在新机按 README 第 49 行说明重建；万相 key 走这里 |
| `projects/`（29 个真实项目） | 本机运行数据 | 不迁移也能开发；要测旧存档迁移就拷几个 `project.json` |
| `dist/` | 构建产物 | `npm run build` 重新生成 |
| `examples/assets/`（71M 测试图） | 运行时出图产物、体积过大 | 不提交；新机跑出图时自动生成 |
| `screenshots/`、`.tts/`、`.workbuddy/` | 运行/个人数据 | 忽略 |
| `MIGRATION.md` | 含本机绝对路径的运维记录 | 忽略 |
| `~/.ssh/id_ed25519_github` | 本机 GitHub 专用私钥，禁止外传 | 新机另生成一对，把公钥加到 GitHub 账号 |

---

## 7. 分支与提交状态

- 本地分支 **`dev`**（从 `main@bf5e410` 新建），含 S0/S1/S2 全部代码改动、`README.md` 同步、`docs/` 两份文档、三份 `tools/baseline-*.txt`。
- **✅ 已推送到 `github.com:kevinzgai/ShortPlay-Studio.git`**（2026-11-09）：`dev` → `7e3ca80`、`main` → `bf5e410`；`dev` 已设 upstream 跟踪 `origin/dev`。用 `git ls-remote --heads origin` 可自行核对。
- `origin` 使用 **SSH**：`git@github.com:kevinzgai/ShortPlay-Studio.git`。本机 `~/.ssh/config` 的 `Host github.com` 段指向专用密钥 `~/.ssh/id_ed25519_github`（`IdentitiesOnly yes`）。
- **坑**：本机原有的 `~/.ssh/id_rsa` 是绑定 `wd-hub` 仓库的 Deploy Key，`ssh -T git@github.com` 会显示 `Hi kevinzgai/wd-hub!` 看似认证成功，但推这个仓库报 `Permission ... denied to deploy key`。GitHub 不允许同一把 deploy key 复用到别的仓库，别再拿旧密钥试。
- 新机 clone 用 HTTPS 即可（免凭证）；要 push 就配自己的 SSH 公钥，或改用 HTTPS + PAT。

### 离线兜底：桌面交接包（仍保留，非必需）

`Desktop/ShortPlay-dev-handoff/` 内有 3 个 patch + 1 个 bundle（含完整 dev 历史，`git bundle verify` 通过）。只有在不方便联网、想完全离线迁移时才需要：

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

- S2 刻意偏离计划两处：① `planOnly()` 仍在（S3 才拆）；② `doGenerate()` 降级为离线规则而非彻底禁用（否则 S2→S4 之间排不出镜头、5 个脚本失去可测路径）。
- D2 的「重跑覆盖手工修改」尚未解决，靠二次确认缓解；真正合并要等按场增量（键已埋好）。
- S6 不做的话，第 3 步看到的提示词可能缺资产描述，需在 README「已知限制」写明。
- 本地规范化依赖空行补场号；PDF 导入不支持。
- `verify_parse_progress.mjs` / `verify_parse_resume.mjs` 不在 SUITES 内，S2 后是死脚本，S4 一并处置。
