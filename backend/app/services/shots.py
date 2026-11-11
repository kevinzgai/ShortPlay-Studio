"""分镜层：逐镜字段归一、通用套话落地、按场次修补。

DETAIL_FIELDS 是模型输出白名单，界面与导出共用同一顺序——别在这里加字段，
加了要同步导出与表头，否则三处顺序会漂。
"""

import re

from app.infra.coerce import num, s
from app.constants import DETAIL_FIELDS, GENERIC_RE, KIND_SET, SIZE_SET


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
