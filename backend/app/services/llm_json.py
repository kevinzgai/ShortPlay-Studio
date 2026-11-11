"""LLM 调用与 JSON 修复：发请求、抽 JSON、坏 JSON 修补后重试。

为什么单独一层：所有 AI 单步接口（plan / shots / assets / frames）都走这里，
把「模型吐坏 JSON」的兼容逻辑收在一处，别散到各业务函数里。
"""

import json
import re
import urllib.error
import urllib.request

from app.config.llm_store import llm_settings, llm_max_tokens


def extract_json(text: str, key: str, expect_list: bool = True):
    """兼容模型把 JSON 包在 ```json ... ``` 里，或前后带解释文字。

    expect_list=False 给通用 Agent 用：它们的输出根键可以是对象（如 report / outline）。
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("模型返回了空内容，可能是该模型别名不可用，请换一个 model")
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("模型没有返回 JSON 对象")
    data = json.loads(text[start:end + 1])
    if isinstance(data, list):
        data = {key: data}
    if not isinstance(data, dict) or key not in data:
        raise ValueError("模型返回的 JSON 缺少 " + key + " 字段")
    if expect_list and not isinstance(data.get(key), list):
        raise ValueError("模型返回的 " + key + " 不是数组")
    return data


def call_llm(system: str, user: str, timeout: int = 120, max_tokens: int = None):
    base, key, model = llm_settings()
    if not (base and key):
        raise RuntimeError("NO_KEY")
    budget = max_tokens or llm_max_tokens()
    body = json.dumps({
        "model": model,
        "temperature": 0.3,
        "max_tokens": budget,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user[:36000]},  # 含带编号的剧本行清单
        ],
    }).encode("utf-8")
    req = urllib.request.Request(
        base + "/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            upstream = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:220]
        raise RuntimeError("模型服务返回 %s：%s" % (exc.code, detail)) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("连不上模型服务或请求超时：%s" % exc) from exc
    try:
        choice = upstream["choices"][0]
        content = choice["message"].get("content") or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("模型返回体结构异常") from exc

    if choice.get("finish_reason") == "length":
        raise RuntimeError(
            "模型输出被截断（max_tokens=%d 不够用）。推理模型的思考过程也占额度，"
            "可在 llm-config.bat 里加大 SHORTPLAY_LLM_MAX_TOKENS，或把单集场次拆少一些。" % budget
        )
    if not content.strip():
        thinking = (choice["message"].get("reasoning_content") or "").strip()
        if thinking:
            raise RuntimeError(
                "模型只输出了思考过程、没有最终答案（推理 token 用尽额度）。"
                "请加大 SHORTPLAY_LLM_MAX_TOKENS，或换回 deepseek-chat。"
            )
        raise RuntimeError("模型返回空内容，请检查 SHORTPLAY_LLM_MODEL 是否是该服务真实支持的模型名")
    return content, model


def _quote_closes(s: str, i: int) -> bool:
    """判断位置 i 的双引号是不是字符串的结束引号。

    后面第一个非空白字符是 , } ] : 才算结束；否则视为字符串内部裸引号。
    """
    j = i + 1
    while j < len(s) and s[j] in " \t\r\n":
        j += 1
    return j >= len(s) or s[j] in ",}]: "


def repair_json(text: str):
    """模型偶尔吐出畸形 JSON，先尝试本地修，修不动再让模型重来一次。"""
    if not text:
        return ""
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.I)
    s = re.sub(r"\s*```$", "", s)
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end <= start:
        return ""
    s = s[start:end + 1]
    # 1) 连续逗号收敛，再去掉对象/数组结尾多余的逗号
    s = re.sub(r",(\s*,)+", r",", s)
    s = re.sub(r",(\s*[}\]])", r"\1", s)
    # 2) 字符串里裸露的换行 / 制表符 / 双引号一律转义
    out, in_str, esc = [], False, False
    for i, ch in enumerate(s):
        if esc:
            out.append(ch); esc = False; continue
        if in_str and ch == "\\":
            out.append(ch); esc = True; continue
        if ch == '"':
            if not in_str:
                in_str = True; out.append(ch)
            elif _quote_closes(s, i):
                in_str = False; out.append(ch)
            else:
                out.append('\\"')  # 值里引用台词时常见的裸引号
            continue
        if in_str and ch == "\n":
            out.append("\\n"); continue
        if in_str and ch == "\t":
            out.append("\\t"); continue
        out.append(ch)
    return "".join(out)


def call_llm_json(system: str, user: str, key: str, timeout: int = 120,
                  expect_list: bool = True):
    """取 JSON：本地修复 → 仍失败则追加一次“只要合法 JSON”的重试。"""
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
