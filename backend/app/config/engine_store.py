"""出图引擎配置：engine-config.json 的读写、环境变量兜底与脱敏。

comfyHost / comfyModel 支持 SHORTPLAY_COMFY* 环境变量覆盖，方便换机器不改文件。
"""

import json
import os
import threading
import urllib.request

from app.paths import ROOT


ENGINE_FILE = ROOT / "engine-config.json"


ENGINE_LOCK = threading.Lock()


_ENGINE_CACHE = {"mtime": None, "doc": None}


ENGINE_DEFAULTS = {
    "gwUrl": "http://127.0.0.1:8000",
    "comfyHost": "http://127.0.0.1:8188",
    "comfyModel": "",  # 模型由网关管理，此字段已废弃（兼容保留）
    "qwenUrl": ("https://cn-beijing.maas.qianwenaiapi.com/api/v1/"
                "services/aigc/multimodal-generation/generation"),
    "qwenModel": "wan2.7-image-pro",
    "qwenSize": "2K",
    "h3Url": "https://api.minimax.cn/v1/images/generations",
    "h3Model": "MiniMax-H3-Image",
    "h3Size": "2720x1536",
}


ENGINE_ENV = {
    "gwUrl": "SHORTPLAY_GW_URL",
    "comfyHost": "SHORTPLAY_COMFY",
    "comfyModel": "SHORTPLAY_COMFY_MODEL",
    "qwenUrl": "SHORTPLAY_QWEN_IMAGE_URL",
    "qwenModel": "SHORTPLAY_QWEN_IMAGE_MODEL",
    "qwenSize": "SHORTPLAY_QWEN_IMAGE_SIZE",
    "qwenKey": "SHORTPLAY_DASHSCOPE_API_KEY",
    "h3Url": "SHORTPLAY_MINIMAX_IMAGE_URL",
    "h3Model": "SHORTPLAY_MINIMAX_IMAGE_MODEL",
    "h3Size": "SHORTPLAY_MINIMAX_IMAGE_SIZE",
    "h3Key": "SHORTPLAY_MINIMAX_API_KEY",
}


def _engine_doc():
    """只收已知键、统一裁剪；坏文件按空配置处理，不让它把服务带崩。"""
    try:
        mtime = ENGINE_FILE.stat().st_mtime_ns
    except OSError:
        mtime = -1
    if mtime == _ENGINE_CACHE["mtime"] and _ENGINE_CACHE["doc"] is not None:
        return _ENGINE_CACHE["doc"]
    try:
        raw = json.loads(ENGINE_FILE.read_text(encoding="utf-8")) if mtime >= 0 else {}
    except (OSError, ValueError):
        raw = {}
    raw = raw if isinstance(raw, dict) else {}
    doc = {}
    for k, limit in (("gwUrl", 300), ("comfyHost", 300), ("comfyModel", 160), ("qwenUrl", 300),
                     ("qwenModel", 120), ("qwenSize", 20), ("qwenKey", 200),
                     ("h3Url", 300), ("h3Model", 120), ("h3Size", 24), ("h3Key", 200)):
        doc[k] = str(raw.get(k) or "").strip()[:limit]
    _ENGINE_CACHE["mtime"], _ENGINE_CACHE["doc"] = mtime, doc
    return doc


def _engine_doc_write(doc):
    tmp = ENGINE_FILE.with_name(ENGINE_FILE.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, ENGINE_FILE)
    _ENGINE_CACHE["mtime"], _ENGINE_CACHE["doc"] = None, None


def _engine_get(key):
    """文件优先 → 环境变量 → 内置默认；顺带把来源告诉界面，省得猜。"""
    v = _engine_doc().get(key) or ""
    if v:
        return v, "file"
    env = (os.environ.get(ENGINE_ENV.get(key, "")) or "").strip()
    if env:
        return env, "env"
    return ENGINE_DEFAULTS.get(key, ""), "default"


def gw_url():
    """H3 + SeedVR2 本地网关地址：出图 / 视频 / 修复都从这走。"""
    return _engine_get("gwUrl")[0].rstrip("/")


def comfy_host():
    return _engine_get("comfyHost")[0].rstrip("/")


def comfy_model():
    return _engine_get("comfyModel")[0]


def qwen_image_url():
    return _engine_get("qwenUrl")[0]


def qwen_image_model():
    return _engine_get("qwenModel")[0]


def qwen_image_size():
    return _engine_get("qwenSize")[0]


def h3_image_url():
    return _engine_get("h3Url")[0]


def h3_image_model():
    return _engine_get("h3Model")[0]


def h3_image_size():
    return _engine_get("h3Size")[0]


def h3_image_key():
    """文件优先 → 环境变量：界面上填的 Key 立即生效，不改 bat、不用重启。"""
    return _engine_get("h3Key")[0]


def engine_config_public():
    """给前端看：只回打码后的 Key 与每项来源，绝不回传明文。"""
    out = {}
    for k in ("gwUrl", "comfyHost", "comfyModel", "qwenUrl", "qwenModel", "qwenSize",
              "h3Url", "h3Model", "h3Size"):
        v, src = _engine_get(k)
        out[k] = {"value": v, "source": src}
    key, key_src = _engine_get("qwenKey")
    out["qwenKey"] = {"mask": _mask_key(key), "source": key_src, "set": bool(key)}
    h3key, h3key_src = _engine_get("h3Key")
    out["h3Key"] = {"mask": _mask_key(h3key), "source": h3key_src, "set": bool(h3key)}
    return out


def _mask_key(k):
    k = str(k or "")
    if not k:
        return ""
    return "***" if len(k) <= 8 else (k[:4] + "***" + k[-4:])


def qwen_image_key():
    """文件优先 → 环境变量：界面上填的 Key 立即生效，不改 bat、不用重启。"""
    return _engine_get("qwenKey")[0]


def qwen_image_status():
    """给前端的探测结果：只有「有没有配 Key」，绝不回传 Key 本身。"""
    key = qwen_image_key()
    return {
        "online": bool(key),
        "model": qwen_image_model(),
        "size": qwen_image_size(),
        "host": qwen_image_url().split("/api/")[0],
        "detail": "" if key else "没配置通义万相 API Key：到「系统设置 · 出图引擎」填一条即可",
    }


def gw_status():
    """本地网关探测：online / 显存 / 队列，前端引擎页与状态灯共用。"""
    try:
        req = urllib.request.Request(gw_url() + "/health")
        with urllib.request.urlopen(req, timeout=4) as r:
            st = json.load(r)
    except Exception as exc:
        return {"online": False, "host": gw_url(),
                "detail": "网关没启动或不可达（%s）" % str(exc)[:80]}
    comfy = st.get("comfyui") or {}
    online = bool(st.get("gateway")) and comfy.get("reachable", False)
    return {"online": online, "host": gw_url(),
            "device": comfy.get("device", ""),
            "vramFreeMB": int(comfy.get("vram_free_mb") or 0),
            "queue": int(st.get("queue") or 0),
            "current": st.get("current") or "",
            "detail": "" if online else "网关在，但 ComfyUI 不可达"}


def h3_image_status():
    """MiniMax H3-Image 探测结果，口径与 qwen_image_status 一致。"""
    key = h3_image_key()
    return {
        "online": bool(key),
        "model": h3_image_model(),
        "size": h3_image_size(),
        "host": h3_image_url().split("/v1/")[0],
        "detail": "" if key else "没配置 MiniMax API Key：到「系统设置 · 出图引擎」填一条即可",
    }


def comfy_unet_names():
    """兼容保留：模型由网关管理，恒返回空列表。"""
    try:
        with urllib.request.urlopen(comfy_host() + "/object_info/UNETLoader", timeout=6) as r:
            info = json.loads(r.read().decode("utf-8"))
        inp = (((info or {}).get("UNETLoader") or {}).get("input") or {})
        # 实测结构是 {"required": {"unet_name": [["a.safetensors", ...]]}}：
        # 列表首元素才是候选；也兼容 {"unet_name": {"options": [...]}} 的老写法
        spec = (inp.get("required") or {}).get("unet_name") or \
               (inp.get("optional") or {}).get("unet_name")
        names = []
        if isinstance(spec, list) and spec:
            head = spec[0]
            names = head if isinstance(head, list) else (head.get("options") if isinstance(head, dict) else [])
        elif isinstance(spec, dict):
            names = spec.get("options") or []
        return [str(x)[:160] for x in (names or []) if str(x).strip()][:60]
    except Exception:
        return []


def engine_config_save(payload):
    """保存引擎配置：只写本机文件，mtime 缓存失效即生效，不用重启。"""
    if not isinstance(payload, dict):
        raise ValueError("参数格式不对")
    with ENGINE_LOCK:
        doc = dict(_engine_doc())
        for k, limit in (("gwUrl", 300), ("comfyHost", 300), ("comfyModel", 160), ("qwenUrl", 300),
                         ("qwenModel", 120), ("qwenSize", 20),
                         ("h3Url", 300), ("h3Model", 120), ("h3Size", 24)):
            if k in payload:
                doc[k] = str(payload.get(k) or "").strip()[:limit]
        # Key 留空 = 不改已存的（与 llm-providers 的编辑约定一致）
        if payload.get("clearQwenKey"):
            doc["qwenKey"] = ""
        elif str(payload.get("qwenKey") or "").strip():
            doc["qwenKey"] = str(payload.get("qwenKey")).strip()[:200]
        if payload.get("clearH3Key"):
            doc["h3Key"] = ""
        elif str(payload.get("h3Key") or "").strip():
            doc["h3Key"] = str(payload.get("h3Key")).strip()[:200]
        _engine_doc_write(doc)
    return engine_config_public()
