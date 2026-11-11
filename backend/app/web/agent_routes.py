"""Agent / Skill 的 GET 与 POST 处理。

这两个函数原本是 Handler 上的方法，搬出来只把 self 换成 h。
留在 HTTP 层会挡住 Step C 换 FastAPI —— 换框架时这 68 行要整体重写一遍，
现在只改签名即可。

为什么不像其他接口那样拆成「一个路径一个函数」：
这 8 个 POST 共用同一套「取 id → 分支 → 统一错误口径」流程，
拆开要复制 8 遍 except，反而更难维护。
"""

import json

from app.services.agents import AGENT_ID_RE, AGENTS, parse_frontmatter
from app.web.responses import fail_response, json_response, query_dict


def agent_get(h, path):
    """path 由调用方显式传入（已去掉 query），与原 Handler._agent_get(path) 行为一致。"""
    q = query_dict(h)
    if path == "/api/agents":
        return json_response(h, AGENTS.describe())
    if path == "/api/agents/prompt":
        aid = q.get("id", "")
        if not AGENT_ID_RE.match(aid):
            return json_response(h, {"detail": "非法角色 id"}, 400)
        raw = AGENTS.read_prompt(aid)
        meta, body = parse_frontmatter(raw) if raw else ({}, "")
        return json_response(h, {"id": aid, "content": raw, "meta": meta,
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
        return json_response(h, {"skills": out})
    if path == "/api/skills/detail":
        sid = q.get("id", "")
        try:
            return json_response(h, {"id": sid, "content": AGENTS.read_skill(sid)})
        except ValueError as exc:
            return json_response(h, {"detail": str(exc)}, 404)
    return None


def agent_post(h, path, payload):
    """Agent / Skill 管理与通用执行；错误统一返回中文，不暴露堆栈。"""
    try:
        aid = str(payload.get("id") or "").strip()
        if path == "/api/agents/save":
            AGENTS.save_prompt(aid, payload.get("content"))
            return json_response(h, {"ok": True, "id": aid})
        if path == "/api/agents/patch":
            AGENTS.patch_agent(aid, payload.get("patch") or {})
            return json_response(h, {"ok": True, "id": aid})
        if path == "/api/agents/add":
            AGENTS.add_agent(payload)
            return json_response(h, {"ok": True, "id": aid, "agents": AGENTS.describe()})
        if path == "/api/agents/delete":
            AGENTS.delete_agent(aid)
            return json_response(h, {"ok": True, "agents": AGENTS.describe()})
        if path == "/api/skills/save":
            AGENTS.save_skill(aid, payload.get("content"))
            return json_response(h, {"ok": True, "id": aid})
        if path == "/api/skills/add":
            sid = aid or "new-skill"
            AGENTS.save_skill(sid, payload.get("content") or
                              "---\nname: %s\ndescription: 自定义技能\n---\n\n# %s\n" % (sid, sid))
            return json_response(h, {"ok": True, "id": sid})
        if path == "/api/skills/delete":
            AGENTS.delete_skill(aid)
            return json_response(h, {"ok": True, "id": aid})
        if path == "/api/agents/run":
            return json_response(h, AGENTS.run(aid, payload))
        return json_response(h, {"detail": "不支持的 Agent 接口"}, 404)
    except ValueError as exc:
        return json_response(h, {"detail": str(exc)[:300]}, 400)
    except RuntimeError as exc:
        return fail_response(h, exc)
    except (KeyError, json.JSONDecodeError) as exc:
        return json_response(h, {"detail": "模型结果解析失败：" + str(exc)[:200]}, 502)
    except Exception as exc:
        return json_response(h, {"detail": "处理失败：" + str(exc)[:200]}, 500)


AGENT_GET_PATHS = ("/api/agents", "/api/agents/prompt", "/api/skills", "/api/skills/detail")
AGENT_POST_PATHS = (
    "/api/agents/save", "/api/agents/patch", "/api/agents/add",
    "/api/agents/delete", "/api/agents/run",
    "/api/skills/save", "/api/skills/add", "/api/skills/delete",
)
