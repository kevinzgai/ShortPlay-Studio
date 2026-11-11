---
name: frames
description: 分镜起始帧提示词的模板渲染规范
---

# 起始帧

- 本地模板渲染，不调用模型；模板一改，全部镜头同步换风格。
- 每帧注入：全局风格锚 + 负面词 + 出场角色 `keywordEn` 原样串 + 场景描述 + 画面主体 / 动作 / 构图 / 景别 / 运镜 / 光线 / 情绪。
- 角色判定**只认 `visual / dialogue / speaker`**；`sizeReason`、`notes` 里的剧情解释不算出场。
- 中文版给豆包 / 即梦，英文版给本地 Flux；明确写「不要三视图、不要设定表、不要拼贴图、不要画面文字」。
- 起始帧图填进 `firstFrameUrl` 后，视频提示词从 `t2v` 转 `i2v`；H3 只吃一张首帧，双图 / 多参考需另做合成或换 r2v。
- 纯 Flux 文生图不保证跨镜头同一张脸；锁脸需 InstantID / PuLID / ControlNet。
