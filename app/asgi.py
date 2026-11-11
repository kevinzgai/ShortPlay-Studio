"""FastAPI 应用（Step C）：把 app/web 的路由表挂到 ASGI 上。

【本层的唯一职责：协议翻译】
路由函数、业务函数**一行没改**——它们仍然是 fn(h, payload) / fn(h) 形态，
通过 app/web/responses.py 的 Sink 收集 Response，本层再翻译成 Starlette 响应。
这是 2026-11-11 响应层解耦（commit b517fd8）换来的收益。

【与旧 stdlib 实现的等价性清单】
  · 路由白名单：未知 POST 路径 404「不支持的接口」（旧 do_POST 的 known_post_paths）
  · 读 body 失败 → 400「请求格式不对：...」
  · 响应头逐字一致（Cache-Control / Content-Disposition / 文件名编码）
  · POST /api/parse/start 等接口的状态码与响应体完全由路由层决定
  · 静态文件：等价于 SimpleHTTPRequestHandler(directory=WEB_ROOT)，含 index.html

【最容易翻车的一处：SSE 不能阻塞事件循环】
旧实现是同步阻塞轮询（parse_task_wait 内部 PARSE_COND.wait）。
若直接放进 async 生成器，整个事件循环会被卡住 → 所有请求一起卡死，
症状是「能用，但偶发全站卡住」，普通断言抓不到。
这里用 anyio.to_thread.run_sync 把阻塞等待丢进线程池，事件循环始终空闲。
配套断言：tools/verify_sse_nonblocking.py（SSE 挂起期间 /api/config 必须 < 500ms）。

【并发 backlog】
旧 StudioServer.request_queue_size = 128 是硬性要求（实测 backlog=5 时 20 路并发
12 路被 RST）。uvicorn 的 backlog 通过 run(backlog=128) 传入，见 app/uvicorn_runner.py。
"""

import json
import mimetypes
import os
from urllib.parse import unquote

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response as StarletteResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.paths import WEB_ROOT
from app.web.agent_routes import (AGENT_GET_PATHS, AGENT_POST_PATHS, agent_get,
                                  agent_post)
from app.web.responses import Response, Sink, read_body
from app.web.routes_get import GET_ROUTES
from app.web.routes_post import UNMATCHED
from app.web.routes_post import dispatch as post_dispatch
from app.web.routes_post import known_paths as known_post_paths

app = FastAPI(
    title="分镜工场 ShortPlay Studio",
    description="本机服务 · 剧本 / 分集 / 分镜 / 资产 / 出片",
    version="1.0.0",
    docs_url="/docs",
    redoc_url=None,
)


# --------------------------------------------------------------------------
# 协议翻译：Response(Sink 收集的纯数据) → Starlette 响应
# --------------------------------------------------------------------------
def to_starlette(resp: Response):
    """把 responses.Response 翻成 Starlette 响应，头部逐字搬运。"""
    if resp is None:  # 路由函数没返回（理论上不该发生）
        return JSONResponse({"detail": "服务内部没有产生响应"}, status_code=500)
    return StarletteResponse(
        content=resp.body,
        status_code=resp.status,
        headers=dict(resp.headers),
        media_type=None,  # Content-Type 已在 headers 里，避免 Starlette 覆盖成默认值
    )


def _sink_for(request: Request, body: bytes = b"") -> Sink:
    """用请求信息造 Sink：method / path(含 query) / headers / body。"""
    headers = {k: v for k, v in request.headers.items()}
    # 保留原始大小写不敏感访问习惯：Sink.headers 是普通 dict，读的时候用 get
    return Sink(method=request.method, path=request.url.path
                + (("?" + request.url.query) if request.url.query else ""),
                headers=headers, body=body)


async def _read_json_body(request: Request):
    """读 JSON body，抛的异常与旧 read_body 一致（ValueError 系）。"""
    raw = await request.body()
    length = int(request.headers.get("content-length", len(raw)) or len(raw))
    return json.loads(raw[:length].decode("utf-8"))


# --------------------------------------------------------------------------
# GET
# --------------------------------------------------------------------------
@app.get("/api/parse/events")
async def parse_events(request: Request):
    """SSE：阻塞等待丢线程池，事件循环不阻塞（见模块 docstring 的风险说明）。"""
    import anyio

    from app.services.parse_task import PARSE_TASKS, parse_task_wait
    from app.web.responses import query_dict

    q = query_dict(_sink_for(request))
    tid = q.get("id", "")
    task = PARSE_TASKS.get(tid)
    if not task:
        return JSONResponse({"detail": "任务不存在或已过期"}, status_code=404)
    try:
        since0 = int(q.get("since") or request.headers.get("last-event-id") or 0)
    except (TypeError, ValueError):
        since0 = 0

    async def gen():
        import time

        since = since0
        last_ping = time.time()
        while True:
            # 关键：把 PARSE_COND.wait 的阻塞丢进线程池，事件循环保持空闲
            events, over = await anyio.to_thread.run_sync(
                lambda: parse_task_wait(task, since, 2.0))
            for ev in events:
                since = ev["seq"]
                yield ("id: %d\ndata: %s\n\n" % (
                    ev["seq"], json.dumps(ev, ensure_ascii=False))).encode("utf-8")
            if events:
                last_ping = time.time()
            elif time.time() - last_ping >= 8:
                yield b": ping\n\n"      # 心跳，防止中间层掐掉空闲连接
                last_ping = time.time()
            if over and not events:
                yield b": end\n\n"
                break

    return StreamingResponse(gen(), media_type="text/event-stream; charset=utf-8", headers={
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
    })


@app.get("/api/{tail:path}")
async def api_get(tail: str, request: Request):
    path = "/api/" + tail
    fn = GET_ROUTES.get(path)
    if fn is not None:
        sink = _sink_for(request)
        return to_starlette(fn(sink))
    if path in AGENT_GET_PATHS:
        sink = _sink_for(request)
        return to_starlette(agent_get(sink, path))
    return JSONResponse({"detail": "不支持的接口"}, status_code=404)


# --------------------------------------------------------------------------
# POST
# --------------------------------------------------------------------------
@app.post("/api/{tail:path}")
async def api_post(tail: str, request: Request):
    path = "/api/" + tail
    # 白名单校验（与旧 do_POST 的顺序一致：先判白名单，再读 body）
    if path not in known_post_paths() and path not in AGENT_POST_PATHS:
        return JSONResponse({"detail": "不支持的接口"}, status_code=404)
    try:
        payload = await _read_json_body(request)
    except (ValueError, KeyError, UnicodeDecodeError) as exc:
        return JSONResponse({"detail": "请求格式不对：" + str(exc)}, status_code=400)

    raw = json.dumps(payload).encode("utf-8")
    sink = _sink_for(request, raw)
    if path in AGENT_POST_PATHS:
        return to_starlette(agent_post(sink, path, payload))
    out = post_dispatch(sink, path, payload)
    if out is UNMATCHED:
        return JSONResponse({"detail": "不支持的接口"}, status_code=404)
    return to_starlette(out)


# --------------------------------------------------------------------------
# 静态资源（必须最后注册，否则 /api 会被 path 通配吃掉）
# --------------------------------------------------------------------------
class _NoCacheStatic(StaticFiles):
    """静态托管：等价旧 SimpleHTTPRequestHandler(directory=WEB_ROOT)。

    只额外做一件事：给 index.html 加 no-store，避免改了前端还看到旧页面
    （旧实现靠浏览器默认缓存，行为略有差异，这里显式对齐「刷新即最新」）。
    """

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        if path in ("", ".", "index.html"):
            resp.headers["Cache-Control"] = "no-store"
        return resp


def mount_static():
    """挂静态目录。WEB_ROOT 不存在时跳过（纯 API 模式仍可用）。"""
    if WEB_ROOT and (WEB_ROOT / "index.html").exists():
        app.mount("/", _NoCacheStatic(directory=str(WEB_ROOT), html=True), name="web")


# 兜底：Starlette 默认 404 是 {"detail":"Not Found"}，
# 旧实现返回 {"detail": "不支持的接口"}；这里保持中文口径统一。
@app.exception_handler(StarletteHTTPException)
async def _http_exc_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404 and not request.url.path.startswith("/api/"):
        # 静态资源找不到：交回 Starlette 默认行为更合适（浏览器直接看到 404）
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    if exc.status_code == 404:
        return JSONResponse({"detail": "不支持的接口"}, status_code=404)
    return JSONResponse({"detail": str(exc.detail)}, status_code=exc.status_code)


mount_static()
