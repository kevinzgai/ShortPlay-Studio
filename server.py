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

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _bytes(self, data, filename, ctype="application/octet-stream", inline=False):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if inline:
            # 内容寻址（文件名 = 图片哈希），所以可以放心长缓存
            self.send_header("Content-Disposition", "inline; filename*=UTF-8''"
                             + urllib.parse.quote(filename))
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        else:
            self.send_header("Content-Disposition",
                             'attachment; filename="export.zip"; '
                             "filename*=UTF-8''" + urllib.parse.quote(filename))
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _read(self):
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _fail(self, exc):
        if isinstance(exc, RuntimeError) and str(exc) == "NO_KEY":
            return self._json({
                "detail": "还没有配置大模型 Key。当前自动使用离线规则引擎，核心功能都可用；"
                          "如需 AI 分集分镜，请复制 llm-config.example.bat 为 llm-config.bat 并填入 Key。"
            }, 503)
        if isinstance(exc, urllib.error.HTTPError):
            return self._json({"detail": "模型服务异常"}, 502)
        return self._json({"detail": str(exc)[:300]}, 502)

    def _query(self):
        return {k: v[0] for k, v in
                urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).items()}

    def _parse_stream(self):
        """SSE：按 seq 增量推事件，任务收尾后关连接；前端断线用 since 续传。"""
        q = self._query()
        tid = q.get("id", "")
        task = PARSE_TASKS.get(tid)
        if not task:
            return self._json({"detail": "任务不存在或已过期"}, 404)
        try:
            since = int(q.get("since") or self.headers.get("Last-Event-ID") or 0)
        except (TypeError, ValueError):
            since = 0
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        self.close_connection = True
        self.wfile.flush()
        last_ping = time.time()
        try:
            while True:
                events, over = parse_task_wait(task, since, 2.0)
                for ev in events:
                    since = ev["seq"]
                    self.wfile.write(("id: %d\ndata: %s\n\n" % (
                        ev["seq"], json.dumps(ev, ensure_ascii=False))).encode("utf-8"))
                if events:
                    self.wfile.flush()
                    last_ping = time.time()
                elif time.time() - last_ping >= 8:
                    self.wfile.write(b": ping\n\n")     # 心跳，防止中间层掐掉空闲连接
                    self.wfile.flush()
                    last_ping = time.time()
                if over and not events:
                    self.wfile.write(b": end\n\n")
                    self.wfile.flush()
                    break
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def _agent_get(self, path):
        q = self._query()
        if path == "/api/agents":
            return self._json(AGENTS.describe())
        if path == "/api/agents/prompt":
            aid = q.get("id", "")
            if not AGENT_ID_RE.match(aid):
                return self._json({"detail": "非法角色 id"}, 400)
            raw = AGENTS.read_prompt(aid)
            meta, body = parse_frontmatter(raw) if raw else ({}, "")
            return self._json({"id": aid, "content": raw, "meta": meta,
                               "compiled": AGENTS.system(aid)[0] if body else ""})
        if path == "/api/skills":
            out = []
            for sid in AGENTS.skill_ids():
                try:
                    meta, body = parse_frontmatter(AGENTS.read_skill(sid))
                except ValueError:
                    meta, body = {}, ""
                out.append({"id": sid, "name": meta.get("name", sid),
                            "description": meta.get("description", ""),
                            "chars": len(body)})
            return self._json({"skills": out})
        if path == "/api/skills/detail":
            sid = q.get("id", "")
            try:
                return self._json({"id": sid, "content": AGENTS.read_skill(sid)})
            except ValueError as exc:
                return self._json({"detail": str(exc)}, 404)
        return None

    def _agent_post(self, path, payload):
        """Agent / Skill 管理与通用执行；错误统一返回中文，不暴露堆栈。"""
        try:
            aid = str(payload.get("id") or "").strip()
            if path == "/api/agents/save":
                AGENTS.save_prompt(aid, payload.get("content"))
                return self._json({"ok": True, "id": aid})
            if path == "/api/agents/patch":
                AGENTS.patch_agent(aid, payload.get("patch") or {})
                return self._json({"ok": True, "id": aid})
            if path == "/api/agents/add":
                AGENTS.add_agent(payload)
                return self._json({"ok": True, "id": aid, "agents": AGENTS.describe()})
            if path == "/api/agents/delete":
                AGENTS.delete_agent(aid)
                return self._json({"ok": True, "agents": AGENTS.describe()})
            if path == "/api/skills/save":
                AGENTS.save_skill(aid, payload.get("content"))
                return self._json({"ok": True, "id": aid})
            if path == "/api/skills/add":
                sid = aid or "new-skill"
                AGENTS.save_skill(sid, payload.get("content") or
                                  "---\nname: %s\ndescription: 自定义技能\n---\n\n# %s\n" % (sid, sid))
                return self._json({"ok": True, "id": sid})
            if path == "/api/skills/delete":
                AGENTS.delete_skill(aid)
                return self._json({"ok": True, "id": aid})
            if path == "/api/agents/run":
                return self._json(AGENTS.run(aid, payload))
            return self._json({"detail": "不支持的 Agent 接口"}, 404)
        except ValueError as exc:
            return self._json({"detail": str(exc)[:300]}, 400)
        except RuntimeError as exc:
            return self._fail(exc)
        except (KeyError, json.JSONDecodeError) as exc:
            return self._json({"detail": "模型结果解析失败：" + str(exc)[:200]}, 502)
        except Exception as exc:
            return self._json({"detail": "处理失败：" + str(exc)[:200]}, 500)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/config":
            base, key, model = llm_settings()
            act = llm_active_provider()
            return self._json({
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
        if path == "/api/llm/providers":
            return self._json(llm_providers_public())
        if path == "/api/engine/config":
            return self._json(engine_config_public())
        if path == "/api/comfy/models":
            return self._json({"models": comfy_unet_names(), "host": comfy_host()})
        if path == "/api/comfy/status":
            return self._json(comfy_status())
        if path == "/api/comfy/job":
            jid = self._query().get("id", "")
            with COMFY_LOCK:
                job = COMFY_JOBS.get(jid)
                snap = json.loads(json.dumps(job)) if job else None
            if not snap:
                return self._json({"detail": "任务不存在或已过期"}, 404)
            # 轮询默认不回传 dataUri（每张几十 KB），只在 finished=1 时取回结果
            if self._query().get("full") != "1":
                for it in snap.get("items", []):
                    it.pop("dataUri", None)
            return self._json(snap)
        if path == "/api/comfy/image":
            name = self._query().get("f", "")
            if not ASSET_IMG_NAME.match(name):
                return self._json({"detail": "非法文件名"}, 400)
            f = ASSET_IMG_DIR / name
            if not f.is_file():
                return self._json({"detail": "图片不存在"}, 404)
            return self._bytes(f.read_bytes(), name, "image/png")
        if path in ("/api/agents", "/api/agents/prompt", "/api/skills", "/api/skills/detail"):
            return self._agent_get(path)
        if path == "/api/parse/events":
            return self._parse_stream()
        if path == "/api/parse/state":
            task = PARSE_TASKS.get(self._query().get("id", ""))
            if not task:
                return self._json({"detail": "任务不存在或已过期"}, 404)
            return self._json(parse_task_snapshot(task))
        if path == "/api/parse/latest":
            return self._json(parse_task_latest())
        if path == "/api/projects":
            return self._json({"projects": project_list(), "dir": str(PROJECTS_DIR)})
        if path == "/api/projects/ref":
            q = self._query()
            pid, fname = q.get("id", ""), q.get("f", "")
            try:
                raw, mime = project_ref_read(pid, fname)
            except ValueError as exc:
                return self._json({"detail": str(exc)}, 404)
            thumb = project_ref_thumb(pid, fname, raw, q.get("w", ""))
            if thumb:
                return self._bytes(thumb, fname, "image/jpeg", inline=True)
            return self._bytes(raw, fname, mime, inline=True)
        if path == "/api/projects/get":
            try:
                return self._json(project_get(self._query().get("id", "")))
            except ValueError as exc:
                return self._json({"detail": str(exc)}, 404)
        return super().do_GET()

    PROJECT_POST_PATHS = (
        "/api/projects/save", "/api/projects/create", "/api/projects/rename",
        "/api/projects/delete", "/api/projects/duplicate",
        "/api/projects/upload-ref",
    )

    AGENT_POST_PATHS = (
        "/api/agents/save", "/api/agents/patch", "/api/agents/add",
        "/api/agents/delete", "/api/agents/run",
        "/api/skills/save", "/api/skills/add", "/api/skills/delete",
    )

    def do_POST(self):
        path = self.path.split("?")[0]
        if path not in ("/api/ai/plan", "/api/ai/storyboard",
                        "/api/ai/adapt", "/api/ai/assets",
                        "/api/ai/frames", "/api/llm/parse",
                        "/api/ai/asset-fill", "/api/comfy/generate", "/api/comfy/prompt",
                        "/api/parse/start", "/api/parse/cancel", "/api/import/docx",
                        "/api/llm/providers/save", "/api/llm/providers/activate",
                        "/api/llm/providers/delete", "/api/llm/test",
                        "/api/engine/config", "/api/engine/test",
                        "/api/export/zip") + self.AGENT_POST_PATHS + self.PROJECT_POST_PATHS:
            return self._json({"detail": "不支持的接口"}, 404)
        try:
            payload = self._read()
        except (ValueError, KeyError, UnicodeDecodeError) as exc:
            return self._json({"detail": "请求格式不对：" + str(exc)}, 400)
        if path in self.PROJECT_POST_PATHS:
            fn = {
                "/api/projects/save": project_save,
                "/api/projects/create": project_create,
                "/api/projects/rename": project_rename,
                "/api/projects/delete": project_delete,
                "/api/projects/duplicate": project_duplicate,
                "/api/projects/upload-ref": project_ref_save,
            }[path]
            try:
                return self._json(fn(payload))
            except ValueError as exc:
                return self._json({"detail": str(exc)[:200]}, 400)
            except OSError as exc:
                return self._json({"detail": "项目写入失败：" + str(exc)[:200]}, 500)

        if path == "/api/import/docx":
            # 只做「docx → 纯文本」：不落盘、不入项目、不回显原始二进制
            try:
                raw = base64.b64decode(str(payload.get("dataB64") or ""), validate=False)
            except Exception:
                return self._json({"detail": "文件内容解码失败，请重新选择文件"}, 400)
            if not raw:
                return self._json({"detail": "文件是空的"}, 400)
            if len(raw) > 24 * 1024 * 1024:
                return self._json({"detail": "文件超过 24MB，请先删掉里面的图片再上传"}, 413)
            try:
                out = docx_extract_text(raw)
            except ValueError as exc:
                return self._json({"detail": str(exc)[:220]}, 400)
            out["name"] = str(payload.get("name") or "")[:120]
            return self._json(out)

        if path == "/api/parse/start":
            try:
                return self._json(parse_task_start(payload))
            except ValueError as exc:
                return self._json({"detail": str(exc)[:200]}, 400)
        if path == "/api/parse/cancel":
            return self._json(parse_task_cancel(payload))

        if path in self.AGENT_POST_PATHS:
            return self._agent_post(path, payload)
        if path == "/api/export/zip":
            try:
                data, name = build_export_zip(payload)
            except Exception as exc:
                return self._json({"detail": "打包失败：" + str(exc)[:200]}, 500)
            return self._bytes(data, name, "application/zip")
        # 以下两个接口不走「剧本长度 >= 20」的通用校验：一个只改单项资产，一个只出图
        if path == "/api/ai/asset-fill":
            try:
                return self._json(fill_asset_with_ai(payload))
            except RuntimeError as exc:
                return self._fail(exc)
            except (ValueError, KeyError, json.JSONDecodeError) as exc:
                return self._json({"detail": "形象补全失败：" + str(exc)[:200]}, 502)
            except Exception as exc:
                return self._json({"detail": "形象补全失败：" + str(exc)[:200]}, 500)
        if path == "/api/llm/providers/save":
            try:
                return self._json(llm_provider_save(payload))
            except ValueError as exc:
                return self._json({"detail": str(exc)[:200]}, 400)
        if path == "/api/llm/providers/activate":
            try:
                return self._json(llm_provider_activate(payload))
            except ValueError as exc:
                return self._json({"detail": str(exc)[:200]}, 400)
        if path == "/api/llm/providers/delete":
            try:
                return self._json(llm_provider_delete(payload))
            except ValueError as exc:
                return self._json({"detail": str(exc)[:200]}, 400)
        if path == "/api/llm/test":
            try:
                return self._json(llm_test(payload))
            except ValueError as exc:
                return self._json({"detail": str(exc)[:200]}, 400)
        if path == "/api/engine/config":
            try:
                return self._json(engine_config_save(payload))
            except ValueError as exc:
                return self._json({"detail": str(exc)[:200]}, 400)
        if path == "/api/engine/test":
            try:
                return self._json(engine_probe(payload.get("kind")))
            except Exception as exc:
                return self._json({"detail": "探测失败：" + str(exc)[:160]}, 502)
        if path == "/api/comfy/prompt":
            # 只拼提示词，不依赖 ComfyUI 在线：没装模型也能先对稿
            try:
                raw_assets = payload.get("assets")
                assets = raw_assets if isinstance(raw_assets, list) else []
                return self._json(comfy_prompt_rows(
                    [a for a in assets[:24] if isinstance(a, dict)],
                    payload.get("variants") if isinstance(payload.get("variants"), dict) else {},
                    _as(payload.get("styleEn"), "", 240)))
            except (ValueError, TypeError) as exc:
                return self._json({"detail": str(exc)[:220]}, 400)
        if path == "/api/comfy/generate":
            engine = payload.get("engine")
            if engine not in ("comfy", "qwen"):
                engine = "comfy"
            seq_n = payload.get("n") if isinstance(payload.get("n"), int) else 1
            seq_n = max(1, min(seq_n, 4))
            if engine == "qwen":
                qs = qwen_image_status()
                if not qs.get("online"):
                    return self._json({"detail": "通义万相没配置好：" + qs.get("detail", "缺 API Key")}, 503)
            else:
                st = comfy_status()
                if not st.get("online"):
                    return self._json({"detail": "本地 ComfyUI 没连上（%s）：%s" %
                                                 (comfy_host(), st.get("detail", "未知原因"))}, 503)
            try:
                # _alist 只收字符串，这里 assets 是对象数组，必须自己取
                raw_assets = payload.get("assets")
                assets = raw_assets if isinstance(raw_assets, list) else []
                return self._json(comfy_job_start(
                    [a for a in assets[:24] if isinstance(a, dict)],
                    payload.get("variants") if isinstance(payload.get("variants"), dict) else {},
                    _as(payload.get("styleEn"), "", 200),
                    payload.get("seed") if isinstance(payload.get("seed"), int) else 0,
                    engine, seq_n))
            except (ValueError, TypeError) as exc:
                return self._json({"detail": str(exc)[:220]}, 400)
            except Exception as exc:
                return self._json({"detail": "出图任务启动失败：" + str(exc)[:200]}, 500)
        script = str(payload.get("script", ""))
        if path != "/api/ai/frames" and len(script.strip()) < 20:
            return self._json({"detail": "剧本文字太短，无法分析"}, 400)

        try:
            if path == "/api/ai/adapt":
                sents = split_source_sentences(script)
                if len(sents) < 3:
                    raise ValueError("原文太短，无法切分场次")
                listing = "\n".join("[%d] %s" % (i, x) for i, x in enumerate(sents))
                user = ("原文句子清单（编号从 0 开始，end 为闭区间）：\n%s\n\n"
                        "共 %d 句。只输出结构 JSON，不要输出原文正文。" % (listing, len(sents)))
                data, model = call_llm_json(agent_system("adapt"), user, "scenes", 240)
                adapted = build_adapted_script(sents, data)
                if len(adapted) < 40:
                    raise ValueError("转写没有生成有效剧本文本")
                chk = check_adaptation(script, adapted)
                result = {
                    "script": adapted,
                    "coverage": {
                        k: chk[k] for k in ("sceneHeads", "sentencesTotal", "sentencesCovered",
                                            "quotesTotal", "quotesCovered")
                    },
                    "warnings": chk["warnings"],
                }
            elif path == "/api/ai/assets":
                scenes = payload.get("scenes") or []
                scene_list = "\n".join(
                    "- 第%s场 [S%s] %s%s｜人物：%s" % (
                        x.get("no"), x.get("no"), x.get("intExt") or "",
                        x.get("location") or "未写明地点",
                        "、".join(str(n) for n in (x.get("characters") or [])) or "未注明")
                    for x in scenes if isinstance(x, dict)) or "（场次信息不可用）"
                user = ("场次清单（evidence 只能引用这里的 S 编号，sceneNos 只能填这里的场号）：\n%s\n\n"
                        "剧本 / 小说全文：\n%s" % (scene_list, script[:26000]))
                data, model = call_llm_json(agent_system("assets"), user, "characters", 240)
                result = build_asset_pack(data, scenes)
            elif path == "/api/ai/frames":
                model = "local-template"
                result = build_frame_prompts(
                    payload.get("shots") or [], payload.get("pack") or {},
                    _as(payload.get("aspect"), "16:9", 12))
            elif path == "/api/llm/parse":  # 兼容旧入口
                data, model = call_llm_json(agent_system("parse"), script, "scenes", 120)
                result = {"scenes": data["scenes"]}
            elif path == "/api/ai/plan":
                scenes = payload.get("scenes") or []
                wanted = payload.get("episodes")
                wanted = int(wanted) if isinstance(wanted, int) and 1 <= wanted <= 6 else "auto"
                scene_list = "\n".join(
                    "- 第%s场 %s%s：%s 句对白 / %s 条动作" % (
                        x.get("no"), x.get("intExt") or "", x.get("location") or "未写明地点",
                        len(x.get("lines") or []), len(x.get("actions") or []))
                    for x in scenes if isinstance(x, dict)) or "（场次信息不可用，请按剧本原文自行判断）"
                user = ("目标集数：%s\n\n场次清单：\n%s\n\n剧本全文：\n%s" %
                        (wanted, scene_list, script[:18000]))
                data, model = call_llm_json(agent_system("plan"), user, "episodes", 180)
                result = normalize_plan(data, scenes, wanted)
            else:
                ep = payload.get("episode") or {}
                scenes = payload.get("scenes") or []
                config = payload.get("config") or {}
                pacing = config.get("pacing") or "standard"
                cap = {"compact": (4, 18), "cinematic": (8, 34)}.get(pacing, (6, 28))
                system = agent_system("storyboard", min_shots=cap[0], max_shots=cap[1])
                ep_text = "第%s集《%s》 场次范围：第%s场–第%s场" % (
                    ep.get("no", 1), ep.get("title", ""), ep.get("sceneFrom", ""), ep.get("sceneTo", ""))
                scene_list = "\n".join(
                    "- 第%s场 %s%s｜对白：%s｜动作：%s" % (
                        x.get("no"), x.get("intExt") or "", x.get("location") or "",
                        " / ".join(str(l.get("text", "")) for l in (x.get("lines") or [])[:6]) or "无",
                        " / ".join(str(a.get("text", "")) for a in (x.get("actions") or [])[:6]) or "无")
                    for x in scenes if isinstance(x, dict)) or "（无场次信息）"
                setting = ("基准单镜时长 %s 秒；节奏 %s；画面比例 %s" %
                           (config.get("defaultDuration", 4), pacing, config.get("aspect", "16:9")))
                index, line_list = build_script_index(scenes)
                user = ("本集信息：%s\n生成设置：%s\n\n本集场次详情：\n%s\n\n"
                        "剧本行清单（refs 只能引用这里的编号，按此顺序编排）：\n%s\n\n"
                        "剧本全文（只处理场次范围内的内容）：\n%s" %
                        (ep_text, setting, scene_list, line_list, script[:20000]))
                data, model = call_llm_json(system, user, "shots", 240)
                result = normalize_shots(data, scenes, config, index)
            result["model"] = model
            return self._json(result)
        except AgentDisabledError as exc:
            return self._json({"detail": str(exc)[:200]}, 400)
        except RuntimeError as exc:
            return self._fail(exc)
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            return self._json({"detail": "模型结果解析失败：" + str(exc)[:200]}, 502)
        except Exception as exc:  # 兜底，避免线程异常导致界面一直转圈
            return self._json({"detail": "处理失败：" + str(exc)[:200]}, 500)


def main():
    no_browser = "--no-browser" in sys.argv
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    base, key, model = llm_settings()
    print("=" * 62)
    print("  分镜工场 ShortPlay Studio 已启动")
    print("  打开： http://127.0.0.1:%d/" % PORT)
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
