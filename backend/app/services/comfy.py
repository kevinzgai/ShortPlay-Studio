"""本地出图（H3 + SeedVR2 网关版）：提示词拼装、网关调用、批量任务与缩略。

设计要点：
  · 出图全部走本地网关（gwUrl，默认 127.0.0.1:8000）——网关有单线程队列，
    studio 不再直连 ComfyUI 抢显存；工作流模板只维护网关一份。
  · 走「提交即返回 jobId + 后台线程串行跑 + 前端轮询」，避免多张图把 HTTP 拖超时；
  · 原图落 examples/assets/，回给前端的是 512px JPEG 缩略 dataURI，
    直接复用 refImage / 撤销栈 / localStorage / zip 导出链路；
  · 网关地址由 engine_store.gw_url() 现读，界面改完立即生效。

旧直连实现（工作流注入 / 参考图上传 / history 轮询 / 下载）已删除，
由 app.services.gateway 承担；本文件保留提示词层与任务管理层。
"""

import base64
import io
import random
import re
import sys
import threading
import time

from app.config.engine_store import (gw_url, h3_image_model, h3_image_status,
                                     qwen_image_model, qwen_image_status)
from app.constants import STYLE_ANCHOR_EN_DEFAULT
from app.infra.coerce import _as, s
from app.paths import ROOT
from app.services import gateway
from app.services.minimax_image import h3_image_generate
from app.services.qwen_image import qwen_image_generate


STYLE_ANCHOR_EN_OBJECT = ("photorealistic, 35mm film grain, "
                          "cool desaturated color grade, no beautification filter")


PERSON_ONLY_TERMS = ("skin", "face", "portrait", "beauty", "hair", "eye",
                     "makeup", "hand", "finger", "body", "lip")


# 微距皮肤词只对「脸占画面大头」的变体有用。三视图是三个全身塞一张图，
# 每张脸几十像素，这时候 "visible pores / natural skin texture" 不是加分项
# 而是灾难：模型只能在指甲盖大的区域硬堆纹理，结果就是磨皮糊或者五官挤在一起。
SKIN_DETAIL_TERMS = ("pore", "pores", "skin texture", "blemish", "wrinkle",
                     "sweat", "micro detail", "subsurface")

FACE_CLOSE_VARIANTS = ("portrait", "faceSheet")


# --------------------------------------------------------------------------
# 角色身份一致性：H3-Image 的参考图通道（image_1..N）
# --------------------------------------------------------------------------
# 「三视图 / 面部四视图 / 定妆半身」原本是三张互不相干的文生图，三个独立随机种子
# 各自从零「想象」一个人，人脸必然不统一 —— 提示词写得再细也只能保证「同一类长相」，
# 保证不了同一张脸。H3-Image 本身是「生成 + 参考编辑」同一个 checkpoint：
# 接上 image_1..N 并按槽位顺序在提示词里称 Picture 1 / Picture 2，就能把一张脸的
# 身份钉死，其余变体都往上靠。
#
# 【锚点必须是脸最大的那张，不是最先出的那张】
# 三视图里每格脸只有 ~100px 高，用它当锚去生成 400px 的半身特写，源里根本没有
# 那么多细节可抄，模型只能自己编 —— 结果还是「三张图三张脸」，只是多绕了一圈。
# 所以锚的优先级按「脸在画面里的像素占比」排：定妆半身 > 面部四视图 > 三视图。
IDENTITY_ANCHOR_ORDER = ("portrait", "faceSheet", "turnaround")


# 参考图在提示词里的身份声明。
# 【<Picture 1> 的尖括号不是装饰，是身份传递的开关】2026-11-12 真机对照实验：
# 裸写 "Picture 1" 出来的三视图是黑发年轻人（身份完全丢失）——H3 的文本编码器
# 有专门的 <Picture n> 绑定 token，裸词不会被关联到参考图槽位，模型等于
# 「收到一张图但提示词从没提过它」，只能凭人设文字自由发挥。
# 加上尖括号后同一 seed 立刻出花白老人、同一张脸。编辑指令式措辞
# （"keep the person, change composition"）试过：身份保住了但三视图连版
# 直接不出了，所以保持「声明式 + 只抄人」的写法。
# 服装要抄：三视图的意义就是「同一人同一套衣服的三个角度」，旧版把
# clothing layout 也列进「别抄」清单，结果立领被画成翻领。改成服装显式照抄。
IDENTITY_REF_PREFIX = (
    "<Picture 1> is an identity reference of the same person. "
    "Reproduce that person exactly: same face (same bone structure, same eyes, nose, "
    "lips and jawline), same hairstyle and hairline, same age and body type, and the "
    "same outfit (same garment types, colors, collar style and fabric). Do not copy "
    "<Picture 1>'s framing, pose, camera angle or background — the person and the "
    "outfit carry over, the composition does not.\n"
)


ASSET_IMG_DIR = ROOT / "examples" / "assets"


ASSET_IMG_NAME = re.compile(r"^[A-Za-z0-9_.\-]+\.png$")


COMFY_VARIANTS = {
    "character": [
        # 【画幅 3:2 → 1:1 是脸崩的主因，不是措辞】
        # 1024×672 横版塞三个全身时，每格只有 341px 宽，头高约 40–50px。
        # 那个尺度上「眼尾微垂 / 唇薄 / 左颊一颗小痣」根本没有落脚像素，
        # 模型只有两条路：要么偷偷画成半身（实测确实如此，构图直接错），
        # 要么强制全身但把脸糊成一团。1152² 方形把每格做到 384×1152、
        # 头高约 100px，同 seed 下痣能画出来、正面与侧脸能认出是同一人。
        {"key": "turnaround", "label": "三视图", "w": 1152, "h": 1152,
         "tpl": "character turnaround reference sheet, three full-body views of the same "
                "woman side by side: front view, side view, back view. Standing straight, "
                "feet aligned on one baseline, equal scale, head to toe fully visible. "
                "Plain white seamless studio background, flat even light, no shadow, "
                "no props, no scenery.\n"
                "Consistent identity: the same one woman in all three views, identical "
                "face, identical hairstyle, identical outfit.\n"
                "{kw}\n"
                "face clearly in focus in the front and side views, correct facial "
                "proportions, sharp eyes, nose and mouth"},
        # 面部四视图 = 四张脸，不是「一张大脸 + 三个全身」。后者把特写和全身
        # 摆在同一张图上，两个尺度互相打架，模型只能把脸画糊；而它的职责本来
        # 就只有「把脸定准」，体型服装交给三视图。
        {"key": "faceSheet", "label": "面部四视图", "w": 1152, "h": 768,
         "tpl": "character face reference sheet, four head close-ups of the same woman in "
                "one row: front view, three-quarter view, side profile, slightly low angle. "
                "Head and shoulders only, bust framing, no full body.\n"
                "Consistent identity: identical face in all four, same hairstyle.\n"
                "{kw}\n"
                "plain white background, even soft light, sharp focus on eyes and mouth, "
                "natural skin texture, realistic film photography"},
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
# 模型架构：出图已全部走本地网关，网关只部署了 MiniMax H3-Image 一套模板，
# arch 概念收敛为固定值。常量与函数保留是因为 routes / diagnostics / 前端
# 都按旧口径读 arch 字段，接口形状不变、语义收紧。
# --------------------------------------------------------------------------
COMFY_ARCH_FLUX = "flux"
COMFY_ARCH_H3_IMAGE = "h3-image"
COMFY_ARCH_H3_VIDEO = "h3-video"

COMFY_ARCH_LABEL = {
    COMFY_ARCH_H3_IMAGE: "MiniMax H3-Image（本地网关）",
    COMFY_ARCH_FLUX: "Flux 文生图（已下线，统一走网关）",
    COMFY_ARCH_H3_VIDEO: "H3 视频（走网关 /v1/videos）",
}

COMFY_DEFAULT_STEPS = {COMFY_ARCH_H3_IMAGE: 6, COMFY_ARCH_FLUX: 4,
                       COMFY_ARCH_H3_VIDEO: 6}


def comfy_arch(unet=None):
    """网关模式下恒为 h3-image：网关只部署了 H3-Image 一条工作流。"""
    return COMFY_ARCH_H3_IMAGE


# --- 同一变体按架构给画幅（保留旧表；网关恒为 h3-image，走变体默认值） ---
VARIANT_SIZE_BY_ARCH = {
    ("turnaround", COMFY_ARCH_FLUX): (1024, 672),
    ("faceSheet", COMFY_ARCH_FLUX): (1024, 672),
}


def comfy_variant_size(v):
    """变体 + 当前架构 → (w, h)。前端 / 出图 / 提示词预览共用同一个口径。"""
    return VARIANT_SIZE_BY_ARCH.get((v["key"], comfy_arch()), (v["w"], v["h"]))


def comfy_arch_info(unet=None):
    """给前端的一句话说明：网关出图恒可用（H3-Image 6 步）。"""
    return {
        "arch": COMFY_ARCH_H3_IMAGE,
        "label": COMFY_ARCH_LABEL[COMFY_ARCH_H3_IMAGE],
        "usable": True, "steps": 6, "model": "MiniMax-H3-Image",
    }


def comfy_arch_error():
    """恒返回空串：网关模式下没有「选错模型」一说了（模型由网关管）。"""
    return ""


def comfy_missing_files():
    """兼容保留：文件齐不齐由网关 /health 兜底，这里恒返回空。"""
    return []


STATUS_OFFLINE_TTL = 3.0
_STATUS_OFFLINE_UNTIL = 0.0


def comfy_status():
    """探测本地网关（含 ComfyUI 可达性与显存）；离线负缓存策略不变。

    网关 /health 在加载模型时也不阻塞（返回 busy），比旧直连 /system_stats 更稳。
    字段与旧版兼容：前端 AssetPanel / EngineDiagnostics 读 online / version /
    vramFreeMB / arch；version 与 model 恒为空串（模型由网关管理）。
    """
    global _STATUS_OFFLINE_UNTIL
    if time.time() < _STATUS_OFFLINE_UNTIL:
        return {"online": False, "host": gw_url(),
                "detail": "刚探测失败（网关未启动），%.0f 秒后自动重试"
                          % max(0.0, _STATUS_OFFLINE_UNTIL - time.time()),
                "qwen": qwen_image_status(), "h3": h3_image_status()}
    try:
        h = gateway.gw_health()
        comfy = h.get("comfyui") or {}
        if not (bool(h.get("gateway")) and comfy.get("reachable", False)):
            raise RuntimeError("网关在，但 ComfyUI 不可达")
        return {
            "online": True, "host": gw_url(), "gateway": True,
            "version": "", "device": str(comfy.get("device", "")),
            "vramFreeMB": int(comfy.get("vram_free_mb") or 0),
            "queue": int(h.get("queue") or 0),
            "model": "", "arch": comfy_arch_info(),
            "qwen": qwen_image_status(), "h3": h3_image_status(),
            "variants": {k: [{"key": v["key"], "label": v["label"],
                              "w": comfy_variant_size(v)[0],
                              "h": comfy_variant_size(v)[1]}
                             for v in vs] for k, vs in COMFY_VARIANTS.items()},
        }
    except Exception as exc:
        _STATUS_OFFLINE_UNTIL = time.time() + STATUS_OFFLINE_TTL
        return {"online": False, "host": gw_url(), "detail": str(exc)[:160],
                "qwen": qwen_image_status(), "h3": h3_image_status()}


def _en_subject(text):
    """英文主体去掉多余冠词、首字母小写。

    模型常回 "A string of yellow paper coins"，模板是 "still life of a single {kw}"，
    直接拼就成 "a single A string of..." 的病句，Flux 对病句的解读会跑偏。
    """
    t = re.sub(r"^(a|an|the)\s+", "", (text or "").strip(), flags=re.I)
    return (t[:1].lower() + t[1:]) if t else t


def _strip_style_terms(src, terms, fallback):
    """按逗号分段剔除命中 terms 的段；以 no 开头的负向约束一律保留。"""
    kept = []
    for part in src.split(","):
        p = part.strip()
        if not p:
            continue
        low = p.lower()
        if low.startswith("no ") or not any(t in low for t in terms):
            kept.append(p)
    return ", ".join(kept) or fallback


def style_for_kind(style_en, kind, variant=""):
    """按资产类型 + 出图变体收风格锚：尺度越小的画面越要剥掉微距词。

    道具图里出现人手，根因之一就是通用风格锚里的 "natural skin texture"
    被无条件拼到了道具上 —— Flux 见到 skin 就画皮肤。
    三视图同理：脸只占几十像素时，皮肤纹理词会把原本就稀缺的像素预算
    全吃掉，逼得模型把小脸画成一团。
    """
    src = (style_en or "").strip() or STYLE_ANCHOR_EN_DEFAULT
    if kind == "character":
        if variant in FACE_CLOSE_VARIANTS:
            return src
        return _strip_style_terms(src, SKIN_DETAIL_TERMS, STYLE_ANCHOR_EN_DEFAULT)
    return _strip_style_terms(src, PERSON_ONLY_TERMS, STYLE_ANCHOR_EN_OBJECT)


def build_comfy_prompt(asset, variant_key, style_en="", with_ref=False):
    """资产字段 → 英文 Flux 提示词。缺英文关键词时明确标记，不让用户以为设定生效了。

    with_ref=True 表示这一张会接参考图，要在最前面声明「脸照 Picture 1 抄、
    构图别照抄」。身份声明必须放开头：H3 对长提示词的注意力是前重后轻，
    把它塞在末尾那一长串技术收尾词后面等于没说。
    """
    kind = _as(asset.get("kind"), "character", 16)
    vs = COMFY_VARIANTS.get(kind, COMFY_VARIANTS["character"])
    v = next((x for x in vs if x["key"] == variant_key), None)
    if not v:
        raise ValueError("未知出图类型：" + str(variant_key)[:40])
    if kind == "character":
        kw = _as(asset.get("keywordEn"), "", 400).strip()
        fallback = not kw
        if fallback:
            kw = _as(asset.get("keyword"), "", 200).strip() or \
                 ("a Chinese film character named " + _as(asset.get("name"), "unknown", 40))
    elif kind == "scene":
        kw = _as(asset.get("sceneEn"), "", 400).strip()
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
    style = style_for_kind(style_en, kind, variant_key)
    style_part = (", " + style) if len(style) < 240 else ""
    suffix = COMFY_SUFFIX_OBJECT if kind == "prop" else COMFY_SUFFIX
    w, h = comfy_variant_size(v)
    text = v["tpl"].format(kw=kw) + style_part + ", " + suffix
    return {"prompt": (IDENTITY_REF_PREFIX + text) if with_ref else text,
            # 无前缀版一直留着：万一批次里锚图读不出来，要能退回纯文生图，
            # 而不是带着「Picture 1」这句话去生成一张根本没有参考图的图。
            "promptBase": text,
            "w": w, "h": h, "label": v["label"], "fallbackEn": fallback}


def _identity_refs(kind, keys):
    """同一资产这一批里，谁出图、谁给谁当脸部锚。

    返回 (ordered, refs)：
      ordered —— 变体按「脸在画面里的占比」从大到小排，锚先出、跟跑的后出；
      refs    —— {变体: 锚变体}，第一个变体没有锚（它就是锚）。

    只有角色需要这条链：场景和道具的「同一性」靠文字描述就够，
    给道具接参考图反而会让它照抄参考图的构图与光位。
    """
    if kind != "character":
        return list(keys), {}
    rank = {k: i for i, k in enumerate(IDENTITY_ANCHOR_ORDER)}
    ordered = sorted(keys, key=lambda k: rank.get(k, len(IDENTITY_ANCHOR_ORDER)))
    refs = {}
    anchor = ""
    for vk in ordered:
        if anchor:
            refs[vk] = anchor
        else:
            anchor = vk
    return ordered, refs


def comfy_prompt_rows(assets, variants, style_en=""):
    """只跑拼装、不排队出图：界面拿它核对「本地实际会发什么」。

    以前资产面板展示的是 AI 写的中文提示词，而本地 Flux 吃的是这里另拼的英文串，
    同一份设定出现两个版本。统一从这一个函数取，复制走的和真正发出去的才是同一串。
    """
    rows = []
    # 预览必须和实际出图同口径：架构不是 H3-Image 就没有参考图通道，
    # 这时候还预览出带「Picture 1」的串，用户会以为参考图生效了。
    ref_ok = comfy_arch() == COMFY_ARCH_H3_IMAGE
    for a in assets[:24]:
        kind = _as(a.get("kind"), "character", 16)
        keys = [k for k in (variants.get(kind) or []) if isinstance(k, str)]
        has_own = bool(_as(a.get("refFile"), "", 200)) if ref_ok else False
        ordered, refs = _identity_refs(kind, keys)
        for vk in ordered[:4]:
            ref_of = ("own" if has_own else refs.get(vk, "")) if ref_ok else ""
            try:
                built = build_comfy_prompt(a, vk, style_en, bool(ref_of))
            except ValueError:
                continue
            rows.append({
                "assetId": _as(a.get("id"), "", 80),
                "assetName": _as(a.get("name"), "", 40),
                "variant": vk, "label": built["label"],
                "prompt": built["prompt"], "w": built["w"], "h": built["h"],
                "fallbackEn": built["fallbackEn"], "refOf": ref_of,
            })
    if not rows:
        raise ValueError("没有可预览的提示词：先选资产，再勾选至少一种素材类型")
    return {"rows": rows, "styleEn": _as(style_en, "", 240) or STYLE_ANCHOR_EN_DEFAULT}


_URI_CACHE = {}

_URI_LOCK = threading.Lock()


def comfy_ref_name(local_name):
    """本地资产图 → data URI（网关 /v1/images/edits 的 image_url 直接吃）。

    旧直连时代这里把 PNG 推进 ComfyUI 的 input/；改走网关后参考图以
    base64 塞进 JSON 即可，不再有上传步骤。进程内按文件名缓存：
    同一批里「三视图 + 四视图 + 半身」反复引用同一张锚图时只编码一次。
    """
    key = str(local_name or "").strip()
    if not key:
        return ""
    with _URI_LOCK:
        hit = _URI_CACHE.get(key)
    if hit:
        return hit
    # 只认 examples/assets/ 里的单层文件名，`../` 一律挡掉（与旧口径一致）。
    # 容错：调用方常把完整相对路径直接塞进来，剥一次头（拒绝不如收下）。
    if key.startswith("examples/assets/"):
        key = key[len("examples/assets/"):]
    if not ASSET_IMG_NAME.match(key) or "/" in key or "\\" in key:
        raise ValueError("参考图名不合法：%s" % key[:60])
    path = ASSET_IMG_DIR / key
    if not path.is_file():
        raise ValueError("参考图不在本地：%s" % key[:60])
    uri = gateway.image_to_data_uri(path.read_bytes())
    with _URI_LOCK:
        _URI_CACHE[key] = uri
    return uri


def _gw_png_from_data(d):
    """网关 edits 响应的一项（url / b64_json）→ PNG 原始字节。"""
    d = d or {}
    if d.get("b64_json"):
        return base64.b64decode(d["b64_json"])
    name = str(d.get("url") or "").rsplit("/", 1)[-1]
    if not name:
        raise RuntimeError("网关结果里没有图片地址：" + repr(d)[:120])
    return gateway.gw_image_bytes(name)


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
    # 参考图通道：网关 H3-Image 恒支持（官方 ref 语义）；云端两家的接口没接图。
    # 不支持时不能往提示词里塞「Picture 1」——那会让模型凭空描述一张不存在的参考图。
    ref_ok = engine == "comfy"
    plan = []
    for a in assets[:24]:
        kind = _as(a.get("kind"), "character", 16)
        keys = [k for k in (variants.get(kind) or []) if isinstance(k, str)]
        # 资产自带的主参考图（用户手选/上传/上一次出的）优先于本批锚变体：
        # 用户既然指定了「这张就是我认可的脸」，就不该被这一批的顺序覆盖
        own = _as(a.get("refFile"), "", 200) if ref_ok else ""
        ordered, refs = _identity_refs(kind, keys)
        for vk in ordered[:4]:
            ref_of = "" if own else refs.get(vk, "")
            try:
                built = build_comfy_prompt(a, vk, style_en, bool(ref_ok and (own or ref_of)))
            except ValueError:
                continue
            plan.append({
                "assetId": _as(a.get("id"), "", 80), "assetCode": _as(a.get("code"), "", 24),
                "assetName": _as(a.get("name"), "", 40), "kind": kind,
                "variant": vk, "variantLabel": built["label"],
                "prompt": built["prompt"], "promptBase": built["promptBase"],
                "w": built["w"], "h": built["h"],
                "fallbackEn": built["fallbackEn"], "n": seq_n,
                # 锚图来源：自有参考图 > 本批先出的变体。空串表示这一张纯文生图。
                "refFile": own, "refVariant": ref_of,
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
               "model": ("MiniMax-H3-Image（网关）" if engine == "comfy"
                         else qwen_image_model() if engine == "qwen" else h3_image_model())}
        COMFY_JOBS[jid] = job
        # 只保留最近 10 个任务，避免长时间运行内存堆积
        if len(COMFY_JOBS) > 10:
            for old in sorted(COMFY_JOBS, key=lambda k: COMFY_JOBS[k]["startedAt"])[:-10]:
                COMFY_JOBS.pop(old, None)
    threading.Thread(target=comfy_worker, args=(jid, plan, engine), daemon=True).start()
    return {"jobId": jid, "total": total_images, "status": "running", "engine": engine}


def _variant_label(kind, vk):
    for v in COMFY_VARIANTS.get(kind, []):
        if v["key"] == vk:
            return v["label"]
    return vk


def comfy_worker(jid, plan, engine="comfy"):
    ASSET_IMG_DIR.mkdir(parents=True, exist_ok=True)
    job = COMFY_JOBS.get(jid)
    # 本批已经出好的锚图：(assetId, variant) → 本地文件名。
    # 锚变体先出、跟跑的变体后出，靠 plan 的顺序保证，不额外调度。
    anchors = {}
    for t in plan:
        if not job or job.get("status") == "cancelled":
            break
        job["current"] = "%s · %s" % (t["assetName"], t["variantLabel"])
        t0 = time.time()
        n = max(1, int(t.get("n", 1)))
        prompt = t["promptBase"]
        refs = []
        ref_label = ""
        try:
            if engine == "comfy":
                src = t.get("refFile") or anchors.get(
                    (t["assetId"], t.get("refVariant") or ""), "")
                if src:
                    try:
                        refs = [comfy_ref_name(src)]
                    except Exception as exc:
                        # 锚图拿不到不能连累这一张：退回纯文生图照样出图，
                        # 只是这张的脸是重新想的，得在错误列表里说清楚
                        job["errors"].append({
                            "assetName": t["assetName"], "variantLabel": t["variantLabel"],
                            "detail": "参考图不可用，这张按纯文生图出（脸不会被统一）："
                                      + str(exc)[:150]})
                    else:
                        ref_label = "自有参考图" if t.get("refFile") else \
                            _variant_label(t["kind"], t.get("refVariant") or "")
            if refs:
                prompt = t["prompt"]
            if engine == "qwen":
                pngs = qwen_image_generate(t["prompt"], n)
            elif engine == "h3":
                pngs = h3_image_generate(t["prompt"], n)
            else:
                # 本地网关：有参考图走 /v1/images/edits（ref 语义，不传 denoise，
                # 与旧直连 PH3_IMAGE_EDIT 同口径；denoise 是 img2img 重绘，
                # 0.5~0.65 才保脸，会把提示词里的三视图构图冲掉，不适合批量定妆）。
                size = "%dx%d" % (t["w"], t["h"])
                if refs:
                    out = gateway.gw_i2i(prompt, refs, size=size,
                                         seed=t["seed"], n=n)
                    pngs = [_gw_png_from_data(d) for d in (out.get("data") or [])]
                else:
                    pngs = []
                    for k in range(n):
                        one = gateway.gw_t2i(prompt, t["w"], t["h"], steps=0,
                                             seed=t["seed"] + k)
                        pngs.append(gateway.gw_image_bytes(one["filename"]))
            for i, png in enumerate(pngs[:n]):
                variant = t["variant"] if len(pngs) == 1 else "%s_s%d" % (t["variant"], i + 1)
                label = (t["variantLabel"] if len(pngs) == 1
                         else "%s %d/%d" % (t["variantLabel"], i + 1, len(pngs)))
                safe = re.sub(r"[^A-Za-z0-9_\-]", "", t["assetCode"] or t["assetId"] or "asset")[:24]
                name = "%s_%s_%d.png" % (safe or "asset", variant, t["seed"] + i)
                (ASSET_IMG_DIR / name).write_bytes(png)
                if i == 0 and i < len(pngs):
                    anchors[(t["assetId"], t["variant"])] = name
                datauri, uncompressed = thumb_datauri(png)
                job["items"].append({
                    "assetId": t["assetId"], "assetCode": t["assetCode"],
                    "assetName": t["assetName"], "kind": t["kind"],
                    "variant": variant, "variantLabel": label,
                    "prompt": prompt, "w": t["w"], "h": t["h"], "seed": t["seed"] + i,
                    "fallbackEn": t["fallbackEn"], "uncompressed": uncompressed,
                    "file": "examples/assets/" + name, "dataUri": datauri,
                    "bytes": len(png), "seconds": round(time.time() - t0, 1),
                    "engine": engine, "refOf": ref_label,
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
    """阻塞式出图：提交本地网关 → 等结果 → 落盘 → 回 URL。

    纯文生图走 POST /v1/images/generations；ref_images 给了参考图
    （填本接口返回过的 filename）走 POST /v1/images/edits（官方 ref 语义，
    传 denoise 则是 img2img 重绘）。返回字段与旧版兼容：
        prompt_id / seed / status / elapsed / filename / url
    图片由本项目自己托管在 V1_IMAGE_URL_PREFIX 下，不依赖网关是否常驻。
    """
    if not isinstance(body, dict):
        raise ValueError("请求体要是 JSON 对象")
    prompt = str(body.get("prompt") or "").strip()[:4000]
    if not prompt:
        raise ValueError("prompt 不能为空")
    w = _v1_int(body.get("width"), 1024, 256, 2048, "width")
    h = _v1_int(body.get("height"), 1024, 256, 2048, "height")
    w -= w % 16
    h -= h % 16  # 网关要求 16 的整数倍；非对齐尺寸自动向下取整
    steps = _v1_int(body.get("steps"), 0, 0, 50, "steps")
    timeout = _v1_int(body.get("timeout"), 600, 30, 1800, "timeout")
    denoise = body.get("denoise")
    if denoise is not None:
        try:
            denoise = min(1.0, max(0.05, float(denoise)))
        except (TypeError, ValueError):
            raise ValueError("denoise 要在 0.05–1.0 之间")
    seed = body.get("seed")
    if seed is None:
        seed = random.randint(1, 2 ** 31 - 1)
    elif isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed 必须是整数")

    # ref_images：本地已出图的名字（就是本接口返回的 filename），用来做身份参考。
    # 有了它就能「先出定妆半身 → 再拿它出三视图」，不必一次把三张都排进批次。
    raw_refs = body.get("ref_images")
    if raw_refs is None:
        raw_refs = body.get("refs") or []
    if not isinstance(raw_refs, list):
        raise ValueError("ref_images 要是数组")
    if len(raw_refs) > 8:
        raise ValueError("ref_images 最多 8 张")
    refs = [comfy_ref_name(str(x or "").strip()) for x in raw_refs if str(x or "").strip()]

    t0 = time.time()
    size = "%dx%d" % (w, h)
    if refs:
        out = gateway.gw_i2i(prompt, refs, size=size, denoise=denoise,
                             seed=seed, timeout=timeout)
        png = _gw_png_from_data((out.get("data") or [{}])[0])
        steps_used = int(out.get("steps") or 6)
    else:
        out = gateway.gw_t2i(prompt, w, h, steps=steps, seed=seed, timeout=timeout)
        png = gateway.gw_image_bytes(out["filename"])
        steps_used = int(out.get("steps") or steps or 6)
    ASSET_IMG_DIR.mkdir(parents=True, exist_ok=True)
    # 12 位十六进制 + _00001_.png，与 Gateway 返回的文件名同款，天然满足
    # ASSET_IMG_NAME 白名单；不用网关的原始文件名，杜绝路径穿越。
    filename = "%012x_00001_.png" % random.getrandbits(48)
    (ASSET_IMG_DIR / filename).write_bytes(png)
    return {
        "prompt_id": out.get("prompt_id") or out.get("request_id") or "",
        "seed": seed, "status": "succeeded",
        "elapsed": round(time.time() - t0, 2),
        "steps": steps_used, "width": w, "height": h,
        "model": "MiniMax-H3-Image", "arch": COMFY_ARCH_H3_IMAGE,
        "refs": len(refs), "denoise": denoise,
        "filename": filename, "url": V1_IMAGE_URL_PREFIX + filename,
    }
