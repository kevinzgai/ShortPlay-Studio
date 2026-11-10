"""HTTP 响应原语：JSON / 字节流 / 读请求体 / 统一错误。

这些函数都接收 handler（self），因为要写 wfile、发响应头。
抽出来是为了让路由层不依赖具体的 Handler 类，Step C 换 FastAPI 时只需换这一层。
"""

import json
import urllib.error
import urllib.parse


def json_response(h, obj, code=200):
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    h.send_response(code)
    h.send_header("Content-Type", "application/json; charset=utf-8")
    h.send_header("Content-Length", str(len(body)))
    h.send_header("Cache-Control", "no-store")
    h.end_headers()
    h.wfile.write(body)


def bytes_response(h, data, filename, ctype="application/octet-stream", inline=False):
    h.send_response(200)
    h.send_header("Content-Type", ctype)
    h.send_header("Content-Length", str(len(data)))
    if inline:
        # 内容寻址（文件名 = 图片哈希），所以可以放心长缓存
        h.send_header("Content-Disposition", "inline; filename*=UTF-8''"
                      + urllib.parse.quote(filename))
        h.send_header("Cache-Control", "public, max-age=31536000, immutable")
    else:
        h.send_header("Content-Disposition",
                      'attachment; filename="export.zip"; '
                      "filename*=UTF-8''" + urllib.parse.quote(filename))
        h.send_header("Cache-Control", "no-store")
    h.end_headers()
    h.wfile.write(data)


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
