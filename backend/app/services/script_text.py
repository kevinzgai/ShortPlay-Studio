"""剧本文本层：docx 取文、分句、忠实转写、场次解析、体检。

输入输出都是纯文本 / dict，不碰网络、不碰磁盘（docx 也是内存里解 zip）。
"""

import io
import re
import zipfile
import xml.etree.ElementTree as ET

from app.infra.coerce import _as, s


DOCX_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


QUOTE_RE = re.compile(r"[“\"「]([^”\"」]{2,})[”\"」]")


INNER_RE = re.compile(r"^我(?:怀疑|知道|觉得|想|心想|暗想|明白|意识到|纳闷|才)")


_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


_PLACEHOLDER = {"未注明", "未指定", "未标注", "未确定", "未写明", "未提及",
                "未填写", "未知", "待定", "不详"}


_INT_EXT_MAP = {"内景": "内景", "内": "内景", "INT": "内景", "INT.": "内景",
                "外景": "外景", "外": "外景", "EXT": "外景", "EXT.": "外景"}


_TIME_WORDS = ("清晨", "早晨", "上午", "中午", "午后", "下午", "黄昏", "傍晚",
               "白天", "日", "夜", "深夜", "凌晨", "晚上", "稍后", "连续", "次日", "雨后")


_SCENE_HEAD_RE = re.compile(r"^\s*第\s*([0-9０-９一二三四五六七八九十百零两]{1,6})\s*场\s*(.*)$")


_SCENE_DLG_RE = re.compile(r"^([^：:△▲\s《【][^：:]{0,11}?)(?:[（(]([^）)]{0,20})[）)])?\s*[：:]\s*(.+)$")


_SCENE_ACT_RE = re.compile(r"^[△▲]\s*(.+)$")


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
