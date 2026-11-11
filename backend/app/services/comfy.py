"""本地 ComfyUI 出图：提示词拼装、工作流提交、轮询等待、下载与缩略。

设计要点：
  · 走「提交即返回 jobId + 后台线程串行跑 + 前端轮询」，避免多张图把 HTTP 拖超时；
  · 原图落 examples/assets/，回给前端的是 512px JPEG 缩略 dataURI，
    直接复用 refImage / 撤销栈 / localStorage / zip 导出链路；
  · 地址与 unet 名不是模块常量，由 comfy_host() / comfy_model() 现读，
    界面改完立即生效（换 Flux 版本不用改代码）。"""

import base64
import hashlib
import http.client
import io
import json
import random
import re
import sys
import threading
import time
import urllib.parse
import urllib.request

from app.config.engine_store import (comfy_host, comfy_model,
                                     h3_image_model, h3_image_status,
                                     qwen_image_model, qwen_image_status)
from app.constants import STYLE_ANCHOR_EN_DEFAULT
from app.infra.coerce import _as, s
from app.paths import ROOT
from app.services.minimax_image import h3_image_generate
from app.services.qwen_image import qwen_image_generate

# ComfyUI 一定在本机（127.0.0.1:8188），必须绕过代理。
# macOS 上 urllib 会读系统代理设置，且系统代理优先级高于 NO_PROXY 环境变量：
# 用户开了 Clash/Surge 之类工具时，连 127.0.0.1 的请求会被转到代理端口
# （实测被转到 127.0.0.1:18900 后 ECONNREFUSED），表现为出图全部失败，
# 而界面上状态灯却是绿的（状态探测同样失败时会被判成 offline，更难查）。
# 用空 ProxyHandler 明确声明「不走代理」，与是否设置环境变量无关。
_LOCAL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


STYLE_ANCHOR_EN_OBJECT = ("photorealistic, 35mm film grain, "
                          "cool desaturated color grade, no beautification filter")


PERSON_ONLY_TERMS = ("skin", "face", "portrait", "beauty", "hair", "eye",
                     "makeup", "hand", "finger", "body", "lip")


ASSET_IMG_DIR = ROOT / "examples" / "assets"


ASSET_IMG_NAME = re.compile(r"^[A-Za-z0-9_.\-]+\.png$")


COMFY_VARIANTS = {
    "character": [
        {"key": "turnaround", "label": "三视图", "w": 1024, "h": 672,
         "tpl": "character turnaround reference sheet, front view, side view, back view, "
                "full body, same person in all three, neutral gray studio background, "
                "flat even lighting, character design sheet, {kw}"},
        {"key": "faceSheet", "label": "面部四视图", "w": 1024, "h": 672,
         "tpl": "character face reference sheet, front view and three-quarter view close-ups, "
                "same person, consistent facial features, soft studio light, "
                "character design sheet, {kw}"},
        {"key": "portrait", "label": "定妆半身", "w": 768, "h": 1024,
         "tpl": "cinematic medium portrait of one Chinese character, {kw}, "
                "shallow depth of field, film still, natural skin texture, muted color grade"},
    ],
    "scene": [
        {"key": "concept", "label": "场景概念图", "w": 1152, "h": 640,
         "tpl": "environment concept art, {kw}, matte painting, cinematic composition, "
                "detailed architecture, atmospheric depth, no people, no text"},
        {"key": "wide", "label": "宽幕建立镜", "w": 1216, "h": 512,
         "tpl": "wide establishing shot, {kw}, anamorphic lens, cinematic lighting, "
                "film still, no people, no text"},
    ],
    "prop": [
        # 道具必须是「静物」语域：单写 product photography 会带上商品广告味，
        # 更关键的是原来没写 no people —— Flux 干脆自己塞一只手进来拿着它。
        {"key": "prop", "label": "道具静物", "w": 896, "h": 896,
         "tpl": "still life of a single {kw}, centered on a plain neutral gray backdrop, "
                "tabletop, soft directional studio light, macro detail, "
                "shallow depth of field, photorealistic product photography, "
                "no people, no human figure, no hands, no face, no text"},
    ],
}


COMFY_SUFFIX = "highly detailed, sharp focus, no text, no watermark"


COMFY_SUFFIX_OBJECT = ("highly detailed, sharp focus, no text, no watermark, "
                       "no people, no human figure, no hands")


# --------------------------------------------------------------------------
# 模型架构识别：同一个 ComfyUI 的 models/unet/ 里混着不同架构的模型，
# UNETLoader 不分架构全列出来，但工作流是完全不同的三套。
# --------------------------------------------------------------------------
COMFY_ARCH_FLUX = "flux"
COMFY_ARCH_H3_IMAGE = "h3-image"
COMFY_ARCH_H3_VIDEO = "h3-video"

COMFY_ARCH_LABEL = {
    COMFY_ARCH_FLUX: "Flux 文生图",
    COMFY_ARCH_H3_IMAGE: "MiniMax H3-Image",
    COMFY_ARCH_H3_VIDEO: "H3 视频（不能出静帧）",
}

# Flux-schnell 蒸馏过，4 步就够；H3-Image 官方口径是 6 步，少给了会糊。
COMFY_DEFAULT_STEPS = {COMFY_ARCH_FLUX: 4, COMFY_ARCH_H3_IMAGE: 6,
                       COMFY_ARCH_H3_VIDEO: 6}


def comfy_arch(unet=None):
    """按 unet 文件名判断走哪条工作流。不传就用当前 comfyModel。

    认名字而不是去 /object_info 查节点组合：文件名是稳定线索，而 object_info
    只能告诉你「这个 unet 存在」，告诉不了「它该配哪个 CLIP」。认不出来按
    flux 处理 —— 保持旧行为，不能让用户配了个自定义 Flux 微调就出不了图。
    """
    n = (unet if unet is not None else comfy_model() or "").lower()
    if "minimax_h3_image" in n:
        return COMFY_ARCH_H3_IMAGE
    if "minimax_h3" in n:      # fl2va 等：视频链路，出不了静帧
        return COMFY_ARCH_H3_VIDEO
    return COMFY_ARCH_FLUX


def comfy_arch_info(unet=None):
    """给前端的一句话说明：这个模型能不能用来出定妆 / 道具图。"""
    a = comfy_arch(unet)
    name = unet if unet is not None else comfy_model()
    return {
        "arch": a, "label": COMFY_ARCH_LABEL.get(a, a),
        "usable": a != COMFY_ARCH_H3_VIDEO,
        "steps": COMFY_DEFAULT_STEPS.get(a, 4),
        "model": name or "",
    }


def comfy_arch_error():
    """不可用模型的一句话原因（可用时返回空串）。

    同步接口、批量任务、测试连接三处**共用这一句**：同一个问题在三个地方
    说法不一致时，用户会以为是三个不同的毛病。
    """
    info = comfy_arch_info()
    if info["usable"]:
        return ""
    return ("当前 comfyModel 是视频模型（%s）：它走 fl2v 视频链路（含 audio VAE），"
            "出不了静帧。定妆 / 道具图请换成 flux1-schnell-fp8 或 minimax_h3_image"
            % info["model"])


def _object_options(node, field):
    """读 /object_info/<node> 里某输入字段的候选值。

    返回 None = 探测失败（连不上 / 节点不存在），**不要当成「文件缺失」**——
    否则 ComfyUI 没起来时诊断会报一堆假缺失。
    """
    try:
        with _LOCAL_OPENER.open(comfy_host() + "/object_info/" + node, timeout=6) as r:
            info = json.load(r)
        inp = ((info or {}).get(node) or {}).get("input") or {}
        spec = (inp.get("required") or {}).get(field) or (inp.get("optional") or {}).get(field)
        if isinstance(spec, list) and spec:
            head = spec[0]
            if isinstance(head, list):
                return [str(x) for x in head]
            if isinstance(head, dict):
                return [str(x) for x in (head.get("options") or [])]
        if isinstance(spec, dict):
            return [str(x) for x in (spec.get("options") or [])]
    except Exception:
        return None
    return []


def comfy_required_files():
    """当前架构的工作流要 ComfyUI 里真实存在哪些 clip / vae 文件。

    【为什么要单独查】「unet 存在」不等于「能跑」：H3-Image 要的是
    qwen3vl_32b（type=minimax）+ minimax_h3_image_vae，Flux 要 clip_l +
    t5xxl + ae。少一个，提交时报的是节点校验失败，界面只会显示「出图失败」，
    用户根本看不出是缺文件。测试连接时先查一遍，能把话说清楚。
    """
    if comfy_arch() == COMFY_ARCH_H3_IMAGE:
        return [("CLIPLoader", "clip_name", "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"),
                ("VAELoader", "vae_name", "minimax_h3_image_vae_fp16.safetensors")]
    return [("DualCLIPLoader", "clip_name1", "clip_l.safetensors"),
            ("DualCLIPLoader", "clip_name2", "t5xxl_fp8_e4m3fn_scaled.safetensors"),
            ("VAELoader", "vae_name", "ae.safetensors")]


def comfy_missing_files():
    """缺哪些依赖文件。空列表 = 齐了，或探测不到（探测不到不算缺）。"""
    missing = []
    for node, field, want in comfy_required_files():
        opts = _object_options(node, field)
        if opts and want not in opts:
            missing.append(want)
    return missing


def comfy_status():
    """探测本机 ComfyUI；不在线时前端把出图按钮置灰并给出明确原因。"""
    try:
        with _LOCAL_OPENER.open(comfy_host() + "/system_stats", timeout=4) as r:
            st = json.load(r)
        dev = (st.get("devices") or [{}])[0]
        return {
            "online": True, "host": comfy_host(),
            "version": ((st.get("system") or {}).get("comfyui_version") or ""),
            "device": dev.get("name", ""),
            "vramFreeMB": int(dev.get("vram_free", 0) / (1024 * 1024)),
            "model": comfy_model(),
            # 架构决定走哪条工作流；usable=false 时前端要把出图按钮置灰并说明原因
            "arch": comfy_arch_info(),
            "qwen": qwen_image_status(),
            "h3": h3_image_status(),
            "variants": {k: [{"key": v["key"], "label": v["label"], "w": v["w"], "h": v["h"]}
                             for v in vs] for k, vs in COMFY_VARIANTS.items()},
        }
    except Exception as exc:
        return {"online": False, "host": comfy_host(), "detail": str(exc)[:160],
                "qwen": qwen_image_status(), "h3": h3_image_status()}


def _en_subject(text):
    """英文主体去掉多余冠词、首字母小写。

    模型常回 "A string of yellow paper coins"，模板是 "still life of a single {kw}"，
    直接拼就成 "a single A string of..." 的病句，Flux 对病句的解读会跑偏。
    """
    t = re.sub(r"^(a|an|the)\s+", "", (text or "").strip(), flags=re.I)
    return (t[:1].lower() + t[1:]) if t else t


def style_for_kind(style_en, kind):
    """按资产类型收风格锚：物体剔掉人像词，全被剔光就退到物体锚。

    道具图里出现人手，根因之一就是通用风格锚里的 "natural skin texture"
    被无条件拼到了道具上 —— Flux 见到 skin 就画皮肤。
    """
    src = (style_en or "").strip() or STYLE_ANCHOR_EN_DEFAULT
    if kind == "character":
        return src
    kept = []
    for part in src.split(","):
        p = part.strip()
        if not p:
            continue
        low = p.lower()
        # 以 no 开头的负向约束（如 "no beautification filter"）保留
        if low.startswith("no ") or not any(t in low for t in PERSON_ONLY_TERMS):
            kept.append(p)
    return ", ".join(kept) or STYLE_ANCHOR_EN_OBJECT


def build_comfy_prompt(asset, variant_key, style_en=""):
    """资产字段 → 英文 Flux 提示词。缺英文关键词时明确标记，不让用户以为设定生效了。"""
    kind = _as(asset.get("kind"), "character", 16)
    vs = COMFY_VARIANTS.get(kind, COMFY_VARIANTS["character"])
    v = next((x for x in vs if x["key"] == variant_key), None)
    if not v:
        raise ValueError("未知出图类型：" + str(variant_key)[:40])
    if kind == "character":
        kw = _as(asset.get("keywordEn"), "", 300).strip()
        fallback = not kw
        if fallback:
            kw = _as(asset.get("keyword"), "", 200).strip() or \
                 ("a Chinese film character named " + _as(asset.get("name"), "unknown", 40))
    elif kind == "scene":
        kw = _as(asset.get("sceneEn"), "", 300).strip()
        fallback = not kw
        if fallback:
            kw = _as(asset.get("appearance"), "", 200).strip() or \
                 "an interior film set, cinematic lighting"
    else:
        # 道具的英文名单独存 propEn。以前拿 appearance 兜底，而 appearance 就等于中文名，
        # Flux 的 T5 几乎读不懂中文 —— 主体词等于没写，剩下全是人像风格词。
        kw = _as(asset.get("propEn"), "", 300).strip()
        fallback = not kw
        if kw:
            kw = _en_subject(kw)
        else:
            cn = _as(asset.get("appearance"), "", 200).strip() or _as(asset.get("name"), "", 40)
            # 中文反正读不懂，但「一个静物」这个英文语域必须给，至少不会画成人物
            kw = "inanimate prop object" + ((", " + cn) if cn else "")
    # 风格紧跟主体描述（权重高），技术收尾词放最后；没设风格时退到中性默认。
    # 逗号不能省：Flux 会把 "eyebrow photorealistic" 连读成一个怪词。
    style = style_for_kind(style_en, kind)
    style_part = (", " + style) if len(style) < 240 else ""
    suffix = COMFY_SUFFIX_OBJECT if kind == "prop" else COMFY_SUFFIX
    return {"prompt": v["tpl"].format(kw=kw) + style_part + ", " + suffix,
            "w": v["w"], "h": v["h"], "label": v["label"], "fallbackEn": fallback}


def comfy_prompt_rows(assets, variants, style_en=""):
    """只跑拼装、不排队出图：界面拿它核对「本地实际会发什么」。

    以前资产面板展示的是 AI 写的中文提示词，而本地 Flux 吃的是这里另拼的英文串，
    同一份设定出现两个版本。统一从这一个函数取，复制走的和真正发出去的才是同一串。
    """
    rows = []
    for a in assets[:24]:
        kind = _as(a.get("kind"), "character", 16)
        keys = [k for k in (variants.get(kind) or []) if isinstance(k, str)]
        for vk in keys[:4]:
            try:
                built = build_comfy_prompt(a, vk, style_en)
            except ValueError:
                continue
            rows.append({
                "assetId": _as(a.get("id"), "", 80),
                "assetName": _as(a.get("name"), "", 40),
                "variant": vk, "label": built["label"],
                "prompt": built["prompt"], "w": built["w"], "h": built["h"],
                "fallbackEn": built["fallbackEn"],
            })
    if not rows:
        raise ValueError("没有可预览的提示词：先选资产，再勾选至少一种素材类型")
    return {"rows": rows, "styleEn": _as(style_en, "", 240) or STYLE_ANCHOR_EN_DEFAULT}


def comfy_workflow(prompt, w, h, seed, steps=0):
    """按 comfyModel 的架构出对应工作流。steps=0 表示「用该架构的默认步数」。

    【为什么不再写死 Flux.1-schnell】
    `unet_name` 候选里一直混着三个模型，其中两个是 MiniMax H3 系（图像 / 视频），
    而旧实现只会拼 Flux 链路（DualCLIPLoader clip_l+t5xxl / FluxGuidance /
    EmptySD3LatentImage）。选了 minimax_h3_image 会一路 `mat1 and mat2 shapes
    cannot be multiplied (256x4096 and 5120x5376)` —— 因为 H3 的 CLIP 是
    qwen3vl_32b（5120 维），Flux 的 t5xxl 是 5376 维，接不上。
    现在按模型名分派：flux 走原链路，H3-Image 走 CLIPLoader(type=minimax) +
    MiniMaxH3ImageConditioning（该节点同时吐 conditioning 和 latent）。

    两条链路共用同一套参数（prompt / w / h / seed / steps），上游「资产 × 变体」
    的批量任务与 /v1/images 同步接口都不用关心用的是哪个架构。
    """
    arch = comfy_arch()
    n = int(steps) if steps else COMFY_DEFAULT_STEPS.get(arch, 4)
    if arch == COMFY_ARCH_H3_VIDEO:
        raise ValueError(comfy_arch_error())
    if arch == COMFY_ARCH_H3_IMAGE:
        return _workflow_h3_image(prompt, w, h, seed, n)
    return _workflow_flux(prompt, w, h, seed, n)


def _workflow_flux(prompt, w, h, seed, steps):
    """Flux.1-schnell fp8 / 4 步 / euler，与 tools/gen_first_frame.py 完全一致。"""
    return {
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": comfy_model(), "weight_dtype": "default"}},
        "2": {"class_type": "DualCLIPLoader",
              "inputs": {"clip_name1": "clip_l.safetensors",
                         "clip_name2": "t5xxl_fp8_e4m3fn_scaled.safetensors",
                         "type": "flux", "device": "default"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "4": {"class_type": "FluxGuidance", "inputs": {"conditioning": ["3", 0], "guidance": 0}},
        "5": {"class_type": "EmptySD3LatentImage",
              "inputs": {"width": w, "height": h, "batch_size": 1}},
        "6": {"class_type": "BasicScheduler",
              "inputs": {"model": ["1", 0], "scheduler": "simple", "steps": steps, "denoise": 1}},
        "7": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "8": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "9": {"class_type": "BasicGuider", "inputs": {"model": ["1", 0], "conditioning": ["4", 0]}},
        "10": {"class_type": "SamplerCustomAdvanced",
               "inputs": {"noise": ["8", 0], "guider": ["9", 0],
                          "sampler": ["7", 0], "sigmas": ["6", 0], "latent_image": ["5", 0]}},
        "11": {"class_type": "VAEDecode", "inputs": {"samples": ["10", 0], "vae": ["12", 0]}},
        "12": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
        "13": {"class_type": "SaveImage",
               "inputs": {"images": ["11", 0], "filename_prefix": "sp_asset"}},
    }


def _workflow_h3_image(prompt, w, h, seed, steps):
    """MiniMax H3-Image：CLIPLoader(type=minimax) + MiniMaxH3ImageConditioning。

    节点图逐字照抄本机 8000 网关（h3+seedvr2-gateway）的 /v1/images 工作流，
    连默认步数 6 和 filename_prefix 的 `apiimg/` 子目录都不改 —— 两边出的图
    要在同一条 ComfyUI 队列里排队、同一套 VAE，出图口径才可比。
    唯一区别：prefix 换成 sp_asset，别把我们的图和网关的产物混在一个目录里。
    """
    return {
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": comfy_model(), "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
                         "type": "minimax", "device": "default"}},
        "3": {"class_type": "VAELoader",
              "inputs": {"vae_name": "minimax_h3_image_vae_fp16.safetensors"}},
        # 这个节点一次吐两个东西：[0] conditioning 给 BasicGuider，[1] latent 给采样器
        "5": {"class_type": "MiniMaxH3ImageConditioning",
              "inputs": {"clip": ["2", 0], "vae": ["3", 0],
                         "prompt": prompt, "width": w, "height": h}},
        "6": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "7": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "8": {"class_type": "BasicScheduler",
              "inputs": {"model": ["1", 0], "scheduler": "simple",
                         "steps": steps, "denoise": 1.0}},
        "9": {"class_type": "BasicGuider",
              "inputs": {"model": ["1", 0], "conditioning": ["5", 0]}},
        "10": {"class_type": "SamplerCustomAdvanced",
               "inputs": {"noise": ["7", 0], "guider": ["9", 0], "sampler": ["6", 0],
                          "sigmas": ["8", 0], "latent_image": ["5", 1]}},
        "11": {"class_type": "VAEDecode", "inputs": {"samples": ["10", 0], "vae": ["3", 0]}},
        "12": {"class_type": "SaveImage",
               "inputs": {"images": ["11", 0], "filename_prefix": "sp_asset"}},
    }


def comfy_submit(prompt, w, h, seed, steps=0):
    """steps=0 交给 comfy_workflow 按架构取默认值（Flux 4 / H3-Image 6）。"""
    body = json.dumps({"prompt": comfy_workflow(prompt, w, h, seed, steps),
                       "client_id": "shortplay-assets"}).encode("utf-8")
    req = urllib.request.Request(comfy_host() + "/prompt", data=body,
                                 headers={"Content-Type": "application/json"})
    with _LOCAL_OPENER.open(req, timeout=30) as r:
        out = json.load(r)
    if out.get("node_errors"):
        raise RuntimeError("ComfyUI 工作流校验失败：" + json.dumps(out["node_errors"], ensure_ascii=False)[:220])
    return out["prompt_id"]


def comfy_wait(pid, timeout=300):
    t0 = time.time()
    while True:
        time.sleep(1.2)
        try:
            with _LOCAL_OPENER.open(comfy_host() + "/history/" + pid, timeout=20) as r:
                hist = json.load(r)
        except Exception:
            if time.time() - t0 > timeout:
                raise RuntimeError("等待 ComfyUI 出图超时（%ds）" % timeout)
            continue
        if pid in hist:
            h = hist[pid]
            st = h.get("status", {})
            if st.get("status_str") != "success":
                raise RuntimeError("ComfyUI 生成失败：" + json.dumps(st, ensure_ascii=False)[:300])
            imgs = []
            for _node, out in (h.get("outputs") or {}).items():
                imgs.extend(out.get("images") or [])
            return imgs
        if time.time() - t0 > timeout:
            raise RuntimeError("等待 ComfyUI 出图超时（%ds）" % timeout)


def comfy_download(info, attempts=2):
    """从 ComfyUI 取回生成的 PNG 原图。

    【为什么带重试】本机回环本该一跳直达，但实测偶发短读：
    Content-Length 说 620KB、实际只收到 480KB 连接就断了，`urlopen().read()`
    抛 `IncompleteRead(491520 bytes read, 128724 more expected)`，整张已经出好的图
    被丢掉，界面显示「出图失败」——用户只能重跑，白等十几秒 GPU。
    成因在 ComfyUI 侧（并发写盘 / 内存吃紧时提前关连接），不是我们的请求有问题；
    图已经落在它的 output/ 里，重取是幂等的，成本远低于重跑。

    只对「短读 / 连接被重置 / 读超时」重试；HTTPError（404 之类）不重试，那是真错。
    """
    q = urllib.parse.urlencode({"filename": info["filename"],
                                "subfolder": info.get("subfolder", ""),
                                "type": info.get("type", "output")})
    url = comfy_host() + "/view?" + q
    retryable = (http.client.HTTPException, ConnectionResetError, TimeoutError)
    last = None
    for i in range(max(1, attempts)):
        try:
            with _LOCAL_OPENER.open(url, timeout=60) as r:
                body = r.read()
                want = r.headers.get("Content-Length", "")
                # read() 少数情况下不抛而是静默短读，这里补一道长度校验
                if want.isdigit() and len(body) != int(want):
                    raise http.client.IncompleteRead(body, int(want) - len(body))
                return body
        except retryable as exc:
            last = exc
            if i + 1 < attempts:
                time.sleep(0.4 * (i + 1))
    raise last if last is not None else RuntimeError("图片下载失败")


def thumb_datauri(png):
    """原 PNG → 512px JPEG dataURI。Pillow 是可选加速，缺了也不能把出图结果弄丢。"""
    try:
        try:
            from PIL import Image
        except ImportError:
            # 服务被 start.bat / 托管进程拉起时，user site 可能没进 sys.path；
            # 本机 Pillow 就装在 user site，显式补一次再试（不引入运行时依赖）
            import site as _site
            p = _site.getusersitepackages()
            if isinstance(p, str) and p and p not in sys.path:
                sys.path.append(p)
            from PIL import Image
        im = Image.open(io.BytesIO(png)).convert("RGB")
        resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
        im.thumbnail((512, 512), resample)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=82, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii"), False
    except Exception:
        # 压缩不可用就回传原 PNG，前端会标记 uncompressed 并提示体积偏大
        return "data:image/png;base64," + base64.b64encode(png).decode("ascii"), True


COMFY_JOBS = {}


COMFY_LOCK = threading.Lock()


COMFY_SEQ = [0]


def comfy_job_start(assets, variants, style_en="", fixed_seed=0, engine="comfy", seq_n=1):
    """把「资产 × 变体」展开成串行任务，立即返回 jobId。

    engine=comfy 走本机 Flux；engine=qwen 走通义万相、engine=h3 走 MiniMax H3-Image，
    云端引擎 seq_n>1 时一次出一组图。
    """
    engine = engine if engine in ("comfy", "qwen", "h3") else "comfy"
    # 架构不对就别建任务：否则界面先返回 jobId、再让每张图各自失败，
    # 用户看到的是「N 张全失败」而不是「模型选错了」，白等一轮。
    if engine == "comfy":
        err = comfy_arch_error()
        if err:
            raise ValueError(err)
    seq_n = max(1, min(int(seq_n or 1), 4)) if engine in ("qwen", "h3") else 1
    plan = []
    for a in assets[:24]:
        kind = _as(a.get("kind"), "character", 16)
        keys = [k for k in (variants.get(kind) or []) if isinstance(k, str)]
        for vk in keys[:4]:
            try:
                built = build_comfy_prompt(a, vk, style_en)
            except ValueError:
                continue
            plan.append({
                "assetId": _as(a.get("id"), "", 80), "assetCode": _as(a.get("code"), "", 24),
                "assetName": _as(a.get("name"), "", 40), "kind": kind,
                "variant": vk, "variantLabel": built["label"],
                "prompt": built["prompt"], "w": built["w"], "h": built["h"],
                "fallbackEn": built["fallbackEn"], "n": seq_n,
                "seed": int(fixed_seed) or random.randint(1, 2 ** 31 - 1),
            })
    if not plan:
        raise ValueError("没有可生成的任务：先选资产，再勾选至少一种素材类型")
    total_images = len(plan) * seq_n
    if total_images > 24:
        raise ValueError("一次最多 24 张，分批生成（当前 %d 张）" % total_images)
    with COMFY_LOCK:
        COMFY_SEQ[0] += 1
        jid = "j%d_%d" % (int(time.time()), COMFY_SEQ[0])
        job = {"id": jid, "status": "running", "total": total_images, "done": 0,
               "current": "", "items": [], "errors": [], "startedAt": time.time(),
               "finishedAt": 0, "engine": engine,
               "model": (comfy_model() if engine == "comfy"
                         else qwen_image_model() if engine == "qwen" else h3_image_model())}
        COMFY_JOBS[jid] = job
        # 只保留最近 10 个任务，避免长时间运行内存堆积
        if len(COMFY_JOBS) > 10:
            for old in sorted(COMFY_JOBS, key=lambda k: COMFY_JOBS[k]["startedAt"])[:-10]:
                COMFY_JOBS.pop(old, None)
    threading.Thread(target=comfy_worker, args=(jid, plan, engine), daemon=True).start()
    return {"jobId": jid, "total": total_images, "status": "running", "engine": engine}


def comfy_worker(jid, plan, engine="comfy"):
    ASSET_IMG_DIR.mkdir(parents=True, exist_ok=True)
    job = COMFY_JOBS.get(jid)
    for t in plan:
        if not job or job.get("status") == "cancelled":
            break
        job["current"] = "%s · %s" % (t["assetName"], t["variantLabel"])
        t0 = time.time()
        n = max(1, int(t.get("n", 1)))
        try:
            if engine == "qwen":
                pngs = qwen_image_generate(t["prompt"], n)
            elif engine == "h3":
                pngs = h3_image_generate(t["prompt"], n)
            else:
                pid = comfy_submit(t["prompt"], t["w"], t["h"], t["seed"])
                imgs = comfy_wait(pid)
                if not imgs:
                    raise RuntimeError("ComfyUI 没有返回图片")
                pngs = [comfy_download(imgs[0])]
            for i, png in enumerate(pngs[:n]):
                variant = t["variant"] if len(pngs) == 1 else "%s_s%d" % (t["variant"], i + 1)
                label = (t["variantLabel"] if len(pngs) == 1
                         else "%s %d/%d" % (t["variantLabel"], i + 1, len(pngs)))
                safe = re.sub(r"[^A-Za-z0-9_\-]", "", t["assetCode"] or t["assetId"] or "asset")[:24]
                name = "%s_%s_%d.png" % (safe or "asset", variant, t["seed"] + i)
                (ASSET_IMG_DIR / name).write_bytes(png)
                datauri, uncompressed = thumb_datauri(png)
                job["items"].append({
                    "assetId": t["assetId"], "assetCode": t["assetCode"],
                    "assetName": t["assetName"], "kind": t["kind"],
                    "variant": variant, "variantLabel": label,
                    "prompt": t["prompt"], "w": t["w"], "h": t["h"], "seed": t["seed"] + i,
                    "fallbackEn": t["fallbackEn"], "uncompressed": uncompressed,
                    "file": "examples/assets/" + name, "dataUri": datauri,
                    "bytes": len(png), "seconds": round(time.time() - t0, 1),
                    "engine": engine,
                })
                job["done"] += 1
            if len(pngs) < n:
                job["done"] += n - len(pngs)
                job["errors"].append({"assetName": t["assetName"], "variantLabel": t["variantLabel"],
                                      "detail": "接口只返回 %d/%d 张" % (len(pngs), n)})
        except Exception as exc:
            job["errors"].append({"assetName": t["assetName"], "variantLabel": t["variantLabel"],
                                  "detail": str(exc)[:220]})
            job["done"] += n
    if job:
        job["status"] = "done" if job.get("status") != "cancelled" else "cancelled"
        job["current"] = ""
        job["finishedAt"] = time.time()


# --------------------------------------------------------------------------
# /v1/images 同步出图：一次请求 → 直接返回可打开的 PNG URL
# --------------------------------------------------------------------------
V1_IMAGE_URL_PREFIX = "/v1/images/file/"


def _v1_int(v, default, lo, hi, label):
    """只收整数；bool 是 int 的子类，必须单独挡掉，否则 True 会被当成 1。"""
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        raise ValueError("%s 必须是整数" % label)
    if not lo <= v <= hi:
        raise ValueError("%s 要在 %d–%d 之间" % (label, lo, hi))
    return v


def sync_image(body):
    """阻塞式文生图：提交 → 等 ComfyUI → 下载原图 → 落盘 → 回 URL。

    与 comfy_job_start() 的异步 job 并存，两条路共用 comfy_workflow()，
    所以「系统设置 · 出图引擎」里换的 comfyHost / comfyModel 对两边同时生效。
    界面批量出资产仍走异步 job（jobId + 轮询 + 缩略图 dataURI），互不影响。

    返回字段对齐本机 8000 的 H3 + SeedVR2 Gateway：
        prompt_id / seed / status / elapsed / filename / url
    差异：本接口恒同步（Gateway 的 wait=false + job 轮询不在这里实现），
    图片由本项目自己托管在 V1_IMAGE_URL_PREFIX 下，不依赖 8000 是否常驻。
    """
    if not isinstance(body, dict):
        raise ValueError("请求体要是 JSON 对象")
    prompt = str(body.get("prompt") or "").strip()[:4000]
    if not prompt:
        raise ValueError("prompt 不能为空")
    err = comfy_arch_error()
    if err:
        raise ValueError(err)
    w = _v1_int(body.get("width"), 1024, 256, 2048, "width")
    h = _v1_int(body.get("height"), 1024, 256, 2048, "height")
    # 0 = 不指定，按模型架构取默认（Flux 4 步 / H3-Image 6 步），
    # 避免调用方为了「默认值」还得知道后端挂的是哪个模型。
    steps = _v1_int(body.get("steps"), 0, 0, 50, "steps")
    timeout = _v1_int(body.get("timeout"), 600, 30, 1800, "timeout")
    seed = body.get("seed")
    if seed is None:
        seed = random.randint(1, 2 ** 31 - 1)
    elif isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed 必须是整数")

    t0 = time.time()
    pid = comfy_submit(prompt, w, h, seed, steps)
    imgs = comfy_wait(pid, timeout=timeout)
    if not imgs:
        raise RuntimeError("ComfyUI 没有返回图片")
    png = comfy_download(imgs[0])
    ASSET_IMG_DIR.mkdir(parents=True, exist_ok=True)
    # 12 位十六进制 + _00001_.png，与 Gateway 返回的文件名同款，天然满足
    # ASSET_IMG_NAME 白名单；不用 ComfyUI 的原始文件名，杜绝路径穿越。
    filename = "%012x_00001_.png" % random.getrandbits(48)
    (ASSET_IMG_DIR / filename).write_bytes(png)
    info = comfy_arch_info()
    return {
        "prompt_id": pid, "seed": seed, "status": "succeeded",
        "elapsed": round(time.time() - t0, 2),
        # 实际用的步数与模型都回传：换过架构后排查「为什么 6 步还是糊」不用猜
        "steps": int(steps) if steps else COMFY_DEFAULT_STEPS.get(info["arch"], 4),
        "width": w, "height": h, "model": info["model"], "arch": info["arch"],
        "filename": filename, "url": V1_IMAGE_URL_PREFIX + filename,
    }
