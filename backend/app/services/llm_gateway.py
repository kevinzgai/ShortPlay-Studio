"""LLM 网关（绞杀者第一步）：ChatOpenAI 替换 urllib 直连 + llm_calls 落库。

对外签名与 app/services/llm_json.py 完全一致（call_llm / call_llm_json），
调用方只改 import 行。**兼容性契约逐字保住**（技术方案 §4 清单）：
  · 返回 (content, model) / (data, model) 二元组
  · RuntimeError("NO_KEY") / 「模型服务返回 %s：%s」/「连不上模型服务或请求超时：%s」
  · finish_reason==length 的截断文案 / reasoning_content 空答案文案
  · temperature=0.3、user 消息 36000 字符截断
  · call_llm_json 修补→重试一次的顺序与重试 system 追加文案（含「中文书名号」）

设计原则：
  · extract_json / repair_json 从 llm_json.py **原样 import**（铁律：逐字保留）。
  · llm_settings() 每次调用实时读——provider 热切换即刻生效（与旧行为一致）。
  · 台账落库失败只打 stderr，绝不连坐业务（铁律三）。
"""

import sys
import time
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.config.db import record_llm_call
from app.config.llm_store import llm_max_tokens, llm_settings
from app.services.llm_json import extract_json, repair_json  # 铁律：不重写

_MAX_USER_CHARS = 36000  # 与旧 call_llm 一致：含带编号的剧本行清单


def _caller_path():
    """自动取业务调用方标识（v1 粒度 = 模块名，如 parse_task / assets）。

    回溯栈找第一个「不是本模块」的帧，取其模块名或文件名：
      · 业务模块调用 → "parse_task" / "assets"（排查时能直接定位到哪个阶段）
      · 脚本 / 手工调试直接调 → 退回脚本文件名，不再是笼统的 "unknown"
    这条信息只在台账里用，取不到也无害，所以不做任何异常放大。
    """
    frame = sys._getframe(1)
    for _ in range(8):
        if frame is None:
            break
        mod = frame.f_globals.get("__name__", "")
        if mod and not mod.endswith("llm_gateway") and mod != __name__:
            leaf = mod.rsplit(".", 1)[-1]
            if leaf and leaf != "__main__":
                return leaf
            # __main__：取脚本文件名，如 debug_assets.py
            fname = frame.f_globals.get("__file__") or ""
            if fname:
                return Path(fname).stem or "main"
            return "main"
        frame = frame.f_back
    return "unknown"


def _chat():
    """按当前生效 provider 构建 ChatOpenAI。base_url 以 / 结尾会双斜杠，先归一。"""
    base, key, model = llm_settings()
    if not (base and key):
        raise RuntimeError("NO_KEY")
    chat = ChatOpenAI(
        model=model,
        api_key=key,
        base_url=base.rstrip("/"),
        temperature=0.3,
        max_tokens=llm_max_tokens(),
        timeout=120,
        max_retries=0,  # 重试语义归业务层（call_llm_json 的修补→重试），框架层不做
    )
    return chat, base, key, model


def _translate_error(exc):
    """langchain 异常 → 旧版中文报错文案（逐字兼容清单）。"""
    status = getattr(exc, "status_code", None)
    if status is not None:
        body = ""
        resp = getattr(exc, "response", None)
        if resp is not None:
            try:
                body = resp.text[:220]
            except Exception:  # noqa: BLE001
                body = ""
        raise RuntimeError("模型服务返回 %s：%s" % (status, body)) from exc
    raise RuntimeError("连不上模型服务或请求超时：%s" % exc) from exc


def _demand_content(choice_msg, budget):
    """旧版对空内容 / 截断 / 只吐思考的三种专用报错（文案逐字保留）。"""
    finish = (choice_msg.response_metadata or {}).get("finish_reason", "")
    if finish == "length":
        raise RuntimeError(
            "模型输出被截断（max_tokens=%d 不够用）。推理模型的思考过程也占额度，"
            "可在 llm-config.bat 里加大 SHORTPLAY_LLM_MAX_TOKENS，或把单集场次拆少一些。" % budget
        )
    content = choice_msg.content or ""
    if isinstance(content, list):  # 部分网关回 content blocks
        content = "".join(b.get("text", "") for b in content if isinstance(b, dict))
    if not content.strip():
        thinking = ((choice_msg.additional_kwargs or {}).get("reasoning_content") or "").strip()
        if thinking:
            raise RuntimeError(
                "模型只输出了思考过程、没有最终答案（推理 token 用尽额度）。"
                "请加大 SHORTPLAY_LLM_MAX_TOKENS，或换回 deepseek-chat。"
            )
        raise RuntimeError("模型返回空内容，请检查 SHORTPLAY_LLM_MODEL 是否是该服务真实支持的模型名")
    return content


def call_llm(system: str, user: str, timeout: int = 120, max_tokens: int = None):
    """同签名替换 llm_json.call_llm。返回 (content, model)。"""
    call_path = _caller_path()
    chat, base, _key, model = _chat()
    budget = max_tokens or llm_max_tokens()
    if max_tokens:  # 调用方显式给过则覆盖
        chat = chat.bind(max_tokens=max_tokens)
    t0 = time.monotonic()
    try:
        msg = chat.invoke([SystemMessage(content=system),
                           HumanMessage(content=user[:_MAX_USER_CHARS])])
    except RuntimeError:
        raise  # NO_KEY 等已在 _chat 抛出的直接透传
    except Exception as exc:  # noqa: BLE001
        record_llm_call(call_path=call_path, provider_id="", base_url=base, model=model,
                        ok=False, latency_ms=int((time.monotonic() - t0) * 1000),
                        error=str(exc)[:200])
        raise _translate_error(exc) from exc

    content = _demand_content(msg, budget)
    usage = msg.usage_metadata or {}  # langchain 标准化字段
    record_llm_call(
        call_path=call_path, provider_id="", base_url=base, model=model, ok=True,
        latency_ms=int((time.monotonic() - t0) * 1000),
        prompt_chars=len(system) + min(len(user), _MAX_USER_CHARS),
        completion_chars=len(content), finish_reason="stop",
        usage={"prompt_tokens": usage.get("input_tokens"),
               "completion_tokens": usage.get("output_tokens"),
               "total_tokens": usage.get("total_tokens")})
    return content, model


def call_llm_json(system: str, user: str, key: str, timeout: int = 120,
                  expect_list: bool = True):
    """取 JSON：本地修复 → 仍失败则追加一次「只要合法 JSON」的重试。

    与 llm_json.call_llm_json 的流程与文案**逐字一致**（铁律），唯一区别是底层
    走 ChatOpenAI。key 参数保留占位（旧签名是传入 JSON 根键名）。
    """
    content, model = call_llm(system, user, timeout)
    try:
        return extract_json(content, key, expect_list), model
    except ValueError as first_err:
        fixed = repair_json(content)
        if fixed:
            try:
                return extract_json(fixed, key, expect_list), model
            except ValueError:
                pass
        retry_system = (system + "\n\n【上一次输出的 JSON 不合法（%s）。"
                                 "这次只输出一个合法 JSON 对象：不要注释、不要代码块、"
                                 "字符串内不要出现未转义的换行或英文双引号，引用台词改用中文书名号。】"
                        % str(first_err)[:80])
        content2, model2 = call_llm(retry_system, user, timeout)
        try:
            return extract_json(content2, key, expect_list), model2
        except ValueError:
            fixed2 = repair_json(content2)
            if fixed2:
                return extract_json(fixed2, key, expect_list), model2
            raise
