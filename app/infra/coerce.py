"""取值与类型归一：截断、过滤、优先级。纯函数，无 IO、无全局状态。"""

import re


def _as(v, default="", limit=200):
    t = str(v if v is not None else "").strip()
    # 模型偶尔把 prompt 里的字数说明抄进字段值，如「暖黄偏灰，20字内」
    t = re.sub(r"[，,、；;]\s*\d+\s*[字词]内\s*$", "", t).strip("，,、；; ")
    return (t[:limit] or default)


def _alist(v, limit=12, item_limit=80):
    if not isinstance(v, list):
        return []
    return [_as(x, "", item_limit) for x in v if _as(x, "", item_limit)][:limit]


def _ints(v, limit=40):
    if not isinstance(v, list):
        return []
    out = []
    for x in v:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            pass
    return out[:limit]


def _priority(v):
    p = _as(v, "P1", 4).upper()
    return p if p in ("P0", "P1") else "P1"


def num(v, default, lo, hi):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, round(f * 2) / 2))


def s(v, limit=600):
    return re.sub(r"\s+", " ", str(v if v is not None else "")).strip()[:limit]
