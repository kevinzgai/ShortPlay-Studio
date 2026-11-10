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
  9. Agent 工作台（角色 / 技能注册表，在线编辑、新增即生效）：
       GET  /api/agents、/api/agents/prompt、/api/skills、/api/skills/detail
       POST /api/agents/run、/api/agents/save、/api/agents/patch、
            /api/agents/add、/api/agents/delete、/api/skills/save 等
 10. 【休眠保留 · 无 UI 入口，勿删（旧项目恢复用）】剧本拆解任务（后端执行 + 事件流）：
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
"""
from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import io
import json
import os
import random
import re
import socket
import sys
import threading
import time
import zipfile
import xml.etree.ElementTree as ET
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# ---- Step A：以下模块已拆到 app/ 包（函数体逐字搬移，行为零变更）----
from app.paths import ROOT, WEB_ROOT, PORT
from app.infra.coerce import _as, _alist, _ints, _priority, num, s
from app.config.base import load_local_config
from app.config.llm_store import (
    load_local_config, _llm_int, _llm_doc, _llm_doc_write, llm_active_provider,
    llm_settings, llm_bootstrap, llm_providers_public, llm_provider_save,
    llm_provider_activate, llm_provider_delete, llm_max_tokens,
)
from app.config.engine_store import (
    _engine_doc, _engine_doc_write, _engine_get, comfy_host, comfy_model,
    qwen_image_url, qwen_image_model, qwen_image_size, engine_config_public,
    _mask_key, qwen_image_key, qwen_image_status, comfy_unet_names, engine_config_save,
)

from app.constants import (
    SIZE_SET, KIND_SET, DETAIL_FIELDS, GENERIC_RE, STYLE_ANCHOR_DEFAULT,
    STYLE_ANCHOR_EN_DEFAULT, NEGATIVE_DEFAULT, SIZE_EN, TURNAROUND_TMPL,
    FACE_SHEET_TMPL, CONCEPT_TMPL, FRAME_TMPL, ASSET_KIND_CN, SOURCE_CN,
    SYSTEM_ASSET_FILL,
)
from app.services.llm_json import (
    extract_json, call_llm, _quote_closes, repair_json, call_llm_json,
)
from app.services.script_text import (
    docx_extract_text, split_source_sentences, _guess_speaker, _render_sentence,
    build_adapted_script, clean_script_text, check_adaptation, _clean_scenes,
    _cn_int, clean_placeholder, split_head_fields, parse_scene_script, _parse_stats,
    DOCX_W, QUOTE_RE, INNER_RE, _CN_DIGITS, _PLACEHOLDER, _INT_EXT_MAP,
    _TIME_WORDS, _SCENE_HEAD_RE, _SCENE_DLG_RE, _SCENE_ACT_RE,
)
from app.services.plan import (
    normalize_plan, build_script_index, _local_plan, _script_slice_for_ep,
)
from app.services.shots import (
    normalize_detail, ground_generic_shot, patch_shot, normalize_shots,
)
from app.services.assets import (
    build_asset_pack, merge_pack_assets, fill_asset_with_ai, build_frame_prompts,
)
from app.services.render import (
    _md, render_assets_md, render_assets_csv, asset_prompts_payload,
)
from app.infra.image import _pil_image, REF_MIME, _decode_data_url
from app.services.qwen_image import _to_png, qwen_image_generate
from app.services.comfy import (
    STYLE_ANCHOR_EN_OBJECT, PERSON_ONLY_TERMS, ASSET_IMG_DIR, ASSET_IMG_NAME,
    COMFY_VARIANTS, COMFY_SUFFIX, COMFY_SUFFIX_OBJECT, comfy_status, _en_subject,
    style_for_kind, build_comfy_prompt, comfy_prompt_rows, comfy_workflow,
    comfy_submit, comfy_wait, comfy_download, thumb_datauri, COMFY_JOBS,
    COMFY_LOCK, COMFY_SEQ, comfy_job_start, comfy_worker,
)
from app.services.projects import (
    PROJECTS_DIR, PROJECT_TRASH_DIR, PROJECT_ID_RE, PROJECT_LOCK,
    PROJECT_MAX_BYTES, _project_now, _project_path, PROJECT_REF_MAX_BYTES,
    PROJECT_REF_NAME_RE, PROJECT_REF_URL_RE, _project_ref_dir, project_ref_save,
    project_ref_read, project_ref_thumb, _sweep_project_refs, _project_summary,
    project_list, project_get, _project_write, project_save, project_create,
    project_rename, project_duplicate, project_delete,
)
from app.services.export_zip import _ref_bytes, build_export_zip
from app.services.agents import (
    SYSTEM_PLAN, SYSTEM_PARSE, SYSTEM_SHOTS, SYSTEM_ADAPT, SYSTEM_ASSETS,
    AGENTS_DIR, AGENT_ID_RE, SKILL_ID_RE, parse_frontmatter, AgentRegistry,
    AGENTS, AgentDisabledError, agent_system,
)
from app.services.parse_task import (
    PARSE_LOCK, PARSE_COND, PARSE_SEQ, PARSE_KEEP, PARSE_END_STATES,
    PARSE_STAGES, PARSE_LABEL, ParseCancelled, ParseTask, parse_task_snapshot,
    parse_task_wait, parse_task_start, parse_task_cancel, parse_task_latest,
    _parse_error_hint, _close_running_stage, parse_task_worker, parse_task_pipeline,
    PARSE_TASKS,
)
from app.services.diagnostics import llm_probe, llm_test, engine_probe

# Step A 轮 4：路由分发下沉到 app/web/，本文件只剩入口与 SSE/Agent 两个专用方法
from app.web.responses import (bytes_response, fail_response, json_response,
                               query_dict, read_body)
from app.web.routes_get import GET_ROUTES
from app.web.routes_post import UNMATCHED, dispatch as post_dispatch
from app.web.routes_post import known_paths as known_post_paths
from app.web.agent_routes import (AGENT_GET_PATHS, AGENT_POST_PATHS, agent_get,
                                  agent_post)
from app.web.sse import parse_stream

# 前端是 Vue 3 + Vite 工程，构建产物在 dist/；没有构建时回退到项目根便于排查

# 每个镜头的结构化分镜卡字段（模型输出白名单，界面与导出共用同一顺序）
# 建立 / 收束镜头的通用套话：命中就用本场剧本原文重写，不把模板交给界面


# --------------------------------------------------------------------------
# 配置：环境变量优先，其次读同目录 llm-config.bat（双击 start.bat 时用）
# --------------------------------------------------------------------------


load_local_config()


# --------------------------------------------------------------------------
# 多模型配置：llm-providers.json（本机文件，已在 .gitignore 里）
#   为什么不再只用 llm-config.bat：bat 只能存一套，换模型得改文件重启。
#   这里允许存多条、随时切换，界面也能直接改地址/Key/模型名。
#   读取优先级：文件里「当前选中且填了 Key」的那条 → 环境变量 / bat（兼容老用户）。
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# 出图引擎配置：engine-config.json（本机文件，已在 .gitignore 里）
#   为什么独立文件：llm-providers.json 的语义是「多条同类选一条生效」，
#   而引擎是「每类一份单例」，混在一起会让 active 的含义变糊。
#   读取优先级与 llm-providers.json 一致：文件非空值 → 环境变量 / bat → 内置默认。
#   Key 只在服务端使用，回前端一律打码。
# --------------------------------------------------------------------------


llm_bootstrap()


# --------------------------------------------------------------------------
# Prompt
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# 资产包：剧本 / 小说 → 角色、场景、道具的一致性锚点与关键提示词
# 铁律（沿用 adapt 的教训）：模型只输出结构 JSON，长提示词一律由服务端模板拼装。
#   · 模型重写长文本 → 90s → max_tokens 截断 → 502
#   · 结构 JSON + 模板 → 约 17s，且模板一改所有资产同步换风格
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# Agent 注册表（架构思路来自 huobao-drama：workspace/prompts + workspace/skills）
#   · 角色 = registry.json 一条记录 + prompts/<id>.md + skills/<skill>/SKILL.md
#   · 文件是唯一事实来源，界面可在线编辑；改完无需重启（每次调用重新读盘）
#   · 文件缺失时回退到上面的内置常量，保证老部署不会 500
#   · 新增角色不改 Python 代码：add_agent() 写三处文件即可，走 /api/agents/<id>/run
# --------------------------------------------------------------------------


# 默认风格必须是「中性」的：这是没跑 AI 分解、用户也没设风格时的兜底，
# 原先写死「中式民俗恐怖」会把任何剧本（例如雨夜便利店）都串成民俗恐怖味。
# 物体（道具 / 场景）不能带人像词：串里出现 "skin texture" 时，Flux 会直接画人。
# 同一个风格锚按用途取不同英文，比每处模板各写一套更不容易漏。
# 命中即视为人像词：只有画人的模板才允许出现，物体类一律剔除。


# --------------------------------------------------------------------------
# 资产包导出：Markdown / CSV / 机器可读 JSON + 整个项目 ZIP
# 原则：模型只出结构，这里的正文全部由模板渲染 —— 与 build_asset_pack 同一条铁律。
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# 稿子导入：.docx（OOXML）只取正文纯文本，纯标准库，不落盘、不外传
#   · .docx = zip 包，正文在 word/document.xml
#   · 只取 w:p（段）里的 w:t（文本），w:br / w:tab 转成换行与空格
#   · w:instrText（域代码）、w:delText（修订删除）跳过，否则会混进乱码
#   · 连续空行最多留一行：场次分隔靠空行，全删会把剧本粘成一坨
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# 通用工具
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# 归一化：模型输出 → 界面可安全消费的数据
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# 云端出图引擎：通义万相 wan2.7-image-pro（组图 / 一致性序列）
#   · 与本地 ComfyUI 共用同一套任务队列、进度、缩略图、灯箱与导出链路
#   · Key 存在 engine-config.json（界面可改）或环境变量里，绝不回传前端 / 写日志 / 进导出包
#   · 接口同步返回带签名的 OSS 图片 URL，必须立刻下载落盘（URL 会过期）
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# AI 单项形象填充 + 本地 ComfyUI 批量出图
#   · 单项填充：给手工新增 / 设定留空的角色补 face / flaw / 记忆点 / 关键词串
#   · 批量出图：Flux.1-schnell（工作流与 tools/gen_first_frame.py 保持一致）
#     走「提交即返回 jobId + 后台线程串行跑 + 前端轮询」，避免多张图把 HTTP 拖超时
#   · 原图落 examples/assets/，回给前端的是 512px JPEG 缩略 dataURI，
#     直接复用现有 refImage / 撤销栈 / localStorage / zip 导出链路
# --------------------------------------------------------------------------
# 地址与 unet 名不再是模块常量：由 comfy_host() / comfy_model() 现读
# （界面改完立即生效，换 Flux 版本不用改代码）


# 每种变体的英文出图模板、默认画幅（都取 16 的倍数，Flux 对尺寸敏感）
# 画幅按用途给真实比例：三视图 3:2、定妆 3:4、概念图 16:9、宽幕 2.375:1、静物 1:1。
# 2026-11-09 提高约 1.5 倍线性分辨率：预览灯箱看的是原图，768 宽放大后会糊。
# 缩略 dataURI 仍固定 512px（见 thumb_datauri），不跟着涨，避免 localStorage 被撑爆。
# 只放技术性收尾词，不放画种：画种由剧本风格锚（styleEn）决定，
# 原先写死 "professional concept art" 会让所有剧本的资产图都长成一个概念美术味。
# 物体类再多压一遍「不要人」：这套 Flux 工作流 FluxGuidance=0、没有 negative 节点，
# 负向词只能写进正向串，而且重复一次才有足够权重。


# --------------------------------------------------------------------------
# 剧本拆解任务（后端实时进度 + 事件流）
#   【休眠保留 · 无 UI 入口，勿删（旧项目恢复用）】S2 起一键入口已移除，
#   当前主流程是四个工作区逐步人工确认 + /api/ai/* 单步接口；本段仅供旧项目恢复进度。
#   为什么放后端：拆解是 6 个阶段、串行几十秒的活。前端自己 Promise 串联时，
#   刷新页面 / 换标签页进度就没了，也没法在关掉页面后继续。改成「后端任务 + 事件流」：
#     POST /api/parse/start   → { taskId }，后端线程开跑，立刻返回
#     GET  /api/parse/events  → SSE（text/event-stream），按 seq 增量推送，断了可 since 续传
#     GET  /api/parse/state   → 整份快照（阶段 / 事件 / 结果），刷新页面靠它恢复
#     GET  /api/parse/latest  → 最近一个任务，页面刚打开时用来接上没看完的进度
#     POST /api/parse/cancel  → 取消（阶段边界生效，已产出的结果不写入项目）
#
#   事件统一结构（seq 单调递增，前端只 append）：
#     { seq, ts, type, status, stage, stageLabel, percent, done, total,
#       state?, tool?, phase?, callId?, label?, detail?, hint?, ms?, data? }
#       type: task | stage | tool | log | ping | done | error
#       state: running | ok | fail | skip（阶段与工具的状态）
#       phase: start | end（工具调用的一对事件，用 callId 配对）
# --------------------------------------------------------------------------
# 项目管理（Studio 式）
#   一个项目 = projects/<id>/project.json，整份界面状态（剧本 / 分镜 / 资产 /
#   资产包 / 起始帧 / 风格）都在 data 里；参考图与生成图的 dataURI 也随项目落盘。
#   放本机磁盘而不是 localStorage，是因为生成几张素材图就能把 5MB 配额撑爆，
#   写失败后刷新页面就「项目没了」——这是原来丢数据的根因。
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def log_message(self, fmt, *args):
        if "/api/" in (self.path or ""):
            sys.stderr.write("[api] " + (fmt % args) + "\n")

    # ---- 响应原语：实现在 app/web/responses.py，这里只做转发 ----
    # 不复写一份，是因为 _agent_get / _agent_post / _parse_stream 还在本类里调用它们，
    # 而路由表那侧也要用同一套。转发保证两边永远是同一份行为。
    def _json(self, obj, code=200):
        return json_response(self, obj, code)

    def _bytes(self, data, filename, ctype="application/octet-stream", inline=False):
        return bytes_response(self, data, filename, ctype, inline)

    def _read(self):
        return read_body(self)

    def _fail(self, exc):
        return fail_response(self, exc)

    def _query(self):
        return query_dict(self)

    # ---- 以下三类走专用实现（长连接 / 多分支），实现在 app/web/ ----
    def _parse_stream(self):
        return parse_stream(self)

    def _agent_get(self, path):
        return agent_get(self, path)

    def _agent_post(self, path, payload):
        return agent_post(self, path, payload)

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
            return self._json({"detail": "不支持的接口"}, 404)
        try:
            payload = self._read()
        except (ValueError, KeyError, UnicodeDecodeError) as exc:
            return self._json({"detail": "请求格式不对：" + str(exc)}, 400)
        if path in AGENT_POST_PATHS:
            return agent_post(self, path, payload)
        out = post_dispatch(self, path, payload)
        if out is UNMATCHED:
            return self._json({"detail": "不支持的接口"}, 404)
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


def main():
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


if __name__ == "__main__":
    main()
