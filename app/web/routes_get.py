"""GET 路由表。

从 server.py 的 Handler.do_GET 整块搬来，改成 {path: fn} 字典。
每个处理函数签名统一为 fn(h) → None（自己写响应），返回值用于表达「这个路径我处理了」。

搬移纪律：判断条件、分支顺序、响应体字段一字不改；只把 self.xxx 换成 h.xxx，
把 self._json(...) 换成 json_response(h, ...)。
"""

import json

from app.config.engine_store import engine_config_public, comfy_host, comfy_unet_names
from app.config.llm_store import (_llm_doc, llm_active_provider, llm_providers_public,
                                  llm_settings)
from app.services.comfy import (ASSET_IMG_DIR, ASSET_IMG_NAME, COMFY_JOBS,
                                COMFY_LOCK, comfy_status)
from app.services.parse_task import PARSE_TASKS, parse_task_latest, parse_task_snapshot
from app.services.projects import (PROJECTS_DIR, project_get, project_list,
                                   project_ref_read, project_ref_thumb)
from app.web.responses import bytes_response, json_response, query_dict


def _config(h):
    base, key, model = llm_settings()
    act = llm_active_provider()
    return json_response(h, {
        "llm": bool(base and key),
        "model": model if (base and key) else "",
        "mode": "llm" if (base and key) else "local",
        "provider": {"id": act["id"], "name": act["name"],
                     "baseUrl": act["baseUrl"], "model": act["model"]} if act else None,
        "providerCount": len(_llm_doc()["providers"]),
        "features": ["adapt", "parse", "assets", "frames", "exportZip",
                     "plan", "storyboard", "agents", "skills", "agentRun",
                     "assetFill", "comfy", "qwenImage", "projects", "parseTask"],
    })


def _llm_providers(h):
    return json_response(h, llm_providers_public())


def _engine_config(h):
    return json_response(h, engine_config_public())


def _comfy_models(h):
    return json_response(h, {"models": comfy_unet_names(), "host": comfy_host()})


def _comfy_status(h):
    return json_response(h, comfy_status())


def _comfy_job(h):
    jid = query_dict(h).get("id", "")
    with COMFY_LOCK:
        job = COMFY_JOBS.get(jid)
        snap = json.loads(json.dumps(job)) if job else None
    if not snap:
        return json_response(h, {"detail": "任务不存在或已过期"}, 404)
    # 轮询默认不回传 dataUri（每张几十 KB），只在 finished=1 时取回结果
    if query_dict(h).get("full") != "1":
        for it in snap.get("items", []):
            it.pop("dataUri", None)
    return json_response(h, snap)


def _comfy_image(h):
    name = query_dict(h).get("f", "")
    if not ASSET_IMG_NAME.match(name):
        return json_response(h, {"detail": "非法文件名"}, 400)
    f = ASSET_IMG_DIR / name
    if not f.is_file():
        return json_response(h, {"detail": "图片不存在"}, 404)
    return bytes_response(h, f.read_bytes(), name, "image/png")


def _parse_state(h):
    task = PARSE_TASKS.get(query_dict(h).get("id", ""))
    if not task:
        return json_response(h, {"detail": "任务不存在或已过期"}, 404)
    return json_response(h, parse_task_snapshot(task))


def _parse_latest(h):
    return json_response(h, parse_task_latest())


def _projects(h):
    return json_response(h, {"projects": project_list(), "dir": str(PROJECTS_DIR)})


def _project_ref(h):
    q = query_dict(h)
    pid, fname = q.get("id", ""), q.get("f", "")
    try:
        raw, mime = project_ref_read(pid, fname)
    except ValueError as exc:
        return json_response(h, {"detail": str(exc)}, 404)
    thumb = project_ref_thumb(pid, fname, raw, q.get("w", ""))
    if thumb:
        return bytes_response(h, thumb, fname, "image/jpeg", inline=True)
    return bytes_response(h, raw, fname, mime, inline=True)


def _project_get(h):
    try:
        return json_response(h, project_get(query_dict(h).get("id", "")))
    except ValueError as exc:
        return json_response(h, {"detail": str(exc)}, 404)


# path → 处理函数。顺序不影响语义（精确匹配），但保持与旧 if-elif 一览表相同便于对照。
GET_ROUTES = {
    "/api/config": _config,
    "/api/llm/providers": _llm_providers,
    "/api/engine/config": _engine_config,
    "/api/comfy/models": _comfy_models,
    "/api/comfy/status": _comfy_status,
    "/api/comfy/job": _comfy_job,
    "/api/comfy/image": _comfy_image,
    "/api/parse/state": _parse_state,
    "/api/parse/latest": _parse_latest,
    "/api/projects": _projects,
    "/api/projects/ref": _project_ref,
    "/api/projects/get": _project_get,
}

# 这几个路径由 Handler 的专用方法处理（SSE 要长连接、Agent 要多次分支），
# 不放进纯函数表，见 HANDLED_ELSEWHERE。
HANDLED_ELSEWHERE = (
    "/api/agents", "/api/agents/prompt", "/api/skills", "/api/skills/detail",
    "/api/parse/events",
)
