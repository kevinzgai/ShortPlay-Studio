"""渲染层：资产清单转 Markdown / CSV，供导出与预览复用。

只做字符串拼装，不落盘——落盘统一由 export_zip 负责。
"""

import datetime as _dt

from app.constants import (ASSET_KIND_CN, NEGATIVE_DEFAULT, SOURCE_CN,
                            STYLE_ANCHOR_DEFAULT)


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

    L.append("## 三、角色出图提示词（一资产一组，多视角拆独立资产）\n")
    for x in chars:
        p = x.get("prompts") or {}
        L.append("### %s %s（%s · %s）" % (x.get("code") or "", x.get("name") or "",
                                          x.get("priority") or "P1",
                                          x.get("role") or x.get("visibility") or "角色"))
        if x.get("keyword"):
            L.append("\n**固定关键词串（复制到每个镜头，一字不改）**\n\n```\n%s\n```" % x["keyword"])
        main = p.get("main") or p.get("turnaround") or ""
        if main:
            L.append("\n**出图提示词**\n\n```\n%s\n```" % main)
            
    L.append("## 四、场景出图提示词\n")
    for x in scenes:
        p = x.get("prompts") or {}
        L.append("### %s %s（%s · %s%s）" % (
            x.get("code") or "", x.get("name") or "", x.get("priority") or "P1",
            x.get("intExt") or "未注明", (" · " + x["time"]) if x.get("time") else ""))
        main = p.get("main") or p.get("concept") or ""
        if main:
            L.append("\n```\n%s\n```" % main)
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
    L.append("- **负面词**：%s" % (st.get("negative") or NEGATIVE_DEFAULT))
    asp = st.get("aspect") or {}
    L.append("- **画幅**：三视图 %s ／ 面部四视图 %s ／ 立绘 %s ／ 概念图 %s ／ 核心宽幕 %s" % (
        asp.get("turnaround", "1:1"), asp.get("faceSheet", "3:2"),
        asp.get("portrait", "3:4"),
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
    """给批量出图脚本消费：一条提示词一个对象，字段不含中文说明。

    【一资产一条】每个资产只出一条 main 提示词；兼容旧包里的
    turnaround / faceSheet / concept（只取其中一条，不重复输出）。
    """
    pack = pack if isinstance(pack, dict) else {}
    a = pack.get("assets") if isinstance(pack.get("assets"), dict) else {}
    st = pack.get("style") if isinstance(pack.get("style"), dict) else {}
    out = []

    def first_prompt(x, keys):
        p = x.get("prompts") or {}
        for k in keys:
            if p.get(k):
                return p[k]
        return ""

    for x in (a.get("characters") or []):
        main = first_prompt(x, ("main", "turnaround", "faceSheet"))
        if main:
            out.append({
                "code": x.get("code"), "name": x.get("name"), "kind": "main",
                "aspect": "3:4",
                "prompt": main,
                "keyword": x.get("keyword") or "",
                "refName": x.get("refName") or "",
            })
    for x in (a.get("scenes") or []):
        main = first_prompt(x, ("main", "concept"))
        if main:
            out.append({
                "code": x.get("code"), "name": x.get("name"), "kind": "main",
                "aspect": "16:9", "prompt": main,
                "keyword": x.get("keyword") or "",
                "refName": x.get("refName") or "",
            })
    return {
        "style": {"anchor": st.get("anchor") or STYLE_ANCHOR_DEFAULT,
                  "negative": st.get("negative") or NEGATIVE_DEFAULT},
        "order": st.get("generationOrder") or [],
        "title": (meta or {}).get("title") or "",
        "prompts": out,
    }
