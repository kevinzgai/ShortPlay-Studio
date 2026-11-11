"""MiniMax H3-Image 生图（同步接口，OpenAI images 兼容格式）。

只负责「给提示词 → 拿回 PNG 字节」，落盘与缩略图交给调用方（与 qwen_image 同口径）。
响应既可能是 {"data":[{"url":...}]}，也可能是 {"data":[{"b64_json":...}]}；
MiniMax 自有错误结构是 {"base_resp":{"status_code":..,"status_msg":..}}，一并带出来。
"""

import base64
import json
import re
import urllib.request

from app.config.engine_store import (h3_image_key, h3_image_model,
                                     h3_image_size, h3_image_url)

# 官方示例尺寸是 "2720x1536"（宽x高，小写 x）；兜底回默认，不让脏配置炸接口
_SIZE_RE = re.compile(r"^\d{3,4}x\d{3,4}$")


def h3_image_generate(prompt, n=1, size="", timeout=300):
    """同步调生图接口 → 下载所有图片 → 返回 PNG bytes 列表。"""
    key = h3_image_key()
    if not key:
        raise RuntimeError("未配置 MiniMax API Key")
    n = max(1, min(int(n or 1), 4))
    sz = str(size or h3_image_size()).strip()
    if not _SIZE_RE.match(sz):
        sz = h3_image_size()
    body = {
        "model": h3_image_model(),
        "prompt": str(prompt or "")[:4000],
        "size": sz,
        "n": n,
        "response_format": "url",
    }
    req = urllib.request.Request(
        h3_image_url(), data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.load(r)
    # MiniMax 业务错误不走 HTTP 状态码，走 base_resp.status_code（0 = 成功）
    br = out.get("base_resp") or {}
    if br.get("status_code") not in (None, 0):
        raise RuntimeError("MiniMax 生图失败：%s" % (br.get("status_msg") or str(br))[:180])
    data = out.get("data") if isinstance(out.get("data"), list) else []
    if not data:
        raise RuntimeError("MiniMax 没返回图片：" + str(out)[:180])
    from app.services.qwen_image import _to_png
    imgs = []
    for item in data:
        if not isinstance(item, dict):
            continue
        url = item.get("url") or ""
        b64 = item.get("b64_json") or ""
        if url:
            with urllib.request.urlopen(url, timeout=120) as ir:
                imgs.append(_to_png(ir.read()))
        elif b64:
            imgs.append(_to_png(base64.b64decode(b64)))
    if not imgs:
        raise RuntimeError("MiniMax 返回的数据里没有可用图片")
    return imgs[:n]
