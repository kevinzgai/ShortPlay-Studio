---
name: 起始帧提示词师
stage: frames
model: ""
engine: local
output: frames
---

本阶段由服务端模板 `FRAME_TMPL` 渲染，不调用大模型。
下面这行文字不会被用作 system prompt，仅作为该角色的说明；
要改提示词请编辑 server.py 的 FRAME_TMPL / STYLE_ANCHOR_DEFAULT。
