# 分镜平台相关资料（reference/）

> 这里放**不参与运行**的资料：参考源码、方法论、提示词范文、外部链路脚本、开发沿革。
> 项目本身的代码在上一级（`frontend/` `server.py` `tools/` `agents/`），别把两者搞混。
>
> 一句话区分：**`reference/` 改坏了不影响程序跑；`frontend/`+`server.py` 才是程序。**
>
> **开源版说明**：`01-参考项目/`、`03-提示词范文/script-writing-studio/`、
> `04-ComfyUI链路/comfyui-h3-demo/`、`05-外部工具链/` 这四处第三方整包源码
> 未随本仓库发布（许可证、署名与体积原因），仅保留在本地开发副本中。
> 下文描述的是本地完整目录结构，开源仓库中相应目录为空。

---

## 为什么要有这个目录

这些资料原先散在三处：本工作区的 `_ref/`、`.tmp-research/`、`.workbuddy/skills/`，
以及邻接工作区的 `scripts/`、`comfyui-h3-demo/`、`toonflow/`。
换机器、清缓存、或者半年后回看这个项目，那些路径基本都失效了。
所以统一收进项目内，**跟着项目一起走**。

---

## 目录结构与用途

```
reference/
├─ README.md                          ← 你在这里（总索引）
├─ 00-项目沿革/
│  └─ 2026-11-06.md ~ 2026-11-09.md   开发日志：每天做了什么、踩了什么坑、为什么这么定
├─ 01-参考项目/
│  └─ huobao-drama-master/            GitHub 同类项目全量源码（只读参考，许可证有坑，见下）
├─ 02-分镜方法论/
│  └─ novel-storyboard/               「段→分镜→分镜图」三层结构 + 18 道质量门的方法论稿
├─ 03-提示词范文/
│  ├─ script-writing-studio/          剧本创作 skill（含 40+ 分阶段参考文档，已注入本项目）
│  └─ 麻衣鬼相-角色三视图与场景概念图提示词.md   三视图/概念图的提示词范本（设计文档的参考源）
├─ 04-ComfyUI链路/
│  ├─ comfyui-h3-demo/                本机视频工作台源码：T2V/I2V/首尾帧/SeedVR2 放大
│  ├─ scripts/                        ComfyUI 直连脚本：工作流转 API、Flux 验证、H3 提交、探针
│  └─ (workflow-audit 在 scripts/workflow-audit)   工作流节点快照，改工作流前对照用
├─ 05-外部工具链/
│  └─ Toonflow-app-master/            无限画布式同类工具（源码，已剔除 data/ 与依赖）
└─ 06-设计原型/
   └─ README.md                       指向 docs/archive/ui-versions/（唯一真源，此处不放副本）
```

---

## 各目录详解

### 00-项目沿革 —— 先读这个

4 份按天记的开发日志，共 136KB。里面是**决策理由**，不是 API 文档：

- 为什么道具图会画出人、怎么定位到的（提示词 A/B 实证过程）
- 为什么「未注明」会顶掉真实地点（三环叠加根因）
- 哪些坑踩过一次就别再踩（行尾 CRLF 要按文件探测、Playwright 遇到 SSE 不能用 `networkidle`）

**接手或回看项目，先花 10 分钟扫这 4 个文件，比读 README 快。**

### 01-参考项目 —— huobao-drama

- 来源：`github.com/chatfire-AI/huobao-drama`，17K ★，TS + Vue
- **许可证：CC BY-NC-SA 4.0 —— 禁止商用**。只能读思路，代码一行都不能搬进商用产品
- 值得看的地方：`backend/` 的资产一致性做法、`frontend/` 的 Vue 组件分层
- 我们的差异（别丢掉的优势）见 `docs/github-参考项目.md` 末尾

### 02-分镜方法论 —— novel-storyboard

- 三层结构：**段**（一次视频生成，≤15s）→ **分镜**（段内 2–5s 剪切）→ **分镜图**（每切一张关键帧）
- 核心是 `schema.md`（storyboard.json 结构）和 `frame.md`（提示词与挂图合同）
- `SKILL.md` 里的 18 道质量门是确定性脚本检查，可借鉴到我们的 `verify_*.mjs`
- 我们的段/镜划分逻辑在 `frontend/src/lib/engine.js`，可对照着看差异

### 03-提示词范文

**script-writing-studio/**（993KB，已作为项目级 skill 注入）
- `SKILL.md` 入口 + `references/` 40+ 篇分阶段文档：剧本创作 → 台词诊断 → 分镜制作 → 提示词转换
- 重点看 `04-core-workflow.md`（分镜核心工作流，87KB 最详细）和 `06-seedance2-adapter.md`（提示词适配）
- 注意：这是**项目级** skill，只影响本工作区会话

**麻衣鬼相-角色三视图与场景概念图提示词.md**
- 三视图 + 概念图的完整提示词写法，是我们 `agents/prompts/assets.md` 的参考源
- `docs/资产与分镜自动分解-系统设计.md` 第 5 行引用的就是它（原先指向外部绝对路径，现已改指这里）

### 04-ComfyUI链路

**comfyui-h3-demo/**（1.5MB，已排除 node_modules / .venv / outputs / gateway_files）
- 本机视频工作台：文生视频 / 图生视频 / 首尾帧 / 修复放大
- `gateway/` 是 FastAPI 服务，`frontend/` 是 Vite 前端，`DESIGN.md` 说明设计取舍
- 关键约束：H3 与 SeedVR2 抢显存，必须串行；切模型有 40–90s 加载期

**scripts/**（ComfyUI 直连）
| 文件 | 用途 |
| --- | --- |
| `convert_comfy.py` | UI 格式工作流（含 subgraph）→ `/prompt` API 格式 |
| `gen_flux_test.py` | 直连 API 跑 Flux.1-schnell，验证模型齐全 |
| `h3_t2v_test.py` / `h3_i2v_api.json` | H3 文生视频测试与 API 请求体样例 |
| `toonflow_comfy_test.py` | 对照 Toonflow 的 provider 结构验证 ComfyUI 可用性 |
| `probe_loadinfo.py` / `probe_origins.py` | 浏览器内探针：CORS / loadInfo 是否被拦 |
| `mcp_call.py` / `check_canvas.py` | MCP 调用封装、画布节点参数检查 |
| `workflow-audit/` | 工作流节点的 args/edges 快照，改工作流前先对照 |

项目主程序走的是 `server.py` 里的 `comfy_*` 函数（默认 `SHORTPLAY_COMFY=http://127.0.0.1:8188`），
这里的脚本是**排查和验证用的旁路工具**，不参与主流程。

### 05-外部工具链 —— Toonflow

- 无限画布范式的同类工具，21K ★，TypeScript
- 已剔除 `data/`（含 ffmpeg 二进制与运行时视频，2.5G）和所有依赖，只留源码与文档
- 价值：**剧本→分镜的数据结构**和资产管理思路，不是 UI
- 我们的判断：搬它的画布范式会丢掉「双击 start.bat 就能跑」的轻量优势

### 06-设计原型

**故意不放文件。** 5 版 UI 原型（Linear/Figma/Runway/Notion/Pinterest）的唯一真源是
`docs/archive/ui-versions/`，因为 `tools/verify_index_linear.mjs` 直接测那个路径。
放副本会导致「测旧版、看新版」。

---

## 迁移说明

本目录由多个工作区的资料归集而成。原始位置、迁移命令与本机路径属内部运维记录，
未包含在开源仓库中。

---

## 阅读路线建议

| 你的目的 | 读这些 |
| --- | --- |
| 接手项目 / 理解为什么这么设计 | `00-项目沿革/` → 根目录 `README.md` |
| 改提示词、出图效果不对 | `03-提示词范文/` → `agents/prompts/assets.md` → `server.py` 的 `style_for_kind` |
| 加分镜规则 / 改编排逻辑 | `02-分镜方法论/` → `frontend/src/lib/engine.js` |
| 接本地 ComfyUI 出图 | `04-ComfyUI链路/` → `server.py` 的 `comfy_*` 段 |
| 找 UI 风格参考 | `06-设计原型/README.md` → `docs/archive/ui-versions/` |
| 想知道踩过哪些坑 | `00-项目沿革/` 每篇末尾的「坑」段 |

---

## 维护约定

1. **reference/ 不参与构建**，加进来不会影响 `npm run build` 或 `python server.py`
2. **别在这里建代码副本**（尤其 `docs/archive/ui-versions/`），要引用就写路径
3. 新增资料按现有编号续排，或放进对应目录并在本文件补一行说明
4. 大文件（>50MB）进来前先问一句：是不是运行时产物？是就别进
