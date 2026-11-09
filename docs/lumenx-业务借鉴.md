# 从 alibaba/lumenx 借了哪些业务实现（2026-11 实抓源码）

不改技术栈，只搬机制。下面每条都注明 lumenx 的出处文件，和我们落到哪个函数。

## 一、资产实体化：分镜只存 id，提示词现编译

**lumenx 做法**（`src/apps/comic_gen/models.py`、`storyboard.py`）
`StoryboardFrame` 里不存"林晚长什么样"，只存 `character_ids[] / scene_id / prop_ids[]`；生成时才由 `_get_character_appearance_keywords()` 把角色外观拼进 prompt。
`Character` 带 `persona`（同一个人的多个视觉形态分组）、`visual_weight`（1–5 戏份权重）、`locked`、`starred`，资产是**带状态的实体**，不是文本。

**我们落地**（`frontend/src/lib/engine.js`）
- `buildAssets(parsed, prev)` 生成 `{characters, scenes, props}`，角色带 `age / role / wardrobe / appearance / weight / locked / touched`
- `bindShot(shot, assets)` 往镜头写 `charIds / sceneId / propIds / assetSig`，**顺序 = 出场顺序**
- `assemblePrompt(shot, assets, config)` 在预览和导出时现编译
- 改一次外观，`assetSig` 变化 → 相关镜头标「设定已改」→ 一键刷新。手改的画面描述不动。

**没照搬**：lumenx 用 LLM 抽取角色，我们用确定性规则——剧本括注 `林晚（27岁，便利店店员）` 直接给出年龄/身份/服装；只在动作里出现、一句台词都没有的角色（群众/反派），用「句读 + 2–3 个汉字 + 人类动作动词（推门/抬头/走进…）」保守抽取，并过滤代词与副词开头的假名，宁可少认也不错认。

## 二、提示词编译：按优先级拼 + 逐段查重

**lumenx 做法**（`prompt_assembly.py: assemble_prompt()`）
顺序固定：画面描述 → 光线 → 运镜 → 景别/角度 → 角色外观；每段都先 `if frame.shot_size not in joined` 再拼，避免同一信息重复堆积。末尾统一 `p.rstrip("。，.")` 再 join。

**我们落地**（`assemblePrompt()`）
`画面描述 → 光线 → 运镜 → 景别/构图 → 角色外观 → 场景 → 道具 → 情绪 → 台词口型 → 画幅`，每段先 against 已拼文本查重，段尾句读先剥再拼（否则会出现「画面里。。中景。」）。

## 三、台词 → 口型提示

**lumenx 做法**（`prompt_assembly.py: enrich_prompt_with_dialogue()`）
台词不是单独挂个元数据字段，而是织成一句画面语言：`{说话人}张嘴说话，表情{emotion}，台词：「{line}」`。视频模型必须看到显式的"说话"才会生成嘴部动作。

**我们落地**（`dialogueCue()`）
同一条思路；说话人优先取 `shot.speaker`，没有就从 `A：台词` 前缀里切；情绪取分镜描述卡的「情绪与表演」。另外 lumenx 还把 `emotion/delivery` 同步进 TTS 指令（`dialogue_instructions`）——我们不出音频，暂不做。

## 四、参考图槽位编号

**lumenx 做法**（`prompt_assembly.py: inject_reference_tags()`）
`[characterN:name]` 是**通用槽位**，不区分角色/场景/道具：角色按 `character_ids` 顺序先占，场景继续往后编号。槽位顺序就是参考图顺序，是模型入参契约。
它的资产取值优先级也定死了：`three_view_asset(选中变体) > full_body > headshot > 旧字段`。

**我们落地**（`tagPrompt()` / `refsFor()`）
角色按出场顺序占 `character1..N`，场景顺延；`refs[]` 输出 `{slot, kind, name, image, role}`，槽位顺序写进导出契约 `schema: "shortplay-v4"`。
`role` 是**照抄时会踩的坑**：lumenx 的槽位喂给 R2V（多参考图）模型，我们的出片端只有 I2V（单张首帧），所以 `mode` 必须写 `i2v / t2v` 而不是 `r2v`，第一个有图的槽额外标 `firstFrame`。详见第七节。

## 五、锁定与陈旧检测

**lumenx 做法**（`models.py`）
- `dialogue_text_hash`：`MD5(dialogue|voice_id|instructions)`，内容一变 UI 就标音频 STALE
- `is_video_pinned`：手选的 take 不被自动覆盖
- `locked`：资产 / 镜头不参与重生成

**我们落地**
- `assetSig` 当 `dialogue_text_hash` 用：资产描述串的哈希，绑定时存进镜头，对比即知是否过期
- `shot.locked` 让批量重生成跳过它，toast 明说"跳过 N 个锁定镜头"
- `asset.locked` 让重新解析剧本不覆盖外观

## 六、三级资产池（只借了思想，没做）

**lumenx 做法**（`test_shared_asset_pool.py`）
`Episode > Series > Global` 三层按 id 去重合并，高优先级覆盖低优先级，回传 `source` 标记；改哪个层级就写回哪个文件（`library_assets.json` / `projects.json` / `series.json`），测试甚至断言"global 分支绝不能碰另外两个文件"。

**我们**只有单项目一层，但资产上的 `source` 字段（`script` / `manual`）和 `buildAssets(prev)` 的合并入参已经留好接口。真要做多剧共用角色池，改这一处就够，不动上层。

## 七、契约对齐：从「字段结构定了」到「语义也定了」

这是照抄 lumenx 最容易翻车的地方，单独记一笔。

**问题**：第四节搬了槽位编号，导出写成 `mode: "r2v" | "t2v"`、`duration: 7`（连续秒）。字段结构没毛病，但拿这份 JSON 去调 `comfyui-h3-demo POST /v1/videos` 第一次就 400：

| 字段 | v2 写的 | 对端真实要求（`gateway/app.py` + `registry.py` 实抓） |
| --- | --- | --- |
| `mode` | `r2v` / `t2v` | 只有 `t2v / i2v / fl2v`；`i2v` 吃**一张首帧图**，不是参考图 |
| `duration` | 2–10 连续秒 | 只有 `5s / 8s / 10s` 三档，其他值直接拒 |
| 宽高 | `aspect: "16:9"` 字符串 | `width % 32 == 0 and height % 32 == 0`（H3 VAE 硬约束） |
| `prompt` | 不限长 | `max_length=4000` |

lumenx 敢用 R2V 命名，是因为它接的 DashScope / Kling 确实有多参考图模式。**我们的出片端没有**，照抄名字等于对外承诺一个不存在的能力。

**落地方案**（`engine.js` 的 `H3_CONTRACT` / `h3Frame` / `h3Duration` / `h3Item` / `h3Preflight`）
- `mode` 由「有没有可当首帧的图」决定：有 → `i2v`（首个有图槽标 `firstFrame`），没有 → `t2v`
- 时长向上吸附到档位（宁可多几帧，也别把台词挤掉），`scriptDuration` 保留原值可回查
- 画幅 × 画质查表得合法宽高，四画幅（16:9 / 9:16 / 1:1 / 2.39:1）× 三档画质 = 12 组，全部 32 倍数
- `preflight` 把翻不动的地方说清：多图镜头标 `multiRef` 并告警、时长吸附后的成片总秒数、超长提示词计数
- 导出菜单里直接显示「出片 1024×576 · 时长吸附到 5/8/10 秒后约 118 秒」——这数字用户必须提前知道

**样本实测**：23 镜的《雨夜便利店》原 100 秒，吸附后 118 秒（+18%），13 个镜头被拉长。这不是 bug，是出片端只有三档的必然结果；把它写进 `preflight` 比让用户导出后自己发现要好。

**教训**：借别人项目的业务结构时，**结构可以抄，取值必须回对端核实**。槽位编号这套契约在 lumenx 世界里是 R2V 的，在我们的世界里是 I2V 的——同一个 `[character1]` 标签，喂进去的模型不同，语义就不同。

## 明确不搬的东西

| lumenx | 为什么不搬 |
| --- | --- |
| Next.js + React + Tauri（Rust）+ PyInstaller 桌面壳 | 我们是 Vue 3 + 纯 Python 标准库 + 双击 `start.bat`，装了就能跑；换过去等于放弃零依赖启动 |
| 阿里云 DashScope / OSS / Kling / Vidu / MuleRouter 出图出视频 | 账单与联网依赖；我们只做分镜表与提示词，出片交给 `comfyui-h3-demo` |
| 变体（variants）+ `selected_id` 多图选择 | 没图可生成，先不做；但 `refImage` 单图字段已就位，将来加 variants 是并集 |
| 无限画布 / 三视图资产生成链 | 漫剧范式（图片驱动），我们是真人短剧的分镜表 |

参考：`docs/github-参考项目.md` 是同批项目的横向对比。
