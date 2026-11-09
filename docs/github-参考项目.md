# GitHub 上可二创的同类项目（2026-11 核实）

数据取自 GitHub API，星数 / 许可证 / 最后提交均为实时抓取，不是二手转载。

## 第一梯队：能直接拿去改的

| 项目 | ★ | 技术栈 | 许可证 | 和我们最像的地方 |
| --- | --- | --- | --- | --- |
| [alibaba/lumenx](https://github.com/alibaba/lumenx) | 1.4K | TS 2.4M + Python 1.1M，Tauri 桌面 + Web | **MIT** | 小说/剧本 → 剧本分析 → 角色 → 分镜 → 视频合成，四段式和我们吻得最紧 |
| [xuanyustudio/LocalMiniDrama](https://github.com/xuanyustudio/LocalMiniDrama) | 2.4K | **Vue + JS**，Electron + Node 后端 | **MIT** | 本地优先、列表精细编辑 + 画布批量编排双视图，最贴我们的 Vue 3 栈 |
| [HBAI-Ltd/Toonflow-app](https://github.com/HBAI-Ltd/Toonflow-app) | 21K | TypeScript，无限画布 | **MIT** | 剧本 → 分镜 → 角色/场景资产 → 图/视频，你本机已有一份源码 |
| [eternityspring/shuohao-skills](https://github.com/eternityspring/shuohao-skills) | 6.2K | JS / Agent Skills | **Apache-2.0** | 拆角色 → 排大纲 → 场景道具设定 → 写剧本 → **切分镜**，提示词与规则可直接搬 |

## 第二梯队：能看思路，但许可有坑

| 项目 | ★ | 栈 | 许可 | 坑 |
| --- | --- | --- | --- | --- |
| [chatfire-AI/huobao-drama](https://github.com/chatfire-AI/huobao-drama) | 17K | TS + **Vue** | **CC BY-NC-SA 4.0** | **禁止商用**，只能自用/学习；商用要重写 |
| [dramaclaw/dramaclaw](https://github.com/dramaclaw/dramaclaw) | 7.4K | Python 16.8M + TS 15.4M，FastAPI | **Elastic License 2.0** | 不能把功能作为托管服务卖给第三方，也不能移除受限功能 |
| [Anil-matcha/Open-AI-Micro-Drama-Generator](https://github.com/Anil-matcha/Open-AI-Micro-Drama-Generator) | 568 | Python / FastAPI | **无 LICENSE 文件** | 默认保留所有权利，**不可分发二创**，只能读代码 |
| [SainathPattipati/ai-video-generation-pipeline](https://github.com/SainathPattipati/ai-video-generation-pipeline) | 8 | Python | MIT | 体量太小（8 星），参考价值有限 |

## 结论

- **要能商用、要最像** → `alibaba/lumenx`（MIT）
- **要最贴现有 Vue 3 工程** → `LocalMiniDrama`（MIT + Vue + Electron）
- **只要提示词与拆解规则** → `shuohao-skills`（Apache-2.0），把「切分镜」那套 skill 逻辑翻成我们 `js/ai.js` 的 system prompt
- **Toonflow 已经在本地**，但它是无限画布范式，搬 UI 不如搬它的**剧本→分镜数据结构**与资产管理思路

## 我们相对它们的差异（别丢掉的优势）

1. **确定性引擎 + 大模型双通道**：它们基本全押大模型，断网即废；我们本地规则引擎可离线产出完整分镜表。
2. **台词/动作逐条覆盖校验**：模型漏句自动补镜并标 `patched`，这点在多数开源项目里没有。
3. **撤销栈 + 手改保留**：重生成默认不覆盖人工字段。
4. **导出五连**：CSV / Markdown / TXT / JSON / 视频提示词。视频提示词已按 `/v1/videos` 的真实取值对齐（`mode` 只出 `t2v/i2v`、时长吸附 5s/8s/10s、宽高 32 倍数、`firstFrame` 标注、`preflight` 预检），拿来就能提交，不是"字段长得像"。

真要二创，建议**只 fork 它们的「角色/资产一致性」与「图像/视频生成编排」**，我们的分镜表、校验、导出继续自己维护——反过来搬它们的画布或 Electron 壳，会把现在轻量的双击启动优势弄丢。
