"""H3 + SeedVR2 本地网关（默认 127.0.0.1:8000）的 HTTP 客户端。

studio 不再直连 ComfyUI：出图、视频全部交给网关。理由：
1. 网关有单线程队列——24G 显存装不下 H3(20G)+SeedVR2(8.2G) 两套模型，
   两处同时提交任务必然互相挤爆显存；studio 直连等于绕过排队。
2. 工作流模板只维护网关一份（84 节点裁剪成 14 节点），studio 不再抄写副本。
3. 白得视频（t2v/i2v/fl2v）与 SeedVR2 修复能力。

接口口径以网关 /docs（Swagger）为准，文档要点：
- 纯文生图   POST /v1/images/generations（width/height 是 16 的倍数）
- 带参考图   POST /v1/images/edits（唯一入口；JSON images:[{image_url}] 支持 data: URI；
             尺寸用 size=宽x高 / aspect_ratio+area，不收 width/height；
             denoise 不传=官方 ref 语义，0.5~0.65 保人物，0.8~0.9 才能出画面内文字）
- 视频       POST /v1/videos（t2v/i2v/fl2v；宽高 32 的倍数，duration 5s/8s/10s）
- 任务       GET /v1/jobs/{id}（status/progress/stage），产物 GET /v1/jobs/{id}/files/{name}
- 出图文件   GET /v1/images/file/{name}（免 key，可直接嵌 img）
"""

import base64
import http.client
import json
import time
import urllib.parse
import urllib.request
import uuid

from app.config.engine_store import gw_url


# 网关一定在本机（127.0.0.1:8000），必须绕过代理——macOS 上 urllib 读系统代理
# 且优先级高于 NO_PROXY，Clash/Surge 之类会把回环请求转去代理端口（实测 502）。
LOCAL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class GatewayError(RuntimeError):
    """网关返回 4xx/5xx 或结构不符合预期时抛出，message 直接给界面。"""


def _get(path, timeout=10):
    req = urllib.request.Request(gw_url() + path)
    with LOCAL_OPENER.open(req, timeout=timeout) as r:
        return json.load(r)


def _post_json(path, body, timeout=30):
    req = urllib.request.Request(
        gw_url() + path, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    try:
        with LOCAL_OPENER.open(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = (exc.read() or b"").decode("utf-8", "replace")[:300]
        except Exception:
            pass
        raise GatewayError("网关 %s（HTTP %d）%s" % (path, exc.code, detail)) from exc
    except OSError as exc:
        raise GatewayError("网关不可达（%s）：本地网关没启动？执行 start_all.ps1" % exc) from exc


def gw_health(timeout=4):
    """GET /health：网关 / ComfyUI / 显存。模型加载中返回 busy，不会卡住。"""
    return _get("/health", timeout=timeout)


def image_to_data_uri(png_bytes, mime="image/png"):
    return "data:%s;base64,%s" % (mime, base64.b64encode(png_bytes).decode("ascii"))


def gw_t2i(prompt, width=1024, height=1024, steps=0, seed=None,
           timeout=600, wait=True):
    """POST /v1/images/generations → 同步（wait=true）返回
    {prompt_id, seed, status, elapsed, filename, url}。"""
    body = {"prompt": prompt, "width": int(width), "height": int(height),
            "timeout": int(timeout), "wait": bool(wait)}
    if steps:
        body["steps"] = int(steps)
    if seed is not None:
        body["seed"] = int(seed)
    out = _post_json("/v1/images/generations", body, timeout=timeout + 15)
    if wait and out.get("status") not in (None, "succeeded"):
        raise GatewayError("文生图失败：%s" % json.dumps(out, ensure_ascii=False)[:200])
    return out


def gw_i2i(prompt, image_uris, size=None, area=None, aspect_ratio=None,
           denoise=None, seed=None, n=1, steps=0, timeout=600, wait=True):
    """POST /v1/images/edits：带 1~16 张参考图的唯一出图入口。

    image_uris 是 data: URI 列表（studio 的参考图都在本地，走 base64 最省事）。
    尺寸三选一：size（宽x高）> aspect_ratio（size=auto 时）> area（1K/2K/4K）。
    denoise 不传 = 官方 ref 语义（保参考图构图，人物像「另一个人」）；
    传 0.5~0.65 = img2img 重绘（几乎同一张脸，画面内文字会崩）。
    """
    if not image_uris:
        raise GatewayError("edits 至少要 1 张参考图；纯文生图请走 generations")
    body = {"prompt": prompt, "model": "MiniMax-H3-Image",
            "images": [{"image_url": u} for u in image_uris],
            "n": max(1, min(int(n), 10)), "timeout": int(timeout), "wait": bool(wait)}
    if size:
        body["size"] = str(size)
    elif area:
        body["area"] = str(area)
    elif aspect_ratio:
        body["aspect_ratio"] = str(aspect_ratio)
    if denoise is not None:
        body["denoise"] = float(denoise)
    if steps:
        body["steps"] = int(steps)
    if seed is not None:
        body["seed"] = int(seed)
    out = _post_json("/v1/images/edits", body, timeout=timeout + 15)
    if wait:
        data = out.get("data") or []
        if not data:
            raise GatewayError("图生图没有返回结果：%s" % json.dumps(out, ensure_ascii=False)[:200])
    return out


def gw_image_bytes(name, timeout=90):
    """按网关返回的 filename 取 PNG 原图（带一次短读重试，与旧直连同款兜底）。"""
    url = gw_url() + "/v1/images/file/" + urllib.parse.quote(str(name))
    retryable = (http.client.HTTPException, ConnectionResetError, TimeoutError)
    last = None
    for i in range(2):
        try:
            with LOCAL_OPENER.open(url, timeout=timeout) as r:
                body = r.read()
                want = r.headers.get("Content-Length", "")
                if want.isdigit() and len(body) != int(want):
                    raise http.client.IncompleteRead(body, int(want) - len(body))
                return body
        except retryable as exc:
            last = exc
            if i + 1 < 2:
                time.sleep(0.4)
    raise last if last is not None else RuntimeError("网关图片下载失败")


def gw_video_start(mode, prompt, image_bytes=None, image_name="frame.png",
                   quality="standard", duration="5s", seed=None, timeout=120):
    """POST /v1/videos：t2v / i2v（image 必填）/ fl2v（首尾帧，本地暂未接）。

    网关这个接口收 multipart/form-data（openapi 实测），image 是二进制文件上传，
    不是 data URI 字符串——发 JSON 会被 FastAPI 拒掉（连接直接被中止）。
    返回网关任务对象（含任务 id）；视频几分钟起步，studio 侧拿 id 轮询 /v1/jobs/{id}。
    """
    fields = {"mode": mode, "prompt": prompt, "quality": quality,
              "duration": duration}
    if seed is not None:
        fields["seed"] = str(int(seed))
    boundary = "----gwbnd" + uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                      % (boundary, k, v)).encode("utf-8"))
    if image_bytes:
        parts.append(("--%s\r\nContent-Disposition: form-data; name=\"image\"; "
                      "filename=\"%s\"\r\nContent-Type: image/png\r\n\r\n"
                      % (boundary, image_name)).encode("utf-8"))
        parts.append(image_bytes)
        parts.append(b"\r\n")
    parts.append(("--%s--\r\n" % boundary).encode("utf-8"))
    body = b"".join(parts)
    req = urllib.request.Request(
        gw_url() + "/v1/videos", data=body,
        headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
    try:
        with LOCAL_OPENER.open(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = (exc.read() or b"").decode("utf-8", "replace")[:300]
        except Exception:
            pass
        raise GatewayError("网关 /v1/videos（HTTP %d）%s" % (exc.code, detail)) from exc
    except OSError as exc:
        raise GatewayError("网关不可达（%s）：本地网关没启动？执行 start_all.ps1" % exc) from exc


def gw_job(job_id, timeout=15):
    return _get("/v1/jobs/" + urllib.parse.quote(str(job_id)), timeout=timeout)


def gw_job_file_bytes(job_id, name, timeout=180):
    """下载视频产物（网关自己的副本目录）。"""
    url = "%s/v1/jobs/%s/files/%s" % (gw_url(), urllib.parse.quote(str(job_id)),
                                      urllib.parse.quote(str(name)))
    with LOCAL_OPENER.open(url, timeout=timeout) as r:
        return r.read()


def gw_job_id(info):
    """网关各版本返回字段不稳（job_id / id / prompt_id），统一在这里取。"""
    for k in ("job_id", "id", "prompt_id"):
        v = (info or {}).get(k)
        if v:
            return str(v)
    raise GatewayError("网关没有返回任务 id：%s" % json.dumps(info, ensure_ascii=False)[:200])
