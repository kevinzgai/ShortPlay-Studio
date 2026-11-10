#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ShortPlay Studio · 本机服务（只用 Python 标准库，零第三方依赖）。

作用：
  1. 托管 dist/ 里的 Vue 前端构建产物（由 start.bat 自动构建）
  2. 探测模型配置：GET  /api/config
  3. AI 自动分集：POST /api/ai/plan
  4. AI 批量分镜：POST /api/ai/storyboard
  5. 小说体 → 场次剧本（工作流前置阶段）：POST /api/ai/adapt
  6. 剧本 → 资产包 / 关键提示词：POST /api/ai/assets
  7. 分镜表 + 资产包 → 每镜起始帧提示词：POST /api/ai/frames
  8. 资产包 + 分镜表 + 剧本 → 整个项目 ZIP：POST /api/export/zip
  9. 兼容旧入口（只读懂剧本）：POST /api/llm/parse
  9. Agent 工作台（角色 / 技能注册表，在线编辑、新增即生效）：
       GET  /api/agents、/api/agents/prompt、/api/skills、/api/skills/detail
       POST /api/agents/run、/api/agents/save、/api/agents/patch、
            /api/agents/add、/api/agents/delete、/api/skills/save 等
 10. 【休眠保留 · 无 UI 入口，勿删（旧项目恢复用）】剧本拆解任务（后端执行 + 事件流）：
       S2 起「AI 一键分集 + 分镜」的一键入口已从前端移除，改为
       ① 改剧本 → ② 分集 → ③ 分镜 → ④ 定妆 四步人工确认（单步接口 /api/ai/*）。
       下面这条 7 阶段流水线代码保留、前端无任何入口，仅用于旧项目刷新时恢复进度；
       删掉会让旧存档报错。不要把它当主流程，也不要新建 UI 入口。
       POST /api/parse/start  开任务，秒回 taskId
       GET  /api/parse/events SSE 推送阶段 / 工具调用事件（since 续传）
       GET  /api/parse/state  整份快照（刷新页面靠它恢复）
       GET  /api/parse/latest 最近一个任务（页面打开时接回进度）
       POST /api/parse/cancel 取消（阶段边界生效）

设计原则：
  - 模型只负责「创作决策」（怎么切集、怎么分镜），不负责程序正确性；
    服务端对返回结果做结构校验与归一化，脏数据一律纠正或降级，绝不直接喂给界面。
  - 角色 = 注册表一条记录 + 一个 prompt 文件 + 若干 SKILL.md；
    新增「剧本评估 / 剧本创作 / 导演」等角色不需要改 Python 代码。
  - 未配置 Key / 超时 / 返回异常，接口给出明确中文原因，前端自动降级到离线规则引擎。
  - 密钥只存在本机 llm-config.bat，不写进网页、不进日志、不进导出文件。
"""
from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import io
import json
import os
import random
import re
import sys
import threading
import time
import zipfile
import xml.etree.ElementTree as ET
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# ---- Step A：以下模块已拆到 app/ 包（函数体逐字搬移，行为零变更）----
from app.paths import ROOT, WEB_ROOT, PORT
from app.infra.coerce import _as, _alist, _ints, _priority, num, s
from app.config.base import load_local_config
from app.config.llm_store import (
    load_local_config, _llm_int, _llm_doc, _llm_doc_write, llm_active_provider,
    llm_settings, llm_bootstrap, llm_providers_public, llm_provider_save,
    llm_provider_activate, llm_provider_delete, llm_max_tokens,
)
from app.config.engine_store import (
    _engine_doc, _engine_doc_write, _engine_get, comfy_host, comfy_model,
    qwen_image_url, qwen_image_model, qwen_image_size, engine_config_public,
    _mask_key, qwen_image_key, qwen_image_status, comfy_unet_names, engine_config_save,
)

# 前端是 Vue 3 + Vite 工程，构建产物在 dist/；没有构建时回退到项目根便于排查
SIZE_SET = {"远景", "全景", "中景", "近景", "特写"}
KIND_SET = {"establishing", "action", "dialogue", "closing"}

# 每个镜头的结构化分镜卡字段（模型输出白名单，界面与导出共用同一顺序）
DETAIL_FIELDS = ("subject", "action", "composition", "sizeReason", "camera",
                 "light", "mood", "sound", "transition")
# 建立 / 收束镜头的通用套话：命中就用本场剧本原文重写，不把模板交给界面
GENERIC_RE = re.compile(
    r"画面(?:缓缓|慢慢)(?:地)?展开|镜头(?:缓缓|慢慢)(?:地)?拉远|氛围收进画面|"
    r"留出转场余韵|安静地停留片刻|交代空间关系|镜头缓缓展开"
)


# --------------------------------------------------------------------------
# 配置：环境变量优先，其次读同目录 llm-config.bat（双击 start.bat 时用）
# --------------------------------------------------------------------------


load_local_config()


# --------------------------------------------------------------------------
# 多模型配置：llm-providers.json（本机文件，已在 .gitignore 里）
#   为什么不再只用 llm-config.bat：bat 只能存一套，换模型得改文件重启。
#   这里允许存多条、随时切换，界面也能直接改地址/Key/模型名。
#   读取优先级：文件里「当前选中且填了 Key」的那条 → 环境变量 / bat（兼容老用户）。
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# 出图引擎配置：engine-config.json（本机文件，已在 .gitignore 里）
#   为什么独立文件：llm-providers.json 的语义是「多条同类选一条生效」，
#   而引擎是「每类一份单例」，混在一起会让 active 的含义变糊。
#   读取优先级与 llm-providers.json 一致：文件非空值 → 环境变量 / bat → 内置默认。
#   Key 只在服务端使用，回前端一律打码。
# --------------------------------------------------------------------------


def llm_probe(base, key, model, timeout=25):
    """真发一次最小请求：这是唯一能证明「地址 + Key + 模型名」三件都对的办法。"""
    base = str(base or "").strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        return {"ok": False, "ms": 0, "detail": "接口地址要以 http:// 或 https:// 开头"}
    if not str(model or "").strip():
        return {"ok": False, "ms": 0, "detail": "缺少模型名称"}
    body = json.dumps({
        "model": str(model).strip(), "temperature": 0, "max_tokens": 48,
        "messages": [{"role": "user", "content": "只回复两个字：通了"}],
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if str(key or "").strip():
        headers["Authorization"] = "Bearer " + str(key).strip()
    t0 = time.time()
    req = urllib.request.Request(base + "/chat/completions", data=body,
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            upstream = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200]
        hint = ""
        if exc.code in (401, 403):
            hint = "（Key 不对或没权限）"
        elif exc.code == 404:
            hint = "（地址或模型名不对，注意 /v1 要带上）"
        return {"ok": False, "ms": int((time.time() - t0) * 1000),
                "detail": "HTTP %s%s：%s" % (exc.code, hint, detail)}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "ms": int((time.time() - t0) * 1000),
                "detail": "连不上或超时：%s" % exc}
    except ValueError:
        return {"ok": False, "ms": int((time.time() - t0) * 1000),
                "detail": "返回的不是 JSON，地址可能不是 OpenAI 兼容接口"}
    ms = int((time.time() - t0) * 1000)
    try:
        choice = upstream["choices"][0]
        content = (choice["message"].get("content") or "").strip()
    except (KeyError, IndexError, TypeError):
        return {"ok": False, "ms": ms, "detail": "返回体结构异常：没有 choices[0].message.content"}
    if not content:
        thinking = (choice["message"].get("reasoning_content") or "").strip()
        return {"ok": False, "ms": ms,
                "detail": "模型只输出了思考过程、没有最终内容；把 max_tokens 调大再试" if thinking
                else "模型返回空内容，检查模型名是否这个服务真的支持"}
    return {"ok": True, "ms": ms, "reply": content[:60],
            "model": upstream.get("model") or str(model).strip()}


def llm_test(payload):
    pid = str(payload.get("id") or "").strip()[:60]
    if pid and not payload.get("baseUrl"):
        doc = _llm_doc()
        row = next((p for p in doc["providers"] if p["id"] == pid), None)
        if not row:
            raise ValueError("这条配置不存在，可能已被删除")
        base, key, model = row["baseUrl"], row["apiKey"], row["model"]
    else:
        base = payload.get("baseUrl")
        key = payload.get("apiKey")
        model = payload.get("model")
        if key is None and pid:
            doc = _llm_doc()
            row = next((p for p in doc["providers"] if p["id"] == pid), {})
            key = row.get("apiKey", "")
    return llm_probe(base, key, model)


llm_bootstrap()


# --------------------------------------------------------------------------
# Prompt
# --------------------------------------------------------------------------
SYSTEM_PLAN = """你是短剧总导演助理，负责把一部剧本切成若干集。只输出严格 JSON，不要解释文字，不要 Markdown 代码块。

你会拿到「剧本全文」和「已识别的场次清单」。输出格式：
{"episodes":[{"no":1,"title":"雨夜来客","synopsis":"一句话概括本集剧情，只写剧本里发生的事","sceneFrom":1,"sceneTo":2,"hook":"本集结尾的悬念或情节点"}]}

硬性规则：
- 切点必须落在场次之间，绝不能把同一场拆到两集；每集覆盖连续场次，所有场次都要被覆盖且不重叠。
- 集数按用户给定；用户说 auto 时自行判断，控制在 1–6 集，短剧常用 2–3 集。
- 每集要有一个能让人想继续看下去的结尾（转折、悬念、未回答的问题），但 hook 只能描述剧本里真实存在的内容。
- 标题与梗概只概括原文，禁止新增剧本里没有的人物、地点、事件、道具、结局或设定。
- no 从 1 开始连续递增；sceneFrom / sceneTo 必须是场次清单里真实存在的场次编号（整数）。
- 只输出一个 JSON 对象。"""

SYSTEM_PARSE = """你是短剧剧本分析助手。只输出严格 JSON，不要任何解释文字，不要 Markdown 代码块。

把用户提供的剧本，按剧情出现顺序拆成 scenes 数组。每个元素格式：
{"no":1,"intExt":"外景","location":"便利店门口","time":"夜","characters":["林晚"],"lines":[{"speaker":"林晚","stage":"","text":"又是一整夜的雨。"}],"actions":["雨下得很急。"]}

硬性规则：
- 不新增剧本里没有的情节、人物、地点或时间；不改写原文措辞，台词必须逐字保留。
- 剧本没写的字段填空字符串或空数组，不要脑补。
- 只输出一个 JSON 对象，形如 {"scenes":[...]}。"""

SYSTEM_SHOTS = """你是短剧分镜师。只输出严格 JSON，不要解释文字，不要 Markdown 代码块。

你会拿到「本集剧本全文」「本集场次信息」「剧本行清单」「生成设置」。按剧本行清单的顺序把这一集拆成分镜表：
{"shots":[{"sceneNo":1,"kind":"establishing","visual":"画面里能看到什么：人物、动作、环境、光线","size":"全景","duration":4,"dialogue":"林晚：又是一整夜的雨。","speaker":"林晚","notes":"固定机位 · 环境音：雨声","refs":["A1-1","D1-1"],"detail":{"subject":"雨夜便利店门口与林晚","action":"雨把霓虹招牌碎在积水里，林晚把伞架搬到门边","composition":"低机位，积水作前景，招牌与人物分列画面两侧","sizeReason":"全景才能同时交代店面与人物站位","camera":"固定机位，轻微手持","light":"霓虹冷光混雨夜路灯的暖黄","mood":"疲惫但警觉","sound":"急雨声，同期声留白","transition":"硬切进入下一镜的动作"}}]}

硬性规则：
- 覆盖：剧本行清单里每一句台词（D 开头）必须且只能被一个镜头的 refs 引用；每条动作（A 开头）尽量被引用，确实无法入画的细节才可跳过。refs 只能写清单里真实存在的编号，没有对应剧本行的镜头 refs 填空数组。
- 按剧本行清单的顺序编排镜头，同一镜头可以引用相邻的多个编号；不要跨场引用，不要倒序。
- dialogue 里的台词必须与剧本原文逐字一致，允许「角色：台词」这种前缀；没有台词的镜头填空字符串，speaker 也填空字符串。
- 严禁新增剧本里没有的人物、地点、事件、道具、台词、结局或技术参数；visual 与 detail 只是把已有内容镜头化表达。
- detail 是这一镜的分镜描述卡，9 个字段都要写，每项一句话，且必须落实到本场真实内容：
  subject 画面主体 / action 具体动作或变化 / composition 构图机位与前后景 / sizeReason 为什么用这个景别 /
  camera 运镜 / light 光线与色温 / mood 情绪与表演 / sound 同期声与环境音 / transition 入点出点的剪辑衔接。
  不要复述整句 visual，不要写「无」「略」「同上」「待定」。
- 建立镜头（establishing）与收束镜头（closing）禁止套话：不得出现「画面缓缓展开」「镜头缓缓拉远」「氛围收进画面」「留出转场余韵」「交代空间关系」等通用句式；必须写本场真实存在的地点、时间，以及剧本行清单里那条具体的环境动作或最后一条动作/台词。
- size 只能是：远景 / 全景 / 中景 / 近景 / 特写。kind 只能是：establishing / action / dialogue / closing。
- duration 是 2–10 之间的数字（秒），按台词长度和动作复杂度调整，不要全部一样。
- sceneNo 必须是本集场次里的真实编号（整数）。
- 单集镜头数控制在 {min_shots}–{max_shots} 之间；宁可紧凑，不要为了凑数重复同一画面。
- notes 写运镜、声音或剪辑提示，不要写剧情解释。
- 只输出一个 JSON 对象。"""


SYSTEM_ADAPT = """你是短剧剧本结构分析师。只输出严格 JSON，不要解释文字，不要 Markdown 代码块。

你会拿到「小说 / 散文原文」按句号切开并编号的**句子清单**。你的任务只是判断结构，**绝对不要改写、重写、复述任何原文句子**。

输出格式：
{"title":"片名","narrator":"水雷","scenes":[{"start":0,"end":9,"intExt":"外景","location":"乡下老宅","time":"未注明","characters":["水雷","爷爷"]}],"dialogues":[{"index":12,"speaker":"爷爷","text":"见不到是好事"}]}

规则：
- start / end 是句子编号（**从 0 开始，end 为闭区间**）；所有句子必须被连续覆盖、不重叠、不遗漏。
- 只在地点 / 时间明显变化，或剧情进入下一件事时切场；每场 5–20 句，全文 5–11 场，宁可少切不要碎切。
- intExt 只能是 外景 / 内景 / 未注明；location 与 time 只能从原文推断，原文没写就写「未注明」，**严禁脑补具体时刻**（不要因为「夏天」就默认写「日」）。
- characters 列本场出场人物，名字必须原文出现过，用于判定直接引语的说话人。
- narrator 是「我」对应的角色名，从原文里找；找不到写「我」。
- title 用原文标题，没有就给最短概括。
- dialogues：把该提成台词的句子标出来（含带引号的直接引语、以及「爷爷笑着说，见不到是好事」这类间接引语）。**text 必须是该句原文里逐字连续的一段子串**，不许改写、不许加字；speaker 从上下文判断，判断不出写「旁白」。没有台词的句子不要列。
- 严禁输出原文正文，只输出结构 JSON。只输出一个 JSON 对象。"""


# --------------------------------------------------------------------------
# 资产包：剧本 / 小说 → 角色、场景、道具的一致性锚点与关键提示词
# 铁律（沿用 adapt 的教训）：模型只输出结构 JSON，长提示词一律由服务端模板拼装。
#   · 模型重写长文本 → 90s → max_tokens 截断 → 502
#   · 结构 JSON + 模板 → 约 17s，且模板一改所有资产同步换风格
# --------------------------------------------------------------------------
SYSTEM_ASSETS = """你是短剧美术设定总监。只输出严格 JSON，不要解释文字，不要 Markdown 代码块。

你会拿到「剧本 / 小说原文」与「场次清单」。请提取本片需要预先制作的视觉资产，只输出结构数据，不要写长段描述文字。

输出格式：
{"style":{"anchor":"全局风格锚，20-40字","anchorEn":"同一风格的英文版，给本地 Flux 用，20词内，只写视觉风格不写剧情","negative":"通用负面词，逗号分隔"},
 "characters":[{"name":"水雷","aliases":["润土"],"priority":"P0","visibility":"全程",
   "age":"18岁","role":"主角","face":"脸型与五官，15字内","flaw":"一处可辨识瑕疵，12字内",
   "wardrobeHook":"一个服装或配饰记忆点，12字内","wardrobe":"服装一句话，20字内",
   "keyword":"固定关键词串：把 age、face、flaw、wardrobeHook、wardrobe 用中文逗号连成一句，40字内，例：18岁，圆脸细眉，右眉尾浅疤，颈挂红绳青玉牌，浅灰旧T恤",
   "keywordEn":"同一串的英文版，给本地 Flux 用，一句，40词内",
   "source":"script|inferred","evidence":["S1"],"sceneNos":[1,2]}],
 "scenes":[{"name":"爷爷家堂屋","priority":"P0","intExt":"内景","time":"黄昏",
   "props":["八仙桌","钟馗像"],"light":"主光与色温，20字内","lens":"镜头焦段，如 24mm广角",
   "sceneEn":"一句英文场景描述，给本地 Flux 用，30词内",
   "source":"script|inferred","evidence":["S1"],"sceneNos":[1]}],
 "props":[{"name":"黄纸铜钱","boundTo":["水雷"],"source":"script","evidence":["S2"]}]}

硬性规则：
- style.anchorEn 是 anchor 的英文视觉风格翻译，只写画种 / 材质 / 光线 / 色调，不要出现人物名、地名、剧情；本地 Flux 只吃英文，中文风格锚传进去等于没传。
- 角色：把同一人的不同称呼合并进 aliases（如 水雷 / 润土、小强 / 强子），严禁拆成两个资产。
- 一致性锚点：face / flaw / wardrobeHook 三项对每个角色都必须给，且同年龄段同性别的角色不得出现雷同组合；这是防止 AI 生成同一张脸的关键。
- keyword 必须可直接原样粘进每个镜头提示词，不要写成完整句子段落。
- keyword 各段之间**必须用中文逗号「，」分隔**，不许连成一长串无标点的字。
- 场景：按「视觉上可区分的场景」拆分，不要只按地点名去重。同一地名但陈设、光线、事件明显不同（例如喜宴长街与荒坟土坡）必须拆成不同资产；仅当跨场次是同一处连续空间才合并。sceneNos 只填该资产真正对应的场次。
- 允许为「设定里存在但本章未出场」的核心角色预建资产，此时 visibility 写「设定未出场」、source 写 inferred。
- source=script 的字段必须能在原文找到依据；推断出的视觉细节一律 source=inferred，且 evidence 必须给出场次编号。
- evidence 只能填场次清单里真实存在的编号（S 加场号）；sceneNos 只能填场次清单里真实存在的场号数字。
- 严禁输出长段提示词、严禁输出原文正文、严禁新增剧本里没有的情节、身世或结局。
- 只输出一个 JSON 对象。"""


# --------------------------------------------------------------------------
# Agent 注册表（架构思路来自 huobao-drama：workspace/prompts + workspace/skills）
#   · 角色 = registry.json 一条记录 + prompts/<id>.md + skills/<skill>/SKILL.md
#   · 文件是唯一事实来源，界面可在线编辑；改完无需重启（每次调用重新读盘）
#   · 文件缺失时回退到上面的内置常量，保证老部署不会 500
#   · 新增角色不改 Python 代码：add_agent() 写三处文件即可，走 /api/agents/<id>/run
# --------------------------------------------------------------------------
AGENTS_DIR = ROOT / "agents"
AGENT_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,40}$")
SKILL_ID_RE = re.compile(r"^[a-z0-9-]{1,48}$")


def parse_frontmatter(raw: str):
    """解析 SKILL.md / prompt 文件的 frontmatter，返回 (meta, body)。无 yaml 依赖。"""
    m = re.match(r"^---\r?\n([\s\S]*?)\r?\n---\r?\n?", raw)
    meta = {}
    body = raw
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip().strip('"').strip("'")
        body = raw[len(m.group(0)):]
    return meta, body.strip()


class AgentRegistry:
    def __init__(self, root: Path):
        self.root = root
        self.prompts = root / "prompts"
        self.skills = root / "skills"
        self.file = root / "registry.json"
        self.lock = threading.Lock()
        # 内置兜底：文件丢了也能跑（键为 agent id）
        self.builtin = {
            "adapt": SYSTEM_ADAPT, "parse": SYSTEM_PARSE, "plan": SYSTEM_PLAN,
            "storyboard": SYSTEM_SHOTS, "assets": SYSTEM_ASSETS,
        }
        for p in (self.prompts, self.skills):
            try:
                p.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass

    # ---------- 读 ----------
    def registry(self):
        try:
            d = json.loads(self.file.read_text(encoding="utf-8"))
            if isinstance(d.get("agents"), list):
                return d
        except (OSError, ValueError, AttributeError):
            pass
        return {"version": 1, "pipeline": [], "agents": []}

    def get(self, agent_id):
        for a in self.registry()["agents"]:
            if a.get("id") == agent_id:
                return a
        return None

    def skill_ids(self):
        """动态扫描：新建 SKILL.md 无需改代码、无需重启即可被发现。"""
        if not self.skills.exists():
            return []
        return sorted(p.parent.name for p in self.skills.glob("*/SKILL.md"))

    def prompt_file(self, agent_id):
        return self.prompts / (agent_id + ".md")

    def read_prompt(self, agent_id):
        f = self.prompt_file(agent_id)
        try:
            return f.read_text(encoding="utf-8")
        except OSError:
            return ""

    def skill_sections(self, agent_id):
        a = self.get(agent_id) or {}
        if a.get("injectSkills") is False:
            return ""
        parts = []
        for sid in a.get("skills") or []:
            f = self.skills / sid / "SKILL.md"
            try:
                _, body = parse_frontmatter(f.read_text(encoding="utf-8"))
                if body:
                    parts.append("## Skill: %s\n%s" % (sid, body))
            except OSError:
                continue
        if not parts:
            return ""
        return ("以下是该 Agent 专属的项目技能规范（SKILL.md），必须在不违背上方输出格式的前提下优先遵守。\n"
                "输出格式以上方【输出格式】为准，最终只输出一个 JSON 对象。\n\n" +
                "\n\n".join(parts))

    def system(self, agent_id, **vars):
        """拼装 system prompt：文件正文（剥 frontmatter）+ 技能全文 + 变量替换。"""
        if not AGENT_ID_RE.match(agent_id):
            raise ValueError("非法角色 id")
        raw = self.read_prompt(agent_id)
        if raw:
            meta, body = parse_frontmatter(raw)
            if not body.strip():
                body = self.builtin.get(agent_id, "")
        else:
            meta, body = {}, self.builtin.get(agent_id, "")
        if not body:
            raise ValueError("角色 %s 没有 prompt，请先在 Agent 工作台补写" % agent_id)
        extra = self.skill_sections(agent_id)
        text = body + ("\n\n" + extra if extra else "")
        for k, v in vars.items():
            text = text.replace("{%s}" % k, str(v))
        return text, meta

    def describe(self):
        reg = self.registry()
        out = []
        for a in reg["agents"]:
            item = dict(a)
            item["promptExists"] = self.prompt_file(a["id"]).exists()
            item["promptChars"] = len(self.read_prompt(a["id"]))
            item["skillFiles"] = [s for s in (a.get("skills") or [])
                                  if (self.skills / s / "SKILL.md").exists()]
            out.append(item)
        return {
            "version": reg.get("version", 1),
            "pipeline": reg.get("pipeline", []),
            "agents": out,
            "skills": self.skill_ids(),
            "dir": str(self.root),
        }

    # ---------- 写 ----------
    def _write_registry(self, reg):
        self.file.write_text(json.dumps(reg, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")

    def save_prompt(self, agent_id, content):
        if not AGENT_ID_RE.match(agent_id):
            raise ValueError("角色 id 只能用小写字母、数字、下划线和连字符")
        if not isinstance(content, str) or len(content) > 30000:
            raise ValueError("prompt 内容过长或格式不对")
        self.prompt_file(agent_id).write_text(content.rstrip() + "\n", encoding="utf-8")
        return True

    def patch_agent(self, agent_id, patch):
        with self.lock:
            reg = self.registry()
            hit = None
            for a in reg["agents"]:
                if a.get("id") == agent_id:
                    hit = a
                    break
            if not hit:
                raise ValueError("角色不存在")
            for k in ("name", "desc", "stage", "outputKey", "userTemplate",
                      "enabled", "injectSkills", "model"):
                if k in patch:
                    hit[k] = patch[k]
            self._write_registry(reg)
        return True

    def add_agent(self, spec):
        aid = str(spec.get("id") or "").strip()
        if not AGENT_ID_RE.match(aid):
            raise ValueError("角色 id 只能用小写字母开头，含小写字母/数字/下划线/连字符")
        name = _as(spec.get("name"), aid, 40)
        stage = _as(spec.get("stage"), "custom", 24)
        output = _as(spec.get("outputKey"), "result", 24)
        tmpl = str(spec.get("userTemplate") or
                   "请根据以下输入，按注入的 Skill 规范输出结果，只输出一个 JSON 对象。\n\n输入：\n{script}")
        skill_id = str(spec.get("skillId") or aid.replace("_", "-")).strip()
        if not SKILL_ID_RE.match(skill_id):
            skill_id = "skill-" + aid.replace("_", "-")[:20]
        with self.lock:
            reg = self.registry()
            if any(a.get("id") == aid for a in reg["agents"]):
                raise ValueError("角色已存在")
            reg["agents"].append({
                "id": aid, "name": name, "stage": stage, "order": len(reg["agents"]) + 1,
                "desc": _as(spec.get("desc"), "自定义角色", 120),
                "engine": "llm", "builtin": "", "outputKey": output, "generic": True,
                "skills": [skill_id], "input": ["script"], "enabled": True,
                "userTemplate": tmpl,
            })
            self._write_registry(reg)
        body = ("你是%s，只输出严格 JSON，不要解释文字，不要 Markdown 代码块。\n\n"
                "遵守注入的 Skill 规范，输出形如 {\"%s\":{...}} 的一个 JSON 对象。" % (name, output))
        self.save_prompt(aid, "---\nname: %s\nstage: %s\nmodel: \"\"\noutput: %s\n---\n\n%s"
                         % (name, stage, output, body))
        self.save_skill(skill_id,
                        "---\nname: %s\ndescription: %s 的自定义技能规范\n---\n\n# %s\n\n"
                        "在此写清输出契约、硬性规则与禁止项；保存后立即生效。\n"
                        "输出必须是一个 JSON 对象，根键为 `%s`。\n" % (skill_id, name, name, output))
        return True

    def delete_agent(self, agent_id):
        if agent_id in self.builtin or agent_id in ("frames",):
            raise ValueError("内建角色不能删除，可在界面里停用")
        with self.lock:
            reg = self.registry()
            left = [a for a in reg["agents"] if a.get("id") != agent_id]
            if len(left) == len(reg["agents"]):
                raise ValueError("角色不存在")
            reg["agents"] = left
            self._write_registry(reg)
        try:
            self.prompt_file(agent_id).unlink()
        except OSError:
            pass
        return True

    def read_skill(self, sid):
        if not SKILL_ID_RE.match(sid):
            raise ValueError("非法技能 id")
        f = self.skills / sid / "SKILL.md"
        try:
            return f.read_text(encoding="utf-8")
        except OSError:
            raise ValueError("技能不存在")

    def save_skill(self, sid, content):
        if not SKILL_ID_RE.match(sid):
            raise ValueError("技能 id 只能用小写字母、数字和连字符")
        if not isinstance(content, str) or len(content) > 30000:
            raise ValueError("技能内容过长或格式不对")
        d = self.skills / sid
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(content.rstrip() + "\n", encoding="utf-8")
        return True

    def delete_skill(self, sid):
        if not SKILL_ID_RE.match(sid):
            raise ValueError("非法技能 id")
        f = self.skills / sid / "SKILL.md"
        if not f.exists():
            raise ValueError("技能不存在")
        f.unlink()
        return True

    # ---------- 通用执行 ----------
    @staticmethod
    def input_blob(agent, payload):
        """把 payload 裁成可塞进 user prompt 的字符串片段（避免超长 / 花括号冲突）。"""
        blob = {}
        for key in ("script", "idea", "scenes", "shots", "pack", "text"):
            blob[key] = ""
        blob["script"] = str(payload.get("script") or payload.get("text") or "")[:24000]
        blob["idea"] = str(payload.get("idea") or blob["script"])[:6000]
        blob["text"] = blob["script"]
        shots = payload.get("shots") or []
        if isinstance(shots, list):
            slim = []
            for sh in shots[:60]:
                if not isinstance(sh, dict):
                    continue
                d = sh.get("detail") or {}
                slim.append({
                    "id": _as(sh.get("code") or sh.get("id"), "", 24),
                    "visual": _as(sh.get("visual"), "", 260),
                    "size": _as(sh.get("size"), "", 12),
                    "dialogue": _as(sh.get("dialogue"), "", 160),
                    "subject": _as(d.get("subject"), "", 160),
                    "action": _as(d.get("action"), "", 200),
                })
            blob["shots"] = json.dumps(slim, ensure_ascii=False)
        scenes = payload.get("scenes") or []
        if isinstance(scenes, list):
            blob["scenes"] = json.dumps(scenes[:40], ensure_ascii=False)[:12000]
        return blob

    def run(self, agent_id, payload):
        a = self.get(agent_id)
        if not a:
            raise ValueError("角色不存在")
        if a.get("enabled") is False:
            raise ValueError("角色已停用")
        if not a.get("generic"):
            raise ValueError("该角色是流水线内建阶段，请走 %s" % (a.get("endpoint") or "对应接口"))
        system, meta = self.system(agent_id)
        tmpl = str(a.get("userTemplate") or "请根据以下输入输出一个 JSON 对象。\n\n{script}")
        user = tmpl
        for k, v in self.input_blob(a, payload).items():
            user = user.replace("{%s}" % k, v)
        data, model = call_llm_json(system, user,
                                    str(a.get("outputKey") or "result"), 240,
                                    expect_list=False)
        return {"agent": agent_id, "outputKey": a.get("outputKey"),
                "result": data, "model": model, "promptChars": len(system)}


AGENTS = AgentRegistry(AGENTS_DIR)


class AgentDisabledError(ValueError):
    """角色被停用：属于配置问题，不该报成「模型结果解析失败」。"""


def agent_system(agent_id, **vars):
    """流水线阶段统一入口：读注册表 → 检查启用状态 → 拼 prompt + 技能。"""
    a = AGENTS.get(agent_id)
    if a and a.get("enabled") is False:
        raise AgentDisabledError(
            "角色「%s」已停用，请在 Agent 工作台启用后重试" % a.get("name", agent_id))
    return AGENTS.system(agent_id, **vars)[0]


# 默认风格必须是「中性」的：这是没跑 AI 分解、用户也没设风格时的兜底，
# 原先写死「中式民俗恐怖」会把任何剧本（例如雨夜便利店）都串成民俗恐怖味。
STYLE_ANCHOR_DEFAULT = "写实电影质感 · 35mm 胶片颗粒 · 冷调 · 无滤镜磨皮"
STYLE_ANCHOR_EN_DEFAULT = ("photorealistic cinematic film still, 35mm film grain, "
                           "cool desaturated color grade, natural skin texture, "
                           "no beautification filter")
# 物体（道具 / 场景）不能带人像词：串里出现 "skin texture" 时，Flux 会直接画人。
# 同一个风格锚按用途取不同英文，比每处模板各写一套更不容易漏。
STYLE_ANCHOR_EN_OBJECT = ("photorealistic, 35mm film grain, "
                          "cool desaturated color grade, no beautification filter")
# 命中即视为人像词：只有画人的模板才允许出现，物体类一律剔除。
PERSON_ONLY_TERMS = ("skin", "face", "portrait", "beauty", "hair", "eye",
                     "makeup", "hand", "finger", "body", "lip")
NEGATIVE_DEFAULT = ("模糊，低清晰度，多余的手指，畸形的四肢，现代感强的插画风，3D渲染，"
                    "动漫感，塑料皮肤，过度磨皮，脸部对称过度，英文字幕，水印，logo，鲜艳高饱和，暖色调")
SIZE_EN = {"远景": "extreme wide shot", "全景": "wide shot", "中景": "medium shot",
           "近景": "medium close-up", "特写": "close-up"}

TURNAROUND_TMPL = (
    "角色设定表，三视图并排（最左为正面全身，中间为侧面全身，最右为背面全身，"
    "三者等比例、足底对齐），全身远景，纯白色背景，无阴影投射。\n"
    "{keyword}\n"
    "面部特征：{face}；可辨识瑕疵：{flaw}。\n"
    "服装：{wardrobe}。配饰与记忆点：{wardrobeHook}。\n"
    "{style}。写实电影质感，自然柔和的顶侧光，8k超高清，哈苏中画幅镜头拍摄；"
    "皮肤有真实毛孔与不均匀的肤色过渡，布料纤维与磨损痕迹清晰可见。表情：中性。\n"
    "比例 3:2 横版。负面词：{negative}"
)
FACE_SHEET_TMPL = (
    "生成参照人物面部特写和人物全身三视图：最左边是人物面部超大特写（占画面高度的三分之二），"
    "右边依次放正面全身、侧面全身、背面全身，四者位于同一画面内，等比例、足底对齐，纯白色背景。\n"
    "{keyword}\n面部特征：{face}；瑕疵：{flaw}；配饰：{wardrobeHook}。\n"
    "{style}。写实电影质感，8k超高清。比例 3:2 横版。"
)
CONCEPT_TMPL = (
    "场景概念图，{name}{tags}。\n"
    "陈设与细节：{props}。\n"
    "物理光影：{light}。\n"
    "材质细节：真实材质与岁月痕迹，无塑料感，无过度磨皮。\n"
    "镜头：{lens}，纵深构图。{style}。写实电影质感，35mm 胶片，浓郁颗粒，"
    "高动态范围，深邃阴影，8k超高清。\n"
    "比例 16:9 横版；核心场景另出 2.35:1 宽银幕版。负面词：{negative}"
)
FRAME_TMPL = (
    "{style}。单帧电影剧照，{aspect}，本镜第 0 帧（起始帧）："
    "不要三视图、不要设定表、不要拼贴图、不要画面文字。\n"
    "出场角色（固定特征原样保持，不得重写）：{keywords}\n"
    "场景：{scene}；{scene_props}；{scene_light}。\n"
    "画面主体：{subject}。动作起点：{action}。\n"
    "构图与机位：{composition}；景别：{size}；运镜：{camera}。\n"
    "光线：{light}。情绪：{mood}。\n"
    "{lens}。写实电影质感，35mm 胶片颗粒，高动态范围，深邃阴影，8k超高清。\n"
    "负面词：{negative}"
)


def build_asset_pack(data, scenes):
    """模型结构 JSON → 完整资产包（含三视图 / 概念图提示词） + 覆盖与锚点校验。"""
    valid_nos, cast_names = set(), set()
    for s in scenes:
        if not isinstance(s, dict):
            continue
        try:
            valid_nos.add(int(s.get("no")))
        except (TypeError, ValueError):
            pass
        for n in (s.get("characters") or []):
            if not isinstance(n, str):
                continue
            name = re.sub(r"[（(].*?[）)]", "", n).strip()
            if name and name not in ("旁白", "画外音", "OS", "V.O."):
                cast_names.add(name)
    valid_ev = set("S%d" % n for n in valid_nos)

    style_raw = data.get("style") if isinstance(data.get("style"), dict) else {}
    style = _as(style_raw.get("anchor"), STYLE_ANCHOR_DEFAULT, 160)
    style_en = _as(style_raw.get("anchorEn"), STYLE_ANCHOR_EN_DEFAULT, 200)
    negative = _as(style_raw.get("negative"), NEGATIVE_DEFAULT, 500)
    warnings = []

    def evidence_of(raw, name, kind):
        ev = [e for e in _alist(raw.get("evidence")) if not valid_ev or e in valid_ev]
        src = _as(raw.get("source"), "inferred", 20)
        if src not in ("script", "inferred"):
            src = "inferred"
        if src == "inferred" and not ev:
            warnings.append("%s「%s」是 AI 推断但没给原文出处，请人工核对" % (kind, name))
        return src, ev

    chars, seen_char = [], {}
    for raw in (data.get("characters") or [])[:40]:
        if not isinstance(raw, dict):
            continue
        name = _as(raw.get("name"), "", 24)
        if not name:
            continue
        if name in seen_char:
            for al in _alist(raw.get("aliases")):
                if al != name and al not in seen_char[name]["aliases"]:
                    seen_char[name]["aliases"].append(al)
            continue
        face = _as(raw.get("face"), "未指定", 60)
        flaw = _as(raw.get("flaw"), "未指定", 60)
        hook = _as(raw.get("wardrobeHook"), "未指定", 60)
        wardrobe = _as(raw.get("wardrobe"), "未指定", 90)
        age = _as(raw.get("age"), "", 24)
        role = _as(raw.get("role"), "", 24)
        keyword = _as(raw.get("keyword"), "", 200) or "，".join(
            x for x in (age, face, flaw, hook, wardrobe) if x and x != "未指定")
        # 模型有时把 five 段连成一长串没有标点的字，读不动也当不好提示词 —— 按锚点重组
        if keyword and "，" not in keyword and "," not in keyword and len(keyword) > 14:
            bits = [x for x in (age, face, flaw, hook, wardrobe) if x and x != "未指定"]
            if len(bits) >= 2:
                keyword = "，".join(bits)
        src, ev = evidence_of(raw, name, "角色")
        nos = [n for n in _ints(raw.get("sceneNos")) if not valid_nos or n in valid_nos]
        item = {
            "id": "c:" + name, "kind": "character", "code": "C%02d" % (len(chars) + 1),
            "name": name, "aliases": [a for a in _alist(raw.get("aliases")) if a != name],
            "priority": _priority(raw.get("priority")),
            "visibility": _as(raw.get("visibility"), "未注明", 24),
            "age": age, "role": role, "wardrobe": wardrobe, "appearance": face,
            "anchors": {"face": face, "flaw": flaw, "wardrobeHook": hook},
            "keyword": keyword,
            "keywordEn": _as(raw.get("keywordEn"), "", 300),
            "source": src, "evidence": ev, "sceneNos": nos,
            "weight": 5 if _priority(raw.get("priority")) == "P0" else 3,
            "refImage": "", "refName": "", "locked": False, "touched": {},
        }
        item["prompts"] = {
            "turnaround": TURNAROUND_TMPL.format(
                keyword=keyword, face=face, flaw=flaw, wardrobe=wardrobe,
                wardrobeHook=hook, style=style, negative=negative),
            "faceSheet": FACE_SHEET_TMPL.format(
                keyword=keyword, face=face, flaw=flaw,
                wardrobeHook=hook, style=style),
            "lineart": "转彩铅素描",
        }
        chars.append(item)
        seen_char[name] = item

    scenes_out = []
    for raw in (data.get("scenes") or [])[:30]:
        if not isinstance(raw, dict):
            continue
        name = _as(raw.get("name"), "", 40)
        if not name:
            continue
        props = _alist(raw.get("props"), 12, 40)
        light = clean_placeholder(raw.get("light"), 80)
        lens_raw = _as(raw.get("lens"), "35mm", 40)
        lm = re.search(r"\d{2,3}\s*mm", lens_raw, flags=re.I)
        lens = lm.group(0).replace(" ", "") if lm else "35mm"
        if "广角" in lens_raw:
            lens += "广角"
        int_ext = clean_placeholder(raw.get("intExt"), 12)
        tm = clean_placeholder(raw.get("time"), 12)
        src, ev = evidence_of(raw, name, "场景")
        nos = [n for n in _ints(raw.get("sceneNos")) if not valid_nos or n in valid_nos]
        item = {
            "id": "sc:%s|%s|%s" % (int_ext, name, tm), "kind": "scene",
            "code": "S%02d" % (len(scenes_out) + 1), "name": name,
            "priority": _priority(raw.get("priority")), "intExt": int_ext, "time": tm,
            "appearance": "；".join(props), "anchors": {"props": props, "light": light, "lens": lens},
            "sceneEn": _as(raw.get("sceneEn"), "", 300),
            "source": src, "evidence": ev, "sceneNos": nos,
            "refImage": "", "refName": "", "locked": False, "starred": False,
        }
        tags = "".join("，" + x for x in (int_ext, tm) if x)
        item["prompts"] = {
            "concept": CONCEPT_TMPL.format(
                name=name, tags=tags,
                props="、".join(props) or "按剧本场次描述", light=light,
                lens=lens, style=style, negative=negative),
            "wide": "同一场景改 2.35:1 宽银幕构图，其余描述不变。",
        }
        scenes_out.append(item)

    props_out = []
    for raw in (data.get("props") or [])[:30]:
        if not isinstance(raw, dict):
            continue
        name = _as(raw.get("name"), "", 40)
        if not name:
            continue
        src, ev = evidence_of(raw, name, "道具")
        props_out.append({
            "id": "p:" + name, "kind": "prop", "code": "P%02d" % (len(props_out) + 1),
            "name": name, "boundTo": _alist(raw.get("boundTo")),
            "appearance": _as(raw.get("appearance"), "", 200) or name,
            "propEn": _as(raw.get("propEn"), "", 300),
            "source": src, "evidence": ev, "refImage": "", "refName": "",
        })

    covered = set()
    for c in chars:
        covered.add(c["name"])
        covered.update(c["aliases"])
    missing_chars = sorted(n for n in cast_names if n not in covered)
    if missing_chars:
        warnings.append("剧本里有 %d 个角色没有对应资产：%s" %
                        (len(missing_chars), "、".join(missing_chars[:8])))
    covered_nos = set()
    for s in scenes_out:
        covered_nos.update(s["sceneNos"])
    missing_nos = sorted(valid_nos - covered_nos)
    if missing_nos:
        warnings.append("有 %d 个场次没有映射到场景资产：%s" %
                        (len(missing_nos), "、".join("第%d场" % n for n in missing_nos[:8])))
    seen_sig = {}
    for c in chars:
        sig = (c["age"], c["anchors"]["face"], c["anchors"]["flaw"], c["anchors"]["wardrobeHook"])
        if sig in seen_sig:
            warnings.append("角色「%s」与「%s」的锚点组合雷同，容易生成同一张脸" %
                            (seen_sig[sig], c["name"]))
        seen_sig[sig] = c["name"]

    return {
        "style": {
            "anchor": style, "anchorEn": style_en, "negative": negative,
            "aspect": {"turnaround": "3:2", "portrait": "3:4",
                       "concept": "16:9", "coreWide": "2.35:1"},
            "generationOrder": [c["code"] for c in chars if c["priority"] == "P0"] +
                               [s["code"] for s in scenes_out if s["priority"] == "P0"],
        },
        "assets": {"characters": chars, "scenes": scenes_out, "props": props_out},
        "coverage": {
            "scriptCharacters": len(cast_names), "assetCharacters": len(chars),
            "charactersCovered": len(cast_names) - len(missing_chars),
            "scenesTotal": len(valid_nos), "scenesCovered": len(valid_nos) - len(missing_nos),
            "assetScenes": len(scenes_out), "assetProps": len(props_out),
            "inferred": sum(1 for x in chars + scenes_out + props_out if x["source"] == "inferred"),
        },
        "warnings": warnings,
    }


def build_frame_prompts(shots, pack, aspect="16:9"):
    """分镜表 + 资产包 → 每镜起始帧提示词。纯代码拼装，不调模型。"""
    assets = pack.get("assets") if isinstance(pack.get("assets"), dict) else {}
    chars = assets.get("characters") or []
    scenes = assets.get("scenes") or []
    st = pack.get("style") if isinstance(pack.get("style"), dict) else {}
    style = _as(st.get("anchor"), STYLE_ANCHOR_DEFAULT, 160)
    negative = _as(st.get("negative"), NEGATIVE_DEFAULT, 500)

    def scene_for(no):
        for s in scenes:
            if no in (s.get("sceneNos") or []):
                return s
        return None

    def chars_for(shot):
        # 判定「出场角色」只认画面描述与台词，不认 notes / detail 卡：
        # 分镜卡里常写剧情解释（如「让娶鬼媳妇这件事有落点」），
        # 角色并未出现在画面里，拿它匹配会误召回未出场角色。
        blob = " ".join(_as(shot.get(k), "", 600) for k in
                        ("visual", "dialogue", "speaker"))
        return [c for c in chars if any(
            n and n in blob for n in [c["name"]] + (c.get("aliases") or []))]

    frames, with_chars, with_scene = [], 0, 0
    for i, shot in enumerate(shots[:200]):
        if not isinstance(shot, dict):
            continue
        detail = shot.get("detail") if isinstance(shot.get("detail"), dict) else {}
        code = _as(shot.get("code"), "SHOT-%03d" % (i + 1), 40)
        try:
            no = int(shot.get("sceneNo"))
        except (TypeError, ValueError):
            no = -1
        sc = scene_for(no)
        chs = chars_for(shot)
        if chs:
            with_chars += 1
        if sc:
            with_scene += 1
        subject = _as(detail.get("subject")) or _as(shot.get("visual"), "按剧本本镜内容", 300)
        action = _as(detail.get("action")) or "动作起点按本镜剧本"
        composition = _as(detail.get("composition")) or "平视机位，纵深构图"
        size = _as(shot.get("size"), "中景", 12)
        camera = _as(detail.get("camera")) or "固定机位"
        light = _as(detail.get("light")) or (sc and sc["anchors"]["light"]) or "冷调自然光"
        mood = _as(detail.get("mood")) or "紧绷"
        sc_anchor = sc["anchors"] if sc else {"props": [], "light": "", "lens": "35mm"}
        prompt_cn = FRAME_TMPL.format(
            style=style, aspect=aspect,
            keywords="；".join(c["keyword"] for c in chs) or "本镜无明确出场角色，不新增人物",
            scene=(sc and sc["name"]) or "本场未写地点",
            scene_props="、".join(sc_anchor["props"]) or "按剧本场次描述",
            scene_light=sc_anchor["light"] or "按场次自然光",
            subject=subject, action=action, composition=composition,
            size=size, camera=camera, light=light, mood=mood,
            lens=sc_anchor["lens"], negative=negative,
        )
        en_bits = [
            "cinematic film still, single frame, opening frame of the shot, %s" % aspect,
            ", ".join(c["keywordEn"] for c in chs if c.get("keywordEn")),
            (sc and sc.get("sceneEn")) or "",
            SIZE_EN.get(size, "medium shot"),
            "35mm film grain, high dynamic range, deep shadows, real skin texture, "
            "photorealistic, 8k, no illustration, no 3d render, no text, no collage",
        ]
        frames.append({
            "code": code, "sceneNo": no, "size": size,
            "aspect": aspect, "prompt": prompt_cn,
            "promptEn": ", ".join(x for x in en_bits if x),
            "negative": negative,
            "keywords": [c["keyword"] for c in chs],
            "refAssets": [c["code"] for c in chs] + ([sc["code"]] if sc else []),
            "firstFrameUrl": "",
        })
    return {
        "frames": frames, "aspect": aspect, "style": style, "negative": negative,
        "stats": {"total": len(frames), "withCharacters": with_chars,
                  "withScene": with_scene,
                  "avgPromptLength": int(sum(len(f["prompt"]) for f in frames) / len(frames))
                  if frames else 0},
    }


# --------------------------------------------------------------------------
# 资产包导出：Markdown / CSV / 机器可读 JSON + 整个项目 ZIP
# 原则：模型只出结构，这里的正文全部由模板渲染 —— 与 build_asset_pack 同一条铁律。
# --------------------------------------------------------------------------
ASSET_KIND_CN = {"character": "角色", "scene": "场景", "prop": "道具"}
SOURCE_CN = {"script": "剧本原文", "inferred": "AI 推断", "manual": "手工新增", "user": "手工修改"}


def merge_pack_assets(pack, assets):
    """把界面上的手改（外观 / 服装 / 关键词 / 锁定 / 参考图）盖回资产包，导出即所见。"""
    pack = pack if isinstance(pack, dict) else {}
    assets = assets if isinstance(assets, dict) else {}

    def index_of(kind, key):
        return {(a.get(kind) or ""): a for a in (assets.get(key) or []) if isinstance(a, dict)}

    by_name = {
        "character": index_of("name", "characters"),
        "scene": index_of("name", "scenes"),
        "prop": index_of("name", "props"),
    }
    out = json.loads(json.dumps(pack, ensure_ascii=False))
    pa = out.get("assets") if isinstance(out.get("assets"), dict) else {}
    for kind, key in (("character", "characters"), ("scene", "scenes"), ("prop", "props")):
        for item in (pa.get(key) or []):
            src = by_name[kind].get(item.get("name") or "")
            if not src:
                continue
            for f in ("appearance", "wardrobe", "keyword", "age", "role",
                      "refName", "locked", "starred"):
                if src.get(f) not in (None, ""):
                    item[f] = src[f]
            # 参考图本身走 assets/refs/，不塞进 json —— 否则 base64 会重复占几 MB
            item["hasRef"] = bool(src.get("refImage"))
            if src.get("touched"):
                item["source"] = item.get("source") or "inferred"
                item["edited"] = sorted(src["touched"].keys())
    return out


def _md(v, limit=400):
    t = str(v if v is not None else "").replace("\r", " ").replace("\n", " ").strip()
    return t.replace("|", "\\|")[:limit] or "—"


def render_assets_md(pack, meta=None):
    """结构复刻参考文档：清单表 / 锚点表 / 三视图 / 概念图 / 参数 / 校验。"""
    pack = pack if isinstance(pack, dict) else {}
    meta = meta if isinstance(meta, dict) else {}
    a = pack.get("assets") if isinstance(pack.get("assets"), dict) else {}
    chars = [x for x in (a.get("characters") or []) if isinstance(x, dict)]
    scenes = [x for x in (a.get("scenes") or []) if isinstance(x, dict)]
    props = [x for x in (a.get("props") or []) if isinstance(x, dict)]
    st = pack.get("style") if isinstance(pack.get("style"), dict) else {}
    cov = pack.get("coverage") if isinstance(pack.get("coverage"), dict) else {}
    warns = [str(w) for w in (pack.get("warnings") or [])]

    L = []
    title = meta.get("title") or "未命名项目"
    L.append("# 《%s》资产包 · 自动分解结果\n" % title)
    L.append("> 生成时间：%s ｜ 模型：%s ｜ 资产：%d 角色 / %d 场景 / %d 道具" % (
        _dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        meta.get("model") or "本地模板", len(chars), len(scenes), len(props)))
    if cov:
        L.append("> 覆盖：角色 %s/%s ｜ 场次 %s/%s ｜ AI 推断 %s 项" % (
            cov.get("charactersCovered", 0), cov.get("scriptCharacters", 0),
            cov.get("scenesCovered", 0), cov.get("scenesTotal", 0), cov.get("inferred", 0)))
    L.append("")
    L.append("## 一、资产清单\n")
    L.append("| 编号 | 类型 | 优先级 | 名称 | 别名 | 出场场次 | 来源 |")
    L.append("| --- | --- | --- | --- | --- | --- | --- |")
    for x in chars + scenes + props:
        nos = "、".join(str(n) for n in (x.get("sceneNos") or [])) or "—"
        L.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            _md(x.get("code"), 8), ASSET_KIND_CN.get(x.get("kind"), "—"),
            _md(x.get("priority"), 4), _md(x.get("name"), 30),
            _md("、".join(x.get("aliases") or []), 30), _md(nos, 40),
            SOURCE_CN.get(x.get("source"), _md(x.get("source"), 10))))
    L.append("")

    L.append("## 二、一致性锚点（固定关键词串 · 原样粘贴，禁止重写）\n")
    L.append("| 编号 | 名称 | 面部 | 瑕疵 / 灯光 | 服装 / 陈设记忆点 | 固定关键词串 |")
    L.append("| --- | --- | --- | --- | --- | --- |")
    for x in chars:
        an = x.get("anchors") or {}
        L.append("| %s | %s | %s | %s | %s | `%s` |" % (
            _md(x.get("code"), 8), _md(x.get("name"), 24), _md(an.get("face"), 60),
            _md(an.get("flaw"), 60), _md(an.get("wardrobeHook"), 60),
            _md(x.get("keyword"), 200)))
    for x in scenes:
        an = x.get("anchors") or {}
        L.append("| %s | %s | %s | %s | %s | `%s` |" % (
            _md(x.get("code"), 8), _md(x.get("name"), 24), "—",
            _md(an.get("light"), 60), _md("、".join(an.get("props") or []), 60),
            _md("，".join(y for y in (x.get("name"), x.get("intExt"), x.get("time"),
                                     an.get("light")) if y), 200)))
    L.append("")

    L.append("## 三、角色三视图 / 四视图提示词\n")
    for x in chars:
        p = x.get("prompts") or {}
        L.append("### %s %s（%s · %s）" % (x.get("code") or "", x.get("name") or "",
                                          x.get("priority") or "P1",
                                          x.get("role") or x.get("visibility") or "角色"))
        if x.get("keyword"):
            L.append("\n**固定关键词串（复制到每个镜头，一字不改）**\n\n```\n%s\n```" % x["keyword"])
        for label, key in (("三视图", "turnaround"), ("面部四视图", "faceSheet")):
            if p.get(key):
                L.append("\n**%s**\n\n```\n%s\n```" % (label, p[key]))
        if p.get("lineart"):
            L.append("\n**线稿**：%s" % p["lineart"])
        L.append("")

    L.append("## 四、场景概念图提示词\n")
    for x in scenes:
        p = x.get("prompts") or {}
        L.append("### %s %s（%s · %s%s）" % (
            x.get("code") or "", x.get("name") or "", x.get("priority") or "P1",
            x.get("intExt") or "未注明", (" · " + x["time"]) if x.get("time") else ""))
        if p.get("concept"):
            L.append("\n```\n%s\n```" % p["concept"])
        if p.get("wide"):
            L.append("\n**宽银幕版**：%s" % p["wide"])
        L.append("")

    if props:
        L.append("## 五、道具\n")
        L.append("| 编号 | 名称 | 描述 | 绑定场景 | 来源 |")
        L.append("| --- | --- | --- | --- | --- |")
        for x in props:
            L.append("| %s | %s | %s | %s | %s |" % (
                _md(x.get("code"), 8), _md(x.get("name"), 30), _md(x.get("appearance"), 60),
                _md("、".join(x.get("boundTo") or []), 40),
                SOURCE_CN.get(x.get("source"), "—")))
        L.append("")

    L.append("## 六、全局参数\n")
    L.append("- **风格锚**：%s" % (st.get("anchor") or STYLE_ANCHOR_DEFAULT))
    L.append("- **风格锚（Flux 英文）**：%s" % (st.get("anchorEn") or STYLE_ANCHOR_EN_DEFAULT))
    L.append("- **负面词**：%s" % (st.get("negative") or NEGATIVE_DEFAULT))
    asp = st.get("aspect") or {}
    L.append("- **画幅**：三视图 %s ／ 立绘 %s ／ 概念图 %s ／ 核心宽幕 %s" % (
        asp.get("turnaround", "3:2"), asp.get("portrait", "3:4"),
        asp.get("concept", "16:9"), asp.get("coreWide", "2.35:1")))
    order = st.get("generationOrder") or []
    L.append("- **建议生成顺序**：%s" % (" → ".join(order) or "按 P0 优先"))
    L.append("- **一致性提醒**：先把 P0 角色的皮肤质感与脸型基准定下来，再铺群演；"
             "同类型角色靠「脸型 + 瑕疵 + 服装」三者差异化。\n")

    L.append("## 七、校验\n")
    if warns:
        for w in warns:
            L.append("- ⚠️ %s" % w)
    else:
        L.append("- ✅ 覆盖率、别名归并、锚点唯一性、溯源完整性全部通过。")
    L.append("")
    L.append("---\n")
    L.append("由 ShortPlay Studio 自动生成。AI 推断项已标注来源，请人工过一遍再出图。")
    return "\n".join(L) + "\n"


def render_assets_csv(pack):
    """人工核对用：一行一个资产，字段扁平化。"""
    a = (pack or {}).get("assets") if isinstance((pack or {}).get("assets"), dict) else {}
    cols = ["编号", "类型", "优先级", "名称", "别名", "年龄", "身份", "内外景", "时间",
            "面部", "瑕疵", "服装记忆点", "陈设", "灯光", "镜头", "固定关键词串",
            "出场场次", "来源", "原文出处", "参考图", "已锁定"]
    rows = [cols]
    for kind, key in (("character", "characters"), ("scene", "scenes"), ("prop", "props")):
        for x in (a.get(key) or []):
            if not isinstance(x, dict):
                continue
            an = x.get("anchors") or {}
            rows.append([
                x.get("code") or "", ASSET_KIND_CN.get(kind, kind), x.get("priority") or "",
                x.get("name") or "", "、".join(x.get("aliases") or []),
                x.get("age") or "", x.get("role") or "",
                x.get("intExt") or "", x.get("time") or "",
                an.get("face") or "", an.get("flaw") or "", an.get("wardrobeHook") or "",
                "、".join(an.get("props") or []) or x.get("appearance") or "",
                an.get("light") or "", an.get("lens") or "",
                x.get("keyword") or "", "、".join(str(n) for n in (x.get("sceneNos") or [])),
                SOURCE_CN.get(x.get("source"), x.get("source") or ""),
                "、".join(x.get("evidence") or []),
                "有" if x.get("refImage") else "无", "是" if x.get("locked") else "否",
            ])

    def cell(v):
        t = str(v if v is not None else "").replace("\r", " ").replace("\n", " ")
        return '"%s"' % t.replace('"', '""') if any(c in t for c in ',"') else t

    return "\ufeff" + "\n".join(",".join(cell(c) for c in r) for r in rows) + "\n"


def asset_prompts_payload(pack, meta=None):
    """给批量出图脚本消费：一条提示词一个对象，字段不含中文说明。"""
    pack = pack if isinstance(pack, dict) else {}
    a = pack.get("assets") if isinstance(pack.get("assets"), dict) else {}
    st = pack.get("style") if isinstance(pack.get("style"), dict) else {}
    out = []
    for x in (a.get("characters") or []):
        p = x.get("prompts") or {}
        for kind in ("turnaround", "faceSheet"):
            if p.get(kind):
                out.append({
                    "code": x.get("code"), "name": x.get("name"), "kind": kind,
                    "aspect": "3:2", "prompt": p[kind],
                    "keyword": x.get("keyword") or "",
                    "refName": x.get("refName") or "",
                })
    for x in (a.get("scenes") or []):
        p = x.get("prompts") or {}
        if p.get("concept"):
            out.append({
                "code": x.get("code"), "name": x.get("name"), "kind": "concept",
                "aspect": "16:9", "prompt": p["concept"],
                "keyword": x.get("sceneEn") or "", "refName": x.get("refName") or "",
            })
    return {
        "style": {"anchor": st.get("anchor") or STYLE_ANCHOR_DEFAULT,
                  "anchorEn": st.get("anchorEn") or STYLE_ANCHOR_EN_DEFAULT,
                  "negative": st.get("negative") or NEGATIVE_DEFAULT},
        "order": st.get("generationOrder") or [],
        "title": (meta or {}).get("title") or "",
        "prompts": out,
    }


def _pil_image():
    """Pillow 只是可选的加速件：拿不到就返回 None，调用方自己退化。"""
    try:
        from PIL import Image
        return Image
    except ImportError:
        pass
    try:
        # 服务被 start.bat / 托管进程拉起时，user site 可能没进 sys.path
        import site as _site
        p = _site.getusersitepackages()
        if isinstance(p, str) and p and p not in sys.path:
            sys.path.append(p)
        from PIL import Image
        return Image
    except Exception:
        return None


REF_MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "webp": "image/webp", "gif": "image/gif", "bmp": "image/bmp",
            "avif": "image/avif"}


def _decode_data_url(data):
    """data:image/png;base64,xxx → (bytes, ext)；不认识的返回 (b"", "")。"""
    m = re.match(r"^data:image/(png|jpeg|jpg|webp|gif|bmp|avif);base64,([A-Za-z0-9+/=\s]+)$",
                 str(data or "").strip(), re.I)
    if not m:
        return b"", ""
    ext = {"jpeg": "jpg", "jpg": "jpg"}.get(m.group(1).lower(), m.group(1).lower())
    try:
        return base64.b64decode(m.group(2)), ext
    except Exception:
        return b"", ""


def _ref_bytes(ref):
    """参考图取值：老项目是 dataURL，新项目是一个存盘地址。→ (bytes, ext)"""
    data = str(ref or "").strip()
    m = re.match(r"^/api/projects/ref\?id=([A-Za-z0-9_-]+)&f=([A-Za-z0-9]+\.[a-z0-9]+)$", data)
    if m:
        try:
            raw, _mime = project_ref_read(m.group(1), m.group(2))
        except ValueError:
            return b"", ""
        return raw, m.group(2).rsplit(".", 1)[-1].lower()
    return _decode_data_url(data)


def build_export_zip(payload):
    """把资产包 + 分镜 + 剧本 + 参考图打成一个 zip。文本由前端渲染，资产正文由这里渲染。"""
    title = _as(payload.get("title"), "短剧", 60)
    safe = re.sub(r'[\\/:*?"<>|\s]+', "_", title) or "shortplay"
    stamp = _as(payload.get("stamp"), _dt.datetime.now().strftime("%Y%m%d"), 12)
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    meta.setdefault("title", title)
    pack = merge_pack_assets(payload.get("pack") or {}, payload.get("assets") or {})

    buf = io.BytesIO()
    written = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        def put(name, text):
            z.writestr(name, str(text).encode("utf-8"))
            written.append(name)

        # 前端已经渲染好的文本（剧本 / 分镜表 / 视频提示词 …）
        for f in (payload.get("files") or []):
            if not isinstance(f, dict):
                continue
            name = _as(f.get("name"), "", 160).replace("..", "_")
            if not name:
                continue
            put(name, f.get("text") or "")

        # 资产三件套：正文在服务端渲染，保证与参考文档结构一致
        put("assets/assets.json", json.dumps(pack, ensure_ascii=False, indent=2))
        put("assets/assets.md", render_assets_md(pack, meta))
        put("assets/assets.csv", render_assets_csv(pack))
        put("assets/asset-prompts.json",
            json.dumps(asset_prompts_payload(pack, meta), ensure_ascii=False, indent=2))

        # 参考图：原文件直接进 zip（不压缩），单张上限 24MB，超了跳过并记账
        skipped = []
        for i, r in enumerate(payload.get("refs") or []):
            if not isinstance(r, dict):
                continue
            raw, ext = _ref_bytes(r.get("data"))
            if not raw:
                continue
            if len(raw) > 24 * 1024 * 1024:
                skipped.append(_as(r.get("name"), "ref-%d" % i, 60))
                continue
            name = _as(r.get("name"), "ref-%02d.%s" % (i + 1, ext or "png"), 80)
            if not name.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".avif")):
                name += "." + (ext or "png")
            path = "assets/refs/" + re.sub(r'[\\/:*?"<>|]+', "_", name)
            z.writestr(path, raw)
            written.append(path)

        manifest = {
            "title": title, "stamp": stamp,
            "generatedAt": _dt.datetime.now().isoformat(timespec="seconds"),
            "model": meta.get("model") or "", "mode": meta.get("mode") or "",
            "stats": payload.get("stats") or {},
            "coverage": pack.get("coverage") or {},
            "warnings": pack.get("warnings") or [],
            "skippedRefs": skipped,
            "files": written,
        }
        put("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

        lines = [
            "《%s》资产与分镜导出包" % title,
            "=" * 40,
            "生成时间：%s" % _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "大模型：%s" % (meta.get("model") or "离线规则引擎"),
            "",
            "目录说明",
            "  assets/assets.md            资产包正文（清单/锚点/三视图/概念图/参数/校验），可直接粘进豆包、即梦",
            "  assets/assets.csv           同一份数据的人工核对表（Excel 可直接打开）",
            "  assets/asset-prompts.json   机器可读的提示词清单，供批量出图脚本消费",
            "  assets/assets.json          完整资产包（含每个资产的提示词与溯源字段）",
            "  assets/refs/                已挂上的参考图",
            "  script/                     剧本原文与 AI 转写稿",
            "  storyboard/                 分镜表（csv / md / txt / json）与每镜起始帧提示词",
            "  video/video-prompts.json    出片提示词（含 preflight 预检结果）",
            "",
            "下面这几条是这套资产包的使用规矩，别跳：",
            "  1. 角色的「固定关键词串」在每个镜头里原样粘贴，禁止重写 —— 一致性全靠它。",
            "  2. 先出 P0 角色的三视图定基准，再铺其他角色，最后补群演。",
            "  3. AI 推断项的 assets.md 里标了来源，出图前请人工过一遍。",
            "  4. 双图输入（线稿 + 色彩参考）当前出片端不支持，只能压成单张参考图。",
            "",
        ]
        if skipped:
            lines.append("以下参考图超过 24MB 未打包（原图太大，压缩后再挂会失真，故跳过）：%s"
                         % "、".join(skipped))
        put("README.txt", "\n".join(lines))

    return buf.getvalue(), "%s_资产与分镜_%s.zip" % (safe, stamp)


# --------------------------------------------------------------------------
# 稿子导入：.docx（OOXML）只取正文纯文本，纯标准库，不落盘、不外传
#   · .docx = zip 包，正文在 word/document.xml
#   · 只取 w:p（段）里的 w:t（文本），w:br / w:tab 转成换行与空格
#   · w:instrText（域代码）、w:delText（修订删除）跳过，否则会混进乱码
#   · 连续空行最多留一行：场次分隔靠空行，全删会把剧本粘成一坨
# --------------------------------------------------------------------------
DOCX_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_extract_text(raw):
    """bytes(.docx) → 纯文本。不是 docx / 加密 / 损坏时抛 ValueError 带人话原因。"""
    if raw[:2] != b"PK":
        raise ValueError("这不是 .docx 文件。老式 .doc 是二进制格式，标准库解不了，"
                         "请在 Word 里「另存为」.docx 或 .txt 再上传")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            if "word/document.xml" not in z.namelist():
                raise ValueError("这个文件里没有正文（缺 word/document.xml），可能加了密或已损坏")
            xml = z.read("word/document.xml")
    except zipfile.BadZipFile:
        raise ValueError("文件损坏，zip 结构读不出来，请重新导出一次")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError("正文 XML 解析失败：" + str(exc)[:100])
    lines = []
    for p in root.iter(DOCX_W + "p"):
        buf = []
        for node in p.iter():
            if node.tag == DOCX_W + "t":
                buf.append(node.text or "")
            elif node.tag == DOCX_W + "tab":
                buf.append(" ")
            elif node.tag == DOCX_W + "br":
                buf.append("\n")
        lines.append("".join(buf).strip())
    out, blank = [], 0
    for ln in lines:
        if ln:
            blank = 0
            out.append(ln)
        else:
            blank += 1
            if blank <= 1:
                out.append("")
    text = "\n".join(out).strip()
    if not text:
        raise ValueError("这份 .docx 里没有可读文字（可能全是图片或文本框）")
    # 给前端一个「这份稿子像什么」的判断依据，避免前端再算一遍
    heads = len(re.findall(r"^\s*第\s*[0-9一二三四五六七八九十]+\s*场", text, re.M))
    dlg = len(re.findall(r"^[^：:\s（）()【】\[\]]{1,12}\s*(?:[（(][^）)]*[）)])?\s*[：:]\s*\S",
                          text, re.M))
    return {"text": text, "chars": len(text.replace(" ", "").replace("\n", "")),
            "sceneHeads": heads, "dialogueLines": dlg,
            "kind": "scene" if heads else ("simple" if dlg >= 3 else "prose")}


QUOTE_RE = re.compile(r"[“\"「]([^”\"」]{2,})[”\"」]")
INNER_RE = re.compile(r"^我(?:怀疑|知道|觉得|想|心想|暗想|明白|意识到|纳闷|才)")


def split_source_sentences(text: str):
    """按句末标点切句；引号内的句号不切，保留原文逐字。"""
    out, buf, depth = [], [], 0
    for ch in (text or ""):
        if ch in "“「『":
            depth += 1
        elif ch in "”」』" and depth > 0:
            depth -= 1
        buf.append(ch)
        if depth == 0 and ch in "。！？\n":
            piece = "".join(buf).strip()
            if piece:
                out.append(piece)
            buf = []
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out


def _guess_speaker(before: str, characters, narrator: str) -> str:
    for name in (characters or []):
        n = str(name or "").strip()
        if n and n in before:
            return n
    if narrator and narrator in before:
        return narrator
    return "旁白"


def _render_sentence(sent: str, characters, narrator: str, dlg_text: str = "", dlg_speaker: str = ""):
    t = re.sub(r"\s+", " ", str(sent or "").strip())
    if not t:
        return []
    # 章节标题行 / 站点分类水印：不进正文
    if re.match(r"^第[一二三四五六七八九十百零\d]+章", t) or re.match(r"^\d{1,2}-\d{1,2}\s*分类", t):
        return []
    quote = QUOTE_RE.search(t)
    text = dlg_text if (dlg_text and dlg_text in t) else (quote.group(1) if quote else "")
    speaker = dlg_speaker or _guess_speaker(t[:quote.start()] if quote else t, characters, narrator)
    if text:
        head, _, raw_tail = t.partition(text)
        head = head.strip(" ，,、：:；;")
        tail = raw_tail.strip(" ，,、：:；;")
        if tail and all(c in "。！？…”」』\"'；;" for c in tail):
            text = text + tail
            tail = ""
        elif tail and len(tail) > 1 and dlg_text:
            text = text + raw_tail.rstrip()  # 补齐半句台词，保留逗号等前导标点
            tail = ""
        lines = []
        if head and len(head) > 1:
            lines.append("△ " + head + ("" if head[-1] in "。！？" else "。"))
        lines.append(speaker + "：" + text)
        if tail and len(tail) > 1:
            lines.append("△ " + tail + ("" if tail[-1] in "。！？" else "。"))
        return lines
    if INNER_RE.search(t):
        return [narrator + "（旁白）：" + t]
    return ["△ " + t]


def build_adapted_script(sents, plan: dict) -> str:
    """模型只给结构，正文由原文句子逐字重组 —— 从根上避免改写与输出截断。"""
    n = len(sents)
    narrator = s(str(plan.get("narrator") or "我"), 20)
    title = s(str(plan.get("title") or "未命名"), 40)
    raw_scenes = [x for x in (plan.get("scenes") or []) if isinstance(x, dict)]
    scenes, cursor = [], 0
    for sc in raw_scenes:
        try:
            start, end = int(sc.get("start")), int(sc.get("end")) + 1
        except (TypeError, ValueError):
            continue
        start = max(cursor, min(start, n))
        end = max(start + 1, min(end, n))
        if end <= start:
            continue
        scenes.append((start, end, sc))
        cursor = end
    if cursor < n:
        scenes.append((cursor, n, {}))
    if not scenes:
        scenes = [(0, n, {})]

    dmap = {}
    for d in (plan.get("dialogues") or []):
        if not isinstance(d, dict):
            continue
        try:
            i = int(d.get("index"))
        except (TypeError, ValueError):
            continue
        if 0 <= i < n:
            dmap[i] = (s(str(d.get("text") or ""), 300), s(str(d.get("speaker") or "旁白"), 20))

    out = ["《%s》" % title, ""]
    last_ext, last_loc, last_chars = "", "", []
    for k, (start, end, sc) in enumerate(scenes, 1):
        ext = clean_placeholder(sc.get("intExt"), 6)
        loc = clean_placeholder(sc.get("location"), 24)
        tm = clean_placeholder(sc.get("time"), 10)
        if not ext and k > 1: ext = last_ext
        if not loc and k > 1: loc = last_loc
        head = " · ".join(x for x in (ext, loc, tm) if x)
        out.append(("第%d场 %s" % (k, head)).strip())
        chars = sc.get("characters") or last_chars
        last_ext, last_loc, last_chars = ext, loc, chars
        buf, rendered = [], []
        for i in range(start, end):
            dtext, dsp = dmap.get(i, ("", ""))
            for line in _render_sentence(sents[i], chars, narrator, dtext, dsp):
                if line.startswith("△ "):
                    buf.append(line[2:])
                else:
                    if buf:
                        rendered.extend("△ " + "".join(buf[j:j + 3]) for j in range(0, len(buf), 3))
                        buf = []
                    rendered.append(line)
        if buf:
            rendered.extend("△ " + "".join(buf[j:j + 3]) for j in range(0, len(buf), 3))
        out.extend(rendered)
        out.append("")
    return "\n".join(out).strip() + "\n"


def clean_script_text(text: str) -> str:
    """剥掉模型偶尔带的代码块与开场白，只留剧本正文。"""
    t = (text or "").strip()
    t = re.sub(r"^```(?:text|markdown|txt)?\s*", "", t, flags=re.I)
    t = re.sub(r"\s*```$", "", t)
    lines = t.splitlines()
    while lines and not re.match(r"^\s*[《第]", lines[0]):
        first = lines[0].strip()
        if not first or (len(first) < 40 and re.search(r"[:：]\s*$|^(以下|转写|剧本|好的|这是)", first)):
            lines.pop(0)
            continue
        break
    return "\n".join(lines).strip()


def check_adaptation(original: str, adapted: str):
    """原文保真校验：按句号切句逐条比对前 8 字，另核对带引号的直接引语。"""
    o = re.sub(r"\s+", "", original or "")
    a = re.sub(r"\s+", "", adapted or "")
    sents = [re.sub(r"\s+", "", x) for x in split_source_sentences(original or "")
             if len(re.sub(r"\s+", "", x)) >= 8]
    hit = sum(1 for x in sents if x[:8] in a)
    quotes = [q.strip() for q in re.findall(r"[「“\"'『]([^」”\"'』]{4,})[」”\"'』]", original or "")]
    qhit = sum(1 for q in quotes if re.sub(r"\s+", "", q)[:10] in a)
    heads = len(re.findall(r"^\s*第\s*\d+\s*场", adapted or "", re.M))
    warnings = []
    if heads < 2:
        warnings.append("只识别出 %d 个场次头，转写可能没切分场次" % heads)
    if sents and hit < len(sents) * 0.9:
        warnings.append("原文 %d 句里只有 %d 句能在转写中逐字找到，可能有改写或漏句" % (len(sents), hit))
    if quotes and qhit < len(quotes):
        warnings.append("%d 句原文直接引语有 %d 句未逐字保留" % (len(quotes), len(quotes) - qhit))
    if len(o) and len(a) < len(o) * 0.75:
        warnings.append("转写明显短于原文（%d → %d 字），请检查是否被截断" % (len(o), len(a)))
    return {
        "sceneHeads": heads,
        "sentencesTotal": len(sents), "sentencesCovered": hit,
        "quotesTotal": len(quotes), "quotesCovered": qhit,
        "warnings": warnings[:5],
    }


# --------------------------------------------------------------------------
# 通用工具
# --------------------------------------------------------------------------
def extract_json(text: str, key: str, expect_list: bool = True):
    """兼容模型把 JSON 包在 ```json ... ``` 里，或前后带解释文字。

    expect_list=False 给通用 Agent 用：它们的输出根键可以是对象（如 report / outline）。
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("模型返回了空内容，可能是该模型别名不可用，请换一个 model")
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("模型没有返回 JSON 对象")
    data = json.loads(text[start:end + 1])
    if isinstance(data, list):
        data = {key: data}
    if not isinstance(data, dict) or key not in data:
        raise ValueError("模型返回的 JSON 缺少 " + key + " 字段")
    if expect_list and not isinstance(data.get(key), list):
        raise ValueError("模型返回的 " + key + " 不是数组")
    return data


def call_llm(system: str, user: str, timeout: int = 120, max_tokens: int = None):
    base, key, model = llm_settings()
    if not (base and key):
        raise RuntimeError("NO_KEY")
    budget = max_tokens or llm_max_tokens()
    body = json.dumps({
        "model": model,
        "temperature": 0.3,
        "max_tokens": budget,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user[:36000]},  # 含带编号的剧本行清单
        ],
    }).encode("utf-8")
    req = urllib.request.Request(
        base + "/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            upstream = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:220]
        raise RuntimeError("模型服务返回 %s：%s" % (exc.code, detail)) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("连不上模型服务或请求超时：%s" % exc) from exc
    try:
        choice = upstream["choices"][0]
        content = choice["message"].get("content") or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("模型返回体结构异常") from exc

    if choice.get("finish_reason") == "length":
        raise RuntimeError(
            "模型输出被截断（max_tokens=%d 不够用）。推理模型的思考过程也占额度，"
            "可在 llm-config.bat 里加大 SHORTPLAY_LLM_MAX_TOKENS，或把单集场次拆少一些。" % budget
        )
    if not content.strip():
        thinking = (choice["message"].get("reasoning_content") or "").strip()
        if thinking:
            raise RuntimeError(
                "模型只输出了思考过程、没有最终答案（推理 token 用尽额度）。"
                "请加大 SHORTPLAY_LLM_MAX_TOKENS，或换回 deepseek-chat。"
            )
        raise RuntimeError("模型返回空内容，请检查 SHORTPLAY_LLM_MODEL 是否是该服务真实支持的模型名")
    return content, model


def _quote_closes(s: str, i: int) -> bool:
    """判断位置 i 的双引号是不是字符串的结束引号。

    后面第一个非空白字符是 , } ] : 才算结束；否则视为字符串内部裸引号。
    """
    j = i + 1
    while j < len(s) and s[j] in " \t\r\n":
        j += 1
    return j >= len(s) or s[j] in ",}]: "


def repair_json(text: str):
    """模型偶尔吐出畸形 JSON，先尝试本地修，修不动再让模型重来一次。"""
    if not text:
        return ""
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.I)
    s = re.sub(r"\s*```$", "", s)
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end <= start:
        return ""
    s = s[start:end + 1]
    # 1) 连续逗号收敛，再去掉对象/数组结尾多余的逗号
    s = re.sub(r",(\s*,)+", r",", s)
    s = re.sub(r",(\s*[}\]])", r"\1", s)
    # 2) 字符串里裸露的换行 / 制表符 / 双引号一律转义
    out, in_str, esc = [], False, False
    for i, ch in enumerate(s):
        if esc:
            out.append(ch); esc = False; continue
        if in_str and ch == "\\":
            out.append(ch); esc = True; continue
        if ch == '"':
            if not in_str:
                in_str = True; out.append(ch)
            elif _quote_closes(s, i):
                in_str = False; out.append(ch)
            else:
                out.append('\\"')  # 值里引用台词时常见的裸引号
            continue
        if in_str and ch == "\n":
            out.append("\\n"); continue
        if in_str and ch == "\t":
            out.append("\\t"); continue
        out.append(ch)
    return "".join(out)


def call_llm_json(system: str, user: str, key: str, timeout: int = 120,
                  expect_list: bool = True):
    """取 JSON：本地修复 → 仍失败则追加一次“只要合法 JSON”的重试。"""
    content, model = call_llm(system, user, timeout)
    try:
        return extract_json(content, key, expect_list), model
    except ValueError as first_err:
        fixed = repair_json(content)
        if fixed:
            try:
                return extract_json(fixed, key, expect_list), model
            except ValueError:
                pass
        retry_system = (system + "\n\n【上一次输出的 JSON 不合法（%s）。"
                                 "这次只输出一个合法 JSON 对象：不要注释、不要代码块、"
                                 "字符串内不要出现未转义的换行或英文双引号，引用台词改用中文书名号。】"
                        % str(first_err)[:80])
        content2, model2 = call_llm(retry_system, user, timeout)
        try:
            return extract_json(content2, key, expect_list), model2
        except ValueError:
            fixed2 = repair_json(content2)
            if fixed2:
                return extract_json(fixed2, key, expect_list), model2
            raise


# --------------------------------------------------------------------------
# 归一化：模型输出 → 界面可安全消费的数据
# --------------------------------------------------------------------------
def normalize_plan(data, scenes, wanted):
    """校验分集：场次连续、不重叠、全覆盖、编号合法；缺口自动补进相邻集。"""
    valid = []
    for x in scenes or []:
        try:
            valid.append(int(x.get("no")))
        except (TypeError, ValueError, AttributeError):
            pass
    if not valid:
        valid = [1]
    lo, hi = min(valid), max(valid)
    raw = [e for e in (data.get("episodes") or []) if isinstance(e, dict)]
    if not raw:
        raise ValueError("模型没有给出任何分集")
    if isinstance(wanted, int) and wanted > 0:
        raw = raw[:wanted]

    eps, cursor = [], lo
    for i, e in enumerate(raw, 1):
        a = int(e.get("sceneFrom", cursor) or cursor)
        b = int(e.get("sceneTo", a) or a)
        a, b = max(lo, min(hi, a)), max(lo, min(hi, b))
        if b < a:
            a, b = b, a
        a = max(a, cursor)
        if a > hi:
            break
        eps.append({
            "no": len(eps) + 1,
            "title": s(e.get("title"), 40) or ("第%d集" % (len(eps) + 1)),
            "synopsis": s(e.get("synopsis"), 160),
            "sceneFrom": a,
            "sceneTo": b,
            "hook": s(e.get("hook"), 120),
        })
        cursor = b + 1
        if cursor > hi:
            break
    if not eps:
        raise ValueError("分集结果没有覆盖任何场次")
    if cursor <= hi:  # 最后一段没被覆盖，并进末集
        eps[-1]["sceneTo"] = hi
    eps[-1]["sceneFrom"] = min(eps[-1]["sceneFrom"], eps[-1]["sceneTo"])
    return {"episodes": eps}


def build_script_index(scenes):
    """给本集每句台词 / 每条动作编号，供模型标注 refs、服务端核对覆盖。

    顺序按剧本原始行号（lineNo），保证 refs 的 seq 与剧本时序一致。
    """
    index, rows = {}, []
    for sc in scenes or []:
        if not isinstance(sc, dict):
            continue
        try:
            no = int(sc.get("no"))
        except (TypeError, ValueError):
            continue
        items = []
        for i, ln in enumerate(sc.get("lines") or [], 1):
            if not isinstance(ln, dict):
                continue
            text = s(ln.get("text"), 240)
            if not text:
                continue
            speaker = s(ln.get("speaker"), 40)
            try:
                line_no = int(ln.get("lineNo") or 0)
            except (TypeError, ValueError):
                line_no = 0
            items.append(("D%d-%d" % (no, i), line_no, "台词",
                          (speaker or "?") + "：" + text, text, speaker, "dialogue"))
        for i, a in enumerate(sc.get("actions") or [], 1):
            text = s(a.get("text") if isinstance(a, dict) else a, 240)
            if not text:
                continue
            try:
                line_no = int(a.get("lineNo") or 0) if isinstance(a, dict) else 0
            except (TypeError, ValueError):
                line_no = 0
            items.append(("A%d-%d" % (no, i), line_no, "动作", text, text, "", "action"))
        items.sort(key=lambda x: (x[1] if x[1] > 0 else 10 ** 6, x[0]))
        for ref, _, typ, label, text, speaker, kind in items:
            index[ref] = {"seq": len(index) + 1, "sceneNo": no, "type": kind,
                          "text": text, "speaker": speaker}
            rows.append("  %s [第%d场·%s] %s" % (ref, no, typ, label))
    return index, "\n".join(rows) or "（剧本没有可编号的台词或动作）"


def normalize_detail(raw):
    """分镜卡：字段白名单 + 长度收敛，缺失留空交给界面提示，不编造内容。"""
    src = raw if isinstance(raw, dict) else {}
    return {k: s(src.get(k), 180) for k in DETAIL_FIELDS}


def ground_generic_shot(shot, scene, index, warnings):
    """建立 / 收束镜头写成套话或整张分镜卡为空时，按本场真实原文重写。"""
    if shot["kind"] not in ("establishing", "closing"):
        return
    detail_filled = any(shot["detail"].values())
    if detail_filled and not GENERIC_RE.search(shot["visual"]):
        return
    refs = sorted((r for r, v in index.items() if v["sceneNo"] == shot["sceneNo"]),
                  key=lambda r: index[r]["seq"])
    if not refs:
        return
    item = index[refs[0] if shot["kind"] == "establishing" else refs[-1]]
    place = "，".join(x for x in (scene.get("intExt"), scene.get("location"), scene.get("time")) if x)
    shot["visual"] = (place + "，" if place else "") + item["text"]
    shot["detail"]["subject"] = shot["detail"]["subject"] or (item["speaker"] or place or "本场")
    shot["detail"]["action"] = shot["detail"]["action"] or item["text"]
    warnings.append("第%d场%s镜头描述过于笼统，已按剧本原文重写" %
                    (shot["sceneNo"], "建立" if shot["kind"] == "establishing" else "收束"))


def patch_shot(ref, item, scene, base_dur):
    """AI 漏掉某句台词 / 动作时补齐一镜，只用剧本原文，不生成新剧情。"""
    text, is_dlg = item["text"], item["type"] == "dialogue"
    speaker = item["speaker"]
    detail = normalize_detail(None)
    detail["subject"] = speaker or scene.get("location") or "本场"
    detail["action"] = text
    return {
        "sceneNo": item["sceneNo"], "kind": "dialogue" if is_dlg else "action",
        "visual": ((speaker + "：") if is_dlg and speaker else "") + text,
        "size": "近景" if is_dlg else "中景",
        "duration": num(base_dur + len(text) // 24, base_dur, 2, 10),
        "dialogue": ((speaker + "：" + text) if is_dlg else ""),
        "speaker": speaker if is_dlg else "",
        "notes": "AI 漏项自动补镜 · 请人工确认画面",
        "detail": detail, "refs": [ref], "patched": True,
    }


def normalize_shots(data, scenes, config, index=None):
    """校验分镜：字段白名单、时长、场次、台词真实性、剧本行覆盖、反套话。"""
    index = index or {}
    valid_no, scene_meta = [], {}
    for x in scenes or []:
        try:
            n = int(x.get("no"))
            valid_no.append(n)
            scene_meta[n] = {
                "intExt": s(x.get("intExt"), 20),
                "location": s(x.get("location"), 60),
                "time": s(x.get("time"), 20),
            }
        except (TypeError, ValueError, AttributeError):
            pass
    if not valid_no:
        valid_no = [1]
    base_dur = num((config or {}).get("defaultDuration"), 4, 2, 10)
    original = set()
    for x in scenes or []:
        for ln in x.get("lines") or []:
            t = re.sub(r"\s+", "", str(ln.get("text") or ""))
            if len(t) >= 3:
                original.add(t)

    out, warnings, seen, used_dialogue = [], [], set(), set()
    for raw in (data.get("shots") or []):
        if not isinstance(raw, dict):
            continue
        try:
            scene_no = int(raw.get("sceneNo"))
        except (TypeError, ValueError):
            scene_no = valid_no[0]
        if scene_no not in scene_meta:
            scene_no = min(valid_no, key=lambda n: abs(n - scene_no))
        size = s(raw.get("size"), 10)
        if size not in SIZE_SET:
            size = "中景"
        kind = s(raw.get("kind"), 20)
        if kind not in KIND_SET:
            kind = "action"
        visual = s(raw.get("visual"), 400)
        if not visual:
            visual = (scene_meta[scene_no]["location"] or "场景") + "，镜头内容见分镜描述卡。"
        notes = s(raw.get("notes"), 240)
        dialogue = s(raw.get("dialogue"), 400)
        speaker = s(raw.get("speaker"), 40)
        if speaker and dialogue and not dialogue.startswith(speaker):
            dialogue = speaker + "：" + dialogue
        if dialogue:
            plain = re.sub(r"\s+", "", re.sub(r"^[^：:]{1,12}[：:]", "", dialogue))
            if original and len(plain) >= 3 and not any(t in plain or plain in t for t in original):
                warnings.append("有一条台词与剧本原文不完全一致，已保留但请人工核对：" + dialogue[:30])
                notes = (notes + " · AI 台词待核对").strip(" ·")
        refs = [str(r) for r in (raw.get("refs") or []) if isinstance(r, (str, int))]
        refs = [r for r in refs if r in index and index[r]["sceneNo"] == scene_no]
        kept = []
        for r in refs:  # 同一句台词只能落在一个镜头里
            if index[r]["type"] == "dialogue" and (r in used_dialogue or r in kept):
                continue
            kept.append(r)
        refs = kept
        for r in refs:
            if index[r]["type"] == "dialogue":
                used_dialogue.add(r)
        key = (scene_no, visual, dialogue)
        if key in seen:  # 模型偶尔会重复吐同一镜
            continue
        seen.add(key)
        shot = {
            "sceneNo": scene_no, "kind": kind, "visual": visual, "size": size,
            "duration": num(raw.get("duration"), base_dur, 2, 10),
            "dialogue": dialogue, "speaker": speaker, "notes": notes,
            "detail": normalize_detail(raw.get("detail")), "refs": refs,
        }
        ground_generic_shot(shot, scene_meta[scene_no], index, warnings)
        out.append(shot)
    if not out:
        raise ValueError("模型没有给出任何分镜")

    # ---- 覆盖核对：台词必须 100%，动作允许被 visual 吸收，剩下的一律补镜 ----
    def shot_seq(sh):
        seqs = [index[r]["seq"] for r in sh.get("refs", []) if r in index]
        return max(seqs) if seqs else -1

    corpus = [re.sub(r"\s+", "", sh["visual"] + " " + sh["detail"]["action"]) for sh in out]
    used_actions = {r for sh in out for r in sh["refs"] if index[r]["type"] == "action"}
    missing = [r for r, v in index.items() if v["type"] == "dialogue" and r not in used_dialogue]
    for r, v in index.items():
        if v["type"] != "action" or r in used_actions:
            continue
        frag = re.sub(r"\s+", "", v["text"])[:8]
        if frag and any(frag in c for c in corpus):
            continue  # 动作已写进画面描述，只是模型没标 refs
        missing.append(r)

    patched_lines = sum(1 for r in missing if index[r]["type"] == "dialogue")
    for r in sorted(missing, key=lambda x: index[x]["seq"]):
        item = index[r]
        sh = patch_shot(r, item, scene_meta.get(item["sceneNo"], {}), base_dur)
        positions = [i for i, c in enumerate(out) if c["sceneNo"] == sh["sceneNo"]]
        if positions:
            pos = positions[-1] + 1
            for i in positions:
                if shot_seq(out[i]) > item["seq"]:
                    pos = i
                    break
        else:
            pos = next((i for i, c in enumerate(out) if c["sceneNo"] > sh["sceneNo"]), len(out))
        out.insert(pos, sh)
    if missing:
        warnings.insert(0, "AI 漏了 %d 句台词 / %d 条动作，已按剧本原文自动补 %d 镜（卡片标「补」）" %
                        (patched_lines, len(missing) - patched_lines, len(missing)))

    dialogue_total = sum(1 for v in index.values() if v["type"] == "dialogue")
    action_total = sum(1 for v in index.values() if v["type"] == "action")
    return {
        "shots": out, "warnings": warnings[:8],
        "coverage": {
            # FromModel 统计模型自己覆盖了多少；漏项已由服务端补镜，最终成片仍是全覆盖
            "dialogueTotal": dialogue_total,
            "dialogueFromModel": dialogue_total - patched_lines,
            "actionTotal": action_total,
            "actionFromModel": action_total - (len(missing) - patched_lines),
            "patched": len(missing),
        },
    }


# --------------------------------------------------------------------------
# 云端出图引擎：通义万相 wan2.7-image-pro（组图 / 一致性序列）
#   · 与本地 ComfyUI 共用同一套任务队列、进度、缩略图、灯箱与导出链路
#   · Key 存在 engine-config.json（界面可改）或环境变量里，绝不回传前端 / 写日志 / 进导出包
#   · 接口同步返回带签名的 OSS 图片 URL，必须立刻下载落盘（URL 会过期）
# --------------------------------------------------------------------------


def engine_probe(kind):
    """连通性探测。ComfyUI 真连一次；万相只校验 Key 是否配好，不空跑计费请求。"""
    kind = str(kind or "comfy").strip()
    if kind == "qwen":
        key = qwen_image_key()
        return {"ok": bool(key), "kind": "qwen", "model": qwen_image_model(),
                "mask": _mask_key(key),
                "detail": ("Key 已保存（%s），实际出图才会产生调用与计费" % _mask_key(key))
                          if key else "没配置 API Key"}
    st = comfy_status()
    if not st.get("online"):
        return {"ok": False, "kind": "comfy", "host": st.get("host", ""),
                "detail": st.get("detail") or "连不上 ComfyUI"}
    want = comfy_model()
    names = comfy_unet_names()
    match = None if not names else (want in names)
    return {"ok": True, "kind": "comfy", "host": st.get("host"),
            "version": st.get("version"), "model": want,
            "modelMatch": match, "models": names[:40],
            "detail": "" if match is not False else
                      ("ComfyUI 里没有 %s，从下面换一个可用的" % want)}


def _to_png(raw):
    """统一落盘为 PNG：实测端点返回 PNG，非 PNG 时用可选 Pillow 转一次。"""
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return raw
    try:
        try:
            from PIL import Image
        except ImportError:
            import site as _site
            p = _site.getusersitepackages()
            if isinstance(p, str) and p and p not in sys.path:
                sys.path.append(p)
            from PIL import Image
        im = Image.open(io.BytesIO(raw)).convert("RGB")
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        return buf.getvalue()
    except Exception as exc:
        raise RuntimeError("通义万相返回的图片不是 PNG，且转换失败：" + str(exc)[:120])


def qwen_image_generate(prompt, n=1, size="", timeout=300):
    """同步调组图接口 → 下载所有图片 → 返回 PNG bytes 列表。

    实测响应：output.choices[0].message.content[] 每项是 {"type":"image","image":"https://..."}；
    也兼容 {"image":{"url":...}} 与 data URI。API 报错时把 message/code 带出来。
    """
    key = qwen_image_key()
    if not key:
        raise RuntimeError("未配置通义万相 API Key")
    n = max(1, min(int(n or 1), 4))
    sz = str(size or qwen_image_size()).strip()
    if not re.match(r"^(1K|2K|4K|[0-9]{3,4}\*[0-9]{3,4})$", sz, re.I):
        sz = qwen_image_size()
    body = {
        "model": qwen_image_model(),
        "input": {"messages": [
            {"role": "user", "content": [{"text": str(prompt or "")[:4000]}]}
        ]},
        "parameters": {"enable_sequential": n > 1, "n": n, "size": sz},
    }
    req = urllib.request.Request(
        qwen_image_url(), data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.load(r)
    urls = []
    for ch in ((out.get("output") or {}).get("choices") or []):
        for c in ((ch.get("message") or {}).get("content") or []):
            if not isinstance(c, dict):
                continue
            v = c.get("image")
            if isinstance(v, str) and v:
                urls.append(v)
            elif isinstance(v, dict):
                u = v.get("url") or v.get("image") or ""
                if u:
                    urls.append(u)
    if not urls:
        why = out.get("message") or out.get("code") or out.get("error") or str(out)[:180]
        raise RuntimeError("通义万相没返回图片：" + str(why)[:180])
    imgs = []
    for u in urls[:n]:
        if u.startswith("data:"):
            imgs.append(_to_png(base64.b64decode(u.split(",", 1)[-1])))
        else:
            with urllib.request.urlopen(u, timeout=120) as r:
                imgs.append(_to_png(r.read()))
    return imgs


# --------------------------------------------------------------------------
# AI 单项形象填充 + 本地 ComfyUI 批量出图
#   · 单项填充：给手工新增 / 设定留空的角色补 face / flaw / 记忆点 / 关键词串
#   · 批量出图：Flux.1-schnell（工作流与 tools/gen_first_frame.py 保持一致）
#     走「提交即返回 jobId + 后台线程串行跑 + 前端轮询」，避免多张图把 HTTP 拖超时
#   · 原图落 examples/assets/，回给前端的是 512px JPEG 缩略 dataURI，
#     直接复用现有 refImage / 撤销栈 / localStorage / zip 导出链路
# --------------------------------------------------------------------------
# 地址与 unet 名不再是模块常量：由 comfy_host() / comfy_model() 现读
# （界面改完立即生效，换 Flux 版本不用改代码）
ASSET_IMG_DIR = ROOT / "examples" / "assets"
ASSET_IMG_NAME = re.compile(r"^[A-Za-z0-9_.\-]+\.png$")

SYSTEM_ASSET_FILL = """你是短剧美术设定总监。只输出严格 JSON，不要解释文字，不要 Markdown 代码块。

你会拿到一个资产（角色、场景或道具）的名字、剧本中与它相关的原文片段、以及界面上已经填好的字段。
请补全这个资产的视觉设定，让用户可以直接拿去出图。

角色输出：
{"age":"18岁","role":"主角","face":"脸型与五官，15字内","flaw":"一处可辨识瑕疵，12字内",
 "wardrobeHook":"服装或配饰记忆点，12字内","wardrobe":"服装一句话，20字内",
 "keyword":"把 age、face、flaw、wardrobeHook、wardrobe 用中文逗号连成一句，40字内",
 "keywordEn":"同一串的英文版，给本地 Flux 用，一句，40词内"}

场景输出：
{"appearance":"环境一句话，30字内","light":"主光与色温，20字内","lens":"镜头焦段，如 24mm广角",
 "props":["陈设A","陈设B"],"sceneEn":"一句英文场景描述，给本地 Flux 用，30词内"}

道具输出：
{"appearance":"材质、颜色、尺寸、年代感或磨损，25字内（只写物体本身，不写属于谁）",
 "propEn":"一句英文静物描述，给本地 Flux 用，含材质与颜色，20词内"}

硬性规则：
- 剧本原文里写明的细节必须原样保留，不许改写；推断出的细节不要写成确定事实。
- 已经填好的非空字段，除非明显与剧本冲突，否则保持不变。
- 严禁新增剧本里没有的情节、身世、结局；严禁输出长段描述文字。
- 三个一致性锚点（face / flaw / wardrobeHook）必须给，且要具体到能画出区别。
- keyword 各段必须用中文逗号「，」分隔。keywordEn / sceneEn / propEn 必须是英文。
- 道具只描述物体本身：appearance 不写持有者、不写人物；propEn 必须是英文静物短语，
  不许出现 a man / woman / someone holding / hand / person 一类词。
- 只输出一个 JSON 对象。"""

# 每种变体的英文出图模板、默认画幅（都取 16 的倍数，Flux 对尺寸敏感）
# 画幅按用途给真实比例：三视图 3:2、定妆 3:4、概念图 16:9、宽幕 2.375:1、静物 1:1。
# 2026-11-09 提高约 1.5 倍线性分辨率：预览灯箱看的是原图，768 宽放大后会糊。
# 缩略 dataURI 仍固定 512px（见 thumb_datauri），不跟着涨，避免 localStorage 被撑爆。
COMFY_VARIANTS = {
    "character": [
        {"key": "turnaround", "label": "三视图", "w": 1024, "h": 672,
         "tpl": "character turnaround reference sheet, front view, side view, back view, "
                "full body, same person in all three, neutral gray studio background, "
                "flat even lighting, character design sheet, {kw}"},
        {"key": "faceSheet", "label": "面部四视图", "w": 1024, "h": 672,
         "tpl": "character face reference sheet, front view and three-quarter view close-ups, "
                "same person, consistent facial features, soft studio light, "
                "character design sheet, {kw}"},
        {"key": "portrait", "label": "定妆半身", "w": 768, "h": 1024,
         "tpl": "cinematic medium portrait of one Chinese character, {kw}, "
                "shallow depth of field, film still, natural skin texture, muted color grade"},
    ],
    "scene": [
        {"key": "concept", "label": "场景概念图", "w": 1152, "h": 640,
         "tpl": "environment concept art, {kw}, matte painting, cinematic composition, "
                "detailed architecture, atmospheric depth, no people, no text"},
        {"key": "wide", "label": "宽幕建立镜", "w": 1216, "h": 512,
         "tpl": "wide establishing shot, {kw}, anamorphic lens, cinematic lighting, "
                "film still, no people, no text"},
    ],
    "prop": [
        # 道具必须是「静物」语域：单写 product photography 会带上商品广告味，
        # 更关键的是原来没写 no people —— Flux 干脆自己塞一只手进来拿着它。
        {"key": "prop", "label": "道具静物", "w": 896, "h": 896,
         "tpl": "still life of a single {kw}, centered on a plain neutral gray backdrop, "
                "tabletop, soft directional studio light, macro detail, "
                "shallow depth of field, photorealistic product photography, "
                "no people, no human figure, no hands, no face, no text"},
    ],
}
# 只放技术性收尾词，不放画种：画种由剧本风格锚（styleEn）决定，
# 原先写死 "professional concept art" 会让所有剧本的资产图都长成一个概念美术味。
COMFY_SUFFIX = "highly detailed, sharp focus, no text, no watermark"
# 物体类再多压一遍「不要人」：这套 Flux 工作流 FluxGuidance=0、没有 negative 节点，
# 负向词只能写进正向串，而且重复一次才有足够权重。
COMFY_SUFFIX_OBJECT = ("highly detailed, sharp focus, no text, no watermark, "
                       "no people, no human figure, no hands")


def comfy_status():
    """探测本机 ComfyUI；不在线时前端把出图按钮置灰并给出明确原因。"""
    try:
        with urllib.request.urlopen(comfy_host() + "/system_stats", timeout=4) as r:
            st = json.load(r)
        dev = (st.get("devices") or [{}])[0]
        return {
            "online": True, "host": comfy_host(),
            "version": ((st.get("system") or {}).get("comfyui_version") or ""),
            "device": dev.get("name", ""),
            "vramFreeMB": int(dev.get("vram_free", 0) / (1024 * 1024)),
            "model": comfy_model(),
            "qwen": qwen_image_status(),
            "variants": {k: [{"key": v["key"], "label": v["label"], "w": v["w"], "h": v["h"]}
                             for v in vs] for k, vs in COMFY_VARIANTS.items()},
        }
    except Exception as exc:
        return {"online": False, "host": comfy_host(), "detail": str(exc)[:160],
                "qwen": qwen_image_status()}


def _en_subject(text):
    """英文主体去掉多余冠词、首字母小写。

    模型常回 "A string of yellow paper coins"，模板是 "still life of a single {kw}"，
    直接拼就成 "a single A string of..." 的病句，Flux 对病句的解读会跑偏。
    """
    t = re.sub(r"^(a|an|the)\s+", "", (text or "").strip(), flags=re.I)
    return (t[:1].lower() + t[1:]) if t else t


def style_for_kind(style_en, kind):
    """按资产类型收风格锚：物体剔掉人像词，全被剔光就退到物体锚。

    道具图里出现人手，根因之一就是通用风格锚里的 "natural skin texture"
    被无条件拼到了道具上 —— Flux 见到 skin 就画皮肤。
    """
    src = (style_en or "").strip() or STYLE_ANCHOR_EN_DEFAULT
    if kind == "character":
        return src
    kept = []
    for part in src.split(","):
        p = part.strip()
        if not p:
            continue
        low = p.lower()
        # 以 no 开头的负向约束（如 "no beautification filter"）保留
        if low.startswith("no ") or not any(t in low for t in PERSON_ONLY_TERMS):
            kept.append(p)
    return ", ".join(kept) or STYLE_ANCHOR_EN_OBJECT


def build_comfy_prompt(asset, variant_key, style_en=""):
    """资产字段 → 英文 Flux 提示词。缺英文关键词时明确标记，不让用户以为设定生效了。"""
    kind = _as(asset.get("kind"), "character", 16)
    vs = COMFY_VARIANTS.get(kind, COMFY_VARIANTS["character"])
    v = next((x for x in vs if x["key"] == variant_key), None)
    if not v:
        raise ValueError("未知出图类型：" + str(variant_key)[:40])
    if kind == "character":
        kw = _as(asset.get("keywordEn"), "", 300).strip()
        fallback = not kw
        if fallback:
            kw = _as(asset.get("keyword"), "", 200).strip() or \
                 ("a Chinese film character named " + _as(asset.get("name"), "unknown", 40))
    elif kind == "scene":
        kw = _as(asset.get("sceneEn"), "", 300).strip()
        fallback = not kw
        if fallback:
            kw = _as(asset.get("appearance"), "", 200).strip() or \
                 "an interior film set, cinematic lighting"
    else:
        # 道具的英文名单独存 propEn。以前拿 appearance 兜底，而 appearance 就等于中文名，
        # Flux 的 T5 几乎读不懂中文 —— 主体词等于没写，剩下全是人像风格词。
        kw = _as(asset.get("propEn"), "", 300).strip()
        fallback = not kw
        if kw:
            kw = _en_subject(kw)
        else:
            cn = _as(asset.get("appearance"), "", 200).strip() or _as(asset.get("name"), "", 40)
            # 中文反正读不懂，但「一个静物」这个英文语域必须给，至少不会画成人物
            kw = "inanimate prop object" + ((", " + cn) if cn else "")
    # 风格紧跟主体描述（权重高），技术收尾词放最后；没设风格时退到中性默认。
    # 逗号不能省：Flux 会把 "eyebrow photorealistic" 连读成一个怪词。
    style = style_for_kind(style_en, kind)
    style_part = (", " + style) if len(style) < 240 else ""
    suffix = COMFY_SUFFIX_OBJECT if kind == "prop" else COMFY_SUFFIX
    return {"prompt": v["tpl"].format(kw=kw) + style_part + ", " + suffix,
            "w": v["w"], "h": v["h"], "label": v["label"], "fallbackEn": fallback}


def comfy_prompt_rows(assets, variants, style_en=""):
    """只跑拼装、不排队出图：界面拿它核对「本地实际会发什么」。

    以前资产面板展示的是 AI 写的中文提示词，而本地 Flux 吃的是这里另拼的英文串，
    同一份设定出现两个版本。统一从这一个函数取，复制走的和真正发出去的才是同一串。
    """
    rows = []
    for a in assets[:24]:
        kind = _as(a.get("kind"), "character", 16)
        keys = [k for k in (variants.get(kind) or []) if isinstance(k, str)]
        for vk in keys[:4]:
            try:
                built = build_comfy_prompt(a, vk, style_en)
            except ValueError:
                continue
            rows.append({
                "assetId": _as(a.get("id"), "", 80),
                "assetName": _as(a.get("name"), "", 40),
                "variant": vk, "label": built["label"],
                "prompt": built["prompt"], "w": built["w"], "h": built["h"],
                "fallbackEn": built["fallbackEn"],
            })
    if not rows:
        raise ValueError("没有可预览的提示词：先选资产，再勾选至少一种素材类型")
    return {"rows": rows, "styleEn": _as(style_en, "", 240) or STYLE_ANCHOR_EN_DEFAULT}


def comfy_workflow(prompt, w, h, seed):
    """与 tools/gen_first_frame.py 完全一致：Flux.1-schnell fp8 / 4 步 / euler。"""
    return {
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": comfy_model(), "weight_dtype": "default"}},
        "2": {"class_type": "DualCLIPLoader",
              "inputs": {"clip_name1": "clip_l.safetensors",
                         "clip_name2": "t5xxl_fp8_e4m3fn_scaled.safetensors",
                         "type": "flux", "device": "default"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "4": {"class_type": "FluxGuidance", "inputs": {"conditioning": ["3", 0], "guidance": 0}},
        "5": {"class_type": "EmptySD3LatentImage",
              "inputs": {"width": w, "height": h, "batch_size": 1}},
        "6": {"class_type": "BasicScheduler",
              "inputs": {"model": ["1", 0], "scheduler": "simple", "steps": 4, "denoise": 1}},
        "7": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "8": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "9": {"class_type": "BasicGuider", "inputs": {"model": ["1", 0], "conditioning": ["4", 0]}},
        "10": {"class_type": "SamplerCustomAdvanced",
               "inputs": {"noise": ["8", 0], "guider": ["9", 0],
                          "sampler": ["7", 0], "sigmas": ["6", 0], "latent_image": ["5", 0]}},
        "11": {"class_type": "VAEDecode", "inputs": {"samples": ["10", 0], "vae": ["12", 0]}},
        "12": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
        "13": {"class_type": "SaveImage",
               "inputs": {"images": ["11", 0], "filename_prefix": "sp_asset"}},
    }


def comfy_submit(prompt, w, h, seed):
    body = json.dumps({"prompt": comfy_workflow(prompt, w, h, seed),
                       "client_id": "shortplay-assets"}).encode("utf-8")
    req = urllib.request.Request(comfy_host() + "/prompt", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        out = json.load(r)
    if out.get("node_errors"):
        raise RuntimeError("ComfyUI 工作流校验失败：" + json.dumps(out["node_errors"], ensure_ascii=False)[:220])
    return out["prompt_id"]


def comfy_wait(pid, timeout=300):
    t0 = time.time()
    while True:
        time.sleep(1.2)
        try:
            with urllib.request.urlopen(comfy_host() + "/history/" + pid, timeout=20) as r:
                hist = json.load(r)
        except Exception:
            if time.time() - t0 > timeout:
                raise RuntimeError("等待 ComfyUI 出图超时（%ds）" % timeout)
            continue
        if pid in hist:
            h = hist[pid]
            st = h.get("status", {})
            if st.get("status_str") != "success":
                raise RuntimeError("ComfyUI 生成失败：" + json.dumps(st, ensure_ascii=False)[:300])
            imgs = []
            for _node, out in (h.get("outputs") or {}).items():
                imgs.extend(out.get("images") or [])
            return imgs
        if time.time() - t0 > timeout:
            raise RuntimeError("等待 ComfyUI 出图超时（%ds）" % timeout)


def comfy_download(info):
    q = urllib.parse.urlencode({"filename": info["filename"],
                                "subfolder": info.get("subfolder", ""),
                                "type": info.get("type", "output")})
    with urllib.request.urlopen(comfy_host() + "/view?" + q, timeout=60) as r:
        return r.read()


def thumb_datauri(png):
    """原 PNG → 512px JPEG dataURI。Pillow 是可选加速，缺了也不能把出图结果弄丢。"""
    try:
        try:
            from PIL import Image
        except ImportError:
            # 服务被 start.bat / 托管进程拉起时，user site 可能没进 sys.path；
            # 本机 Pillow 就装在 user site，显式补一次再试（不引入运行时依赖）
            import site as _site
            p = _site.getusersitepackages()
            if isinstance(p, str) and p and p not in sys.path:
                sys.path.append(p)
            from PIL import Image
        im = Image.open(io.BytesIO(png)).convert("RGB")
        resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
        im.thumbnail((512, 512), resample)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=82, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii"), False
    except Exception:
        # 压缩不可用就回传原 PNG，前端会标记 uncompressed 并提示体积偏大
        return "data:image/png;base64," + base64.b64encode(png).decode("ascii"), True


COMFY_JOBS = {}
COMFY_LOCK = threading.Lock()
COMFY_SEQ = [0]


def comfy_job_start(assets, variants, style_en="", fixed_seed=0, engine="comfy", seq_n=1):
    """把「资产 × 变体」展开成串行任务，立即返回 jobId。

    engine=comfy 走本机 Flux；engine=qwen 走通义万相，seq_n>1 时一次出一组连续一致的图。
    """
    engine = engine if engine in ("comfy", "qwen") else "comfy"
    seq_n = max(1, min(int(seq_n or 1), 4)) if engine == "qwen" else 1
    plan = []
    for a in assets[:24]:
        kind = _as(a.get("kind"), "character", 16)
        keys = [k for k in (variants.get(kind) or []) if isinstance(k, str)]
        for vk in keys[:4]:
            try:
                built = build_comfy_prompt(a, vk, style_en)
            except ValueError:
                continue
            plan.append({
                "assetId": _as(a.get("id"), "", 80), "assetCode": _as(a.get("code"), "", 24),
                "assetName": _as(a.get("name"), "", 40), "kind": kind,
                "variant": vk, "variantLabel": built["label"],
                "prompt": built["prompt"], "w": built["w"], "h": built["h"],
                "fallbackEn": built["fallbackEn"], "n": seq_n,
                "seed": int(fixed_seed) or random.randint(1, 2 ** 31 - 1),
            })
    if not plan:
        raise ValueError("没有可生成的任务：先选资产，再勾选至少一种素材类型")
    total_images = len(plan) * seq_n
    if total_images > 24:
        raise ValueError("一次最多 24 张，分批生成（当前 %d 张）" % total_images)
    with COMFY_LOCK:
        COMFY_SEQ[0] += 1
        jid = "j%d_%d" % (int(time.time()), COMFY_SEQ[0])
        job = {"id": jid, "status": "running", "total": total_images, "done": 0,
               "current": "", "items": [], "errors": [], "startedAt": time.time(),
               "finishedAt": 0, "engine": engine,
               "model": comfy_model() if engine == "comfy" else qwen_image_model()}
        COMFY_JOBS[jid] = job
        # 只保留最近 10 个任务，避免长时间运行内存堆积
        if len(COMFY_JOBS) > 10:
            for old in sorted(COMFY_JOBS, key=lambda k: COMFY_JOBS[k]["startedAt"])[:-10]:
                COMFY_JOBS.pop(old, None)
    threading.Thread(target=comfy_worker, args=(jid, plan, engine), daemon=True).start()
    return {"jobId": jid, "total": total_images, "status": "running", "engine": engine}


def comfy_worker(jid, plan, engine="comfy"):
    ASSET_IMG_DIR.mkdir(parents=True, exist_ok=True)
    job = COMFY_JOBS.get(jid)
    for t in plan:
        if not job or job.get("status") == "cancelled":
            break
        job["current"] = "%s · %s" % (t["assetName"], t["variantLabel"])
        t0 = time.time()
        n = max(1, int(t.get("n", 1)))
        try:
            if engine == "qwen":
                pngs = qwen_image_generate(t["prompt"], n)
            else:
                pid = comfy_submit(t["prompt"], t["w"], t["h"], t["seed"])
                imgs = comfy_wait(pid)
                if not imgs:
                    raise RuntimeError("ComfyUI 没有返回图片")
                pngs = [comfy_download(imgs[0])]
            for i, png in enumerate(pngs[:n]):
                variant = t["variant"] if len(pngs) == 1 else "%s_s%d" % (t["variant"], i + 1)
                label = (t["variantLabel"] if len(pngs) == 1
                         else "%s %d/%d" % (t["variantLabel"], i + 1, len(pngs)))
                safe = re.sub(r"[^A-Za-z0-9_\-]", "", t["assetCode"] or t["assetId"] or "asset")[:24]
                name = "%s_%s_%d.png" % (safe or "asset", variant, t["seed"] + i)
                (ASSET_IMG_DIR / name).write_bytes(png)
                datauri, uncompressed = thumb_datauri(png)
                job["items"].append({
                    "assetId": t["assetId"], "assetCode": t["assetCode"],
                    "assetName": t["assetName"], "kind": t["kind"],
                    "variant": variant, "variantLabel": label,
                    "prompt": t["prompt"], "w": t["w"], "h": t["h"], "seed": t["seed"] + i,
                    "fallbackEn": t["fallbackEn"], "uncompressed": uncompressed,
                    "file": "examples/assets/" + name, "dataUri": datauri,
                    "bytes": len(png), "seconds": round(time.time() - t0, 1),
                    "engine": engine,
                })
                job["done"] += 1
            if len(pngs) < n:
                job["done"] += n - len(pngs)
                job["errors"].append({"assetName": t["assetName"], "variantLabel": t["variantLabel"],
                                      "detail": "接口只返回 %d/%d 张" % (len(pngs), n)})
        except Exception as exc:
            job["errors"].append({"assetName": t["assetName"], "variantLabel": t["variantLabel"],
                                  "detail": str(exc)[:220]})
            job["done"] += n
    if job:
        job["status"] = "done" if job.get("status") != "cancelled" else "cancelled"
        job["current"] = ""
        job["finishedAt"] = time.time()


def fill_asset_with_ai(payload):
    """单个资产的形象补全；只输出结构 JSON，长提示词仍由模板渲染。"""
    kind = _as(payload.get("kind"), "character", 16)
    name = _as(payload.get("name"), "", 40)
    if not name:
        raise ValueError("缺少资产名称")
    script = _as(payload.get("script"), "", 26000)
    current = payload.get("current") if isinstance(payload.get("current"), dict) else {}
    cur_txt = json.dumps(current, ensure_ascii=False)[:1800]
    user = ("资产类型：%s\n资产名称：%s\n\n界面上已填的字段（已填的尽量保留）：\n%s\n\n"
            "剧本 / 原文片段：\n%s" % (kind, name, cur_txt, script[:12000] or "（原文不可用，请只做保守补全）"))
    # 这里模型返回的是单个对象（不是数组），expect_list 必须显式关掉
    if kind == "prop":
        # 道具两个字段模型可能只给一个：先要 propEn（出图关键），缺了再按 appearance 收
        try:
            data, model = call_llm_json(SYSTEM_ASSET_FILL, user, "propEn",
                                        120, expect_list=False)
        except ValueError:
            data, model = call_llm_json(SYSTEM_ASSET_FILL, user, "appearance",
                                        120, expect_list=False)
    else:
        data, model = call_llm_json(SYSTEM_ASSET_FILL, user,
                                    "keyword" if kind == "character" else "sceneEn",
                                    120, expect_list=False)
    out = {}
    if kind == "character":
        for k in ("age", "role", "face", "flaw", "wardrobeHook", "wardrobe", "keyword", "keywordEn"):
            out[k] = _as(data.get(k), "", 300)
    elif kind == "prop":
        out["appearance"] = _as(data.get("appearance"), "", 200)
        out["propEn"] = _as(data.get("propEn"), "", 300)
    else:
        out["sceneEn"] = _as(data.get("sceneEn"), "", 300)
        out["light"] = _as(data.get("light"), "", 80)
        out["lens"] = _as(data.get("lens"), "", 40)
        out["appearance"] = _as(data.get("appearance"), "", 200)
        out["props"] = _alist(data.get("props"), 12, 40)
    out["model"] = model
    return out


# --------------------------------------------------------------------------
# 剧本拆解任务（后端实时进度 + 事件流）
#   【休眠保留 · 无 UI 入口，勿删（旧项目恢复用）】S2 起一键入口已移除，
#   当前主流程是四个工作区逐步人工确认 + /api/ai/* 单步接口；本段仅供旧项目恢复进度。
#   为什么放后端：拆解是 6 个阶段、串行几十秒的活。前端自己 Promise 串联时，
#   刷新页面 / 换标签页进度就没了，也没法在关掉页面后继续。改成「后端任务 + 事件流」：
#     POST /api/parse/start   → { taskId }，后端线程开跑，立刻返回
#     GET  /api/parse/events  → SSE（text/event-stream），按 seq 增量推送，断了可 since 续传
#     GET  /api/parse/state   → 整份快照（阶段 / 事件 / 结果），刷新页面靠它恢复
#     GET  /api/parse/latest  → 最近一个任务，页面刚打开时用来接上没看完的进度
#     POST /api/parse/cancel  → 取消（阶段边界生效，已产出的结果不写入项目）
#
#   事件统一结构（seq 单调递增，前端只 append）：
#     { seq, ts, type, status, stage, stageLabel, percent, done, total,
#       state?, tool?, phase?, callId?, label?, detail?, hint?, ms?, data? }
#       type: task | stage | tool | log | ping | done | error
#       state: running | ok | fail | skip（阶段与工具的状态）
#       phase: start | end（工具调用的一对事件，用 callId 配对）
# --------------------------------------------------------------------------
PARSE_TASKS: dict = {}
PARSE_LOCK = threading.Lock()
PARSE_COND = threading.Condition(PARSE_LOCK)
PARSE_SEQ = [0]
PARSE_KEEP = 8                                  # 只留最近 8 个任务，防内存堆积
PARSE_END_STATES = ("done", "failed", "cancelled")

# 阶段表：权重之和 100，进度条按权重累加；分镜阶段内部再按「集」细分
PARSE_STAGES = (
    ("detect", "识别剧本格式", 5),
    ("adapt", "忠实转写", 20),
    ("assets", "资产分解", 20),
    ("plan", "自动分集", 15),
    ("storyboard", "逐集分镜", 30),
    ("frames", "起始帧提示词", 5),
    ("verify", "覆盖校验", 5),
)
PARSE_LABEL = {k: label for k, label, _ in PARSE_STAGES}


class ParseCancelled(Exception):
    """任务被取消：阶段边界抛出，不写任何结果。"""


class ParseTask:
    def __init__(self, tid, project=""):
        self.id = tid
        self.project = project          # 属于哪个项目：刷新后只在同一项目里恢复进度
        self.status = "queued"
        self.created_at = time.time()
        self.started_at = 0.0
        self.finished_at = 0.0
        self.seq = 0
        self.events = []
        self.stages = [{"key": k, "label": label, "weight": w, "status": "pending",
                        "detail": "", "tool": "", "startedAt": 0.0, "endedAt": 0.0,
                        "frac": 0.0, "ms": 0} for k, label, w in PARSE_STAGES]
        self.cur = ""
        self.done = 0                            # 已完成阶段数（分镜阶段按集额外累加）
        self.total = len(PARSE_STAGES)
        self.errors = []
        self.warnings = []
        self.result = None
        self.cancelled = False

    # ---------------- 进度 ----------------
    def stage_of(self, key):
        for x in self.stages:
            if x["key"] == key:
                return x
        raise KeyError(key)

    def percent(self):
        total = sum(x["weight"] for x in self.stages) or 1
        acc = 0.0
        for x in self.stages:
            if x["status"] in ("ok", "skip", "fail"):
                acc += x["weight"]
            elif x["status"] == "running":
                acc += x["weight"] * min(1.0, max(0.0, x["frac"]))
        return max(0, min(100, int(round(acc * 100.0 / total))))

    def emit(self, type_, **kw):
        """追加一条事件并唤醒等流的连接。调用方不要持锁。"""
        with PARSE_COND:
            self.seq += 1
            ev = {
                "seq": self.seq,
                "ts": round(time.time() - self.created_at, 2),
                "type": type_,
                "status": self.status,
                "stage": kw.pop("stage", self.cur),
                "percent": self.percent(),
                "done": self.done,
                "total": self.total,
            }
            ev["stageLabel"] = PARSE_LABEL.get(ev["stage"], "")
            ev.update(kw)
            self.events.append(ev)
            if len(self.events) > 320:           # 长时间任务也不能把内存吃光
                del self.events[:-320]
            PARSE_COND.notify_all()
            return ev

    def begin_stage(self, key, tool, label, detail=""):
        st = self.stage_of(key)
        st.update(status="running", tool=tool, detail=detail, frac=0.0,
                  startedAt=round(time.time() - self.created_at, 2))
        self.cur = key
        self.emit("stage", stage=key, state="running", label=label, detail=detail, tool=tool)
        self.emit("tool", stage=key, phase="start", callId="%s#1" % key,
                  tool=tool, label=label, detail=detail)

    def end_stage(self, key, state="ok", detail="", ms=0.0, count=True):
        st = self.stage_of(key)
        st["status"] = state
        st["endedAt"] = round(time.time() - self.created_at, 2)
        st["ms"] = int(ms)
        if detail:
            st["detail"] = detail
        st["frac"] = 1.0 if state in ("ok", "fail") else st["frac"]
        # 分镜阶段已经按集累加过 done，收尾时不能再加一次，否则「已完成」会超过总数
        if count and state in ("ok", "skip", "fail"):
            self.done = min(self.total, self.done + 1)
        self.emit("stage", stage=key, state=state, label=st["label"],
                  detail=st["detail"], ms=int(ms), tool=st["tool"])
        self.emit("tool", stage=key, phase="end", callId="%s#1" % key, state=state,
                  tool=st["tool"], label=st["label"], detail=st["detail"], ms=int(ms))

    def sub_progress(self, frac, detail=""):
        """当前阶段内部进度（分镜按集推进）。"""
        if not self.cur:
            return
        st = self.stage_of(self.cur)
        st["frac"] = max(0.0, min(1.0, frac))
        if detail:
            st["detail"] = detail
        self.emit("stage", stage=self.cur, state="running", label=st["label"],
                  detail=st["detail"], tool=st["tool"])

    def check_cancel(self):
        if self.cancelled:
            raise ParseCancelled()

    def heartbeat(self, key, base):
        """模型调用期间没有中间产物：每 6 秒刷一次「已等 Ns」，别让界面看着像卡死。"""
        task = self

        class _HB:
            def __enter__(self_inner):
                self_inner.stop = threading.Event()

                def run():
                    n = 0
                    while not self_inner.stop.wait(6):
                        n += 1
                        st = task.stage_of(key)
                        task.sub_progress(st["frac"],
                                          "%s · 模型处理中 %ds" % (base, n * 6))

                self_inner.thread = threading.Thread(target=run, daemon=True)
                self_inner.thread.start()
                return self_inner

            def __exit__(self_inner, *exc):
                self_inner.stop.set()

        return _HB()


def parse_task_snapshot(task):
    with PARSE_LOCK:
        return {
            "id": task.id, "project": task.project, "status": task.status,
            "percent": task.percent(), "done": task.done, "total": task.total,
            "stage": task.cur, "stageLabel": PARSE_LABEL.get(task.cur, ""),
            "createdAt": round(task.created_at, 3),
            "startedAt": round(task.started_at, 3),
            "endedAt": round(task.finished_at, 3),
            "elapsed": round((task.finished_at or time.time()) -
                             (task.started_at or task.created_at), 1),
            "ended": task.status in PARSE_END_STATES,
            "stages": json.loads(json.dumps(task.stages)),
            "events": json.loads(json.dumps(task.events)),
            "errors": json.loads(json.dumps(task.errors)),
            "warnings": list(task.warnings),
            "result": task.result if task.status == "done" else None,
        }


def parse_task_wait(task, since, timeout=2.0):
    """阻塞到有新事件或任务收尾；SSE 与轮询都走它。"""
    with PARSE_COND:
        pend = [e for e in task.events if e["seq"] > since]
        over = task.status in PARSE_END_STATES
        if pend or over:
            return [json.loads(json.dumps(e)) for e in pend], over
        PARSE_COND.wait(timeout)
        pend = [json.loads(json.dumps(e)) for e in task.events if e["seq"] > since]
        return pend, task.status in PARSE_END_STATES


def parse_task_start(payload):
    script = str(payload.get("script", ""))
    if len(script.strip()) < 20:
        raise ValueError("剧本文字太短，无法分析")
    with PARSE_LOCK:
        PARSE_SEQ[0] += 1
        tid = "t%d_%d" % (int(time.time()), PARSE_SEQ[0])
        task = ParseTask(tid, _as(payload.get("projectId"), "", 64))
        PARSE_TASKS[tid] = task
        for old in sorted(PARSE_TASKS, key=lambda k: PARSE_TASKS[k].created_at)[:-PARSE_KEEP]:
            if PARSE_TASKS[old].status in PARSE_END_STATES:
                PARSE_TASKS.pop(old, None)
    threading.Thread(target=parse_task_worker, args=(task, payload), daemon=True).start()
    return {"taskId": tid, "total": task.total,
            "stages": json.loads(json.dumps(task.stages)),
            "stageLabels": PARSE_LABEL, "status": "queued"}


def parse_task_cancel(payload):
    tid = str(payload.get("id", ""))
    task = PARSE_TASKS.get(tid)
    if not task:
        return {"ok": False, "detail": "任务不存在或已过期"}
    task.cancelled = True
    with PARSE_COND:
        PARSE_COND.notify_all()
    return {"ok": True, "id": tid, "status": task.status}


def parse_task_latest():
    """页面刚打开：有在跑的任务就接上，没有就返回最近一次已结束的（不再自动弹窗）。"""
    with PARSE_LOCK:
        if not PARSE_TASKS:
            return {"task": None}
        tid = sorted(PARSE_TASKS, key=lambda k: PARSE_TASKS[k].created_at)[-1]
    return {"task": parse_task_snapshot(PARSE_TASKS[tid])}


def _parse_error_hint(stage, exc):
    msg = str(exc)
    if msg == "NO_KEY":
        return ("还没有配置大模型 Key：把 llm-config.example.bat 复制成 llm-config.bat 填上 Key，"
                "或者点「用本地规则生成」直接出分镜。")
    if isinstance(exc, urllib.error.HTTPError):
        return "模型服务返回错误（%s）。检查 Key、余额和网络后重试。" % getattr(exc, "code", "?")
    if isinstance(exc, AgentDisabledError):
        return "这一步用的角色被禁用了：到「生成设置 → 角色」里重新启用后再试。"
    return {
        "adapt": "转写没成功：可以只转写一次再重试，或直接改剧本格式。",
        "assets": "资产分解失败：分镜仍可用，只是资产设定会用规则抽取的空壳。",
        "plan": "分集没成功：可以点「用本地规则生成」直接出分镜。",
        "storyboard": "分镜失败：失败的那几集会保留本地规则版，其余集不受影响；可单独重试。",
    }.get(stage, "失败不会改动你现有的剧本与分镜，可以直接重试。")


def _clean_scenes(raw, limit=240):
    """前端解析好的场次清单（含对白 / 动作），只收需要的字段，防超大 payload。"""
    out = []
    for i, x in enumerate(raw or []):
        if not isinstance(x, dict):
            continue
        try:
            no = int(x.get("no"))
        except (TypeError, ValueError):
            no = i + 1
        lines = []
        for l in (x.get("lines") or [])[:80]:
            if isinstance(l, dict):
                lines.append({"speaker": _as(l.get("speaker"), "", 24),
                              "stage": _as(l.get("stage"), "", 24),
                              "text": _as(l.get("text"), "", 400)})
        actions = []
        for a in (x.get("actions") or [])[:80]:
            if isinstance(a, dict):
                actions.append({"text": _as(a.get("text"), "", 400)})
        out.append({
            "no": no,
            "intExt": _as(x.get("intExt"), "", 20),
            "location": _as(x.get("location"), "", 60),
            "time": _as(x.get("time"), "", 20),
            "characters": [_as(n, "", 24) for n in (x.get("characters") or [])[:16]
                           if isinstance(n, (str, int))],
            "lines": lines, "actions": actions,
        })
        if len(out) >= limit:
            break
    return out


_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _cn_int(txt):
    """场号：支持 12 / １２ / 十二 / 二十三 这几种写法。"""
    t = str(txt or "").strip().translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    if t.isdigit():
        return int(t)
    if not t:
        return 0
    if "十" in t:
        left, _, right = t.partition("十")
        tens = _CN_DIGITS.get(left, 1) if left else 1
        ones = _CN_DIGITS.get(right, 0) if right else 0
        return tens * 10 + ones
    return _CN_DIGITS.get(t, 0)


# 「原文没写」的兜底占位词：不是真实内容，既不进正文、不进资产名，也不进提示词
_PLACEHOLDER = {"未注明", "未指定", "未标注", "未确定", "未写明", "未提及",
                "未填写", "未知", "待定", "不详"}
_INT_EXT_MAP = {"内景": "内景", "内": "内景", "INT": "内景", "INT.": "内景",
                "外景": "外景", "外": "外景", "EXT": "外景", "EXT.": "外景"}
_TIME_WORDS = ("清晨", "早晨", "上午", "中午", "午后", "下午", "黄昏", "傍晚",
               "白天", "日", "夜", "深夜", "凌晨", "晚上", "稍后", "连续", "次日", "雨后")


def clean_placeholder(v, limit=80):
    """占位词一律当空串，避免「未注明」流进正文和提示词。"""
    t = _as(v, "", limit)
    return "" if t in _PLACEHOLDER else t


def split_head_fields(text):
    """把「内景 · 爷爷家堂屋 · 日」拆成 (内外景, 地点, 时间)。

    按语义归类而不是按位置：省略任一段、顺序颠倒都能对上；
    历史上写进正文的「未注明」也会被丢掉，不会顶掉真正的地点。
    """
    int_ext, loc, tm = "", "", ""
    for part in re.split(r"[·・|｜/]", text or ""):
        q = part.strip(" 　")
        if not q or q in _PLACEHOLDER:
            continue
        key = q.upper()
        if not int_ext and key in _INT_EXT_MAP:
            int_ext = _INT_EXT_MAP[key]
            continue
        if not tm and (q in _TIME_WORDS or
                       (len(q) <= 6 and any(len(w) > 1 and w in q for w in _TIME_WORDS))):
            tm = q
            continue
        if not loc:
            loc = q
    return int_ext, loc, tm


_SCENE_HEAD_RE = re.compile(r"^\s*第\s*([0-9０-９一二三四五六七八九十百零两]{1,6})\s*场\s*(.*)$")
_SCENE_DLG_RE = re.compile(r"^([^：:△▲\s《【][^：:]{0,11}?)(?:[（(]([^）)]{0,20})[）)])?\s*[：:]\s*(.+)$")
_SCENE_ACT_RE = re.compile(r"^[△▲]\s*(.+)$")


def parse_scene_script(text):
    """把场次剧本切回结构（后端转写产物就是这套固定格式）。

    只用于任务内部：转写后的剧本要在后端继续喂给资产 / 分集 / 分镜，
    界面上仍以 engine.js 的解析结果为准（同一份文本，场号一致）。
    """
    scenes, cur, title = [], None, ""
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("《") and line.endswith("》") and not title:
            title = line.strip("《》")
            continue
        m = _SCENE_HEAD_RE.match(line)
        if m:
            no = _cn_int(m.group(1)) or (len(scenes) + 1)
            head_ext, head_loc, head_time = split_head_fields(m.group(2))
            cur = {"no": no, "intExt": head_ext,
                   "location": head_loc,
                   "time": head_time,
                   "characters": [], "lines": [], "actions": []}
            scenes.append(cur)
            continue
        if cur is None:
            continue
        ma = _SCENE_ACT_RE.match(line)
        if ma:
            cur["actions"].append({"text": ma.group(1)[:400]})
            continue
        md = _SCENE_DLG_RE.match(line)
        if md:
            name = md.group(1).strip()
            cur["lines"].append({"speaker": name, "stage": (md.group(2) or "").strip(),
                                 "text": md.group(3).strip()[:400]})
            if name and name not in cur["characters"]:
                cur["characters"].append(name)
            continue
        cur["actions"].append({"text": line[:400]})
    return {"title": title, "scenes": scenes}


def _parse_stats(scenes):
    chars = set()
    for sc in scenes:
        for n in sc.get("characters") or []:
            if n:
                chars.add(n)
    return {"scenes": len(scenes),
            "lines": sum(len(sc.get("lines") or []) for sc in scenes),
            "actions": sum(len(sc.get("actions") or []) for sc in scenes),
            "characters": len(chars)}


def _local_plan(scenes, wanted):
    """分集兜底：模型挂了也能按场次连续切，不阻断出分镜。"""
    nos = sorted({int(x["no"]) for x in scenes if isinstance(x.get("no"), int)}) or [1]
    n = wanted if isinstance(wanted, int) and wanted > 0 else max(1, int(round(len(nos) / 4.0)))
    n = max(1, min(n, len(nos)))
    per = -(-len(nos) // n)
    eps = []
    for i in range(n):
        chunk = nos[i * per:(i + 1) * per]
        if not chunk:
            break
        eps.append({"no": len(eps) + 1, "title": "第%d集" % (len(eps) + 1), "synopsis": "",
                    "sceneFrom": chunk[0], "sceneTo": chunk[-1], "hook": "", "source": "local"})
    if eps:
        eps[-1]["sceneTo"] = nos[-1]
    return {"episodes": eps}


def _close_running_stage(task, state, detail):
    """任务异常 / 取消时，把停在 running 的阶段补一个收尾事件。"""
    with PARSE_LOCK:
        keys = [x["key"] for x in task.stages if x["status"] == "running"]
    for k in keys:
        task.end_stage(k, state, detail, 0)


def parse_task_worker(task, payload):
    with PARSE_LOCK:
        task.status = "running"
        task.started_at = time.time()
    task.emit("task", label="拆解任务已启动",
              detail="后端按阶段处理，进度会实时推送到界面")
    try:
        result = parse_task_pipeline(task, payload)
        with PARSE_LOCK:
            task.result = result
            task.status = "done"
            task.done = task.total
            task.cur = "done"
        st = result.get("stats") or {}
        task.emit("done", label="拆解完成",
                  detail="%d 场 / %d 集 / %d 镜" % (st.get("scenes", 0),
                                                    len(result.get("episodes") or []),
                                                    result.get("shotsTotal", 0)),
                  data={"stats": st, "warnings": len(result.get("warnings") or [])})
    except ParseCancelled:
        with PARSE_LOCK:
            task.status = "cancelled"
        _close_running_stage(task, "skip", "已取消")
        task.emit("error", state="cancelled", label="已取消",
                  detail="任务被手动取消，已有结果没有写入项目")
    except Exception as exc:
        detail = str(exc)[:300] or exc.__class__.__name__
        with PARSE_LOCK:
            task.status = "failed"
            task.errors.append({"stage": task.cur or "detect", "message": detail,
                                "hint": _parse_error_hint(task.cur, exc)})
        # 出错时把「进行中」的那个阶段收尾，否则界面会一直转圈显示它在跑
        _close_running_stage(task, "fail", "失败：" + detail[:60])
        task.emit("error", label="拆解失败", detail=detail,
                  hint=_parse_error_hint(task.cur, exc))
    finally:
        with PARSE_LOCK:
            task.finished_at = time.time()
        PARSE_COND.notify_all()


def parse_task_pipeline(task, payload):
    """六个阶段串起来：detect → adapt → assets → plan → storyboard → frames → verify。

    每个阶段失败都不直接崩掉整个任务（分镜按集降级），只有「一镜都产不出来」才算任务失败。
    """
    script = str(payload.get("script", ""))
    config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    wanted = payload.get("episodes", "auto")
    scenes = _clean_scenes(payload.get("scenes"))
    novel = bool(payload.get("novel"))
    warnings, degraded, groups, coverage = [], [], [], {}
    model, pack, frames, frame_stats, adapted = "", None, [], None, False
    cov = {"dialogueTotal": 0, "dialogueFromModel": 0, "actionTotal": 0,
           "actionFromModel": 0, "patched": 0}

    # ---------------- 1. 识别格式（纯本地） ----------------
    t0 = time.time()
    task.begin_stage("detect", "rule:detect_format", "识别剧本格式",
                     detail="检查场次行 / 对白行 / 文本类型")
    task.check_cancel()
    if not scenes:
        scenes = parse_scene_script(script)["scenes"]
    stats = _parse_stats(scenes)
    task.end_stage("detect", "ok",
                   detail="%s：%d 场 / %d 句对白 / %d 角色" % (
                       "小说 · 散文体，需先转写" if novel else "场次剧本",
                       stats["scenes"], stats["lines"], stats["characters"]),
                   ms=(time.time() - t0) * 1000)
    if not stats["scenes"] or not stats["lines"]:
        raise ValueError("剧本里没有识别到场次或对白，先把格式确认一下再试")

    # ---------------- 2. 忠实转写（仅小说体） ----------------
    if novel:
        t0 = time.time()
        task.begin_stage("adapt", "llm:adapt_script", "忠实转写场次剧本",
                         detail="模型只输出结构，正文由原文句子逐字重组")
        sents = split_source_sentences(script)
        if len(sents) < 3:
            raise ValueError("原文太短，无法切分场次（至少需要 3 句）")
        listing = "\n".join("[%d] %s" % (i, x) for i, x in enumerate(sents))
        user = ("原文句子清单（编号从 0 开始，end 为闭区间）：\n%s\n\n共 %d 句。"
                "只输出结构 JSON，不要输出原文正文。" % (listing, len(sents)))
        try:
            data, model = call_llm_json(agent_system("adapt"), user, "scenes", 240)
            task.check_cancel()
            adapted_text = build_adapted_script(sents, data)
            if len(adapted_text) < 40:
                raise ValueError("转写没有生成有效剧本文本")
            chk = check_adaptation(script, adapted_text)
            script = adapted_text
            adapted = True
            parsed_new = parse_scene_script(script)
            scenes = parsed_new["scenes"]
            stats = _parse_stats(scenes)
            warnings.extend("转写校验：" + w for w in chk["warnings"])
            task.end_stage("adapt", "ok",
                           detail="%d 场 / %d 句对白，原文覆盖 %d/%d 句" % (
                               stats["scenes"], stats["lines"],
                               chk["sentencesCovered"], chk["sentencesTotal"]),
                           ms=(time.time() - t0) * 1000)
        except ParseCancelled:
            raise
        except Exception as exc:
            warnings.append("转写失败（%s），已按原文继续" % str(exc)[:80])
            task.end_stage("adapt", "fail",
                           detail="转写失败，已按原文继续：" + str(exc)[:60],
                           ms=(time.time() - t0) * 1000)
    else:
        task.end_stage("adapt", "skip", detail="已经是场次剧本，跳过转写", ms=0)

    # ---------------- 3. 资产分解 ----------------
    t0 = time.time()
    task.begin_stage("assets", "llm:decompose_assets", "分解角色 / 场景 / 道具",
                     detail="从剧本抽资产，写三视图 / 概念图提示词与固定关键词串")
    scene_list = "\n".join(
        "- 第%s场 [S%s] %s%s｜人物：%s" % (
            x.get("no"), x.get("no"), x.get("intExt") or "",
            x.get("location") or "未写明地点",
            "、".join(str(n) for n in (x.get("characters") or [])) or "未注明")
        for x in scenes) or "（场次信息不可用）"
    try:
        user = ("场次清单（evidence 只能引用这里的 S 编号，sceneNos 只能填这里的场号）：\n%s\n\n"
                "剧本 / 小说全文：\n%s" % (scene_list, script[:26000]))
        with task.heartbeat("assets", "正在拆解资产"):
            data, model = call_llm_json(agent_system("assets"), user, "characters", 240)
        task.check_cancel()
        pack = build_asset_pack(data, scenes)
        pack["model"] = model
        a = pack.get("assets") or {}
        task.end_stage("assets", "ok",
                       detail="%d 角色 / %d 场景 / %d 道具" % (
                           len(a.get("characters") or []), len(a.get("scenes") or []),
                           len(a.get("props") or [])),
                       ms=(time.time() - t0) * 1000)
    except ParseCancelled:
        raise
    except Exception as exc:
        pack = build_asset_pack({"characters": [], "scenes": [], "props": []}, scenes)
        pack["model"] = ""
        warnings.append("资产分解失败（%s），已退回规则抽取：设定会是空壳" % str(exc)[:80])
        task.end_stage("assets", "fail",
                       detail="失败，退回规则抽取：" + str(exc)[:60],
                       ms=(time.time() - t0) * 1000)

    # ---------------- 4. 分集 ----------------
    t0 = time.time()
    task.begin_stage("plan", "llm:plan_episodes", "规划分集",
                     detail="通读剧本，按钩子与节奏切集")
    target = wanted if isinstance(wanted, int) and 1 <= wanted <= 6 else "auto"
    ep_scene_list = "\n".join(
        "- 第%s场 %s%s：%s 句对白 / %s 条动作" % (
            x.get("no"), x.get("intExt") or "", x.get("location") or "未写明地点",
            len(x.get("lines") or []), len(x.get("actions") or []))
        for x in scenes) or "（场次信息不可用，请按剧本原文自行判断）"
    try:
        user = ("目标集数：%s\n\n场次清单：\n%s\n\n剧本全文：\n%s" %
                (target, ep_scene_list, script[:18000]))
        with task.heartbeat("plan", "正在规划分集"):
            data, model2 = call_llm_json(agent_system("plan"), user, "episodes", 180)
        task.check_cancel()
        episodes = normalize_plan(data, scenes, target)["episodes"]
        for e in episodes:
            e["source"] = "ai"
        model = model2 or model
        task.end_stage("plan", "ok",
                       detail="%d 集：%s" % (len(episodes),
                                             " / ".join("第%s集" % e["no"] for e in episodes[:6])),
                       ms=(time.time() - t0) * 1000)
    except ParseCancelled:
        raise
    except Exception as exc:
        episodes = _local_plan(scenes, target)["episodes"]
        warnings.append("自动分集失败（%s），已按场次连续切成 %d 集" %
                        (str(exc)[:80], len(episodes)))
        task.end_stage("plan", "fail",
                       detail="失败，按场次兜底切成 %d 集" % len(episodes),
                       ms=(time.time() - t0) * 1000)
    if not episodes:
        raise ValueError("没有可用的分集方案")

    # ---------------- 5. 逐集分镜 ----------------
    t0 = time.time()
    with PARSE_LOCK:
        task.total = len(task.stages) + max(0, len(episodes) - 1)
    task.begin_stage("storyboard", "llm:storyboard", "逐集拆解分镜",
                     detail="共 %d 集，逐集串行生成" % len(episodes))
    cap = {"compact": (4, 18), "cinematic": (8, 34)}.get(config.get("pacing") or "standard",
                                                         (6, 28))
    for i, ep in enumerate(episodes, 1):
        task.check_cancel()
        task.sub_progress((i - 1) / len(episodes),
                          "正在生成第 %d / %d 集《%s》" % (i, len(episodes), ep.get("title", "")))
        call_id = "storyboard#%d" % i
        label = "第 %d 集《%s》" % (ep["no"], ep.get("title", ""))
        task.emit("tool", phase="start", callId=call_id, tool="llm:storyboard",
                  label=label, detail="第 %s–%s 场" % (ep["sceneFrom"], ep["sceneTo"]))
        ep_scenes = [x for x in scenes if ep["sceneFrom"] <= int(x["no"]) <= ep["sceneTo"]]
        te = time.time()
        try:
            system = agent_system("storyboard", min_shots=cap[0], max_shots=cap[1])
            index, line_list = build_script_index(ep_scenes)
            s_list = "\n".join(
                "- 第%s场 %s%s｜对白：%s｜动作：%s" % (
                    x.get("no"), x.get("intExt") or "", x.get("location") or "",
                    " / ".join(str(l.get("text", "")) for l in (x.get("lines") or [])[:6]) or "无",
                    " / ".join(str(a.get("text", "")) for a in (x.get("actions") or [])[:6]) or "无")
                for x in ep_scenes) or "（无场次信息）"
            user = ("本集信息：第%s集《%s》 场次范围：第%s场–第%s场\n生成设置：基准单镜时长 %s 秒；"
                    "节奏 %s；画面比例 %s\n\n本集场次详情：\n%s\n\n"
                    "剧本行清单（refs 只能引用这里的编号，按此顺序编排）：\n%s\n\n"
                    "剧本全文（只处理场次范围内的内容）：\n%s" % (
                        ep["no"], ep.get("title", ""), ep["sceneFrom"], ep["sceneTo"],
                        config.get("defaultDuration", 4), config.get("pacing") or "standard",
                        config.get("aspect") or "16:9", s_list, line_list,
                        _script_slice_for_ep(script, ep)))
            with task.heartbeat("storyboard", "第 %d 集分镜" % ep["no"]):
                data, model3 = call_llm_json(system, user, "shots", 240)
            task.check_cancel()
            r = normalize_shots(data, ep_scenes, config, index)
            groups.append(r["shots"])
            model = model3 or model
            for k in cov:
                cov[k] += int((r.get("coverage") or {}).get(k) or 0)
            for w in r.get("warnings") or []:
                warnings.append("第%s集：%s" % (ep["no"], w))
            task.emit("tool", phase="end", callId=call_id, state="ok",
                      tool="llm:storyboard", label=label,
                      detail="%d 镜" % len(r["shots"]), ms=int((time.time() - te) * 1000))
            with PARSE_LOCK:
                task.done = min(task.total, task.done + 1)
        except ParseCancelled:
            raise
        except Exception as exc:
            degraded.append({"no": ep["no"], "reason": str(exc)[:160]})
            groups.append([])                     # 前端按 degraded 用本地规则补这一集
            task.emit("tool", phase="end", callId=call_id, state="fail",
                      tool="llm:storyboard", label=label,
                      detail="失败，该集交回前端用本地规则补齐：" + str(exc)[:50],
                      ms=int((time.time() - te) * 1000))
            with PARSE_LOCK:
                task.done = min(task.total, task.done + 1)
        task.sub_progress(i / len(episodes),
                          "已完成第 %d / %d 集" % (i, len(episodes)))
    ok_eps = len(groups) - len(degraded)
    task.end_stage("storyboard", "ok" if not degraded else "fail",
                   detail=("%d / %d 集完成" % (ok_eps, len(episodes)) if not degraded else
                           "%d 集失败（已回退本地规则），其余 %d 集正常" % (len(degraded), ok_eps)),
                   ms=(time.time() - t0) * 1000, count=False)
    if ok_eps <= 0:
        raise ValueError("所有集的分镜都失败了：%s" % (degraded[0]["reason"] if degraded else "未知原因"))

    # ---------------- 6. 起始帧提示词（本地模板，秒回） ----------------
    t0 = time.time()
    task.begin_stage("frames", "local:frame_prompts", "生成起始帧提示词",
                     detail="资产包 + 分镜表 → 每镜首帧的中英提示词")
    flat = []
    for ei, ep in enumerate(episodes):
        for si, sh in enumerate(groups[ei] if ei < len(groups) else [], 1):
            flat.append(dict(sh, episode=ep["no"], code="E%02d-%03d" % (ep["no"], si)))
    try:
        task.check_cancel()
        r = build_frame_prompts(flat, pack or {}, config.get("aspect") or "16:9")
        frames, frame_stats = r["frames"], r["stats"]
        task.end_stage("frames", "ok", detail="%d 镜首帧提示词" % len(frames),
                       ms=(time.time() - t0) * 1000)
    except ParseCancelled:
        raise
    except Exception as exc:
        warnings.append("起始帧提示词生成失败：" + str(exc)[:80])
        task.end_stage("frames", "fail", detail="失败：" + str(exc)[:60],
                       ms=(time.time() - t0) * 1000)

    # ---------------- 7. 覆盖校验 ----------------
    t0 = time.time()
    task.begin_stage("verify", "rule:coverage_check", "核对台词 / 动作覆盖",
                     detail="逐条比对剧本行，漏项已由服务端补镜")
    task.check_cancel()
    dl = cov.get("dialogueTotal") or 0
    dn = cov.get("dialogueFromModel") or 0
    al = cov.get("actionTotal") or 0
    an = cov.get("actionFromModel") or 0
    if dl and dn < dl:
        warnings.append("有 %d 句台词是服务端补镜补上的，建议抽查" % (dl - dn))
    if al and an < al:
        warnings.append("有 %d 条动作被画面吸收或补镜，建议抽查" % (al - an))
    task.end_stage("verify", "ok" if dn >= dl else "fail",
                   detail="台词 %d/%d · 动作 %d/%d · 补镜 %d" % (
                       dn, dl, an, al, cov.get("patched") or 0),
                   ms=(time.time() - t0) * 1000)

    shots_total = sum(len(g) for g in groups)
    return {
        "script": script, "adapted": adapted,
        "scenes": scenes, "stats": stats,
        "episodes": episodes, "groups": groups, "shotsTotal": shots_total,
        "assetPack": pack, "assetWarnings": (pack or {}).get("warnings") or [],
        "frames": frames, "frameStats": frame_stats,
        "coverage": cov, "warnings": warnings, "degraded": degraded,
        "model": model, "assetModel": (pack or {}).get("model") or "",
    }


def _script_slice_for_ep(script, ep):
    """取某集的剧本文本：有场次行就按行号切，没有就整篇给（与前端 scriptSlice 同义）。"""
    lines = (script or "").splitlines()
    picked, on = [], False
    for ln in lines:
        m = _SCENE_HEAD_RE.match(ln)
        if m:
            no = _cn_int(m.group(1))
            on = ep["sceneFrom"] <= no <= ep["sceneTo"]
        if on:
            picked.append(ln)
    text = "\n".join(picked).strip()
    return text or (script or "")[:20000]


# --------------------------------------------------------------------------
# 项目管理（Studio 式）
#   一个项目 = projects/<id>/project.json，整份界面状态（剧本 / 分镜 / 资产 /
#   资产包 / 起始帧 / 风格）都在 data 里；参考图与生成图的 dataURI 也随项目落盘。
#   放本机磁盘而不是 localStorage，是因为生成几张素材图就能把 5MB 配额撑爆，
#   写失败后刷新页面就「项目没了」——这是原来丢数据的根因。
# --------------------------------------------------------------------------
PROJECTS_DIR = ROOT / "projects"
PROJECT_TRASH_DIR = PROJECTS_DIR / ".trash"
PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")
PROJECT_LOCK = threading.Lock()
PROJECT_MAX_BYTES = 64 * 1024 * 1024     # 单项目上限，防止异常请求把磁盘写满


def _project_now():
    return _dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _project_path(pid):
    if not PROJECT_ID_RE.match(str(pid or "")):
        raise ValueError("非法项目 id")
    return PROJECTS_DIR / pid / "project.json"


PROJECT_REF_MAX_BYTES = 24 * 1024 * 1024    # 单张参考图上限（存原文件，不压缩）
PROJECT_REF_NAME_RE = re.compile(r"^[A-Za-z0-9]{8,40}\.(png|jpg|jpeg|webp|gif|bmp|avif)$")
PROJECT_REF_URL_RE = re.compile(r"/api/projects/ref\?id=[A-Za-z0-9_-]+&f=([A-Za-z0-9]+\.[a-z0-9]+)")


def _project_ref_dir(pid):
    return PROJECTS_DIR / pid / "refs"


def project_ref_save(payload):
    """上传的参考图落盘存原文件，返回一个 URL。

    以前参考图会被前端压成 512px JPEG 再塞进 project.json 的 dataURI —— 画质有损，
    而且 base64 会把项目文件撑大。现在原图按内容哈希存到 projects/<id>/refs/，
    项目里只留一个 URL：画质不动，project.json 也不再随图片膨胀。
    """
    pid = str(payload.get("id") or "").strip()
    if not PROJECT_ID_RE.match(pid) or not (PROJECTS_DIR / pid).is_dir():
        raise ValueError("项目不存在或已被删除")
    raw, ext = _decode_data_url(payload.get("data"))
    if not raw:
        raise ValueError("这不是一张能识别的图片（支持 png / jpg / webp / gif / bmp / avif）")
    if len(raw) > PROJECT_REF_MAX_BYTES:
        raise ValueError("图片超过 24MB，换一张小一点的")
    d = _project_ref_dir(pid)
    d.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha1(raw).hexdigest()[:20] + "." + ext
    f = d / name
    if not f.is_file():                      # 同一张图重复上传只留一份
        tmp = d / (name + ".tmp")
        tmp.write_bytes(raw)
        os.replace(tmp, f)
    return {"ok": True, "file": name, "bytes": len(raw), "ext": ext,
            "originalName": _as(payload.get("name"), "", 120),
            "url": "/api/projects/ref?id=" + pid + "&f=" + name}


def project_ref_read(pid, name):
    pid = str(pid or "")
    name = str(name or "")
    if not PROJECT_ID_RE.match(pid) or not PROJECT_REF_NAME_RE.match(name):
        raise ValueError("非法图片路径")
    f = _project_ref_dir(pid) / name
    if not f.is_file():
        raise ValueError("图片不存在")
    return f.read_bytes(), REF_MIME.get(name.rsplit(".", 1)[-1].lower(), "application/octet-stream")


def project_ref_thumb(pid, name, raw, width):
    """按宽度要一张缩略图（缓存到 refs/.thumb/），拿不到 Pillow 就返回 None。

    原图是几千万像素的照片，列表里 22px 的缩略图没必要解码整张 —— 那会白吃几百 MB
    内存。缩略图只用于界面显示，落盘的原图一点不动，下载 / 打包拿到的还是原图。
    """
    try:
        w = int(str(width or "0"))
    except (TypeError, ValueError):
        return None
    if w < 16 or w > 640:
        return None
    d = _project_ref_dir(pid) / ".thumb"
    f = d / ("%s_w%d.jpg" % (name.rsplit(".", 1)[0], w))
    if f.is_file():
        try:
            return f.read_bytes()
        except OSError:
            return None
    Image = _pil_image()
    if Image is None:
        return None
    try:
        im = Image.open(io.BytesIO(raw))
        im = im.convert("RGB")
        im.thumbnail((w, w), getattr(getattr(Image, "Resampling", Image), "LANCZOS"))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=82, optimize=True)
        out = buf.getvalue()
        d.mkdir(parents=True, exist_ok=True)
        (d / f.name).write_bytes(out)
        return out
    except Exception:
        return None


def _sweep_project_refs(pid, doc):
    """删掉项目里已经没人引用的参考图（换图 / 删资产留下的孤儿）。

    刚写入不足 1 小时的文件不动：上传和保存是两次请求，中间那一小段时间
    文件还没被 project.json 引用，扫掉就把用户刚传的图删了。
    """
    d = _project_ref_dir(pid)
    if not d.is_dir():
        return
    try:
        keep = set(PROJECT_REF_URL_RE.findall(json.dumps(doc, ensure_ascii=False)))
    except (TypeError, ValueError):
        return
    now = time.time()
    for f in d.iterdir():
        if not f.is_file() or f.name in keep:
            continue
        try:
            if now - f.stat().st_mtime < 3600:
                continue
            f.unlink()
        except OSError:
            pass


def _project_summary(pid, doc):
    """列表只回摘要，不回整份 data——否则项目一多，列表接口就变成几 MB。"""
    data = doc.get("data") if isinstance(doc.get("data"), dict) else {}
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    assets = data.get("assets") if isinstance(data.get("assets"), dict) else {}
    return {
        "id": doc.get("id") or pid,
        "name": doc.get("name") or "未命名项目",
        "createdAt": doc.get("createdAt") or "",
        "updatedAt": doc.get("updatedAt") or "",
        "step": int(data.get("step") or 1),
        "shots": len(data.get("shots") or []),
        "episodes": len(data.get("episodes") or []),
        "scriptChars": len(data.get("script") or ""),
        "title": (meta.get("title") or "")[:80],
        "assets": sum(len(assets.get(k) or []) for k in ("characters", "scenes", "props")),
        "genImages": sum(len(a.get("genImages") or [])
                         for k in ("characters", "scenes", "props")
                         for a in (assets.get(k) or []) if isinstance(a, dict)),
    }


def project_list():
    items = []
    if PROJECTS_DIR.is_dir():
        for d in PROJECTS_DIR.iterdir():
            if not d.is_dir() or d.name.startswith(".") or not PROJECT_ID_RE.match(d.name):
                continue
            f = d / "project.json"
            if not f.is_file():
                continue
            try:
                doc = json.loads(f.read_text("utf-8"))
            except Exception:
                continue          # 单个项目损坏不影响整个列表
            items.append(_project_summary(d.name, doc))
    items.sort(key=lambda x: x.get("updatedAt") or "", reverse=True)
    return items


def project_get(pid):
    f = _project_path(pid)
    if not f.is_file():
        raise ValueError("项目不存在或已被删除")
    try:
        doc = json.loads(f.read_text("utf-8"))
    except Exception as exc:
        raise ValueError("项目文件损坏：" + str(exc)[:120])
    return doc


def _project_write(pid, doc):
    d = PROJECTS_DIR / pid
    d.mkdir(parents=True, exist_ok=True)
    body = json.dumps(doc, ensure_ascii=False).encode("utf-8")
    if len(body) > PROJECT_MAX_BYTES:
        raise ValueError("项目太大（%.1f MB），请先清掉一些生成图"
                         % (len(body) / 1024 / 1024))
    f = d / "project.json"
    tmp = d / "project.json.tmp"
    tmp.write_bytes(body)
    os.replace(tmp, f)        # 原子替换：写到一半断电/崩溃不会留下半份项目
    _sweep_project_refs(pid, doc)
    return len(body)


def project_save(payload):
    pid = str(payload.get("id") or "").strip()
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("缺少项目数据")
    if not PROJECT_ID_RE.match(pid):
        raise ValueError("非法项目 id")
    name = _as(payload.get("name") or data.get("name"), "未命名项目", 80)
    with PROJECT_LOCK:
        f = _project_path(pid)
        created = _project_now()
        if f.is_file():
            try:
                created = json.loads(f.read_text("utf-8")).get("createdAt") or created
            except Exception:
                pass
        now = _project_now()
        doc = {"id": pid, "name": name, "createdAt": created,
               "updatedAt": now, "schema": 2, "data": data}
        size = _project_write(pid, doc)
    return {"ok": True, "id": pid, "name": name, "createdAt": created,
            "updatedAt": now, "bytes": size, "summary": _project_summary(pid, doc)}


def project_create(payload):
    name = _as(payload.get("name"), "未命名项目", 80)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    now = _dt.datetime.now()
    pid = "p_%s_%04x" % (now.strftime("%Y%m%d_%H%M%S"), random.randint(0, 0xffff))
    with PROJECT_LOCK:
        doc = {"id": pid, "name": name, "createdAt": _project_now(),
               "updatedAt": _project_now(), "schema": 2, "data": data}
        _project_write(pid, doc)
    return {"ok": True, "project": {"id": pid, "name": name, "createdAt": doc["createdAt"],
                                    "updatedAt": doc["updatedAt"], "data": data}}


def project_rename(payload):
    pid = str(payload.get("id") or "").strip()
    name = _as(payload.get("name"), "", 80)
    if not name:
        raise ValueError("项目名不能为空")
    with PROJECT_LOCK:
        f = _project_path(pid)
        if not f.is_file():
            raise ValueError("项目不存在")
        try:
            doc = json.loads(f.read_text("utf-8"))
        except Exception as exc:
            raise ValueError("项目文件损坏：" + str(exc)[:120])
        doc["name"] = name
        doc["updatedAt"] = _project_now()
        _project_write(pid, doc)
    return {"ok": True, "id": pid, "name": name, "updatedAt": doc["updatedAt"]}


def project_duplicate(payload):
    pid = str(payload.get("id") or "").strip()
    src = project_get(pid)
    now = _dt.datetime.now()
    nid = "p_%s_%04x" % (now.strftime("%Y%m%d_%H%M%S"), random.randint(0, 0xffff))
    with PROJECT_LOCK:
        # 参考图存的是 .../ref?id=<项目>&f=<文件>，副本得指向自己的目录，
        # 否则一改原项目的图，副本跟着变；删了原项目，副本全是裂图。
        data = json.loads(json.dumps(src.get("data") or {}, ensure_ascii=False)
                          .replace("/api/projects/ref?id=" + pid + "&",
                                   "/api/projects/ref?id=" + nid + "&"))
        doc = {"id": nid, "name": (_as(src.get("name"), "未命名项目", 70) + " 副本")[:80],
               "createdAt": _project_now(), "updatedAt": _project_now(), "schema": 2,
               "data": data}
        _project_write(nid, doc)
        srcdir, dstdir = _project_ref_dir(pid), _project_ref_dir(nid)
        if srcdir.is_dir():
            dstdir.mkdir(parents=True, exist_ok=True)
            for f in srcdir.iterdir():
                if f.is_file() and PROJECT_REF_NAME_RE.match(f.name):
                    (dstdir / f.name).write_bytes(f.read_bytes())
    return {"ok": True, "id": nid, "summary": _project_summary(nid, doc)}


def project_delete(payload):
    """不真删：移到 projects/.trash/，手滑还能捞回来。"""
    pid = str(payload.get("id") or "").strip()
    d = PROJECTS_DIR / pid
    if not PROJECT_ID_RE.match(pid) or not d.is_dir():
        raise ValueError("项目不存在")
    with PROJECT_LOCK:
        PROJECT_TRASH_DIR.mkdir(parents=True, exist_ok=True)
        target = PROJECT_TRASH_DIR / (pid + "_" + _dt.datetime.now().strftime("%Y%m%d_%H%M%S"))
        os.replace(d, target)
    return {"ok": True, "id": pid, "trashedTo": str(target.name)}


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def log_message(self, fmt, *args):
        if "/api/" in (self.path or ""):
            sys.stderr.write("[api] " + (fmt % args) + "\n")

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _bytes(self, data, filename, ctype="application/octet-stream", inline=False):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if inline:
            # 内容寻址（文件名 = 图片哈希），所以可以放心长缓存
            self.send_header("Content-Disposition", "inline; filename*=UTF-8''"
                             + urllib.parse.quote(filename))
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        else:
            self.send_header("Content-Disposition",
                             'attachment; filename="export.zip"; '
                             "filename*=UTF-8''" + urllib.parse.quote(filename))
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _read(self):
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _fail(self, exc):
        if isinstance(exc, RuntimeError) and str(exc) == "NO_KEY":
            return self._json({
                "detail": "还没有配置大模型 Key。当前自动使用离线规则引擎，核心功能都可用；"
                          "如需 AI 分集分镜，请复制 llm-config.example.bat 为 llm-config.bat 并填入 Key。"
            }, 503)
        if isinstance(exc, urllib.error.HTTPError):
            return self._json({"detail": "模型服务异常"}, 502)
        return self._json({"detail": str(exc)[:300]}, 502)

    def _query(self):
        return {k: v[0] for k, v in
                urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).items()}

    def _parse_stream(self):
        """SSE：按 seq 增量推事件，任务收尾后关连接；前端断线用 since 续传。"""
        q = self._query()
        tid = q.get("id", "")
        task = PARSE_TASKS.get(tid)
        if not task:
            return self._json({"detail": "任务不存在或已过期"}, 404)
        try:
            since = int(q.get("since") or self.headers.get("Last-Event-ID") or 0)
        except (TypeError, ValueError):
            since = 0
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        self.close_connection = True
        self.wfile.flush()
        last_ping = time.time()
        try:
            while True:
                events, over = parse_task_wait(task, since, 2.0)
                for ev in events:
                    since = ev["seq"]
                    self.wfile.write(("id: %d\ndata: %s\n\n" % (
                        ev["seq"], json.dumps(ev, ensure_ascii=False))).encode("utf-8"))
                if events:
                    self.wfile.flush()
                    last_ping = time.time()
                elif time.time() - last_ping >= 8:
                    self.wfile.write(b": ping\n\n")     # 心跳，防止中间层掐掉空闲连接
                    self.wfile.flush()
                    last_ping = time.time()
                if over and not events:
                    self.wfile.write(b": end\n\n")
                    self.wfile.flush()
                    break
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def _agent_get(self, path):
        q = self._query()
        if path == "/api/agents":
            return self._json(AGENTS.describe())
        if path == "/api/agents/prompt":
            aid = q.get("id", "")
            if not AGENT_ID_RE.match(aid):
                return self._json({"detail": "非法角色 id"}, 400)
            raw = AGENTS.read_prompt(aid)
            meta, body = parse_frontmatter(raw) if raw else ({}, "")
            return self._json({"id": aid, "content": raw, "meta": meta,
                               "compiled": AGENTS.system(aid)[0] if body else ""})
        if path == "/api/skills":
            out = []
            for sid in AGENTS.skill_ids():
                try:
                    meta, body = parse_frontmatter(AGENTS.read_skill(sid))
                except ValueError:
                    meta, body = {}, ""
                out.append({"id": sid, "name": meta.get("name", sid),
                            "description": meta.get("description", ""),
                            "chars": len(body)})
            return self._json({"skills": out})
        if path == "/api/skills/detail":
            sid = q.get("id", "")
            try:
                return self._json({"id": sid, "content": AGENTS.read_skill(sid)})
            except ValueError as exc:
                return self._json({"detail": str(exc)}, 404)
        return None

    def _agent_post(self, path, payload):
        """Agent / Skill 管理与通用执行；错误统一返回中文，不暴露堆栈。"""
        try:
            aid = str(payload.get("id") or "").strip()
            if path == "/api/agents/save":
                AGENTS.save_prompt(aid, payload.get("content"))
                return self._json({"ok": True, "id": aid})
            if path == "/api/agents/patch":
                AGENTS.patch_agent(aid, payload.get("patch") or {})
                return self._json({"ok": True, "id": aid})
            if path == "/api/agents/add":
                AGENTS.add_agent(payload)
                return self._json({"ok": True, "id": aid, "agents": AGENTS.describe()})
            if path == "/api/agents/delete":
                AGENTS.delete_agent(aid)
                return self._json({"ok": True, "agents": AGENTS.describe()})
            if path == "/api/skills/save":
                AGENTS.save_skill(aid, payload.get("content"))
                return self._json({"ok": True, "id": aid})
            if path == "/api/skills/add":
                sid = aid or "new-skill"
                AGENTS.save_skill(sid, payload.get("content") or
                                  "---\nname: %s\ndescription: 自定义技能\n---\n\n# %s\n" % (sid, sid))
                return self._json({"ok": True, "id": sid})
            if path == "/api/skills/delete":
                AGENTS.delete_skill(aid)
                return self._json({"ok": True, "id": aid})
            if path == "/api/agents/run":
                return self._json(AGENTS.run(aid, payload))
            return self._json({"detail": "不支持的 Agent 接口"}, 404)
        except ValueError as exc:
            return self._json({"detail": str(exc)[:300]}, 400)
        except RuntimeError as exc:
            return self._fail(exc)
        except (KeyError, json.JSONDecodeError) as exc:
            return self._json({"detail": "模型结果解析失败：" + str(exc)[:200]}, 502)
        except Exception as exc:
            return self._json({"detail": "处理失败：" + str(exc)[:200]}, 500)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/config":
            base, key, model = llm_settings()
            act = llm_active_provider()
            return self._json({
                "llm": bool(base and key),
                "model": model if (base and key) else "",
                "mode": "llm" if (base and key) else "local",
                "provider": {"id": act["id"], "name": act["name"],
                             "baseUrl": act["baseUrl"], "model": act["model"]} if act else None,
                "providerCount": len(_llm_doc()["providers"]),
                "features": ["adapt", "parse", "assets", "frames", "exportZip",
                             "plan", "storyboard", "agents", "skills", "agentRun",
                             "assetFill", "comfy", "qwenImage", "projects", "parseTask"],
            })
        if path == "/api/llm/providers":
            return self._json(llm_providers_public())
        if path == "/api/engine/config":
            return self._json(engine_config_public())
        if path == "/api/comfy/models":
            return self._json({"models": comfy_unet_names(), "host": comfy_host()})
        if path == "/api/comfy/status":
            return self._json(comfy_status())
        if path == "/api/comfy/job":
            jid = self._query().get("id", "")
            with COMFY_LOCK:
                job = COMFY_JOBS.get(jid)
                snap = json.loads(json.dumps(job)) if job else None
            if not snap:
                return self._json({"detail": "任务不存在或已过期"}, 404)
            # 轮询默认不回传 dataUri（每张几十 KB），只在 finished=1 时取回结果
            if self._query().get("full") != "1":
                for it in snap.get("items", []):
                    it.pop("dataUri", None)
            return self._json(snap)
        if path == "/api/comfy/image":
            name = self._query().get("f", "")
            if not ASSET_IMG_NAME.match(name):
                return self._json({"detail": "非法文件名"}, 400)
            f = ASSET_IMG_DIR / name
            if not f.is_file():
                return self._json({"detail": "图片不存在"}, 404)
            return self._bytes(f.read_bytes(), name, "image/png")
        if path in ("/api/agents", "/api/agents/prompt", "/api/skills", "/api/skills/detail"):
            return self._agent_get(path)
        if path == "/api/parse/events":
            return self._parse_stream()
        if path == "/api/parse/state":
            task = PARSE_TASKS.get(self._query().get("id", ""))
            if not task:
                return self._json({"detail": "任务不存在或已过期"}, 404)
            return self._json(parse_task_snapshot(task))
        if path == "/api/parse/latest":
            return self._json(parse_task_latest())
        if path == "/api/projects":
            return self._json({"projects": project_list(), "dir": str(PROJECTS_DIR)})
        if path == "/api/projects/ref":
            q = self._query()
            pid, fname = q.get("id", ""), q.get("f", "")
            try:
                raw, mime = project_ref_read(pid, fname)
            except ValueError as exc:
                return self._json({"detail": str(exc)}, 404)
            thumb = project_ref_thumb(pid, fname, raw, q.get("w", ""))
            if thumb:
                return self._bytes(thumb, fname, "image/jpeg", inline=True)
            return self._bytes(raw, fname, mime, inline=True)
        if path == "/api/projects/get":
            try:
                return self._json(project_get(self._query().get("id", "")))
            except ValueError as exc:
                return self._json({"detail": str(exc)}, 404)
        return super().do_GET()

    PROJECT_POST_PATHS = (
        "/api/projects/save", "/api/projects/create", "/api/projects/rename",
        "/api/projects/delete", "/api/projects/duplicate",
        "/api/projects/upload-ref",
    )

    AGENT_POST_PATHS = (
        "/api/agents/save", "/api/agents/patch", "/api/agents/add",
        "/api/agents/delete", "/api/agents/run",
        "/api/skills/save", "/api/skills/add", "/api/skills/delete",
    )

    def do_POST(self):
        path = self.path.split("?")[0]
        if path not in ("/api/ai/plan", "/api/ai/storyboard",
                        "/api/ai/adapt", "/api/ai/assets",
                        "/api/ai/frames", "/api/llm/parse",
                        "/api/ai/asset-fill", "/api/comfy/generate", "/api/comfy/prompt",
                        "/api/parse/start", "/api/parse/cancel", "/api/import/docx",
                        "/api/llm/providers/save", "/api/llm/providers/activate",
                        "/api/llm/providers/delete", "/api/llm/test",
                        "/api/engine/config", "/api/engine/test",
                        "/api/export/zip") + self.AGENT_POST_PATHS + self.PROJECT_POST_PATHS:
            return self._json({"detail": "不支持的接口"}, 404)
        try:
            payload = self._read()
        except (ValueError, KeyError, UnicodeDecodeError) as exc:
            return self._json({"detail": "请求格式不对：" + str(exc)}, 400)
        if path in self.PROJECT_POST_PATHS:
            fn = {
                "/api/projects/save": project_save,
                "/api/projects/create": project_create,
                "/api/projects/rename": project_rename,
                "/api/projects/delete": project_delete,
                "/api/projects/duplicate": project_duplicate,
                "/api/projects/upload-ref": project_ref_save,
            }[path]
            try:
                return self._json(fn(payload))
            except ValueError as exc:
                return self._json({"detail": str(exc)[:200]}, 400)
            except OSError as exc:
                return self._json({"detail": "项目写入失败：" + str(exc)[:200]}, 500)

        if path == "/api/import/docx":
            # 只做「docx → 纯文本」：不落盘、不入项目、不回显原始二进制
            try:
                raw = base64.b64decode(str(payload.get("dataB64") or ""), validate=False)
            except Exception:
                return self._json({"detail": "文件内容解码失败，请重新选择文件"}, 400)
            if not raw:
                return self._json({"detail": "文件是空的"}, 400)
            if len(raw) > 24 * 1024 * 1024:
                return self._json({"detail": "文件超过 24MB，请先删掉里面的图片再上传"}, 413)
            try:
                out = docx_extract_text(raw)
            except ValueError as exc:
                return self._json({"detail": str(exc)[:220]}, 400)
            out["name"] = str(payload.get("name") or "")[:120]
            return self._json(out)

        if path == "/api/parse/start":
            try:
                return self._json(parse_task_start(payload))
            except ValueError as exc:
                return self._json({"detail": str(exc)[:200]}, 400)
        if path == "/api/parse/cancel":
            return self._json(parse_task_cancel(payload))

        if path in self.AGENT_POST_PATHS:
            return self._agent_post(path, payload)
        if path == "/api/export/zip":
            try:
                data, name = build_export_zip(payload)
            except Exception as exc:
                return self._json({"detail": "打包失败：" + str(exc)[:200]}, 500)
            return self._bytes(data, name, "application/zip")
        # 以下两个接口不走「剧本长度 >= 20」的通用校验：一个只改单项资产，一个只出图
        if path == "/api/ai/asset-fill":
            try:
                return self._json(fill_asset_with_ai(payload))
            except RuntimeError as exc:
                return self._fail(exc)
            except (ValueError, KeyError, json.JSONDecodeError) as exc:
                return self._json({"detail": "形象补全失败：" + str(exc)[:200]}, 502)
            except Exception as exc:
                return self._json({"detail": "形象补全失败：" + str(exc)[:200]}, 500)
        if path == "/api/llm/providers/save":
            try:
                return self._json(llm_provider_save(payload))
            except ValueError as exc:
                return self._json({"detail": str(exc)[:200]}, 400)
        if path == "/api/llm/providers/activate":
            try:
                return self._json(llm_provider_activate(payload))
            except ValueError as exc:
                return self._json({"detail": str(exc)[:200]}, 400)
        if path == "/api/llm/providers/delete":
            try:
                return self._json(llm_provider_delete(payload))
            except ValueError as exc:
                return self._json({"detail": str(exc)[:200]}, 400)
        if path == "/api/llm/test":
            try:
                return self._json(llm_test(payload))
            except ValueError as exc:
                return self._json({"detail": str(exc)[:200]}, 400)
        if path == "/api/engine/config":
            try:
                return self._json(engine_config_save(payload))
            except ValueError as exc:
                return self._json({"detail": str(exc)[:200]}, 400)
        if path == "/api/engine/test":
            try:
                return self._json(engine_probe(payload.get("kind")))
            except Exception as exc:
                return self._json({"detail": "探测失败：" + str(exc)[:160]}, 502)
        if path == "/api/comfy/prompt":
            # 只拼提示词，不依赖 ComfyUI 在线：没装模型也能先对稿
            try:
                raw_assets = payload.get("assets")
                assets = raw_assets if isinstance(raw_assets, list) else []
                return self._json(comfy_prompt_rows(
                    [a for a in assets[:24] if isinstance(a, dict)],
                    payload.get("variants") if isinstance(payload.get("variants"), dict) else {},
                    _as(payload.get("styleEn"), "", 240)))
            except (ValueError, TypeError) as exc:
                return self._json({"detail": str(exc)[:220]}, 400)
        if path == "/api/comfy/generate":
            engine = payload.get("engine")
            if engine not in ("comfy", "qwen"):
                engine = "comfy"
            seq_n = payload.get("n") if isinstance(payload.get("n"), int) else 1
            seq_n = max(1, min(seq_n, 4))
            if engine == "qwen":
                qs = qwen_image_status()
                if not qs.get("online"):
                    return self._json({"detail": "通义万相没配置好：" + qs.get("detail", "缺 API Key")}, 503)
            else:
                st = comfy_status()
                if not st.get("online"):
                    return self._json({"detail": "本地 ComfyUI 没连上（%s）：%s" %
                                                 (comfy_host(), st.get("detail", "未知原因"))}, 503)
            try:
                # _alist 只收字符串，这里 assets 是对象数组，必须自己取
                raw_assets = payload.get("assets")
                assets = raw_assets if isinstance(raw_assets, list) else []
                return self._json(comfy_job_start(
                    [a for a in assets[:24] if isinstance(a, dict)],
                    payload.get("variants") if isinstance(payload.get("variants"), dict) else {},
                    _as(payload.get("styleEn"), "", 200),
                    payload.get("seed") if isinstance(payload.get("seed"), int) else 0,
                    engine, seq_n))
            except (ValueError, TypeError) as exc:
                return self._json({"detail": str(exc)[:220]}, 400)
            except Exception as exc:
                return self._json({"detail": "出图任务启动失败：" + str(exc)[:200]}, 500)
        script = str(payload.get("script", ""))
        if path != "/api/ai/frames" and len(script.strip()) < 20:
            return self._json({"detail": "剧本文字太短，无法分析"}, 400)

        try:
            if path == "/api/ai/adapt":
                sents = split_source_sentences(script)
                if len(sents) < 3:
                    raise ValueError("原文太短，无法切分场次")
                listing = "\n".join("[%d] %s" % (i, x) for i, x in enumerate(sents))
                user = ("原文句子清单（编号从 0 开始，end 为闭区间）：\n%s\n\n"
                        "共 %d 句。只输出结构 JSON，不要输出原文正文。" % (listing, len(sents)))
                data, model = call_llm_json(agent_system("adapt"), user, "scenes", 240)
                adapted = build_adapted_script(sents, data)
                if len(adapted) < 40:
                    raise ValueError("转写没有生成有效剧本文本")
                chk = check_adaptation(script, adapted)
                result = {
                    "script": adapted,
                    "coverage": {
                        k: chk[k] for k in ("sceneHeads", "sentencesTotal", "sentencesCovered",
                                            "quotesTotal", "quotesCovered")
                    },
                    "warnings": chk["warnings"],
                }
            elif path == "/api/ai/assets":
                scenes = payload.get("scenes") or []
                scene_list = "\n".join(
                    "- 第%s场 [S%s] %s%s｜人物：%s" % (
                        x.get("no"), x.get("no"), x.get("intExt") or "",
                        x.get("location") or "未写明地点",
                        "、".join(str(n) for n in (x.get("characters") or [])) or "未注明")
                    for x in scenes if isinstance(x, dict)) or "（场次信息不可用）"
                user = ("场次清单（evidence 只能引用这里的 S 编号，sceneNos 只能填这里的场号）：\n%s\n\n"
                        "剧本 / 小说全文：\n%s" % (scene_list, script[:26000]))
                data, model = call_llm_json(agent_system("assets"), user, "characters", 240)
                result = build_asset_pack(data, scenes)
            elif path == "/api/ai/frames":
                model = "local-template"
                result = build_frame_prompts(
                    payload.get("shots") or [], payload.get("pack") or {},
                    _as(payload.get("aspect"), "16:9", 12))
            elif path == "/api/llm/parse":  # 兼容旧入口
                data, model = call_llm_json(agent_system("parse"), script, "scenes", 120)
                result = {"scenes": data["scenes"]}
            elif path == "/api/ai/plan":
                scenes = payload.get("scenes") or []
                wanted = payload.get("episodes")
                wanted = int(wanted) if isinstance(wanted, int) and 1 <= wanted <= 6 else "auto"
                scene_list = "\n".join(
                    "- 第%s场 %s%s：%s 句对白 / %s 条动作" % (
                        x.get("no"), x.get("intExt") or "", x.get("location") or "未写明地点",
                        len(x.get("lines") or []), len(x.get("actions") or []))
                    for x in scenes if isinstance(x, dict)) or "（场次信息不可用，请按剧本原文自行判断）"
                user = ("目标集数：%s\n\n场次清单：\n%s\n\n剧本全文：\n%s" %
                        (wanted, scene_list, script[:18000]))
                data, model = call_llm_json(agent_system("plan"), user, "episodes", 180)
                result = normalize_plan(data, scenes, wanted)
            else:
                ep = payload.get("episode") or {}
                scenes = payload.get("scenes") or []
                config = payload.get("config") or {}
                pacing = config.get("pacing") or "standard"
                cap = {"compact": (4, 18), "cinematic": (8, 34)}.get(pacing, (6, 28))
                system = agent_system("storyboard", min_shots=cap[0], max_shots=cap[1])
                ep_text = "第%s集《%s》 场次范围：第%s场–第%s场" % (
                    ep.get("no", 1), ep.get("title", ""), ep.get("sceneFrom", ""), ep.get("sceneTo", ""))
                scene_list = "\n".join(
                    "- 第%s场 %s%s｜对白：%s｜动作：%s" % (
                        x.get("no"), x.get("intExt") or "", x.get("location") or "",
                        " / ".join(str(l.get("text", "")) for l in (x.get("lines") or [])[:6]) or "无",
                        " / ".join(str(a.get("text", "")) for a in (x.get("actions") or [])[:6]) or "无")
                    for x in scenes if isinstance(x, dict)) or "（无场次信息）"
                setting = ("基准单镜时长 %s 秒；节奏 %s；画面比例 %s" %
                           (config.get("defaultDuration", 4), pacing, config.get("aspect", "16:9")))
                index, line_list = build_script_index(scenes)
                user = ("本集信息：%s\n生成设置：%s\n\n本集场次详情：\n%s\n\n"
                        "剧本行清单（refs 只能引用这里的编号，按此顺序编排）：\n%s\n\n"
                        "剧本全文（只处理场次范围内的内容）：\n%s" %
                        (ep_text, setting, scene_list, line_list, script[:20000]))
                data, model = call_llm_json(system, user, "shots", 240)
                result = normalize_shots(data, scenes, config, index)
            result["model"] = model
            return self._json(result)
        except AgentDisabledError as exc:
            return self._json({"detail": str(exc)[:200]}, 400)
        except RuntimeError as exc:
            return self._fail(exc)
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            return self._json({"detail": "模型结果解析失败：" + str(exc)[:200]}, 502)
        except Exception as exc:  # 兜底，避免线程异常导致界面一直转圈
            return self._json({"detail": "处理失败：" + str(exc)[:200]}, 500)


def main():
    no_browser = "--no-browser" in sys.argv
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    base, key, model = llm_settings()
    print("=" * 62)
    print("  分镜工场 ShortPlay Studio 已启动")
    print("  打开： http://127.0.0.1:%d/" % PORT)
    print("  AI 模式： " + ("已接入 %s（AI 分集 + AI 分镜）" % model if base and key else "离线规则引擎（无需联网）"))
    print("  停止服务：按 Ctrl+C，或直接关掉这个窗口")
    print("=" * 62, flush=True)
    if not no_browser:
        threading.Timer(0.8, lambda: webbrowser.open("http://127.0.0.1:%d/" % PORT)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()