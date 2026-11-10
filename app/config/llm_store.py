"""多模型（LLM）配置：llm-providers.json 的读写、脱敏与切换。

读取优先级：文件里「当前选中且填了 Key」的那条 → 环境变量 / llm-config.bat（兼容老用户）。
Key 一律经 _mask_key 脱敏后才允许出现在接口返回里。
"""

import json
import os
import re
import threading

from app.paths import ROOT
from app.config.base import load_local_config
from app.config.engine_store import _mask_key


LLM_FILE = ROOT / "llm-providers.json"


LLM_LOCK = threading.Lock()


_LLM_CACHE = {"mtime": None, "doc": None}


def _llm_int(v, default):
    try:
        n = int(v)
    except (TypeError, ValueError):
        return default
    return max(1024, min(n, 64000))


def _llm_doc():
    try:
        mtime = LLM_FILE.stat().st_mtime_ns
    except OSError:
        mtime = -1
    if mtime == _LLM_CACHE["mtime"] and _LLM_CACHE["doc"] is not None:
        return _LLM_CACHE["doc"]
    try:
        raw = json.loads(LLM_FILE.read_text(encoding="utf-8")) if mtime >= 0 else {}
    except (OSError, ValueError):
        raw = {}
    provs, seen = [], set()
    for i, p in enumerate((raw.get("providers") or []) if isinstance(raw, dict) else []):
        if not isinstance(p, dict):
            continue
        base = str(p.get("baseUrl") or "").strip().rstrip("/")[:300]
        if not base:
            continue
        pid = str(p.get("id") or "").strip()[:60] or ("p%d" % (i + 1))
        while pid in seen:
            pid += "_"
        seen.add(pid)
        provs.append({
            "id": pid,
            "name": str(p.get("name") or "").strip()[:40] or base,
            "baseUrl": base,
            "apiKey": str(p.get("apiKey") or "").strip()[:200],
            "model": str(p.get("model") or "").strip()[:120],
            "maxTokens": _llm_int(p.get("maxTokens"), 16384),
        })
    active = str(raw.get("active") or "").strip()[:60] if isinstance(raw, dict) else ""
    doc = {"active": active, "providers": provs}
    _LLM_CACHE["mtime"], _LLM_CACHE["doc"] = mtime, doc
    return doc


def _llm_doc_write(doc):
    tmp = LLM_FILE.with_name(LLM_FILE.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, LLM_FILE)
    _LLM_CACHE["mtime"], _LLM_CACHE["doc"] = None, None


def llm_active_provider():
    """当前生效的一条：必须填了 Key，否则等于没接。"""
    doc = _llm_doc()
    for p in doc["providers"]:
        if p["id"] == doc["active"] and p["apiKey"]:
            return p
    for p in doc["providers"]:
        if p["apiKey"]:
            return p
    return None


def llm_settings():
    p = llm_active_provider()
    if p:
        return p["baseUrl"], p["apiKey"], p["model"] or "deepseek-chat"
    base = os.environ.get("SHORTPLAY_LLM_BASE_URL", "").strip().rstrip("/")
    key = os.environ.get("SHORTPLAY_LLM_API_KEY", "").strip()
    model = os.environ.get("SHORTPLAY_LLM_MODEL", "").strip() or "deepseek-flash"
    if not base and key:
        base = "https://api.openai.com/v1"
    return base, key, model


def llm_bootstrap():
    """首次启动：把 bat / 环境变量里那套配置落成一条可选中的记录，界面才有东西可编辑。"""
    if LLM_FILE.exists():
        return
    base = os.environ.get("SHORTPLAY_LLM_BASE_URL", "").strip().rstrip("/")
    key = os.environ.get("SHORTPLAY_LLM_API_KEY", "").strip()
    if not (base and key):
        return
    model = os.environ.get("SHORTPLAY_LLM_MODEL", "").strip() or "deepseek-chat"
    with LLM_LOCK:
        _llm_doc_write({"active": "env", "providers": [{
            "id": "env", "name": "本机 bat 配置 · " + model,
            "baseUrl": base, "apiKey": key, "model": model,
            "maxTokens": _llm_int(os.environ.get("SHORTPLAY_LLM_MAX_TOKENS"), 16384),
        }]})


def llm_providers_public():
    doc = _llm_doc()
    act = llm_active_provider()
    return {
        "ok": True,
        "active": act["id"] if act else "",
        "providers": [{
            "id": p["id"], "name": p["name"], "baseUrl": p["baseUrl"],
            "model": p["model"], "maxTokens": p["maxTokens"],
            "hasKey": bool(p["apiKey"]), "keyMask": _mask_key(p["apiKey"]),
        } for p in doc["providers"]],
        "env": {
            "baseUrl": os.environ.get("SHORTPLAY_LLM_BASE_URL", ""),
            "model": os.environ.get("SHORTPLAY_LLM_MODEL", ""),
            "hasKey": bool(os.environ.get("SHORTPLAY_LLM_API_KEY", "").strip()),
        },
    }


def llm_provider_save(payload):
    base = str(payload.get("baseUrl") or "").strip().rstrip("/")[:300]
    if not base.startswith(("http://", "https://")):
        raise ValueError("接口地址要以 http:// 或 https:// 开头")
    name = str(payload.get("name") or "").strip()[:40]
    model = str(payload.get("model") or "").strip()[:120]
    pid = str(payload.get("id") or "").strip()[:60]
    key_in = payload.get("apiKey")
    key = "" if key_in is None else str(key_in).strip()[:200]
    with LLM_LOCK:
        doc = _llm_doc()
        row = next((p for p in doc["providers"] if p["id"] == pid), None) if pid else None
        if row is None:
            row = {"id": "", "apiKey": ""}
            doc["providers"].append(row)
        if payload.get("clearKey"):
            row["apiKey"] = ""
        elif key:
            row["apiKey"] = key
        row["name"] = name or base
        row["baseUrl"] = base
        row["model"] = model
        row["maxTokens"] = _llm_int(payload.get("maxTokens"), 16384)
        if not row.get("id"):
            row["id"] = "p" + hashlib.sha1((base + "|" + model + "|" + name).encode("utf-8")).hexdigest()[:8]
        if payload.get("activate") or not doc.get("active"):
            doc["active"] = row["id"]
        _llm_doc_write(doc)
    return llm_providers_public()


def llm_provider_activate(payload):
    pid = str(payload.get("id") or "").strip()[:60]
    if not pid:
        raise ValueError("缺少要启用的模型 id")
    with LLM_LOCK:
        doc = _llm_doc()
        if not any(p["id"] == pid for p in doc["providers"]):
            raise ValueError("这条配置不存在，可能已被删除")
        doc["active"] = pid
        _llm_doc_write(doc)
    return llm_providers_public()


def llm_provider_delete(payload):
    pid = str(payload.get("id") or "").strip()[:60]
    if not pid:
        raise ValueError("缺少要删除的模型 id")
    with LLM_LOCK:
        doc = _llm_doc()
        doc["providers"] = [p for p in doc["providers"] if p["id"] != pid]
        if doc.get("active") == pid:
            doc["active"] = doc["providers"][0]["id"] if doc["providers"] else ""
        _llm_doc_write(doc)
    return llm_providers_public()


def llm_max_tokens():
    """输出上限。推理模型的思考 token 也算在这里面，所以默认给足 16384。"""
    p = llm_active_provider()
    if p and p.get("maxTokens"):
        return _llm_int(p["maxTokens"], 16384)
    raw = os.environ.get("SHORTPLAY_LLM_MAX_TOKENS", "").strip()
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return 16384
    return max(1024, min(val, 64000))
