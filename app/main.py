#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ShortPlay Studio · 本机服务（只用 Python 标准库，零第三方依赖）。

作用：
  1. 托管 dist/ 里的 Vue 前端构建产物（由 start.bat 自动构建）
  2. 探测模型配置：GET  /api/config
  3. AI 自动分集：POST /api/ai/plan
  4. AI 批量分镜：POST /api/ai/storyboard
  5. 小说体 → 场次剧本（工作流前置阶段）：POST /api/ai/adapt
  6. 剧本 → 资产包 / 关键提示词：POST /api/ai/assets
  7. 分镜表 + 资产包 → 每镜起始帧提示词：POST /api/ai/frames
  8. 资产包 + 分镜表 + 剧本 → 整个项目 ZIP：POST /api/export/zip
  9. 兼容旧入口（只读懂剧本）：POST /api/llm/parse
 10. Agent 工作台（角色 / 技能注册表，在线编辑、新增即生效）：
       GET  /api/agents、/api/agents/prompt、/api/skills、/api/skills/detail
       POST /api/agents/run、/api/agents/save、/api/agents/patch、
            /api/agents/add、/api/agents/delete、/api/skills/save 等
 11. 【休眠保留 · 无 UI 入口，勿删（旧项目恢复用）】剧本拆解任务（后端执行 + 事件流）：
       S2 起「AI 一键分集 + 分镜」的一键入口已从前端移除，改为
       ① 改剧本 → ② 分集 → ③ 分镜 → ④ 定妆 四步人工确认（单步接口 /api/ai/*）。
       下面这条 7 阶段流水线代码保留、前端无任何入口，仅用于旧项目刷新时恢复进度；
       删掉会让旧存档报错。不要把它当主流程，也不要新建 UI 入口。
       POST /api/parse/start  开任务，秒回 taskId
       GET  /api/parse/events SSE 推送阶段 / 工具调用事件（since 续传）
       GET  /api/parse/state  整份快照（刷新页面靠它恢复）
       GET  /api/parse/latest 最近一个任务（页面打开时接回进度）
       POST /api/parse/cancel 取消（阶段边界生效）

设计原则：
  - 模型只负责「创作决策」（怎么切集、怎么分镜），不负责程序正确性；
    服务端对返回结果做结构校验与归一化，脏数据一律纠正或降级，绝不直接喂给界面。
  - 角色 = 注册表一条记录 + 一个 prompt 文件 + 若干 SKILL.md；
    新增「剧本评估 / 剧本创作 / 导演」等角色不需要改 Python 代码。
  - 未配置 Key / 超时 / 返回异常，接口给出明确中文原因，前端自动降级到离线规则引擎。
  - 密钥只存在本机 llm-config.bat，不写进网页、不进日志、不进导出文件。

【本文件为什么存在】
拆分前这些都是 server.py 的内容（4418 行）。A 阶段把业务搬进 app/services/、
路由搬进 app/web/、配置搬进 app/config/ 之后，server.py 里只剩「装配」这一类代码：
  · 监听地址与端口（局域网 / 仅本机）
  · 静态目录（dist/ 或 SHORTPLAY_WEB_ROOT 指向的前端仓产物）
  · listen backlog（见 StudioServer 的说明，直接影响并发是否被 RST）
  · HTTP 分发（两张路由表 + SSE / Agent 三个专用分支）
  · 启动横幅与浏览器自动打开
把它单独成层，server.py 才能是「3 行薄壳」（start.bat 里 `py server.py` 不用改），
将来换 FastAPI 时替换的也只是这一层的 run()，app/web/ 的路由表可原样保留。

设计原则之外的一条：**本文件不做业务判断**。一旦这里出现 if 判断业务字段，
说明有逻辑没归位到 app/services/。
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from app.config.base import load_local_config
from app.config.llm_store import llm_bootstrap, llm_settings
from app.paths import PORT, WEB_ROOT
from app.web.agent_routes import (AGENT_GET_PATHS, AGENT_POST_PATHS, agent_get,
                                  agent_post)
from app.web.responses import json_response, read_body
from app.web.routes_get import GET_ROUTES
from app.web.routes_post import UNMATCHED, dispatch as post_dispatch
from app.web.routes_post import known_paths as known_post_paths
from app.web.sse import parse_stream

# 配置在 import 时就加载完毕（与拆分前 server.py 的时机一字不差）。
# 为什么不做成 run() 里的第一步：旧语义是「入口一 import，llm 配置就绪」，
# 诊断类接口与部分测试按这个前提写的；挪进 run() 会变成「调用才就绪」，
# 属于行为变更，不在本轮范围内。
load_local_config()
llm_bootstrap()


class Handler(SimpleHTTPRequestHandler):
    """HTTP 分发：静态文件交给父类，/api/** 交给 app/web/ 的路由表。

    这里刻意不留 _json / _bytes / _fail / _query 这类转发方法：路由处理函数
    统一用 app/web/responses.py 的原语，Handler 自己只在「读 body 失败」和
    「路径不在白名单」两处写响应，直接用 json_response 即可，少一层跳转。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def log_message(self, fmt, *args):
        # 静态资源的访问日志压掉，只留 /api/ 的，否则刷屏且盖住真正的错误
        if "/api/" in (self.path or ""):
            sys.stderr.write("[api] " + (fmt % args) + "\n")

    def do_GET(self):
        """GET 分发：纯函数路由表 + 需要长连接/多分支的专用实现。"""
        path = self.path.split("?")[0]
        fn = GET_ROUTES.get(path)
        if fn is not None:
            return fn(self)
        if path in AGENT_GET_PATHS:
            return agent_get(self, path)
        if path == "/api/parse/events":
            return parse_stream(self)
        return super().do_GET()

    def do_POST(self):
        """POST 分发：白名单校验 → 读 body → 路由表。

        白名单 = 纯函数路由表 + Agent 路径，未知路径一律 404，
        避免随手加个接口就意外对外暴露。
        """
        path = self.path.split("?")[0]
        if path not in known_post_paths() and path not in AGENT_POST_PATHS:
            return json_response(self, {"detail": "不支持的接口"}, 404)
        try:
            payload = read_body(self)
        except (ValueError, KeyError, UnicodeDecodeError) as exc:
            return json_response(self, {"detail": "请求格式不对：" + str(exc)}, 400)
        if path in AGENT_POST_PATHS:
            return agent_post(self, path, payload)
        out = post_dispatch(self, path, payload)
        if out is UNMATCHED:
            return json_response(self, {"detail": "不支持的接口"}, 404)
        return out


class StudioServer(ThreadingHTTPServer):
    """带足够 backlog 的本地服务。

    【为什么必须改 backlog】
    TCPServer.request_queue_size 默认只有 5，是「已完成三次握手但还没被 accept
    的排队长度」。浏览器打开一次页面会并发拉几十个静态资源（JS/CSS/字体/图片），
    超过 5 个就会让内核直接 RST 掉新连接，客户端看到的是
    `Connection reset by peer` —— 不报错、不进日志，表现为偶发失败：
      · /api/comfy/status 偶发拿不到 → 界面误判「ComfyUI 没连上」并禁用出图按钮
      · /api/comfy/generate 偶发 503 → 出图静默不触发
    实测 20 路并发：backlog=5 时 12/20 被 reset；改成 128 后 20/20 正常。
    单机自用场景没有资源压力，给大一点只有好处。
    """

    request_queue_size = 128
    allow_reuse_address = True
    daemon_threads = True


def _lan_ip():
    """取本机局域网出口 IP：UDP connect 只让内核选路由，不实际发包，跨网卡/跨平台。
    取不到返回 None，横幅只显示本机地址，不影响服务启动。
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        return ip if ip and not ip.startswith("127.") else None
    except OSError:
        return None
    finally:
        sock.close()


def run():
    """启动服务：解析参数 → 绑定端口 → 打印横幅 → 阻塞 serve_forever。"""
    no_browser = "--no-browser" in sys.argv
    # 默认监听所有网卡 → 同一局域网的其他设备可直接访问。
    # 只想本机用时：SHORTPLAY_HOST=127.0.0.1 python3 server.py
    host = os.environ.get("SHORTPLAY_HOST", "0.0.0.0")
    server = StudioServer((host, PORT), Handler)
    base, key, model = llm_settings()
    print("=" * 62)
    print("  分镜工场 ShortPlay Studio 已启动")
    print("  监听： %s:%d" % (host, PORT))
    print("  本机： http://127.0.0.1:%d/" % PORT)
    if host in ("0.0.0.0", "::"):
        lan = _lan_ip()
        print("  局域网： " + ("http://%s:%d/  ← 同一 WiFi 下其他设备用这个" % (lan, PORT)
                              if lan else "已监听所有网卡，请用本机 IP + 端口访问"))
    print("  AI 模式： " + ("已接入 %s（AI 分集 + AI 分镜）" % model if base and key else "离线规则引擎（无需联网）"))
    print("  停止服务：按 Ctrl+C，或直接关掉这个窗口")
    print("=" * 62, flush=True)
    if not no_browser:
        threading.Timer(0.8, lambda: webbrowser.open("http://127.0.0.1:%d/" % PORT)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。", flush=True)
    finally:
        server.server_close()
