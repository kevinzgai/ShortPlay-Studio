# -*- coding: utf-8 -*-
"""初始化 Agent 工作区（幂等，可反复运行）。

思路来源：huobao-drama 的 workspace/prompts + workspace/skills。
- 从 server.py 原样抽取 6 个 SYSTEM_* 常量 → agents/prompts/<id>.md
- 生成 registry.json（角色注册表 / 流水线顺序 / 输入输出契约）
- 生成每个角色的 SKILL.md（技能规范，支持界面在线编辑、新增即生效）

默认不覆盖已存在文件（在线编辑过的 prompt / skill 不会被冲掉）。
需要强制重建时加 --force。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server.py"
AGENTS = ROOT / "agents"
PROMPTS = AGENTS / "prompts"
SKILLS = AGENTS / "skills"
FORCE = "--force" in sys.argv

# server.py 常量 → agent id
BUILTIN = {
    "SYSTEM_ADAPT": "adapt",
    "SYSTEM_PARSE": "parse",
    "SYSTEM_PLAN": "plan",
    "SYSTEM_SHOTS": "storyboard",
    "SYSTEM_ASSETS": "assets",
}

META = {
    "adapt": ("剧本结构分析师", "adapt", "scenes"),
    "parse": ("场次拆解师", "parse", "scenes"),
    "plan": ("总导演助理 · 分集", "plan", "episodes"),
    "storyboard": ("分镜大师", "storyboard", "shots"),
    "assets": ("美术设定总监", "assets", "characters"),
}

REGISTRY = {
    "version": 1,
    "note": "新增角色 = 加一条 agents 记录 + prompts/<id>.md + skills/<skill>/SKILL.md，无需改 Python 代码。",
    "pipeline": ["adapt", "parse", "plan", "storyboard", "assets", "frames"],
    "agents": [
        {"id": "adapt", "name": "剧本结构分析师", "stage": "adapt", "order": 1,
         "desc": "小说 / 散文 → 场次剧本。模型只判结构，正文由服务端逐句重组，原文逐字保真。",
         "engine": "llm", "builtin": "SYSTEM_ADAPT", "outputKey": "scenes",
         "skills": ["adapt"], "endpoint": "/api/ai/adapt", "enabled": True},
        {"id": "parse", "name": "场次拆解师", "stage": "parse", "order": 2,
         "desc": "格式化剧本 → 场次 / 台词 / 动作结构，台词逐字保留。",
         "engine": "llm", "builtin": "SYSTEM_PARSE", "outputKey": "scenes",
         "skills": ["parse"], "endpoint": "/api/llm/parse", "enabled": True},
        {"id": "plan", "name": "总导演助理 · 分集", "stage": "plan", "order": 3,
         "desc": "按场次边界分集，给出集标题、梗概与集尾钩子。",
         "engine": "llm", "builtin": "SYSTEM_PLAN", "outputKey": "episodes",
         "skills": ["plan"], "endpoint": "/api/ai/plan", "enabled": True},
        {"id": "storyboard", "name": "分镜大师", "stage": "storyboard", "order": 4,
         "desc": "逐集拆镜头，9 项分镜描述卡，refs 覆盖剧本行清单，台词逐字一致。",
         "engine": "llm", "builtin": "SYSTEM_SHOTS", "outputKey": "shots",
         "skills": ["storyboard"], "endpoint": "/api/ai/storyboard", "enabled": True,
         "vars": ["min_shots", "max_shots"]},
        {"id": "assets", "name": "美术设定总监", "stage": "assets", "order": 5,
         "desc": "剧本 → 角色 / 场景 / 道具资产包，含一致性锚点与固定关键词串。",
         "engine": "llm", "builtin": "SYSTEM_ASSETS", "outputKey": "characters",
         "skills": ["assets"], "endpoint": "/api/ai/assets", "enabled": True},
        {"id": "frames", "name": "起始帧提示词师", "stage": "frames", "order": 6,
         "desc": "本地模板渲染（不调模型）：分镜 × 资产包 → 77 镜起始帧中英文提示词。",
         "engine": "local", "builtin": "", "outputKey": "frames",
         "skills": ["frames"], "endpoint": "/api/ai/frames", "enabled": True},
        {"id": "script_evaluator", "name": "剧本评估师", "stage": "review", "order": 7,
         "desc": "按短剧节奏铁律体检剧本：黄金前 3 秒、反转密度、钩子结尾、爽点与风险。",
         "engine": "llm", "builtin": "", "outputKey": "report", "generic": True,
         "skills": ["script-evaluator"], "input": ["script"], "enabled": True,
         "userTemplate": "请评估以下剧本 / 小说原文，只输出结构 JSON，不要解释文字。\n\n原文：\n{script}"},
        {"id": "script_writer", "name": "剧本创作师", "stage": "write", "order": 8,
         "desc": "一句话创意 → 分集大纲（集标题、梗概、钩子），不改动词典之外的既有剧本。",
         "engine": "llm", "builtin": "", "outputKey": "outline", "generic": True,
         "skills": ["script-writer"], "input": ["idea"], "enabled": True,
         "userTemplate": "请把以下创意扩写成短剧分集大纲，只输出结构 JSON，不要解释文字。\n\n创意：\n{idea}"},
        {"id": "director", "name": "导演台 · 镜头语言", "stage": "director", "order": 9,
         "desc": "逐镜补全导演台四要素：机位 / 站位 / 角度 / 光照，供 AI 视频工具照台本布景。",
         "engine": "llm", "builtin": "", "outputKey": "shots", "generic": True,
         "skills": ["director"], "input": ["shots"], "enabled": True,
         "userTemplate": "请为以下分镜清单逐镜补全导演台四要素，只输出结构 JSON，不要解释文字。\n\n分镜清单：\n{shots}"},
    ],
}

SKILL_DOCS = {
    "adapt": """---
name: adapt
description: 小说体转写为场次剧本的保真规范
---

# 原文保真转写

## 铁律
- **模型只输出结构 JSON，绝不输出原文正文。** 长正文一律由服务端按句子编号逐句重组。
  历史教训：让模型重写 3000 字全文 → 90 秒 → max_tokens 截断 → 502；改结构 JSON 后约 17 秒、90/99 句保真。
- 句子编号从 0 开始，`end` 为闭区间；所有句子必须连续覆盖、不重叠、不遗漏。
- `dialogues[].text` 必须是该句原文里逐字连续的子串，不许改写、不许加字、不许丢标点。
- 转写结果必须过 `check_adaptation()`：句子覆盖率、引语保留率、场次头合法性、warning 数。

## 切场规则
- 只在地点 / 时间明显变化，或剧情进入下一件事时切场；每场 5–20 句，全文 5–11 场，宁可少切不要碎切。
- 原文没写的时间写「未注明」，严禁脑补（不要因为「夏天」就默认写「日」）。
- 「旁白」不是角色，不能进 characters。
""",
    "parse": """---
name: parse
description: 格式化剧本的场次拆解规范
---

# 场次拆解

- 按剧情出现顺序输出 scenes；台词必须逐字保留，允许「角色：台词」前缀。
- 不新增剧本里没有的情节、人物、地点、时间；没写的字段填空字符串或空数组，不要脑补。
- 角色名去括号（「林晚（主角）」→「林晚」），同一人的别名合并，避免生成两张脸。
- 输出只含一个 JSON 对象：`{"scenes":[...]}`。
""",
    "plan": """---
name: plan
description: 分集与钩子设计规范
---

# 分集

- 切点必须落在**场次之间**，绝不能把同一场拆到两集；所有场次被覆盖且不重叠。
- 集数按用户给定，`auto` 时控制在 1–6 集，短剧常用 2–3 集。
- 每集结尾必须有钩子（转折 / 悬念 / 未回答的问题），但 hook 只能描述剧本里真实存在的内容。
- 标题与梗概只概括原文，禁止新增人物、地点、事件、道具、结局或设定。
- 解决危机的情节放在下一集开头，绝不在本集结尾把事情解决圆满。
""",
    "storyboard": """---
name: storyboard
description: 分镜大师的覆盖校验与分镜描述卡规范
---

# 分镜拆解

## 覆盖校验（硬性）
- 剧本行清单里每句台词（D 开头）必须且只能被一个镜头的 `refs` 引用；每条动作（A 开头）尽量被引用。
- `refs` 是**剧本行编号**，只写清单里真实存在的编号；不要与「参考图槽位」混用（后者叫 refSlots）。
- 按清单顺序编排，同一镜头可引用相邻多个编号，不跨场、不倒序。

## 9 项分镜描述卡
`subject / action / composition / sizeReason / camera / light / mood / sound / transition` 每项一句话，必须落实到本场真实内容。
不要复述整句 visual，不要写「无」「略」「同上」「待定」。

## 禁套话
建立镜头与收束镜头禁止「画面缓缓展开」「镜头缓缓拉远」「氛围收进画面」「留出转场余韵」「交代空间关系」等通用句式；
必须写本场真实地点、时间，以及清单里那条具体的环境动作或最后一条动作 / 台词。

## 保真
台词逐字一致；严禁新增剧本里没有的人物、地点、事件、道具、台词、结局或技术参数。
`sizeReason` 是剧情解释，**不是角色出场依据**（起始帧资产召回时不得用它匹配角色）。
""",
    "assets": """---
name: assets
description: 资产一致性锚点、别名归并与溯源规范
---

# 美术设定

## 一致性锚点：3 个怪特征 + 1 个服装记忆点
`face / flaw / wardrobeHook` 三项对每个角色都必须给，且同年龄段同性别的角色不得出现雷同组合。
靠固定关键词串而不是每镜重写全脸：**`keyword` / `keywordEn` 生成后原样粘贴，禁止重写**。

## 别名归并
同一人的不同称呼（水雷 / 润土、小强 / 强子）必须合并进 `aliases`，严禁拆成两个资产。

## 场景按视觉区分
不要只按地点名去重：同一地名但陈设、光线、事件明显不同（喜宴长街 vs 荒坟土坡）必须拆成不同资产。
`sceneNos` 只填真正对应的场次。

## 溯源双通道
- 剧情链严格逐字保真；资产链允许 `source=inferred`，但必须带 `evidence`（场次 S 编号）。
- `inferred` 只补视觉外观，不补身世 / 情节 / 新角色；**绝不回写剧本、不进台词、不参与保真校验**。
- 允许为「设定里存在但本章未出场」的核心角色预建资产，标 `visibility=设定未出场`。

## 输出
只输出结构 JSON，长提示词（三视图 8 段式 / 概念图 5 段式）由服务端模板渲染，模型不写长段文字。
""",
    "frames": """---
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
""",
    "script-evaluator": """---
name: script-evaluator
description: 剧本评估师的短剧节奏铁律与输出契约
---

# 剧本评估

## 六条节奏铁律
1. **黄金前 3 秒**：开篇必须是强情节（一巴掌、一句冲击力台词、一个动作场面），绝不用风景或走路开场。
2. **30 秒一反转，1 分钟一高潮**：单集约 600–800 字内至少包含一次完整起承转合。
3. **钩子结尾**：每集最后 10 秒抛出未知悬念或即将爆发的冲突，绝不在集尾圆满解决。
4. **情绪拉扯**：前期把主角踩入谷底（愤怒 + 同情），随后绝地反击（释放感）。
5. **强设定**：重生 / 系统 / 读心术 / 隐藏首富 / 隐世战神，让反杀合理化。
6. **短平快**：没有废话与无效空镜头，每一秒都在推进剧情或情绪。

## 输出契约（只输出一个 JSON 对象）
{"report":{"score":72,"hook":"开篇 3 秒是否有强情节，一句话结论","strengths":["..."],"risks":["..."],"beats":[{"at":"第1场","type":"反转","note":"..."}],"suggestions":["..."]}}
- `score` 为 0–100 整数；`strengths / risks / suggestions` 各 1–5 条，每条一句话。
- 只评价**原文里真实存在**的内容，禁止虚构情节、禁止改写原文、禁止输出原文正文。
""",
    "script-writer": """---
name: script-writer
description: 一句话创意扩写为分集大纲的输出契约
---

# 创意扩写

- 只输出**结构 JSON**，不写剧本正文、不写台词全文（正文由后续 adapt / storyboard 阶段生成）。
- 必须含强设定（金手指）、集尾钩子、情绪拉扯曲线；集数默认 3，最多 10。
- 每集标题不超过 12 字，梗概一句话，hook 一句话且必须是悬念而非结局。

## 输出契约
{"outline":{"title":"片名","logline":"一句话故事","device":"强设定","episodes":[{"no":1,"title":"...","synopsis":"...","hook":"..."}]}}
""",
    "director": """---
name: director
description: 导演台四要素：机位 / 站位 / 角度 / 光照
---

# 导演台 · 镜头语言控制

每个镜头必须明确四要素，让 AI 视频工具「照台本布景拍戏」，无需二次脑补画面构成。

## ① 机位（Camera Position）：方位 + 高度 + 距离
- 方位：正面 / 左45° / 右45° / 正侧90° / 背面 / 环绕
- 高度：低机位 / 平视 / 高机位 / 顶机位
- 距离：远景 >20m / 全景 8–20m / 中景 3–8m / 近景 1–3m / 特写 <1m
- 例：`右45°低机位，距主体4米`

## ② 站位（Blocking）：角色@九宫格位置 + 朝向 + 状态
- 位置：左1/3、居中、右1/3、下1/3、上1/3；朝向：面朝镜头 / 侧对 / 背对 / 面朝左 / 面朝右
- 关系：对峙 / 合围 / 环绕 / 高低差；多角色逗号分隔，群体写动线
- 例：`女主@居中面朝镜头跪坐，男主@女主怀中横卧`

## ③ 角度（Camera Angle）：类型 + 程度
- 平视 / 仰拍 / 俯拍 / 过肩 / 主观视角 / 荷兰角 / 上帝视角；程度如「低角度仰拍15°」
- 情绪高潮多用特写或推镜，战斗场面增加镜头密度

## ④ 光照（Lighting）：主光方向 + 色温氛围 + 环境光效 + 时段
- 方向：前光 / 前侧45° / 侧光 / 侧逆 / 逆光 / 顶光 / 底光
- 氛围：冷蓝 / 暖金 / 紫红 / 青灰 / 高对比；光效：丁达尔 / 雾气分层 / 月光 / 火光
- 例：`黄昏冷蓝雾霭，左前侧45°柔光主光，逆光金色轮廓光，雾中丁达尔光缝`

## 输出契约（只输出一个 JSON 对象）
{"shots":[{"id":"E01-001","position":"右45°低机位，距主体4米","blocking":"女主@居中面朝镜头跪坐","angle":"低角度仰拍15°","lighting":"左前侧45°柔光，冷蓝雾霭，逆光轮廓光，黄昏","note":"一句话导演提示"}]}
- `id` 必须原样取自输入分镜清单，不新增、不遗漏、不改名。
- 四要素全部必填；只做镜头语言，**不得改写剧情、台词、景别与时长**。
""",
}


def put(path: Path, text: str):
    if path.exists() and not FORCE:
        return "skip"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    return "write"


def main():
    import json
    src = SERVER.read_text(encoding="utf-8")
    found = dict(re.findall(r'^(SYSTEM_[A-Z_]+) = """([\s\S]*?)"""', src, re.M))
    log = []

    # 1) 6 个内建 prompt 原样搬出
    for const, aid in BUILTIN.items():
        if const not in found:
            print("!! server.py 里找不到", const)
            continue
        name, stage, output = META[aid]
        fm = ('---\nname: %s\nstage: %s\nmodel: ""\noutput: %s\n---\n\n' %
              (name, stage, output))
        log.append((str(PROMPTS / (aid + ".md")),
                    put(PROMPTS / (aid + ".md"), fm + found[const].strip())))

    # 2) local 角色也有一份可编辑说明（不参与 LLM 调用）
    fm_frames = ('---\nname: 起始帧提示词师\nstage: frames\nmodel: ""\n'
                 'engine: local\noutput: frames\n---\n\n'
                 '本阶段由服务端模板 `FRAME_TMPL` 渲染，不调用大模型。\n'
                 '下面这行文字不会被用作 system prompt，仅作为该角色的说明；\n'
                 '要改提示词请编辑 server.py 的 FRAME_TMPL / STYLE_ANCHOR_DEFAULT。\n')
    log.append((str(PROMPTS / "frames.md"), put(PROMPTS / "frames.md", fm_frames)))

    # 3) 新增 3 个角色的 prompt 正文
    extra_prompts = {
        "script_evaluator": ("剧本评估师", "review", "report",
            "你是资深短剧策划与剧本评估师，只输出严格 JSON，不要解释文字，不要 Markdown 代码块。\n\n"
            "按注入的 Skill 规范《剧本评估》六条节奏铁律评估用户给出的剧本 / 小说原文，"
            "指出开篇 3 秒、反转密度、集尾钩子、情绪拉扯、强设定、废镜头六方面问题。\n"
            "只评价原文里真实存在的内容，禁止虚构情节，禁止改写原文，禁止输出原文正文。\n"
            "输出格式：{\"report\":{\"score\":72,\"hook\":\"...\",\"strengths\":[\"...\"],"
            "\"risks\":[\"...\"],\"beats\":[{\"at\":\"第1场\",\"type\":\"反转\",\"note\":\"...\"}],"
            "\"suggestions\":[\"...\"]}}。只输出一个 JSON 对象。\n"
            "JSON 合法性：字符串值里禁止出现未转义的英文双引号与换行；"
            "引用原文台词一律用中文书名号《》或单引号，不要整段抄原文。"),
        "script_writer": ("剧本创作师", "write", "outline",
            "你是资深短剧编剧，只输出严格 JSON，不要解释文字，不要 Markdown 代码块。\n\n"
            "按注入的 Skill 规范《创意扩写》把用户的一句话创意扩写成分集大纲："
            "必须有强设定、情绪拉扯曲线、每集结尾钩子，台词与正文一律不写。\n"
            "输出格式：{\"outline\":{\"title\":\"片名\",\"logline\":\"一句话故事\","
            "\"device\":\"强设定\",\"episodes\":[{\"no\":1,\"title\":\"...\","
            "\"synopsis\":\"...\",\"hook\":\"...\"}]}}。只输出一个 JSON 对象。"),
        "director": ("导演台 · 镜头语言", "director", "shots",
            "你是影视导演台执行导演，只输出严格 JSON，不要解释文字，不要 Markdown 代码块。\n\n"
            "你会拿到一份分镜清单。按注入的 Skill 规范《导演台 · 镜头语言控制》"
            "为每一镜补全机位 / 站位 / 角度 / 光照四要素，四要素全部必填，"
            "且必须与本镜的画面主体、动作、景别自洽。\n"
            "严禁改写剧情、台词、景别、时长，严禁新增或遗漏镜头，id 必须原样取自输入。\n"
            "输出格式：{\"shots\":[{\"id\":\"E01-001\",\"position\":\"...\","
            "\"blocking\":\"...\",\"angle\":\"...\",\"lighting\":\"...\",\"note\":\"...\"}]}。"
            "只输出一个 JSON 对象。"),
    }
    for aid, (name, stage, output, body) in extra_prompts.items():
        fm = ('---\nname: %s\nstage: %s\nmodel: ""\noutput: %s\n---\n\n' %
              (name, stage, output))
        log.append((str(PROMPTS / (aid + ".md")), put(PROMPTS / (aid + ".md"), fm + body)))

    # 4) SKILL.md
    for sid, doc in SKILL_DOCS.items():
        log.append((str(SKILLS / sid / "SKILL.md"),
                    put(SKILLS / sid / "SKILL.md", doc)))

    # 5) registry
    log.append((str(AGENTS / "registry.json"),
                put(AGENTS / "registry.json",
                    json.dumps(REGISTRY, ensure_ascii=False, indent=2))))

    w = sum(1 for _, st in log if st == "write")
    print("agents 工作区就绪：新建 %d 个文件，跳过 %d 个已存在文件" % (w, len(log) - w))
    print("目录：", AGENTS)


if __name__ == "__main__":
    main()
