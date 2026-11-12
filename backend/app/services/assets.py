"""资产层：资产包构建、整包合并、AI 补全、首帧提示词。

资产清单以分镜引用为准（S5 起），剧本只兜底；首帧提示词在定妆后生成（S6 起）。
"""

import json
import re

from app.infra.coerce import _alist, _as, _ints, _priority
from app.constants import (CONCEPT_TMPL, FRAME_TMPL,
                            NEGATIVE_DEFAULT, STYLE_ANCHOR_DEFAULT,
                            SYSTEM_ASSET_FILL)
from .llm_gateway import call_llm_json
from .script_text import clean_placeholder


def _char_main_prompt(item, style, negative):
    """角色主提示词：一条 = 定妆半身（正面胸像），尾部带全身三视图的补充说明。

    一个资产只有这一条出图提示词；三视图 / 面部四视图等其它视角按
    「一个资产一组提示词」的规则另拆独立资产，不再往这里叠。
    """
    an = item.get("anchors") or {}
    kw = item.get("keyword") or "，".join(
        x for x in (item.get("age"), an.get("face"), an.get("flaw"),
                    an.get("wardrobeHook"), item.get("wardrobe")) if x)
    return (
        "角色定妆图：正面胸像半身，视线平视镜头，表情中性，纯色干净背景，均匀柔光。\n"
        "{kw}\n"
        "面部特征：{face}；可辨识瑕疵：{flaw}。服装：{wardrobe}；"
        "配饰与记忆点：{hook}。\n"
        "{style}。写实电影质感，真实皮肤纹理，无磨皮；眼睛、鼻梁与唇形清晰。"
        "负面词（仅豆包 / 即梦等支持负面提示词的引擎有效）：{negative}"
    ).format(kw=kw, face=an.get("face") or "未指定", flaw=an.get("flaw") or "未指定",
             wardrobe=item.get("wardrobe") or "未指定", hook=an.get("wardrobeHook") or "未指定",
             style=style, negative=negative)


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
            "source": src, "evidence": ev, "sceneNos": nos,
            "weight": 5 if _priority(raw.get("priority")) == "P0" else 3,
            "refImage": "", "refName": "", "locked": False, "touched": {},
        }
        # 【一资产一提示词】主资产只带一条出图提示词（prompts.main = 定妆半身视角）。
        # 多视角一律拆成独立变体资产；主资产的 keyword 串是镜头一致性的真源。
        # 2026-11-12 起 Flux 双轨下线：全系统只剩中文一套提示词，*En/promptEn 删除。
        item["prompts"] = {"main": _char_main_prompt(item, style, negative)}
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
            "source": src, "evidence": ev, "sceneNos": nos,
            "refImage": "", "refName": "", "locked": False, "starred": False,
        }
        tags = "".join("，" + x for x in (int_ext, tm) if x)
        # 【一资产一提示词】场景主资产只留概念图一条。多视角按规则应拆成独立资产，
        # 不在同一资产上叠加第二组提示词（需要时用户可复制主资产另建宽幕变体）。
        item["prompts"] = {"main": CONCEPT_TMPL.format(
            name=name, tags=tags,
            props="、".join(props) or "按剧本场次描述", light=light,
            lens=lens, style=style, negative=negative)}
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
            "anchor": style, "negative": negative,
            # 三视图改 1:1：3:2 横版里三个全身的头只有 40–50px，脸必崩
            "aspect": {"turnaround": "1:1", "faceSheet": "3:2", "portrait": "3:4",
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
        # 出图主体字段是中文（道具=appearance），直接以它为首选期望字段
        try:
            data, model = call_llm_json(SYSTEM_ASSET_FILL, user, "appearance",
                                        120, expect_list=False)
        except ValueError:
            data, model = call_llm_json(SYSTEM_ASSET_FILL, user, "appearance",
                                        120, expect_list=False)
    else:
        data, model = call_llm_json(SYSTEM_ASSET_FILL, user,
                                    "keyword" if kind == "character" else "appearance",
                                    120, expect_list=False)
    out = {}
    if kind == "character":
        for k in ("age", "role", "face", "flaw", "wardrobeHook", "wardrobe", "keyword"):
            out[k] = _as(data.get(k), "", 300)
    elif kind == "prop":
        out["appearance"] = _as(data.get("appearance"), "", 200)
    else:
        out["light"] = _as(data.get("light"), "", 80)
        out["lens"] = _as(data.get("lens"), "", 40)
        out["appearance"] = _as(data.get("appearance"), "", 200)
        out["props"] = _alist(data.get("props"), 12, 40)
    out["model"] = model
    return out


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
        frames.append({
            "code": code, "sceneNo": no, "size": size,
            "aspect": aspect, "prompt": prompt_cn,
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
