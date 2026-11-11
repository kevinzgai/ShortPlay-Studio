"""POST 路由表。

从 server.py 的 Handler.do_POST 整块搬来。与原实现的两点差异，仅为结构：
  1. 原来的「白名单校验 + 读 body」前置段，改成 HANDLED_POST_PATHS 集合 + dispatch；
  2. 原来最后那段「六个 AI 接口共用一个 try（if-elif 分支）」保留原样，
     因为它们的错误处理完全一致，拆开反而要复制六遍 except。

业务函数、判定条件、状态码、响应体字段一字未改。

【易错点 · 顺序敏感】原实现的 AI 段前面有一句「剧本 < 20 字就 400」，
它对 /api/ai/frames 例外。这段校验必须留在 AI 分支内部、且在分支判断之前，
不能提到 dispatch 层，否则 /api/ai/frames 会被误拦。
"""

import base64
import json

from app.config.engine_store import (comfy_host, engine_config_save,
                                     h3_image_status, qwen_image_status)
from app.services.agents import AgentDisabledError, agent_system
from app.services.assets import build_asset_pack, build_frame_prompts, fill_asset_with_ai
from app.services.comfy import (comfy_job_start, comfy_prompt_rows, comfy_status)
from app.services.diagnostics import engine_probe, llm_test
from app.services.export_zip import build_export_zip
from app.services.llm_json import call_llm_json
from app.services.parse_task import (parse_task_cancel, parse_task_start)
from app.services.plan import build_script_index, normalize_plan
from app.services.projects import (project_create, project_delete, project_duplicate,
                                   project_ref_save, project_rename, project_save)
from app.services.script_text import (build_adapted_script, check_adaptation,
                                      docx_extract_text, split_source_sentences)
from app.services.shots import normalize_shots
from app.config.llm_store import (llm_provider_activate, llm_provider_delete,
                                  llm_provider_save)
from app.infra.coerce import _as
from app.web.responses import bytes_response, fail_response, json_response, query_dict


# --------------------------------------------------------------------------
# 项目类：统一 ValueError → 400，OSError → 500
# --------------------------------------------------------------------------
PROJECT_POST_PATHS = {
    "/api/projects/save": project_save,
    "/api/projects/create": project_create,
    "/api/projects/rename": project_rename,
    "/api/projects/delete": project_delete,
    "/api/projects/duplicate": project_duplicate,
    "/api/projects/upload-ref": project_ref_save,
}


def _project_dispatch(h, path, payload):
    fn = PROJECT_POST_PATHS[path]
    try:
        return json_response(h, fn(payload))
    except ValueError as exc:
        return json_response(h, {"detail": str(exc)[:200]}, 400)
    except OSError as exc:
        return json_response(h, {"detail": "项目写入失败：" + str(exc)[:200]}, 500)


# --------------------------------------------------------------------------
# 各个独立接口
# --------------------------------------------------------------------------
def _import_docx(h, payload):
    # 只做「docx → 纯文本」：不落盘、不入项目、不回显原始二进制
    try:
        raw = base64.b64decode(str(payload.get("dataB64") or ""), validate=False)
    except Exception:
        return json_response(h, {"detail": "文件内容解码失败，请重新选择文件"}, 400)
    if not raw:
        return json_response(h, {"detail": "文件是空的"}, 400)
    if len(raw) > 24 * 1024 * 1024:
        return json_response(h, {"detail": "文件超过 24MB，请先删掉里面的图片再上传"}, 413)
    try:
        out = docx_extract_text(raw)
    except ValueError as exc:
        return json_response(h, {"detail": str(exc)[:220]}, 400)
    out["name"] = str(payload.get("name") or "")[:120]
    return json_response(h, out)


def _parse_start(h, payload):
    try:
        return json_response(h, parse_task_start(payload))
    except ValueError as exc:
        return json_response(h, {"detail": str(exc)[:200]}, 400)


def _parse_cancel(h, payload):
    return json_response(h, parse_task_cancel(payload))


def _export_zip(h, payload):
    try:
        data, name = build_export_zip(payload)
    except Exception as exc:
        return json_response(h, {"detail": "打包失败：" + str(exc)[:200]}, 500)
    return bytes_response(h, data, name, "application/zip")


def _asset_fill(h, payload):
    # 不走「剧本长度 >= 20」的通用校验：只改单项资产
    try:
        return json_response(h, fill_asset_with_ai(payload))
    except RuntimeError as exc:
        return fail_response(h, exc)
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        return json_response(h, {"detail": "形象补全失败：" + str(exc)[:200]}, 502)
    except Exception as exc:
        return json_response(h, {"detail": "形象补全失败：" + str(exc)[:200]}, 500)


def _provider_save(h, payload):
    try:
        return json_response(h, llm_provider_save(payload))
    except ValueError as exc:
        return json_response(h, {"detail": str(exc)[:200]}, 400)


def _provider_activate(h, payload):
    try:
        return json_response(h, llm_provider_activate(payload))
    except ValueError as exc:
        return json_response(h, {"detail": str(exc)[:200]}, 400)


def _provider_delete(h, payload):
    try:
        return json_response(h, llm_provider_delete(payload))
    except ValueError as exc:
        return json_response(h, {"detail": str(exc)[:200]}, 400)


def _llm_test(h, payload):
    try:
        return json_response(h, llm_test(payload))
    except ValueError as exc:
        return json_response(h, {"detail": str(exc)[:200]}, 400)


def _engine_config_save(h, payload):
    try:
        return json_response(h, engine_config_save(payload))
    except ValueError as exc:
        return json_response(h, {"detail": str(exc)[:200]}, 400)


def _engine_test(h, payload):
    try:
        return json_response(h, engine_probe(payload.get("kind")))
    except Exception as exc:
        return json_response(h, {"detail": "探测失败：" + str(exc)[:160]}, 502)


def _comfy_prompt(h, payload):
    # 只拼提示词，不依赖 ComfyUI 在线：没装模型也能先对稿
    try:
        raw_assets = payload.get("assets")
        assets = raw_assets if isinstance(raw_assets, list) else []
        return json_response(h, comfy_prompt_rows(
            [a for a in assets[:24] if isinstance(a, dict)],
            payload.get("variants") if isinstance(payload.get("variants"), dict) else {},
            _as(payload.get("styleEn"), "", 240)))
    except (ValueError, TypeError) as exc:
        return json_response(h, {"detail": str(exc)[:220]}, 400)


def _comfy_generate(h, payload):
    engine = payload.get("engine")
    if engine not in ("comfy", "qwen", "h3"):
        engine = "comfy"
    seq_n = payload.get("n") if isinstance(payload.get("n"), int) else 1
    seq_n = max(1, min(seq_n, 4))
    if engine == "qwen":
        qs = qwen_image_status()
        if not qs.get("online"):
            return json_response(h, {"detail": "通义万相没配置好：" + qs.get("detail", "缺 API Key")}, 503)
    elif engine == "h3":
        hs = h3_image_status()
        if not hs.get("online"):
            return json_response(h, {"detail": "MiniMax 没配置好：" + hs.get("detail", "缺 API Key")}, 503)
    else:
        st = comfy_status()
        if not st.get("online"):
            return json_response(h, {"detail": "本地 ComfyUI 没连上（%s）：%s" %
                                               (comfy_host(), st.get("detail", "未知原因"))}, 503)
    try:
        # _alist 只收字符串，这里 assets 是对象数组，必须自己取
        raw_assets = payload.get("assets")
        assets = raw_assets if isinstance(raw_assets, list) else []
        return json_response(h, comfy_job_start(
            [a for a in assets[:24] if isinstance(a, dict)],
            payload.get("variants") if isinstance(payload.get("variants"), dict) else {},
            _as(payload.get("styleEn"), "", 200),
            payload.get("seed") if isinstance(payload.get("seed"), int) else 0,
            engine, seq_n))
    except (ValueError, TypeError) as exc:
        return json_response(h, {"detail": str(exc)[:220]}, 400)
    except Exception as exc:
        return json_response(h, {"detail": "出图任务启动失败：" + str(exc)[:200]}, 500)


# --------------------------------------------------------------------------
# AI 段：六个接口共用一个 try / 一套 except，保持原实现的错误口径
# --------------------------------------------------------------------------
AI_PATHS = (
    "/api/ai/adapt", "/api/ai/assets", "/api/ai/frames",
    "/api/llm/parse", "/api/ai/plan", "/api/ai/storyboard",
)


def _ai(h, path, payload):
    script = str(payload.get("script", ""))
    if path != "/api/ai/frames" and len(script.strip()) < 20:
        return json_response(h, {"detail": "剧本文字太短，无法分析"}, 400)

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
        return json_response(h, result)
    except AgentDisabledError as exc:
        return json_response(h, {"detail": str(exc)[:200]}, 400)
    except RuntimeError as exc:
        return fail_response(h, exc)
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        return json_response(h, {"detail": "模型结果解析失败：" + str(exc)[:200]}, 502)
    except Exception as exc:  # 兜底，避免线程异常导致界面一直转圈
        return json_response(h, {"detail": "处理失败：" + str(exc)[:200]}, 500)


# --------------------------------------------------------------------------
# 路由表：path → 处理函数（签名统一 fn(h, payload)）
# --------------------------------------------------------------------------
POST_ROUTES = {
    "/api/import/docx": _import_docx,
    "/api/parse/start": _parse_start,
    "/api/parse/cancel": _parse_cancel,
    "/api/export/zip": _export_zip,
    "/api/ai/asset-fill": _asset_fill,
    "/api/llm/providers/save": _provider_save,
    "/api/llm/providers/activate": _provider_activate,
    "/api/llm/providers/delete": _provider_delete,
    "/api/llm/test": _llm_test,
    "/api/engine/config": _engine_config_save,
    "/api/engine/test": _engine_test,
    "/api/comfy/prompt": _comfy_prompt,
    "/api/comfy/generate": _comfy_generate,
}

for _p in AI_PATHS:
    POST_ROUTES[_p] = lambda h, payload, _path=_p: _ai(h, _path, payload)


class Unmatched:
    """「本模块不认这个路径」的哨兵。

    【为什么不能用 None 表示未匹配】
    处理函数返回的是 responses.Response（2026-11-11 改造前返回 None，因为当时
    json_response 直接写 socket 不返回值）。若拿 None 当「没匹配到」，语义上仍能
    工作，但一旦某个处理函数将来显式 return None（例如忘记 return），上层就会在
    响应已经写出之后再补一个 404，一个请求发出两个响应 —— curl 只看到最后一个
    404，前端则直接判失败。实测表现：出图接口 200 之后紧跟 404，图片回挂彻底失效。
    用独立的哨兵类型，让「未匹配」和「已处理」在任何情况下都不会混淆。
    """
    __slots__ = ()


UNMATCHED = Unmatched()


def dispatch(h, path, payload):
    """有 body 的 POST 分发。返回 UNMATCHED 表示此路径不归本模块管。"""
    if path in PROJECT_POST_PATHS:
        return _project_dispatch(h, path, payload)
    fn = POST_ROUTES.get(path)
    if fn is None:
        return UNMATCHED
    return fn(h, payload)


def known_paths():
    """全部由本模块处理的 POST 路径（含项目类），供上层做 404 白名单。"""
    return set(PROJECT_POST_PATHS) | set(POST_ROUTES)
