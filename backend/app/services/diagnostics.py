"""系统设置里的「连通性自检」：模型与出图引擎各真发一次最小请求。

这是唯一能证明「地址 + Key + 模型名」三件都对的办法，
所以不查缓存、不看配置值，一律实打实发请求。"""

import json
import time
import urllib.error
import urllib.request

from app.config.engine_store import (
                                     _mask_key, qwen_image_key,
                                     qwen_image_model)
from app.config.llm_store import _llm_doc, llm_bootstrap
from app.infra.coerce import s
from app.services.comfy import comfy_arch_info, comfy_status

def llm_probe(base, key, model, timeout=25):
    """真发一次最小请求：这是唯一能证明「地址 + Key + 模型名」三件都对的办法。"""
    base = str(base or "").strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        return {"ok": False, "ms": 0, "detail": "接口地址要以 http:// 或 https:// 开头"}
    if not str(model or "").strip():
        return {"ok": False, "ms": 0, "detail": "缺少模型名称"}
    body = json.dumps({
        "model": str(model).strip(), "temperature": 0, "max_tokens": 48,
        "messages": [{"role": "user", "content": "只回复两个字：通了"}],
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if str(key or "").strip():
        headers["Authorization"] = "Bearer " + str(key).strip()
    t0 = time.time()
    req = urllib.request.Request(base + "/chat/completions", data=body,
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            upstream = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200]
        hint = ""
        if exc.code in (401, 403):
            hint = "（Key 不对或没权限）"
        elif exc.code == 404:
            hint = "（地址或模型名不对，注意 /v1 要带上）"
        return {"ok": False, "ms": int((time.time() - t0) * 1000),
                "detail": "HTTP %s%s：%s" % (exc.code, hint, detail)}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "ms": int((time.time() - t0) * 1000),
                "detail": "连不上或超时：%s" % exc}
    except ValueError:
        return {"ok": False, "ms": int((time.time() - t0) * 1000),
                "detail": "返回的不是 JSON，地址可能不是 OpenAI 兼容接口"}
    ms = int((time.time() - t0) * 1000)
    try:
        choice = upstream["choices"][0]
        content = (choice["message"].get("content") or "").strip()
    except (KeyError, IndexError, TypeError):
        return {"ok": False, "ms": ms, "detail": "返回体结构异常：没有 choices[0].message.content"}
    if not content:
        thinking = (choice["message"].get("reasoning_content") or "").strip()
        return {"ok": False, "ms": ms,
                "detail": "模型只输出了思考过程、没有最终内容；把 max_tokens 调大再试" if thinking
                else "模型返回空内容，检查模型名是否这个服务真的支持"}
    return {"ok": True, "ms": ms, "reply": content[:60],
            "model": upstream.get("model") or str(model).strip()}


def llm_test(payload):
    pid = str(payload.get("id") or "").strip()[:60]
    if pid and not payload.get("baseUrl"):
        doc = _llm_doc()
        row = next((p for p in doc["providers"] if p["id"] == pid), None)
        if not row:
            raise ValueError("这条配置不存在，可能已被删除")
        base, key, model = row["baseUrl"], row["apiKey"], row["model"]
    else:
        base = payload.get("baseUrl")
        key = payload.get("apiKey")
        model = payload.get("model")
        if key is None and pid:
            doc = _llm_doc()
            row = next((p for p in doc["providers"] if p["id"] == pid), {})
            key = row.get("apiKey", "")
    return llm_probe(base, key, model)


def engine_probe(kind):
    """连通性探测。ComfyUI 真连一次；云端引擎只校验 Key 是否配好，不空跑计费请求。"""
    kind = str(kind or "comfy").strip()
    if kind == "h3":
        from app.config.engine_store import _mask_key, h3_image_key, h3_image_model
        key = h3_image_key()
        return {"ok": bool(key), "kind": "h3", "model": h3_image_model(),
                "mask": _mask_key(key),
                "detail": ("Key 已保存（%s），实际出图才会产生调用与计费" % _mask_key(key))
                          if key else "没配置 API Key"}
    if kind == "qwen":
        key = qwen_image_key()
        return {"ok": bool(key), "kind": "qwen", "model": qwen_image_model(),
                "mask": _mask_key(key),
                "detail": ("Key 已保存（%s），实际出图才会产生调用与计费" % _mask_key(key))
                          if key else "没配置 API Key"}
    st = comfy_status()
    if not st.get("online"):
        return {"ok": False, "kind": "comfy", "host": st.get("host", ""),
                "detail": st.get("detail") or "连不上本地网关"}
    info = comfy_arch_info()
    # 网关模式：模型/工作流都由网关管理，这里只确认「网关 + ComfyUI 双在线」。
    return {"ok": True, "kind": "comfy", "host": st.get("host"),
            "arch": info["arch"], "archLabel": info["label"], "steps": info["steps"],
            "vramFreeMB": st.get("vramFreeMB"), "queue": st.get("queue", 0),
            "detail": ""}
