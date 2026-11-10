"""通义万相组图（同步接口）。

只负责「给提示词 → 拿回 PNG 字节」，落盘与缩略图交给调用方。
Pillow 是可选加速件：拿不到就退化，转换失败时抛明确中文原因。"""

import base64
import io
import json
import re
import sys
import urllib.request

from app.config.engine_store import (qwen_image_key, qwen_image_model,
                                     qwen_image_size, qwen_image_url)

def _to_png(raw):
    """统一落盘为 PNG：实测端点返回 PNG，非 PNG 时用可选 Pillow 转一次。"""
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return raw
    try:
        try:
            from PIL import Image
        except ImportError:
            import site as _site
            p = _site.getusersitepackages()
            if isinstance(p, str) and p and p not in sys.path:
                sys.path.append(p)
            from PIL import Image
        im = Image.open(io.BytesIO(raw)).convert("RGB")
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        return buf.getvalue()
    except Exception as exc:
        raise RuntimeError("通义万相返回的图片不是 PNG，且转换失败：" + str(exc)[:120])


def qwen_image_generate(prompt, n=1, size="", timeout=300):
    """同步调组图接口 → 下载所有图片 → 返回 PNG bytes 列表。

    实测响应：output.choices[0].message.content[] 每项是 {"type":"image","image":"https://..."}；
    也兼容 {"image":{"url":...}} 与 data URI。API 报错时把 message/code 带出来。
    """
    key = qwen_image_key()
    if not key:
        raise RuntimeError("未配置通义万相 API Key")
    n = max(1, min(int(n or 1), 4))
    sz = str(size or qwen_image_size()).strip()
    if not re.match(r"^(1K|2K|4K|[0-9]{3,4}\*[0-9]{3,4})$", sz, re.I):
        sz = qwen_image_size()
    body = {
        "model": qwen_image_model(),
        "input": {"messages": [
            {"role": "user", "content": [{"text": str(prompt or "")[:4000]}]}
        ]},
        "parameters": {"enable_sequential": n > 1, "n": n, "size": sz},
    }
    req = urllib.request.Request(
        qwen_image_url(), data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.load(r)
    urls = []
    for ch in ((out.get("output") or {}).get("choices") or []):
        for c in ((ch.get("message") or {}).get("content") or []):
            if not isinstance(c, dict):
                continue
            v = c.get("image")
            if isinstance(v, str) and v:
                urls.append(v)
            elif isinstance(v, dict):
                u = v.get("url") or v.get("image") or ""
                if u:
                    urls.append(u)
    if not urls:
        why = out.get("message") or out.get("code") or out.get("error") or str(out)[:180]
        raise RuntimeError("通义万相没返回图片：" + str(why)[:180])
    imgs = []
    for u in urls[:n]:
        if u.startswith("data:"):
            imgs.append(_to_png(base64.b64decode(u.split(",", 1)[-1])))
        else:
            with urllib.request.urlopen(u, timeout=120) as r:
                imgs.append(_to_png(r.read()))
    return imgs
