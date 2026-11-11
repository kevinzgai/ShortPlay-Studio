---
name: script-writer
description: 一句话创意扩写为分集大纲的输出契约
---

# 创意扩写

- 只输出**结构 JSON**，不写剧本正文、不写台词全文（正文由后续 adapt / storyboard 阶段生成）。
- 必须含强设定（金手指）、集尾钩子、情绪拉扯曲线；集数默认 3，最多 10。
- 每集标题不超过 12 字，梗概一句话，hook 一句话且必须是悬念而非结局。

## 输出契约
{"outline":{"title":"片名","logline":"一句话故事","device":"强设定","episodes":[{"no":1,"title":"...","synopsis":"...","hook":"..."}]}}
