"""【休眠保留 · 无 UI 入口，勿删（旧项目恢复用）】

S2 起「AI 一键分集 + 分镜」的一键入口已从前端移除，改为
① 改剧本 → ② 分集 → ③ 分镜 → ④ 定妆 四步人工确认（单步接口 /api/ai/*）。
下面这条 7 阶段流水线代码保留、前端无任何入口，仅用于旧项目刷新时恢复进度；
删掉会让旧存档报错。不要把它当主流程，也不要新建 UI 入口。

单独成文件，是为了让它彻底不干扰主干阅读。"""

import json
import threading
import time
import urllib.request

from app.infra.coerce import _as, s
from app.services.agents import AgentDisabledError, agent_system
from app.services.assets import build_asset_pack, build_frame_prompts
from app.services.llm_gateway import call_llm_json
from app.services.plan import (_local_plan, _script_slice_for_ep,
                               build_script_index, normalize_plan)
from app.services.script_text import (_clean_scenes, _parse_stats,
                                      build_adapted_script, check_adaptation,
                                      parse_scene_script, split_source_sentences)
from app.services.shots import normalize_shots

PARSE_TASKS: dict = {}
PARSE_LOCK = threading.Lock()


PARSE_COND = threading.Condition(PARSE_LOCK)


PARSE_SEQ = [0]


PARSE_KEEP = 8                                  # 只留最近 8 个任务，防内存堆积


PARSE_END_STATES = ("done", "failed", "cancelled")


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
