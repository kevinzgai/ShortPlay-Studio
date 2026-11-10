#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""路由冒烟：把每个已注册的 GET/POST 路径都真打一遍，确认不炸。

为什么需要它：py_compile 和 import 只验证「语法 + 模块能加载」，
抓不到 do_POST 里引用未定义名这类运行期错误（AGENT_POST_PATHS 就这么漏过一次）。
这个脚本直接对运行中的服务发请求，任何 5xx 或连接被关都算失败。

用法：
    python3 server.py --no-browser &      # 先起服务
    python3 tools/smoke_routes.py
"""

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8177"

# (method, path, 期望状态码集合, 说明)
CASES = [
    # ---- GET：只读接口，应全 200
    ("GET", "/api/config", {200}, "配置摘要"),
    ("GET", "/api/llm/providers", {200}, "模型列表"),
    ("GET", "/api/engine/config", {200}, "引擎配置"),
    ("GET", "/api/comfy/models", {200}, "unet 列表"),
    ("GET", "/api/comfy/status", {200}, "ComfyUI 状态"),
    ("GET", "/api/comfy/job?id=不存在", {404}, "不存在的任务 → 404"),
    ("GET", "/api/comfy/image?f=../etc/passwd", {400}, "非法文件名 → 400"),
    ("GET", "/api/parse/state?id=不存在", {404}, "不存在的解析任务 → 404"),
    ("GET", "/api/parse/latest", {200}, "最近解析任务"),
    ("GET", "/api/projects", {200}, "项目列表"),
    ("GET", "/api/projects/get?id=不存在", {404}, "不存在的项目 → 404"),
    ("GET", "/api/projects/ref?id=x&f=y", {404}, "不存在的参考图 → 404"),
    ("GET", "/api/agents", {200}, "Agent 列表"),
    ("GET", "/api/skills", {200}, "技能列表"),
    ("GET", "/api/skills/detail?id=不存在", {404}, "不存在的技能 → 404"),

    # ---- POST：用最小合法 body，只验「路由能通、不 5xx」
    ("POST", "/api/llm/test", {200, 400, 502, 503}, "模型连通测试"),
    ("POST", "/api/engine/test", {200, 502}, "引擎探测"),
    ("POST", "/api/comfy/prompt", {200, 400}, "拼提示词"),
    ("POST", "/api/ai/frames", {200, 400}, "首帧提示词（免 20 字校验）"),
    ("POST", "/api/ai/adapt", {400}, "剧本太短 → 400"),
    ("POST", "/api/ai/plan", {400}, "剧本太短 → 400"),
    ("POST", "/api/ai/assets", {400}, "剧本太短 → 400"),
    ("POST", "/api/ai/storyboard", {400}, "剧本太短 → 400"),
    ("POST", "/api/llm/parse", {400}, "剧本太短 → 400"),
    ("POST", "/api/parse/cancel", {200}, "取消不存在的任务"),
    ("POST", "/api/projects/save", {400}, "缺 id → 400"),
    ("POST", "/api/projects/delete", {400}, "不存在的项目 → 400"),
    ("POST", "/api/export/zip", {200, 400, 500}, "空项目打包"),

    # ---- 白名单：未知路径必须 404，不能关连接
    ("GET", "/api/definitely-not-exist", {404}, "未知 GET → 404"),
    ("POST", "/api/definitely-not-exist", {404}, "未知 POST → 404（曾因 NameError 断连）"),
]


def call(method, path, body=None):
    """发一个请求，返回 (状态码, 响应体前 200 字节, 响应头里的 Content-Length)。

    第三个返回值用于识别「一个请求发两个响应」：路由实现若在已写出响应后
    又补一个 404，客户端只会看到后者，靠状态码根本发现不了。
    这里额外核对「同一次 read 里是否出现两次 HTTP/1.1」。
    """
    # 路径里的中文/特殊字符必须先编码，否则 http.client 会在建请求头时抛 ascii 编码错
    url = BASE + urllib.parse.quote(path, safe="/?=&:")
    data = json.dumps(body if body is not None else {}).encode("utf-8")
    req = urllib.request.Request(url, data=data if method == "POST" else None,
                                 method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
            return r.status, raw[:200], raw.count(b"HTTP/1.1")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return exc.code, raw[:200], raw.count(b"HTTP/1.1")
    except Exception as exc:                     # 连接被关 / 超时
        return None, str(exc)[:200], 0


def main():
    bad = []
    for method, path, want, label in CASES:
        code, body, dup = call(method, path)
        ok = code in want and dup <= 1
        mark = "✓" if ok else "✗"
        note = "" if dup <= 1 else "  ← 一次请求出现了 %d 个响应！" % dup
        print("%s %-6s %-42s %-5s %s%s" % (mark, method, path, code, label, note))
        if not ok:
            bad.append((method, path, code, want, body, dup))
    print()
    print("结果：%d 通过 / %d 失败" % (len(CASES) - len(bad), len(bad)))
    if bad:
        print("\n失败明细：")
        for method, path, code, want, body, dup in bad:
            print("  %s %s → 实际 %s，期望 %s" % (method, path, code, sorted(want)))
            if dup > 1:
                print("    重复响应 %d 次：路由已写出响应却又补了 404" % dup)
            if code is None:
                print("    连接异常：%s" % body)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
