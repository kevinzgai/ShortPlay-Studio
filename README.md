# 分镜工场 · ShortPlay Studio

面向非专业用户的傻瓜式短剧分镜平台：**导入剧本 → AI 自动分集 → AI 批量拆镜 → 预览 / 改 / 排 / 导出**。
最少输入、默认配置已经配好。剧本与密钥都只留在本机（AI 调用只把剧本文字发给你自己配置的模型端点）。

前端是 **Vue 3 + Vite 工程**，后端是 **Python 标准库**写的小服务（静态托管 + 模型转发 + 结果校验）。

> 分镜平台相关资料集中在 [`reference/`](reference/README.md)。

---

## 一、启动

**双击 `start.bat`（Windows）** —— 脚本会：首次自动 `npm install` → 每次自动 `npm run build` → 启动本机服务并打开 `http://127.0.0.1:8177/`。

运行时不需要 Node；Node 只在构建前端时用一次（`start.bat` 已经替你做了）。服务端只用 Python 标准库，无需 pip 安装。端口可用 `SHORTPLAY_PORT` 改，8177 与 ComfyUI 网关（8000 / 8188）不冲突。

> 工程化后不再支持双击 `index.html` 的 `file://` 纯离线路径：Vue SFC 需要构建产物，请统一走 `start.bat`。
> 想对比规则引擎与 AI 的结果，访问 `http://127.0.0.1:8177/?ai=0`：强制离线规则引擎 + 不分集，且**不发任何模型请求**。

开发模式（改前端热更新）：

```bat
py server.py --no-browser          :: 先起 8177，提供 /api/*
npm run dev --prefix frontend      :: 再起 5173，Vite 自动代理 /api 到 8177
```

### AI 模式配置

`start.bat` 会自动加载同目录的 `llm-config.bat`。首次使用请把 `llm-config.example.bat` 复制为 `llm-config.bat` 并填入你自己的 Key；不配置也能用，会自动回退内置离线规则引擎。

换模型 / 换服务商：编辑 `llm-config.bat`（格式参见 `llm-config.example.bat`），任何兼容 OpenAI `/chat/completions` 的端点都行：

```bat
set "SHORTPLAY_LLM_BASE_URL=https://api.deepseek.com"
set "SHORTPLAY_LLM_API_KEY=sk-..."
set "SHORTPLAY_LLM_MODEL=deepseek-flash"
set "SHORTPLAY_LLM_MAX_TOKENS=16384"
```

> `llm-config.bat` 含私钥，已写进 `.gitignore`，**不要提交或分享**。密钥只在 `server.py` 进程内使用，不会写进网页、日志或导出文件。

### 多模型接入（可存多条，界面里切换）

不想改 bat、或者要同时留几个服务商时，走界面：**⚙ 生成设置 → 语言模型**。这里能编辑显示名称、接口地址、密钥、模型名、最大输出 tokens，并有「测试连接」——它会真的发一次 `chat/completions`，返回 `✓ 连通 2.1s · 模型回了「通了」` 才算配好。

- 配置存在 `llm-providers.json`（含密钥，已 gitignore），**不是** `llm-config.bat` 的替代，而是叠加：
  读取优先级 = 列表里「使用中」且填了 Key 的那条 → 环境变量 / `llm-config.bat`（老用户零迁移）。
- 首次启动会自动把 bat 里那套配置落成一条记录，所以打开设置就能直接改，不用手写 JSON。
- 切换模型只影响后续请求；重新打开页面会记住「使用中」那条。
- 密钥接口一律只返回掩码（形如 `abcd-***wxyz`），完整 Key 只存本机，不会经过前端。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/llm/providers` | 列表 + 当前生效 + 掩码 Key |
| POST | `/api/llm/providers/save` | 新增 / 编辑一条；`apiKey` 不传表示沿用旧 Key，`activate` 可顺便切换 |
| POST | `/api/llm/providers/activate` | 切换当前使用的模型 |
| POST | `/api/llm/providers/delete` | 删除一条（不影响服务端） |
| POST | `/api/llm/test` | 真发一次最小请求验证「地址 + Key + 模型名」三件都对 |

> 本机额外接了一条 `http://127.0.0.1:18900/v1` · `trae/DeepSeek-V4-Flash`（Trae 网关），与原来的 DeepSeek 并存；默认仍是 DeepSeek，想换在设置里点「设为当前」即可。

**关于 `deepseek-flash`（推理模型）**

| 现象 | 原因 | 已做的处理 |
| --- | --- | --- |
| 小 `max_tokens` 时返回空内容 | 推理 token 先吃掉额度，`content` 被截成空 | 默认 `max_tokens=16384`；额度耗尽时给中文提示而不是空表 |
| 偶发 JSON 不合法 | 推理模型输出比 `deepseek-chat` 更容易带 `,,`、尾逗号、字符串内裸换行 | `repair_json()` 本地修复 → 仍旧失败则追加一次「只要合法 JSON」的重试 |
| 单集耗时 30–50s（`deepseek-chat` 约 7s） | 每次都要先思考 | 前端进度条分段显示；接口超时放宽到 180s / 240s |
| `finish_reason=length` | 输出被截断 | 直接抛中文错误，提示加大 `SHORTPLAY_LLM_MAX_TOKENS` |

> 该端点的 `/models` 只列 `deepseek-flash`、`deepseek-v4-pro` 两个名字；`deepseek-chat` 虽然是**别名**（请求体回退为 `deepseek-flash`）但仍能正常路由，可作为非推理备选。

### AI 到底做了什么

| 阶段 | 模型负责 | 程序负责 |
| --- | --- | --- |
| **自动分集** `/api/ai/plan` | 读全剧，决定切几集、每集标题 / 梗概 / 集尾钩子 / 场次范围 | 校验场次连续、不重叠、全覆盖、不拆散一场；限制 1–6 集 |
| **逐集分镜** `/api/ai/storyboard` | 按剧本行顺序给出每一镜的画面、景别、时长、台词、备注、**9 项分镜描述卡**与 `refs` 引用 | 景别白名单、时长 2–10 秒、场次越界纠正、去重、台词比对、**逐条覆盖核对 / 漏项自动补镜 / 建立收束反套话** |
| **资产分解** `/api/ai/assets` | 从剧本 / 小说提取角色、场景、道具，给出「3 个怪特征 + 1 个服装记忆点」与固定关键词串 | 编号、别名归并、锚点唯一性、场次覆盖、推断项溯源校验；三视图 / 概念图长提示词由模板渲染 |
| **起始帧提示词** `/api/ai/frames` | — | 纯代码拼装：分镜卡 + 资产关键词串 + 场景锚点 → 每镜第 0 帧提示词（中文 / 英文双版） |
| **编排落表** | — | 集号、镜号 `E01-001`、场景标签、来源标记、撤销栈、导出 |

硬性约束写进系统提示：**台词逐字一致，不新增剧本里没有的人物 / 地点 / 事件 / 道具 / 结局**。**降级策略**：没配 Key、断网、超时、模型返回非 JSON → 回退内置规则引擎；某一集失败 → 只补该集，其余保留 AI 结果，状态条写明是哪几集。任何情况下都不会留下空表。

### 剧本 → 资产包 → 分镜起始帧（新增）

两个新接口，模型只输出结构 JSON，长提示词一律由服务端模板拼装（沿用 `adapt` 的教训：让模型重写长文本会触发截断）：

| 接口 | 输入 | 输出 |
|---|---|---|
| `POST /api/ai/assets` | `script` + `scenes` | 角色 / 场景 / 道具资产包，含 3 锚点、固定关键词串、三视图与概念图提示词、覆盖校验与 `source/evidence` 溯源 |
| `POST /api/ai/frames` | `shots` + `pack` | 每镜起始帧提示词（中文给豆包 / 即梦、英文给本地 Flux）、引用资产编号、`firstFrameUrl` 占位 |

一次性跑通全流程：

```bat
py tools/gen_assets_demo.py                    :: 真模型 → 资产包 / 提示词 / 77 镜起始帧提示词
py tools/gen_first_frame.py --indices 0,40    :: 本地 ComfyUI Flux 出起始帧图
```

本机实测：17.4s 出 8 角色 / 7 场景 / 8 道具、9 场全覆盖、0 warning、77 镜起始帧；Flux 两张 9:16 竖版各约 6–10s。产物见 `examples/guihun-assets.json`、`guihun-asset-prompts.md`、`guihun-first-frames.*`、`first-frames/`。

> 坑：判定「出场角色」只认 `visual / dialogue / speaker`，**不要用分镜描述卡或备注** —— `sizeReason` 写「让娶鬼媳妇这件事有落点」会把没出场的角色误召回起始帧。场景资产要按「视觉可区分」拆，别只按地点名去重。
> 边界：纯 Flux 文生图跨镜头会变脸，景别也不保证精确；要一致性得接 InstantID / PuLID 或三视图参考图。H3 `i2v` 只吃一张首帧图，起始帧图正好填 `firstFrameUrl`。前端 UI 尚未接线，当前由脚本 / 接口使用。

---

## 二、三步走

**第 1 步 · 导入剧本**：粘贴、上传 `.txt` / `.md`、拖拽，或点「载入完整示例剧本」。实时显示识别到几场、几角色、几句对白。折叠的「生成设置」已配好默认值；AI 模式下可切「自动判断 / 不分集 / 固定 2–4 集」，也能一键关掉 AI 回到规则引擎。

**第 2 步 · 拆解 + 体检 + 分集**：列出场次、角色、场景、对白、动作；AI 同步给出**分集方案卡**。体检卡逐条列出缺地点 / 缺内外景 / 场号重复 / 角色名不统一等，每条给补全入口。补全会**写回剧本文本**（插入 `【地点：…】` 这类标记），界面、剧本、导出结果永远一致且可撤销。场景地点必须由人确认，不会自动脑补。

**第 3 步 · 逐集分镜表**：每镜含 **镜号 `E01-001` / 画面描述 / 景别 / 时长 / 台词 / 备注**，AI 镜头带 `AI` 徽标；点「分镜卡 n/9」展开 **AI 分镜描述卡**（主体 / 动作 / 构图 / 景别依据 / 运镜 / 光线 / 情绪 / 声音 / 剪辑衔接），逐项可改、可撤销。服务端因漏项自动补齐的镜头带「补」标记。顶部状态条显示模型名、集数、降级与待核对提示；分集筛选条可切「全部 / 单集」。点文字直接改，拖 `⠿` 或点 ↑↓ 排序，勾选多条可批量删除或重生成。右侧是取景示意预览 + **这一镜的最终提示词**。

### 角色与场景资产（全片一致性的锚点）

第 2 步多了一张「角色与场景设定」卡，第 3 步顶部可折叠展开同一张卡。机制：

| 能力 | 说明 |
| --- | --- |
| **自动抽取** | 从剧本括注里抽外观线索：`林晚（27岁，便利店店员）` → 年龄 / 身份；`陈默（30岁，外套湿透）` → 服装。**一句台词都没有、只在动作里出现的角色也会被识别**（保守地用「句读 + 人名 + 人类动作动词」匹配，宁缺毋滥），否则提示词里就没有他的外观 |
| **改一次，全片同步** | 资产是实体，分镜只存 `charIds / sceneId / propIds`，提示词在预览和导出时**现编译**。改角色外观不用逐镜改 |
| **参考图槽位** | 可给角色 / 场景挂一张参考图（**原图不压缩**，落盘到 `projects/<项目>/refs/`，项目里只存地址）。槽位编号 `character1 / character2 …`，**角色按出场顺序在前，场景顺延**，与 lumenx 的 `[characterN:name]` 契约一致 |
| **设定过期检测** | 资产签名（`assetSig`）一变，相关镜头打「设定已改」徽标 + 一键刷新。刷新只重算提示词，不动手改的画面描述 |
| **锁定** | 角色可锁定（重新解析剧本不覆盖其外观）；镜头可锁定（批量重生成跳过它） |
| **道具** | 手动加，画面描述里提到它名字就自动绑定，提示词里带一行「道具：…」 |

提示词编译顺序（每段先查重，避免「中景，中景」堆叠）：
`画面描述 → 光线 → 运镜 → 景别/构图 → 角色外观 → 场景 → 道具 → 情绪 → 台词口型 → 画幅`。
台词会额外编译成口型提示（`林晚张嘴说话，表情克制，台词：「…」`）——视频模型必须看到显式的「说话」才会生成嘴部动作。


### AI 补形象 & 本地 ComfyUI 批量出图

**剧本视觉风格**在资产面板顶部常驻一条，不依赖 AI 分解：7 个预设（写实电影 / 中式民俗恐怖 / 赛博霓虹 / 水墨国风 / 日系动画 / 黑白胶片 / 3D 渲染）一键填入「中文锚 + Flux 英文锚」，两串都能手改；点「跟随剧本」回到 AI 分解推断的风格，没分解时用中性默认（`写实电影质感 · 35mm 胶片颗粒 · 冷调 · 无滤镜磨皮`）——以前这里写死「中式民俗恐怖」，任何剧本都串味。风格改动进撤销栈、独立落本地存储，并自动重算已有起始帧提示词。

风格串有三条去处：中文锚 → 三视图 / 概念图 / 起始帧长提示词与 zip 里的 `assets.md`；英文锚 → `/api/comfy/generate` 的 `styleEn`，由 `build_comfy_prompt()` 放在主体描述之后、技术收尾词之前；`assetPack.style.anchorEn` → 导出 manifest。**Flux 只吃英文，中文锚传进去等于没传**。`COMFY_SUFFIX` 里写死的 `professional concept art` 已移除，否则所有剧本的资产图都长成一个概念美术味。另注意：ComfyUI 的 Flux 工作流没有负面提示词节点（`FluxGuidance=0` / `BasicGuider`），中文 `negative` 暂不作用于本地出图，别误以为它生效 —— 想要「不要人」这类约束，只能写进正向串。

风格锚会按资产类型收一遍（`style_for_kind()`）：角色保留 `natural skin texture` 这类人像词，道具 / 场景一律剔除（`skin / face / portrait / beauty / hair / hand …`），全被剔光就退到 `STYLE_ANCHOR_EN_OBJECT`。原因是道具图曾经集体长出人手 —— 通用风格锚里的 `natural skin texture` 被无条件拼到了静物后面。

资产卡头部多了 **「✦ AI 补形象」**：只把剧本里提到这个角色 / 场景的行（±2 行）发给模型，补脸型 / 瑕疵 / 服装记忆点 / 固定关键词串与**英文关键词**；手填过的非空字段保留，改动进撤销栈。

资产面板顶部是**本地出图工具条**（需本机 ComfyUI 跑在 `8188`）：选范围（当前资产 / P0 / 本栏全部）→ 勾素材类型（角色：三视图 / 面部四视图 / 定妆半身；场景：概念图 / 宽幕建立镜；道具：静物）→ 点「✦ 一键生成 N 张」。走 `Flux.1-schnell fp8`（4 步 / euler），单张 8–20 秒，进度条实时刷新，一次最多 12 张。出的图回挂到对应资产，第一张自动设为主参考图，原图落 `examples/assets/`。

**看大图**：点任意一张生成图进全屏预览（`←` `→` 切图、`Esc` 或点空白处关闭），可复制该张的英文 Flux 提示词、下载原图、直接设为主参考图。预览读的是落盘**原图**，不是 512px 缩略 dataURI —— 缩略图只用于卡片显示，分辨率不跟着涨，否则 `localStorage` 会被撑爆。卡片按每张图的真实画幅铺开，不再统一裁成 4:3：三视图 1024×672（3:2）、定妆 768×1024（3:4）、概念图 1152×640（16:9）、宽幕 1216×512（2.375:1）、静物 896×896。

**一键复制提示词**：角色 / 场景 / 道具三类都有，三个入口——

- 详情头部 `⧉ 复制提示词`：这个资产的全部提示词。**只有一条时给原文**（可直接贴进出图工具），多条才加 `【小标题】` 分段（贴文档 / 发给协作者）
- 头部 `EN`：只复制英文串，专给 Flux / Midjourney / 即梦。**只在有英文时出现**
- 列表行悬停的 `⧉`：不用点进详情，整行直接复制；键盘聚焦也会露出
- 列表底部 `⧉ 全部复制`：本栏所有资产拼成一份文本，每条带 `◆ 名称（编号）` 与 `———` 分隔

复制内容按类型取：角色 = 三视图 / 面部四视图 / 固定关键词串 / `keywordEn`；场景 = 概念图 / 宽幕版 / `sceneEn`；**道具没有预生成提示词**，用「名称：描述（出现在 谁的画面里）」拼一句（后端 `props_out` 的 `appearance` 由 AI 产出，缺省才等于名称），并在详情里以「道具提示词」区块给出。道具现在也有英文主体 `propEn`（AI 分解 / AI 补形象产出），出图时优先用它，缺了才退回 `inanimate prop object + 中文名` 并在界面标「缺英文关键词」。

> 这里的 `EN` 很关键：`keywordEn` / `sceneEn` 一直存在，但此前只写进 ComfyUI 请求，界面上既看不见也拿不出来 —— 想拿同一套词去即梦 / MJ 出图只能手抄。

| 接口 | 作用 |
|---|---|
| `POST /api/ai/asset-fill` | 单项形象补全，不重跑整剧本分解 |
| `GET /api/comfy/status` | 探测 ComfyUI / 模型 / 变体表 |
| `POST /api/comfy/generate` | 提交批量任务（可带 `styleEn` 剧本风格英文锚），秒回 `jobId` |
| `GET /api/comfy/job?id=…[&full=1]` | 轮询进度 / 取回缩略图 |
| `GET /api/comfy/image?f=…` | 查看落盘原图 |
| `GET /api/projects` | 项目列表（只回摘要：名称 / 更新时间 / 集数镜数资产数 / 生成图数） |
| `GET /api/projects/get?id=…` | 取整份项目（含剧本、分镜、资产与图片 dataURI） |
| `POST /api/projects/save` | 写回整份项目，原子替换 `projects/<id>/project.json` |
| `POST /api/projects/create` | 新建项目，返回 `project`（含空 data） |
| `POST /api/projects/rename` | 只改项目名 |
| `POST /api/projects/duplicate` | 连内容一起复制一份 |
| `POST /api/projects/delete` | 移到 `projects/.trash/`，不真删 |

> 坑一：Flux 只吃英文。**规则引擎抽出的资产没有 `keywordEn`**，界面会打 `!` 并用中文兜底，画面会打折 —— 先「AI 分解资产」或「✦ AI 补形象」再出图。
> 坑二：多张图必须走「提交即返回 + 后台串行 + 前端轮询」，塞在一个 HTTP 请求里等必然超时。
> 坑三：Pillow 只作可选缩略图压缩；服务以某些方式启动时 user site 没进 `sys.path`，`thumb_datauri()` 会显式补一次，仍失败则回传原 PNG 并在界面提示体积偏大。
> 坑四：**某个画幅第一次出图会特别慢**（实测 1024×672 首张 145s、第二张同尺寸 10.9s），是 PyTorch/cuDNN 对新 tensor shape 做一次 kernel autotune，不是卡死也不是分辨率太高。换了尺寸后第一张耐心等，别据此回调画幅。
> 坑五：改了 `server.py` 要重启 8177 才生效；`Stop-Process` 只按端口杀容易留下旧进程继续抢请求（本机 Windows 允许同端口复用），按命令行匹配 `*shortplay-studio*server.py*` 全杀再起。

> 坑六：**道具图里出现人手 / 人像**，是三个条件叠出来的：通用风格锚带 `natural skin texture`、道具没有英文主体（中文名被 T5 忽略）、道具模板漏写 `no people`。修法是分层风格锚 + `propEn` + 静物模板（`still life of a single … no people, no human figure, no hands, no face`），四者缺一都还会复发。同 seed 只换提示词的对照图见 `screenshots/prop_ab_cur.png`（坏）/ `prop_fix_coins_771.png`（好）。

### 剧本怎么写（混用也行）

```
《片名》
第1场 外景 · 便利店门口 · 夜
雨下得很急，霓虹招牌在水洼里碎成一片。      ← 无冒号叙述 = 动作 / 画面描述
△ 一辆黑色轿车停在路边，没有熄火。           ← △ 开头也识别为动作
林晚：又是一整夜的雨。                     ← 角色：台词
陈默（压低声音）：你不是第一次来这儿。        ← 括号里是舞台提示
【地点：便利店门口】【时间：夜】【内外景：内景】  ← 补全按钮自动写
【角色别名：明=小明】                      ← 合并同一角色的不同写法
```

也支持 `场景1`、`1. INT. 咖啡馆 - 日`、`【场景：…】`、`地点：… / 时间：…` 独立行。完全没有场次标记的纯文本按单场处理并给出提示。

---

## 三、交互与安全

- **状态反馈**：空剧本不能进下一步；AI 生成时遮罩显示「规划分集 → 正在生成第 N / M 集」，`aiBusy` 拦同步连点（连点 3 次只发 1 次请求）；失败给中文原因 + 保留结果 + 可重试。
- **误操作可撤销**：AI 生成、删除、插入、排序、批量重生成、补全、改配置、载入示例全部进入统一撤销栈（最多 60 步）。`Ctrl+Z` / `Ctrl+Shift+Z` / `Ctrl+Y`。
- **手动修改受保护**：重生成默认保留手改字段，改过标「已手改」。
- **一致性护栏**：剧本或设置改动后，第 3 步提示「下面的分镜还是按旧剧本/旧设置排的」并给重排按钮。
- **项目管理**：一个项目 = 一部剧的全套内容（剧本 / 分集 / 分镜 / 资产 / 资产包 / 起始帧 / 风格）。顶栏项目胶囊随时切换、新建、重命名、复制、删除；切换前自动落盘。
- **自动保存到磁盘**：改完 0.8 秒自动写入 `projects/<项目 id>/project.json`（原子替换），刷新、关浏览器、重启服务都回到上次打开的项目与步骤；关页瞬间的改动走 `sendBeacon` 补一次。浏览器只留一份缓存用于首屏秒开与断网兜底，不再受 `localStorage` 5MB 限制。

导出 5 种：CSV（带 BOM）、Markdown、TXT 拍摄清单、完整 JSON、视频提示词 JSON。CSV 多「出场角色」列、9 列分镜描述卡与「自动补镜」列，Markdown 增角色设定表 + 「出场角色」列，TXT 逐项列出角色与分镜卡；三者与完整 JSON 保持同一份数据。分集模式下 CSV 多「集」列，Markdown / TXT 按集分组。

**视频提示词 JSON 契约（`schema: "shortplay-v4"`）**：

```jsonc
{
  "schema": "shortplay-v4",
  "target": "comfyui-h3-demo POST /v1/videos",
  "contract": { "modes": ["t2v", "i2v", "fl2v"], "durations": ["5s", "8s", "10s"], "promptMaxLength": 4000 },
  "frame": { "quality": "standard", "aspect": "16:9", "width": 1024, "height": 576 },  // 宽高必为 32 倍数
  "preflight": { "t2v": 15, "i2v": 8, "durationSnapped": 13,
                 "scriptSeconds": 100, "outputSeconds": 118,
                 "cutChecks": [...],                                    // 镜头级校验（时长/台词/H3 禁名字）
                 "warnings": ["……成片 100 秒 → 118 秒"] },
  // 段 = 一次生成调用。不跨场、≤10s（对端 duration 上限）。段内每镜 [Shot k] 一行、带切点时刻。
  "segments": [{
    "seg": "01", "sceneNo": 1, "scene": "第1场 外景 · 便利店门口 · 夜",
    "shots": ["001", "002"], "seconds": 10, "duration": "10s",
    "mode": "i2v", "firstFrameUrl": "data:image/jpeg;…",
    "h3Prompt": "For the target video, at 0.00 seconds…\nintegrated_multimodal_description:\n[Shot 1] 一名便利店店员…\n[Shot 2] At 00:00:05.000, the camera cuts to…\noverall_soundscape: …\nnon_diegetic_music: N/A"
  }],
  "assets": { "characters": [...], "scenes": [...], "props": [...] },   // 槽位解析用
  "items": [{
    "shot": "E01-005",
    "mode": "i2v",         // 有首帧图 = i2v；没有 = t2v（不是 r2v，对端没有多参考图模式）
    "duration": "8s",      // 已吸附到 5s / 8s / 10s
    "scriptDuration": 7,   // 分镜表原时长，便于回查
    "width": 1024, "height": 576,
    "prompt": "……角色：林晚，27岁，便利店店员。……",                // 纯文本版（deepseek 等通用模型用）
    "taggedPrompt": "林晚[character1:林晚]……",                      // 认槽位的模型用
    "h3Shot": "一名便利店店员把伞架搬到门边……中景。",               // H3 正文：通用身份、禁画风
    "h3Prompt": "For the target video…[Shot 1] …",                  // 该镜单独作为一段的 H3 提示词
    "refs": [{ "slot": "character1", "kind": "character", "name": "林晚", "image": "", "role": "firstFrame" }],
    "cast": ["林晚"], "locked": false, "assetStale": false
  }]
}
```

槽位顺序 = 参考图顺序，一旦开始对接出片工具就是**外部契约**，不要再改。挂在角色 / 场景上的参考图会随 `refs[].image` 一起导出：老项目是 dataURL，新项目是 `projects/<id>/refs/` 下的原图（导出时由服务端读原文件塞进 zip）。

**为什么是 v4（分两步升级）**：

- **v3（之前）**修正了 v2 的 `mode: "r2v"` 假名码：对端只有 `t2v / i2v / fl2v`，`i2v` 吃一张首帧图；`duration` 只有 `5s / 8s / 10s`；宽高必须 32 倍数。
- **v4 新增「段」**：借鉴 `shuohao-skills/novel-storyboard` 的「段 = 一次 H3 生成」思想，把镜头按「不跨场 + ≤10s」分组成段，整段一条 `h3Prompt`，段内每镜 `[Shot k]` 一行带切点时刻。**23 镜 → 13 段**，省 43% 生成调用，段内天然连续。
- **v4 的 H3 正文遵守官方规范**（学自 `shuohao-skills/references/h3-prompt.md`）：**用通用身份替代角色名**（林晚 → 一名便利店店员）、**不写画风与画幅**（交给调用方参数）、**台词逐字进 `<d>[Chinese]…</d>` 块**、声音分三层（台词→正文、环境声→`soundscape`、配乐→`music`）。
- 镜头级校验进 `preflight.cutChecks`：每切时长在 2–10s、台词能否装进镜头（4 字/秒）、H3 正文是否残留角色名。


---

## 项目管理（Studio 式）

顶栏左侧胶囊显示当前项目，点开就是项目面板：新建 / 打开 / 重命名 / 复制 / 删除。左侧导航的「项目（N）」是同一入口。

**为什么要从 localStorage 搬到磁盘**：旧版把整份状态塞进 `localStorage` 一个 key。生成几张素材图（每张 40–60KB dataURI，还会同时写进 `refImage` 和 `genImages`）就会顶到 5MB 配额；`setItem` 抛错后保存静默失败，刷新页面读到的还是更早的一份数据，表现出来就是「项目没了」。现在项目正文写 `projects/<id>/project.json`，图片再多也不受浏览器配额约束；`localStorage` 只留一份缓存，用于首屏秒开和服务不可用时兜底。

**目录与写入**

```
projects/
├─ p_20261109_140532_2e46/
│  └─ project.json        # id / name / createdAt / updatedAt / schema / data{…}
└─ .trash/                # 删除的项目整目录挪进来，需要时手动捞回
```

- 写入是 `project.json.tmp` → `os.replace` 原子替换，断电或进程被杀不会留下半份项目；
- 单项目上限 64MB，超了接口明确报「项目太大，请先清掉一些生成图」；
- 列表接口只回摘要，不回正文，项目多了首屏也不拖慢。

**自动保存与恢复**

| 时机 | 行为 |
|---|---|
| 任意改动 | 800ms 防抖后写盘，状态条显示「保存中… / 已保存 · HH:MM」 |
| 切换 / 新建项目 | 先 `await` 当前项目落盘，再加载目标，避免把旧内容写进新项目 |
| 关页 / 切后台 | `beforeunload` + `visibilitychange` 走 `sendBeacon` 补一次，最后一秒的输入也不会丢 |
| 刷新 / 重开浏览器 | `projects` 列表 → 上次打开的 id（`shortplay-last-project`）→ 没有就接**最近更新**的项目；都没有才新建空项目 |
| 服务不可用 | 用浏览器缓存继续，状态条标「服务不可用 · 已用本机缓存」，不会白屏 |

**URL 参数**：`?project=<id>` 直接打开指定项目（可做书签）；`?fresh=1` 强制新建空项目（自动化测试用）；`?ai=0` 仍是离线规则引擎模式。

**旧存档迁移已下线**：早期版本会把 `shortplay-studio-v1` 自动迁成项目，这个一次性逻辑已经删掉（迁移早已完成，留着只是多一条写路径）。历史浏览器里残留的 `shortplay-studio-v1` / `.bak` 不会再被读，需要的话手动从 DevTools 里取。

### 参考图 / 生成图为什么不会丢

参考图（`refImage`）会跟着项目一起落盘 —— 上传时是**原图直接存到 `projects/<项目>/refs/`（内容哈希命名，不重编码、不缩尺寸）**，项目文件里只留一个 `/api/projects/ref?id=…&f=…` 地址；批量出图（`genImages`）仍是缩略 dataURI + 落盘原图（`/api/comfy/image`）。它们最容易在「刷新后重建资产」这一步被洗掉，现在有这几道保险：

1. **资产重建只有一份认领规则**：`prevIndex()` 建索引，`claimScene()` / `claimChar()` 统一按 `id` → `内外景+时间+名字` → **场次号** → 名字 兜底，并沿用旧 `id`；一条旧资产最多被认领一次（否则「老宅·日」「老宅·夜」会抢到同一张图）。AI 资产包常把场景名写成「乡下老宅外」，剧本解析出的是「乡下老宅」，只按 id / 名字认领必然对不上，一刷新参考图和手改的外观就全丢，紧接着的自动保存还会把这个「洗白」版本写回磁盘 —— 图就永久没了。
2. **重建不删有内容的资产**：`buildAssets` 只负责按剧本补骨架，凡是带过参考图 / 手改字段 / 锁定 / 提示词的旧资产一律保留。否则「奶奶」这种只在台词里被提到、剧本没给她单独场次的角色，一刷新就被静默清掉。
3. **图仓兜底**：`studio.js` 里按「资产 id + 名字」维护一份图片仓（读项目时灌入、上传 / 出图 / 设主图时登记、主动移除时注销）。每次 `projectData()` 落盘前先 `bankApply()`，凡是图仓里有图而当前资产为空的，自动补回来。**自动保存从此不可能把已经存在的图写没**。
4. **本机缓存也算一个来源**：首屏 `restoreCache()` 灌进图仓后，即使磁盘那份缺图（历史上被洗过），打开项目也会自动补回图，然后正常落盘。

**画质与内存的取舍**：落盘的是原图（`refs/<内容哈希>.<ext>`，单张上限 24MB，同一张图重复上传只留一份），界面上的 22px 列表缩略图和 320px 头像则向服务端要 `&w=64` / `&w=320` 的小图（Pillow 缩一次缓存在 `refs/.thumb/`，Pillow 缺失时自动退回原图）。这样既不为缩略图解码三千万像素白吃内存，也不会像以前那样把原图压成 512px 存死。换图 / 删资产留下的孤儿文件会在保存时按「无人引用且超过 1 小时」清掉；复制项目会把 `refs/` 一起拷走并把地址改指副本。

**边界**：两个标签页同时开同一个项目时是「最后写入者胜」，没有做冲突合并；生成过程中禁止切换项目（会把 AI 结果写串），其余操作不受影响。

---

## 四、前端工程结构

> 布局为 **linear.app 式三栏**：左侧 236px 工作流导航（`AppRail`，吸顶、步骤状态点）→ 主区（面包屑条 + 步骤内容）→ 右侧检查器（取景预览 / 生成设置，`clamp(300px,22vw,440px)`）。≤1180px 检查器落到内容下方，≤1024px 导航折成顶部横向条（单行、可横滑、隐藏滚动条），≤760px 再收成纯数字步骤。第 3 步切「表格」视图时检查器自动让位，7 列数据吃满整宽。

```
shortplay-studio/
├─ frontend/                       Vue 3 + Vite 工程（唯一前端真源）
│  ├─ index.html                   Vite 入口
│  ├─ vite.config.js              构建到 ../dist，dev 代理 /api → 8177
│  ├─ package.json                vue ^3.5 / vite ^5.4 / @vitejs/plugin-vue
│  └─ src/
│     ├─ main.js                  挂载 + boot()
│     ├─ App.vue                  三栏骨架 + 全局键盘/拖拽/编辑事件委托
│     ├─ assets/styles.css        设计系统 token（linear.app 深色原生 / 亮度阶梯 / 半透明边框）
│     ├─ lib/engine.js            剧本解析 / 体检 / 补全 / 分集 / 分镜 / 导出（ESM 纯函数）
│     ├─ lib/ai.js                AI 编排：分集 → 逐集分镜 → 归一化 → 降级（ESM）
│     ├─ lib/projects.js          项目库 API：list / get / create / save / rename / duplicate / delete
│     ├─ stores/studio.js         reactive 状态机：撤销栈 / 项目持久化 / 生成 / 编辑 / 导出
│     ├─ components/AppRail.vue   左侧工作流导航（步骤 / 工具 / 保存状态）
│     ├─ components/ProjectPanel.vue  项目面板（新建 / 打开 / 重命名 / 复制 / 删除）
│     ├─ assets/projects.css      顶栏项目胶囊 + 项目面板样式
│     └─ components/              TopBar(项目胶囊 + 面包屑) / StepOne / SettingsFields / StepTwo /
│                                EpisodePlan / AssetPanel / StepThree / ShotCard /
│                                ShotsTable / PreviewPanel / FeedbackLayer / AgentWorkbench
├─ projects/                      项目库（每个项目一个目录 + project.json，已 gitignore）
│  └─ .trash/                     删除的项目移到这里，不直接抹掉
├─ dist/                          npm run build 产物，server.py 托管它
├─ docs/archive/ui-versions/      5 版 UI 原型（历史留档，代码里 0 引用，已从根目录移走）
├─ reference/                     分镜平台相关资料（不参与运行，见 reference/README.md）
│  ├─ 00-项目沿革/                 按天记的开发日志：决策理由与踩过的坑，接手先读
│  ├─ 01-参考项目/                 huobao-drama 全量源码（CC BY-NC-SA，禁商用，只读参考）
│  ├─ 02-分镜方法论/               novel-storyboard：段→分镜→分镜图 + 18 道质量门
│  ├─ 03-提示词范文/               script-writing-studio skill + 三视图/概念图提示词范本
│  ├─ 04-ComfyUI链路/              comfyui-h3-demo 源码 + 直连脚本 + 工作流快照
│  ├─ 05-外部工具链/               Toonflow 源码（已剔除 data/ 与依赖）
│  └─ 06-设计原型/                 指向 docs/archive/ui-versions/（唯一真源）
├─ MIGRATION.md                   迁移记录：路径处理、合并策略、验证结果
├─ server.py                      标准库静态托管 + 3 个模型接口 + 结果校验
├─ start.bat                      一键启动（GBK，自动装依赖 + 构建 + 起服务）
├─ llm-config.bat                 本机模型配置（含密钥，已 gitignore）
├─ tools/gen_example.js           刷新离线示例（直接 import src/lib/engine.js）
├─ tools/gen_ai_example.js        真模型刷新 AI 示例（import src/lib/ai.js）
├─ tools/verify_platform.py       离线主流程回归 42 项
├─ tools/verify_ai.py             AI 主流程回归 32 项
├─ tools/verify_all.mjs           一键串行跑全部回归，输出汇总表（node tools/verify_all.mjs [关键字]）
├─ tools/verify_assets.mjs        资产层 + 提示词编译 + 出片端契约 + H3 提示词纯逻辑回归 69 项（node，无浏览器）
├─ tools/verify_asset_ui.py       资产层 + 导出契约 + H3 UI 回归 45 项（Playwright 有窗口）
└─ examples/                      示例剧本 + 两套批量分镜结果
```

**分层**：`lib/` 是浏览器与 Node 共用的纯逻辑（零 DOM），`stores/` 只管数据与流程（零 innerHTML），`components/` 只负责声明式渲染。改编排规则只动 `lib/engine.js`，改 AI 链路只动 `lib/ai.js` + `server.py`，改界面只动对应 `.vue`，彼此不耦合。

**DOM 契约**：所有 id / class / 文案与旧版保持一致，因此 `tools/verify_*.py` 两个点测脚本无需改动即可回归。

---

## 五、示例与验证

`examples/` 两套结果都由**与界面完全相同的链路**生成：

| 文件 | 内容 |
| --- | --- |
| `sample-script.txt` | 完整示例《雨夜便利店》：4 场 / 2 角色 / 8 句对白 / 13 条动作，体检 0 问题 |
| `sample-problem-script.txt` | 「待补全」示例：故意留了场号重复、角色名不统一、缺场景信息 |
| `sample-ai-storyboard.*` | 真·大模型产出的分集 + 逐集分镜（每次集数 / 镜数可能略有不同） |
| `sample-storyboard.*` | 离线规则引擎版：23 镜 / 约 100 秒，用于对比 |

重新生成：离线版 `node tools/gen_example.js`；AI 版先 `py server.py --no-browser`，再 `node tools/gen_ai_example.js`。

| 验证 | 覆盖 | 结果 |
| --- | --- | --- |
| `npm run build --prefix frontend` | Vue SFC 编译 / 产物输出 dist | 34 模块通过 |
| `tools/verify_platform.py` | 离线主流程（`?ai=0`）：导入 → 拆解 → 23 镜 → 编辑 → 删除撤销 → 排序 → 重生成 → 导出 → 体检补全 → 表格；**跑完只删本次创建的项目**，不会往项目库里堆「雨夜便利店」 | 42/42 |
| `tools/verify_ai.py` | 真模型：自动分集 → 逐集分镜 → 集筛选 → 编辑撤销 → 导出带集 → 连点拦截 → 断网降级 → 重试恢复 | 32/32 |
| `tools/verify_all.mjs` | **一键全跑**：上面这些套件串行执行（并发跑会互相改变项目数量，让「项目列表条数」类断言假失败），最后打一张通过汇总表；加关键字只跑匹配的，例 `node tools/verify_all.mjs assets` | — |
| `tools/verify_assets.mjs` | 资产层纯逻辑：括注抽外观 / 手改与锁定不被覆盖 / 说话人优先绑定 / 槽位编号 / 提示词去重 / 过期签名 / 出片端契约 / **H3 提示词（禁名、<d> 块、段分组）** | 69/69 |
| `tools/verify_asset_layout.mjs` | **资产清单密度**：行高 ≤36px / 左 264 右吃满 / 只渲染 1 个详情 / 点行切换 / 搜索过滤 / 定高不撑破 / 无横向溢出 | 13/13 |
| `tools/verify_assets_panel.mjs` | **资产包面板 + 整包导出**：空态引导 / 编号与优先级 / 三锚点 / 关键词串注入 / 覆盖率 / 提示词正文 / 参考图挂载 / ZIP 下载 / 无 JS 报错 | 12/12 |
| `tools/verify_projects.mjs` | **项目化管理**：首次建项目 / 改名跟随剧本 / 自动落盘 / 刷新恢复（项目、步骤、镜数）/ 新建与切换互不污染 / 重命名 / 删除后接续 / 复制副本 / 新浏览器接最近项目 / 1.2MB 生成图可落盘 | 30/30 |
| `tools/verify_ref_original.mjs` | **参考图原图不压缩**：传 2400×1600 PNG → 资产里只存服务端地址、`project.json` 仍是 4KB、落盘文件与源文件**逐字节相同**、浏览器按 2400×1600 解码、刷新后不变、ZIP 里带的是原图；老项目 dataURI 图片向后兼容 | 15/15 |
| `tools/verify_ref_upload.mjs` | **参考图落盘**：角色 / 场景上传 → 立刻刷新 → 磁盘与缩略图都还在；含「资产包项目（AI 分解过、场景名和剧本差一个字）」这一真实事故场景；场景数不被重建搞乱 | 11/11 |
| `tools/verify_linear_ui.mjs` | **Linear 深色三栏**：导航 236px / 面包屑 54px / h1 32px·510·−0.704px / cv01+ss03 / 卡片 #111214·12px / 表格表头 / 导出菜单 / Agent 工作台 / 1440 无溢出 / 全流程 21 镜 | 19/19 |
| `tools/verify_asset_ui.py` | 资产层界面：改外观进存储 / 挂参考图 / 道具 / 过期徽标与刷新 / 锁定跳过重生成 / 导出带 refs / H3 提示词 | 45/45 |

点测均为有窗口模式，截图落在 `screenshots/`。

## 资产包 · 从剧本自动分解到「能出图」

链路补齐成 8 段：**识别格式 → 忠实转写 → 剧本体检 → 资产分解 → 自动分集 → 逐集分镜 → 起始帧提示词 → 覆盖校验**。
`AI.run()` 在 `parse` 之后插 `POST /api/ai/assets`，失败只降级这一层（退回 `E.buildAssets()` 的规则结果），不影响分镜。

| 层 | 做什么 | 落点 |
| --- | --- | --- |
| 资产生产 | 剧本 / 小说全文 + 场次索引 → 结构 JSON（编号 C01/S01、P0/P1、三锚点、别名、溯源），服务端渲染三视图 / 四视图 / 概念图长提示词 | `server.py: build_asset_pack`、`TURNAROUND_TMPL` / `FACE_SHEET_TMPL` / `CONCEPT_TMPL` |
| 资产合并 | 资产包叠进界面资产层：**用户手改与锁定优先**，剧本里有但包漏掉的角色自动补位 | `engine.js: applyAssetPack` |
| 一致性注入 | 角色的 `keyword`（固定关键词串）在 `assemblePrompt()` 里原样注入，所有镜头一字不改 | `engine.js: appearanceText` |
| 起始帧 | 资产包 + 分镜表 → 每镜中英文起始帧提示词（`/api/ai/frames`，纯模板秒回） | `build_frame_prompts` |
| 体检 | `preflight` 新增 `assetBound` / `assetKeywordExpected` / `assetKeywordInjected` | `engine.js: h3Preflight` |

**资产包面板**（第 2 步）不是一张表，是配置台：**左侧 264px 密排清单**（一行 34px，22px 缩略图 + 编号 + P0 标 + 锁标，顶部带搜索）、**右侧编辑区**只渲染当前选中的那一个，面板定高、左右各自滚动。上方是覆盖率（角色/场次/AI 推断项/起始帧数）、风格锚、建议生成顺序、校验提示与 `只看 P0`；详情里是编号与来源标记（剧本原文绿 / AI 推断黄）、**三锚点**（面部 / 瑕疵 / 服装记忆点）、紫色关键词串一行（可改可复制）、默认展开的出图提示词、参考图与锁定。

**整包导出**：`POST /api/export/zip`（服务端零依赖 `zipfile`）。文本由前端渲染，资产正文与 README / manifest 由服务端渲染：

```
README.txt                      使用规矩（关键词串原样粘贴等 4 条）
manifest.json                   统计、覆盖率、警告、文件清单
script/原始剧本.txt
assets/assets.md                资产包正文：清单 / 锚点 / 三视图 / 概念图 / 参数 / 校验
assets/assets.csv               人工核对表（Excel 直开，带 BOM）
assets/asset-prompts.json       机器可读提示词，供批量出图脚本消费
assets/assets.json              完整资产包（含溯源字段，不含 base64 图片）
assets/refs/C01_林晚.jpg        已挂上的参考图（原图，单张上限 24MB）
storyboard/分镜表.csv|md|json    分镜表全套
storyboard/拍摄清单.txt
storyboard/视频提示词.json       含 preflight 预检
storyboard/起始帧提示词.md|json  每镜首帧提示词（中文给豆包/即梦，英文给本地 Flux）
```

入口只有一个：「导出 ▾ → 整包导出 · ZIP」（第 2 步页面右上、第 3 步工具栏都有这个菜单，同一份实现）。资产面板不再单独摆「打包下载」按钮。

## 六、功能收敛（2026-11-09）

同一件事只留一个入口、一份实现。改的是重复，不是能力：每个被合并的动作都还有 ≥1 个可达入口，`Ctrl+K` 命令面板兜底。

| 原来 | 现在 |
| --- | --- |
| 项目入口 2 个（顶栏胶囊 + 左栏按钮） | 只留顶栏胶囊；命令面板加「切换 / 管理项目」 |
| 设置入口 2 套（第 1 步内联 details + 弹窗） | 只留弹窗（左栏「生成设置」/ 命令面板） |
| 刷新 2 个并排按钮（刷新 N 镜提示词 / 重算起始帧） | 1 个按钮按状态变形：有镜头过期就刷提示词，否则重算起始帧 |
| 导出 3 处（分镜工具栏 / 资产面板「打包下载」/ 命令面板） | 1 个 `ExportMenu.vue`，挂在第 2、3 步，zip 是其中一项 |
| 复制提示词 6 个按钮 | 3 种语义：详情「复制提示词」/ `EN` / 单条「复制」（行内 ⧉、关键词 ⧉、灯箱复制都删了） |
| 资产重建两份查找规则 | `prevIndex` + `claimScene` / `claimChar` 一份规则 |
| 提示词两个真相：界面是 AI 写的中文可读版，出图另拼一串英文 | 新增 `POST /api/comfy/prompt`（只拼不出图），资产详情多一块「本地 Flux 提示词」，拿到的就是真正会发出去的那串 |
| 持久化三条写路径（project.json / localStorage / 旧存档迁移） | 迁移逻辑删除，只剩 project.json + 缓存兜底 |
| UI 原型堆在根目录 `ui-versions/` | 移到 `docs/archive/ui-versions/` |

**为什么提示词要对齐**：以前「复制提示词」复制的是 AI 写的中文设定，本地 Flux 吃的却是 `keywordEn` 另拼的英文串，等于一套设定两个真相，复制出去给即梦 / MJ 的和本地出的根本不是同一个描述。现在两边都从服务端 `build_comfy_prompt()` 取。

## 设计系统（linear.app · 深色原生）

界面皮肤取自 `awesome-design-skill / design-md/linear.app`，不是「浅色换成深色」，而是按这套系统的规则重建：

| 维度 | 取值 |
| --- | --- |
| 画布 / 面板 / 抬升面 | `#08090a` / `#0d0e10` / `#111214`（层级靠亮度阶梯，不用投影） |
| 文字 | 主 `#f7f8f8`（不用纯白）· 次 `#c3c9d3` · 辅助 `#8a8f98` · 最弱 `#62666d` |
| 边框 | 一律半透明白 `rgba(255,255,255,.055/.07/.11)`，无实色深边 |
| 强调色 | `#7170ff`（交互）/ `#9a99ff`（深色底上的链接与高亮）/ `#5a5ae0`（主按钮） |
| 字体 | Inter + `font-feature-settings:"cv01","ss03"`；三档字重 **400 / 510 / 590**（不用 700） |
| 字号 | h1 32px / −0.704px，h2 17px / −0.24px，正文 14px，元信息 11–12px |
| 圆角 | 按钮与输入 6px，卡片与面板 12px，胶囊 999px |
| 动效 | 150ms，只变背景/边框/颜色，不做位移（卡片 hover 抬 2px 是唯一例外） |

改皮肤只需动 `assets/styles.css` 顶部 `:root` 的 token；`controls.css` / `agents.css` 全部读同一套变量，会跟着变。打印样式强制回浅色纸面（`@media print` 里重设底色与文字色）。

## 视觉特效（FX LAB）

- 左下角渐变悬浮球：展开特效控制台，可切「浅色极光 / 暗夜霓虹」双皮肤、动效「全开 / 舒缓 / 静止」及总开关。
- `Ctrl/⌘ + K` 唤起命令面板：搜索并执行导航、撤销重做、导出、设置、皮肤切换，以及按镜号 / 画面描述检索镜头并定位。
- 纯 CSS 增强：极光背景、玻璃卡片与渐变描边、流光主按钮、点击水波纹、呼吸状态点、玻璃 Toast、卡片入场动画；悬停悬浮球可看实时镜头数 / 时长 / 集数的滚动 HUD。
- **默认关闭**（Linear 深色是基线，玻璃层会盖掉层级语言）。设置存于 `localStorage["shortplay.fx.v2"]`；开启后玻璃面板已改为深色半透明，不再把卡片刷成白底。打印时自动隐藏所有特效浮层。

## 内置剧本《鬼婚，逃命》

- 第一步新增「载入《鬼婚，逃命》」按钮，一键把第一章放进输入框；原文存档在 `examples/鬼婚逃命-原文.txt`。
- 原作是**小说体第一人称**，没有场次行和「角色：台词」，直接喂解析器会退化成「1 场 / 0 台词 / 90+ 条动作」。`frontend/src/lib/sampleGuihun.js` 是唯一真源，只做格式转写：加场次头、给原文直接引语加角色名、内心独白标「水雷（旁白）」、叙述句按原顺序合并为动作行，**不新增人物 / 地点 / 情节**。
- 转写结果：10 场 / 7 角色 / 19 句对白 / 55 条动作 / 3257 字，另存 `examples/鬼婚逃命-分镜剧本.txt` 供「上传 .txt」使用。
- 重新生成：`node tools/gen_guihun.js`（需 8177 服务在跑），输出 `examples/guihun-storyboard.{json,csv,md,txt}` 与 `guihun-video-prompts.json`。生成参数用 `pacing: cinematic`（单集上限 34 镜）与 `9:16`，`standard` 的 28 镜上限对 10 场长章节不够。

## 控件系统

`frontend/src/assets/controls.css` 是独立的基础控件皮肤层，在 `main.js` 里最后引入（打包顺序实测 `fx.css → styles.css → controls.css`）。**零第三方依赖、零 DOM 改动**，所有 `id` / `class` / `data-field` 事件委托保持原样。

- 统一 `input / select / textarea / checkbox / radio / file / button`：34px 高、9px 圆角、1px 边分层、hover 只变边色、3px 品牌聚焦环、150ms 过渡。
- 自绘细节：下拉 SVG 箭头、复选框勾选与半选态、收敛的 number 步进器、文件选择按钮、按钮顶部内高光与 `:focus-visible` 环。
- 字段组标签左侧 3px 重边线（聚焦时点亮品牌色）、剧本编辑区稿纸竖线与品牌色光标。
- 基础规则一律包 `:where()`（特异性 0），`.cell` / `.script-area` / `.aset-input` / `.size-sel` 等既有类样式照常优先；暗夜霓虹通过覆盖 CSS 变量自动适配，打印与 `prefers-reduced-motion` 有对应降级。

## 分镜核对文档

`py tools/gen_storyboard_doc.py` 读取 `examples/guihun-storyboard.json`，生成自包含的 `examples/guihun-storyboard.html`（无外部依赖，双击即可打开）。顶部是自动体检出的「待你核对」与「已校验通过」两组结论，点疑点可直接筛出相关镜头；支持分集、按问题类型筛选、全文搜索，每镜可展开 9 项分镜描述卡，打印时自动展开全部。重跑 `node tools/gen_guihun.js` 后再执行本脚本即可刷新，**不会重新调用模型**。

## 小说体 → 分镜表：自动工作流

STEP 01 现在是一条显式流水线：**识别格式 → 忠实转写 → 剧本体检 → 自动分集 → 逐集分镜 → 覆盖校验**。界面上有 6 段阶段条显示当前进度。

- **自动识别**：`AI.isNovelScript()` 判断「无场次行 + 几乎无「角色：台词」行 + 长文本」；命中就显示提示条，此时直接拆解只会得到 1 场 / 0 句对白。
- **一键跑完**：点「AI 一键分集 + 分镜」时，`AI.run()` 会在 `plan` 之前自动插入 `/api/ai/adapt`，转写后**重新 `parseScript` 并重算本地兜底镜头**，后续所有阶段都基于转写版；产物回填输入框并落在撤销栈里（`Ctrl+Z` 可回到小说原文）。
- **只跑一步**：「只转写成场次剧本」只执行 stage 1，方便先看、先改再继续；离线规则引擎下会提示需要开启 AI。
- **服务端 `/api/ai/adapt` 的设计要点**：模型**只输出结构 JSON**（场次 `start/end` 闭区间、内外景/地点/时间、台词句子索引与原文子串），正文由 `split_source_sentences` + `build_adapted_script` 按原文逐句重组 —— 逐字保真、输出极短、不会被 `max_tokens` 截断。`check_adaptation` 按句核对保真率、直接引语保留数与截断风险，异常以 `warnings` 返回。
- 真模型产物：`examples/鬼婚逃命-原文.txt` → `examples/鬼婚逃命-AI转写剧本.txt`（9 场 / 19 句对白 / 42 条动作，原文句子 90/99 逐字可查、8 句直接引语全保留、0 警告，约 17 秒）。手工金标准在 `examples/鬼婚逃命-分镜剧本.txt`（10 场 / 19 句对白 / 55 条动作）。
- 已知取舍：自动版更保守（原文没写时间就标「未注明」，不脑补「日」）；模型偶尔只给半句台词，服务端会补齐到句末。

## 剧本拆解任务 · 后端实时进度（2026-11-09）

拆解从「前端串 6 个请求 + 一行 busy 文案」改成**后端任务 + 事件流**：

- 任务在后端线程里跑，关掉标签页/刷新页面都不影响；回来凭 `taskId` 补齐已发生的事件。
- 每个阶段、每次模型调用都是一条事件，前端只做「append + 渲染」，不猜进度。
- 模型调用期间每 6 秒刷一次「已等 Ns」，20 秒没动静也不会像卡死。

### 数据结构

**任务快照**（`GET /api/parse/state`、`/api/parse/latest`）：

```json
{
  "id": "t1794211697_6",
  "project": "p_20261109_160729_03a2",
  "status": "running",
  "percent": 45,
  "done": 3, "total": 8,
  "stage": "storyboard", "stageLabel": "逐集分镜",
  "elapsed": 31.4, "ended": false,
  "stages": [
    { "key": "detect", "label": "识别剧本格式", "weight": 5, "status": "ok",
      "detail": "场次剧本：4 场 / 8 句对白 / 2 角色", "tool": "rule:detect_format",
      "startedAt": 0.0, "endedAt": 0.02, "frac": 1.0, "ms": 20 }
  ],
  "events": [
    { "seq": 9, "ts": 13.19, "type": "stage", "status": "running", "stage": "assets",
      "stageLabel": "资产分解", "percent": 45, "done": 3, "total": 8,
      "state": "ok", "label": "资产分解", "detail": "2 角色 / 4 场景 / 5 道具",
      "ms": 13187, "tool": "llm:decompose_assets" }
  ],
  "errors": [{ "stage": "adapt", "message": "原文太短…", "hint": "…" }],
  "warnings": [],
  "result": null
}
```

`percent` 由后端算：每个阶段有权重（detect 5 / adapt 20 / assets 20 / plan 15 /
storyboard 30 / frames 5 / verify 5，合计 100），进行中的阶段按 `frac` 折算，
跳过与失败的阶段直接计满——所以进度条不会因为「跳过一个阶段」而倒着走。

**事件**（SSE `data:` 里一条一个 JSON，`seq` 单调递增）：

| 字段 | 说明 |
|---|---|
| `seq` | 自增序号，断线用 `since` / `Last-Event-ID` 续传 |
| `type` | `task` / `stage` / `tool` / `done` / `error` |
| `status` | 任务状态 `queued` / `running` / `done` / `failed` / `cancelled` |
| `stage` / `stageLabel` | 阶段 key 与中文名 |
| `state` | 阶段或工具的 `running` / `ok` / `fail` / `skip` |
| `phase` / `callId` | 工具调用的 `start` / `end` 与配对 id（如 `storyboard#2`） |
| `tool` / `label` / `detail` / `ms` | 工具名、人类可读标题、结果摘要、耗时 |
| `percent` / `done` / `total` | 推送时刻的整体进度 |

**阶段与工具**：`detect`（rule）→ `adapt`（llm）→ `assets`（llm）→ `plan`（llm）→
`storyboard`（llm × 集数）→ `frames`（本地模板）→ `verify`（rule）。分镜阶段每集
一对 `tool start/end` 事件，前端日志里就是按集滚动的「工具调用情节」。

### 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/parse/start` | body：`{script, scenes, novel, episodes, config, projectId}`；秒回 `{taskId, total, stages}` |
| GET | `/api/parse/events?id=&since=` | `text/event-stream`；支持 `Last-Event-ID`；空闲 8s 发 `: ping` 心跳；任务收尾后关闭 |
| GET | `/api/parse/state?id=` | 整份快照（含 `result`，仅 `done` 时带） |
| GET | `/api/parse/latest` | 最近一个任务，用于页面打开时接回 |
| POST | `/api/parse/cancel` | `{id}`；置取消标记，在下一个阶段边界停下，不写任何结果 |

`start` 立刻返回、后台线程开跑；`stages` 是当时的实时快照，前端拿来先画骨架。

### 状态机与异常

```
queued ──▶ running ──▶ done
              │  ├──▶ failed      （任一阶段抛错；已完成的阶段保留）
              │  └──▶ cancelled   （POST cancel，阶段边界生效）
              └─ 服务重启 = 任务丢失（内存态），前端退化为原错误提示
```

- **单阶段失败不炸整条链**：转写失败按原文继续；资产失败退回规则抽取空壳；
  分集失败按场次连续切；某集分镜失败只把该集交给前端用本地规则补齐。
  只有「一镜都产不出来」才整任务失败。
- **失败提示分三层**：`errors[0].message`（技术原因）、`hint`（怎么办）、
  前端三个按钮（重试 / 用本地规则生成 / 知道了）。
- **实时性兜底**：`EventSource` 连续两次 error 就切 900ms 轮询 `/api/parse/state`，
  卡片上标「轮询中」，进度照常推进。
- **页面刷新**：`/api/parse/latest` 若返回同项目、仍在跑的任务，前端自动接回
  （`resumeParseTask`），历史事件按 `seq` 重放，不会从头再来。
- **不串项目**：任务记录 `projectId`，别的项目的任务不会被当前页面接管。
- **SSE 常驻连接**：有任务在跑时页面不会进入 `networkidle`，自动化测试要等
  `domcontentloaded` 或用选择器等待。

### 前端接入

| 位置 | 作用 |
|---|---|
| `lib/ai.js` | `startParseTask` / `watchParseTask`（SSE+轮询）/ `parseTaskState` / `parseTaskLatest` / `cancelParseTask` |
| `stores/studio.js` | `ui.parse` 进度态、`applyParseEvent`（增量）、`applyAiResult`（回填）、`resumeParseTask` |
| `components/ParseProgress.vue` | 进度条 + 阶段清单（完成/进行中/等待）+ 工具调用情节 + 失败块 |
| `assets/parse.css` | 卡片样式（sticky 在顶栏下方，暗色） |

所有失败路径都不改现有剧本与分镜：`begin()` 快照只在拿到 `result` 后打。

### 验证

`node tools/verify_parse_progress.mjs` 16/16（真跑一轮拆解：进度递增、阶段推进、
工具调用增长、100% 收尾、自动进第 3 步、结果落盘）；
`node tools/verify_parse_resume.mjs` 14/14（中途刷新接回同一任务且进度不倒退、
取消后状态 cancelled 且不写结果）。

---

## Agent 工作台 · 角色与技能注册表

参考 `huobao-drama` 的做法（Agent 注册表 + 文件化 `SKILL.md` + 界面在线编辑），把原先写死在 `server.py` 里的 6 个 `SYSTEM_*` 提示词抽成了**可插拔角色**。仍然是零第三方依赖、单文件 Python 服务，没有引入 LangChain / Mastra。

```
agents/
  registry.json              角色注册表：id / stage / outputKey / endpoint / skills / enabled / 流水线顺序
  prompts/<id>.md            frontmatter(name, stage, model, output) + 系统提示词正文
  skills/<skill>/SKILL.md    该角色的技能规范全文，调用时拼进 system prompt
```

**内置 9 个角色**：流水线 6 阶段（转写 / 拆解 / 分集 / 分镜 / 资产 / 起始帧）+ 3 个协作角色 —— **剧本评估师**（按黄金前 3 秒、30 秒一反转、钩子结尾等六条节奏铁律打分）、**剧本创作师**（一句话创意 → 分集大纲）、**导演台 · 镜头语言**（逐镜补全机位 / 站位 / 角度 / 光照四要素）。

| 能力 | 落点 |
|---|---|
| 顶栏「Agent 工作台」 | 流水线阶段条、角色卡、启停开关、Prompt 在线编辑、SKILL.md 在线编辑、单角色试跑 |
| `GET /api/agents`、`/api/agents/prompt`、`/api/skills`、`/api/skills/detail` | 注册表与文件读取；`compiled` 返回「prompt + 技能注入 + 变量替换」后的实际 system prompt |
| `POST /api/agents/save`、`/patch`、`/add`、`/delete`、`/skills/*` | 文件读写；**保存后立即生效，无需重启**，新建 `SKILL.md` 动态扫描即可被发现 |
| `POST /api/agents/run` | 通用执行器：`userTemplate` 占位符由服务端填入，输出只收结构 JSON，走同一套 `repair_json` 修复与校验 |

**新增一个角色不改 Python 代码**：在工作台填 id / 名称 / 阶段 / 输出根键 / user 模板 → 服务端自动写 `registry.json` + `prompts/<id>.md` + `skills/<id>/SKILL.md` → 立刻可试跑。只有「要接进主流水线、参与逐集编排」才需要写编排代码。文件是唯一事实来源，缺失时回退到内置常量；角色停用会返回明确的 400 提示而不是伪装成模型错误。

**保留的既有铁律**：模型只输出结构 JSON（长提示词仍由模板渲染，不重演 3000 字重写导致截断的坑）、原文保真校验、逐集降级兜底、台词逐字一致。技能注入后 `adapt` 真模型回归仍是 90/99 句保真、8/8 引语、0 警告。

复跑初始化：`py tools/init_agents.py`（幂等，默认不覆盖已编辑过的文件；`--force` 强制重建）。UI 点测：`node tools/verify_agent_ui.mjs`（有窗口模式，截图落在 `screenshots/`）。
