# 对接 shuohao-skills/novel-storyboard（2026-11 实抓源码）

`eternityspring/shuohao-skills`（Apache-2.0，6212★）是「AI 短剧制作 skill 集合」：大纲 → 角色 → 美术 → 剧本 → 分镜 五件套。我们只取 `novel-storyboard` 分镜 skill 的**可落地机制**，不搬它的 skill 运行框架（Claude Code / codex 的 agent skill 形态）。

> 关键前提：**我们本地 ComfyUI 的 H3 和它文档里写的 MiniMax-H3 是同一个模型**（节点 `MiniMaxH3AudioConditioningT8` / `MiniMaxH3MultiRateSamplerEXPT8`，`gateway/registry.py`）。所以它的 H3 提示词规范可以直接用——不需要翻译成别的协议。

## 借鉴了什么

| shuohao 做法 | 出处文件 | 我们落到哪 | 价值 |
| --- | --- | --- | --- |
| **段 = 一次生成调用**（≈15s，不跨场；段内 3–5 切，每切 2–5s） | `references/schema.md` | `engine.js: segmentShots()`（上限 10s 对齐对端 duration） | 23 镜 → 13 段，-43% 生成调用 |
| **H3 正文用通用身份**（an old ferryman），正文禁角色名 | `references/shot-writing.md` | `engine.js: genericRole() + h3ShotDesc()` | 视频模型规范要求，不然会生成"第一个人物" |
| **台词逐字进 `<d>[Chinese]…</d>` 块** | `references/h3-prompt.md` | `h3ShotDesc()` 对白段 | 音视频联合模型认这个标记才生成嘴部动作 |
| **不写画风 / 不写画幅**到正文 | `references/shot-writing.md`「不写的东西」 | `h3ShotDesc()` 去掉"短剧质感/16:9画幅" | 画风是调用方参数，写进正文会打架 |
| **声音分三层**：台词→正文、环境声→soundscape、配乐→music | `references/h3-prompt.md` | `h3Prompt()` 三段结构 | H3 是音视频联合模型，没声音描述闲置一半能力 |
| **段级 blocking / 镜头六个构图量化字段**（lens/机位/构图/视线/焦点/稳定） | `references/schema.md` cut 字段 | `normalizeDetail()` 白名单 + `SHOT_CRAFT` | 纯参考图出片时构图的全部来源 |
| **镜头级校验门**（时长 2–5s、台词装得下、正文禁名） | `SKILL.md` Step 3 的 18 门 | `engine.js: validateShots()` → `preflight.cutChecks` | 输出前就把硬问题拦下 |

## 没照搬（以及为什么）

| shuohao | 为什么不搬 |
| --- | --- |
| 分镜图（每切一张 PNG 提示词 `frame`，直呼角色名） | 我们接的是 `comfyui-h3-demo /v1/videos`，只有 `t2v/i2v/fl2v`，没有多图对齐；`frame`（出图提示词）要等接到专门的文生图接口才有意义 |
| `[Shot k]` 多切 + 参考图对齐时刻（<Picture N> 钉 X.XX 秒） | 对端 I2V 只吃**一张首帧**，多图对齐（R2V）没接。我们保留段内切点时刻 `At 00:mm:ss`（段级多镜一次生成仍可用），但 `<Picture N>` 多图引用告警降级 |
| 18 道质量门的 agent 化、`.gates.jsonl` 统计 | 密集的 LLM 编排，我们前端数据流不适合；只搬「可确定性检查的」那部分进 `validateShots` |
| Seedance 提示词 | 我们没有 Seedance 端 |
| Skill 的 `seed/render/export` CLI、报告 HTML | 我们有 Vue 界面在做这些事 |

## 落地位置速查

- `frontend/src/lib/engine.js`
  - `genericRole(assets, name)` → 角色名 → 通用身份（年龄 + 职业，剥掉人称）
  - `h3ShotDesc(shot, assets, sec)` → 单镜 H3 正文行（通用身份 + 动作 + 台词 `<d>` 块）
  - `h3Prompt(shots, assets, config, refUrl)` → 整段 H3（对齐行 / `[Shot k]` 行 / `soundscape` / `music`）
  - `segmentShots(shots, maxSec)` → 按「不跨场 + ≤10s」分组，返回段（含段内切点 start）
  - `h3SegmentPrompt(seg, ...)` → 段级 H3 提示词
  - `validateShots(shots, assets)` → 镜头级校验（时长 / 台词装得下 / H3 正文禁名）
  - `normalizeDetail` 增加 `SHOT_CRAFT` 6 字段
- `frontend/src/stores/studio.js` → `shotSegments` / `activeSegmentOf` 计算属性
- `frontend/src/components/PreviewPanel.vue` → 「H3 视频提示词」折叠面板（当前段整段提示词 + 复制）
- 导出 `schema: "shortplay-v4"` → 含 `segments[]`（段）、每镜 `h3Prompt/h3Shot`、`preflight.cutChecks`

## 自己会踩的坑

1. **名字替换要处理「名（身份括注）」整体**：`林晚（27岁，便利店店员）` 若只换「林晚」一个字会得到 `27岁，便利店店员（27岁，便利店店员）` 的重复。先正则剥「名(… )」整体，再替换剩余名。
2. **说话人身份 vs 动作主体别重复前置**：speaker 已经放进 `<d>` 外说「…店员说」，动作行又写「…店员把伞架…」，同一身份出两次。用「是否空动作」分流，别两处都写。
3. **台词秒数推导别忘拆「：」**：`林晚：又是一整夜的雨` 若把「林晚：」算进字数会高估 20%。`validateShots` 用 `split("：").slice(1)` 只算真正台词。
4. **H3 完美纯文本并存**：`h3Prompt/h3Shot` 是给 H3 的，`prompt/taggedPrompt` 保留给 deepseek 这类不看 H3 规范的通用模型。两侧规则相反（允许名字 vs 禁名字），别用一个函数输出。

## 下一步候选（未做）

- **多图对齐（R2V）**：等 `comfyui-h3-demo` 支持多参考图，或换 Kling/Vidu 那类模型，再把 `refs[]` 多槽位真正喂进去（现在标 `multiRef` 告警降级）。
- **分镜图（frame）生成**：需要专门的文生图接口；当前 `comfyui-h3-demo` 的主业是视频，不是出静态图。
- **blocking 段级走位**：`segmentShots` 已分组，可在每组上方生成一句话的人物位置描述（现在每镜 6 字段在单镜足够）。