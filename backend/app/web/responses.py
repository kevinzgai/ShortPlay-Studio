"""HTTP 响应原语：JSON / 字节流 / 读请求体 / 统一错误。

【2026-11-11 改造 · 为换 FastAPI 铺路】
原来这些函数直接写 h.wfile，路由层因此绑死在 SimpleHTTPRequestHandler 上，
换框架必须改 36 个处理函数 + 88 处响应调用。现在改成「构造 Response 对象，
再按目标类型投递」：

  · h 是真实 Handler（有 wfile）→ 照旧写 socket（行为与改造前**逐字一致**）
  · h 是 Sink（见下方）       → 只收集 Response，不碰 socket

收益：
  1. 路由函数一行不改，返回值从 None 变成 Response（更好测，也能顺手消掉
     routes_post.UNMATCHED 注释里「处理函数都返回 None」那个坑）；
  2. 可以脱离 socket 直接测路由：Sink(method, path, body) 传进去即可，
     断言 resp.status / resp.json()；
  3. 换 FastAPI 时只需把 Response 翻译成 JSONResponse / StreamingResponse，
     路由层零改动。

【为什么不直接把 h 换成 request 对象】
那样 88 处调用点都要改，且 SSE 长连接、静态文件托管不属于「纯请求-响应」，
一次性重写风险远大于收益。分两步走：先让响应可脱离 socket，再换框架。
"""

import io
import json
import urllib.error
import urllib.parse


class Response:
    """纯数据响应：状态码 + 头 + body，不持有任何 socket 引用。"""

    __slots__ = ("body", "status", "headers")

    def __init__(self, body=b"", status=200, headers=None):
        self.body = body
        self.status = status
        # dict 保序，写入顺序与改造前 send_header 的调用顺序一致
        self.headers = dict(headers or {})

    def header(self, name, default=None):
        return self.headers.get(name, default)

    def json(self):
        """把 body 当 JSON 解析（测试用）。"""
        return json.loads(self.body.decode("utf-8"))

    def text(self):
        return self.body.decode("utf-8", "replace")

    def __repr__(self):
        return "<Response %s %dB>" % (self.status, len(self.body))


class Sink:
    """假 handler：冒充 SimpleHTTPRequestHandler 给路由函数用，只收响应不写网络。

    只实现路由层真正用到的那几个属性：method / path / headers / rfile。
    **没有 wfile**——路由函数若绕过 responses.py 直接写 socket，这里会立刻
    AttributeError 暴露出来，而不是悄悄成功。
    """

    def __init__(self, method="GET", path="/", headers=None, body=b""):
        self.method = method
        self.path = path
        self._body = body if isinstance(body, bytes) else str(body).encode("utf-8")
        self.headers = dict(headers or {})
        # body 非空且调用方没显式给 Content-Length 时自动补上，
        # 否则 read_body 读 0 字节 → json.loads("") 报警，测试写起来很别扭。
        if self._body and "Content-Length" not in self.headers:
            self.headers["Content-Length"] = str(len(self._body))
        self.response = None

    @property
    def rfile(self):
        return io.BytesIO(self._body)

    @property
    def wfile(self):
        raise AttributeError(
            "Sink 不支持直接写 wfile：路由函数必须通过 app/web/responses.py 的"
            "原语返回响应，否则换 FastAPI 时这一处会失效")

    def __repr__(self):
        return "<Sink %s %s>" % (self.method, self.path)


def _emit(h, resp):
    """按 h 的类型投递响应：Sink 收集，真实 Handler 写 socket。"""
    if isinstance(h, Sink):
        h.response = resp
        return resp
    h.send_response(resp.status)
    for k, v in resp.headers.items():
        h.send_header(k, v)
    h.end_headers()
    h.wfile.write(resp.body)
    return resp


def json_response(h, obj, code=200):
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    return _emit(h, Response(body, code, {
        "Content-Type": "application/json; charset=utf-8",
        "Content-Length": str(len(body)),
        "Cache-Control": "no-store",
    }))


def bytes_response(h, data, filename, ctype="application/octet-stream", inline=False):
    headers = {
        "Content-Type": ctype,
        "Content-Length": str(len(data)),
    }
    if inline:
        # 内容寻址（文件名 = 图片哈希），所以可以放心长缓存
        headers["Content-Disposition"] = ("inline; filename*=UTF-8''"
                                          + urllib.parse.quote(filename))
        headers["Cache-Control"] = "public, max-age=31536000, immutable"
    else:
        headers["Content-Disposition"] = ('attachment; filename="export.zip"; '
                                          "filename*=UTF-8''" + urllib.parse.quote(filename))
        headers["Cache-Control"] = "no-store"
    return _emit(h, Response(data, 200, headers))


def read_body(h):
    length = int(h.headers.get("Content-Length", "0"))
    return json.loads(h.rfile.read(length).decode("utf-8"))


def fail_response(h, exc):
    if isinstance(exc, RuntimeError) and str(exc) == "NO_KEY":
        return json_response(h, {
            "detail": "还没有配置大模型 Key。当前自动使用离线规则引擎，核心功能都可用；"
                      "如需 AI 分集分镜，请复制 llm-config.example.bat 为 llm-config.bat 并填入 Key。"
        }, 503)
    if isinstance(exc, urllib.error.HTTPError):
        return json_response(h, {"detail": "模型服务异常"}, 502)
    return json_response(h, {"detail": str(exc)[:300]}, 502)


def query_dict(h):
    return {k: v[0] for k, v in
            urllib.parse.parse_qs(urllib.parse.urlsplit(h.path).query).items()}
