"""Agent 工作台：角色 / 技能注册表。

设计口径：角色 = 注册表一条记录 + 一个 prompt 文件 + 若干 SKILL.md；
新增「剧本评估 / 剧本创作 / 导演」等角色不需要改 Python 代码。"""

import json
import re
import threading
from pathlib import Path

from app.infra.coerce import _as, s
from app.paths import ROOT
from app.services.llm_gateway import call_llm_json

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
