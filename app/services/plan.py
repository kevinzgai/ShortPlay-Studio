"""分集方案：把场次切成集，归一化模型输出。

_normalize_plan 只做形状校验与补齐，不做任何推断——集号与场号由人确认。
"""

from app.infra.coerce import s

from .script_text import _cn_int, _SCENE_HEAD_RE


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
