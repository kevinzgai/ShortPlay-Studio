"""整项目打包导出。

原则与 build_asset_pack 同一条：模型只出结构，这里的正文全部由模板渲染。
参考图兼容两代存档：老项目是 dataURL，新项目是 /api/projects/ref 存盘地址。"""

import datetime as _dt
import hashlib
import io
import json
import re
import zipfile

from app.infra.coerce import _as
from app.infra.image import _decode_data_url
from app.services.assets import merge_pack_assets
from app.services.projects import project_ref_read
from app.services.render import (asset_prompts_payload, render_assets_csv,
                                 render_assets_md)

def _ref_bytes(ref):
    """参考图取值：老项目是 dataURL，新项目是一个存盘地址。→ (bytes, ext)"""
    data = str(ref or "").strip()
    m = re.match(r"^/api/projects/ref\?id=([A-Za-z0-9_-]+)&f=([A-Za-z0-9]+\.[a-z0-9]+)$", data)
    if m:
        try:
            raw, _mime = project_ref_read(m.group(1), m.group(2))
        except ValueError:
            return b"", ""
        return raw, m.group(2).rsplit(".", 1)[-1].lower()
    return _decode_data_url(data)


def build_export_zip(payload):
    """把资产包 + 分镜 + 剧本 + 参考图打成一个 zip。文本由前端渲染，资产正文由这里渲染。"""
    title = _as(payload.get("title"), "短剧", 60)
    safe = re.sub(r'[\\/:*?"<>|\s]+', "_", title) or "shortplay"
    stamp = _as(payload.get("stamp"), _dt.datetime.now().strftime("%Y%m%d"), 12)
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    meta.setdefault("title", title)
    pack = merge_pack_assets(payload.get("pack") or {}, payload.get("assets") or {})

    buf = io.BytesIO()
    written = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        def put(name, text):
            z.writestr(name, str(text).encode("utf-8"))
            written.append(name)

        # 前端已经渲染好的文本（剧本 / 分镜表 / 视频提示词 …）
        for f in (payload.get("files") or []):
            if not isinstance(f, dict):
                continue
            name = _as(f.get("name"), "", 160).replace("..", "_")
            if not name:
                continue
            put(name, f.get("text") or "")

        # 资产三件套：正文在服务端渲染，保证与参考文档结构一致
        put("assets/assets.json", json.dumps(pack, ensure_ascii=False, indent=2))
        put("assets/assets.md", render_assets_md(pack, meta))
        put("assets/assets.csv", render_assets_csv(pack))
        put("assets/asset-prompts.json",
            json.dumps(asset_prompts_payload(pack, meta), ensure_ascii=False, indent=2))

        # 参考图：原文件直接进 zip（不压缩），单张上限 24MB，超了跳过并记账
        skipped = []
        for i, r in enumerate(payload.get("refs") or []):
            if not isinstance(r, dict):
                continue
            raw, ext = _ref_bytes(r.get("data"))
            if not raw:
                continue
            if len(raw) > 24 * 1024 * 1024:
                skipped.append(_as(r.get("name"), "ref-%d" % i, 60))
                continue
            name = _as(r.get("name"), "ref-%02d.%s" % (i + 1, ext or "png"), 80)
            if not name.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".avif")):
                name += "." + (ext or "png")
            path = "assets/refs/" + re.sub(r'[\\/:*?"<>|]+', "_", name)
            z.writestr(path, raw)
            written.append(path)

        manifest = {
            "title": title, "stamp": stamp,
            "generatedAt": _dt.datetime.now().isoformat(timespec="seconds"),
            "model": meta.get("model") or "", "mode": meta.get("mode") or "",
            "stats": payload.get("stats") or {},
            "coverage": pack.get("coverage") or {},
            "warnings": pack.get("warnings") or [],
            "skippedRefs": skipped,
            "files": written,
        }
        put("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

        lines = [
            "《%s》资产与分镜导出包" % title,
            "=" * 40,
            "生成时间：%s" % _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "大模型：%s" % (meta.get("model") or "离线规则引擎"),
            "",
            "目录说明",
            "  assets/assets.md            资产包正文（清单/锚点/三视图/概念图/参数/校验），可直接粘进豆包、即梦",
            "  assets/assets.csv           同一份数据的人工核对表（Excel 可直接打开）",
            "  assets/asset-prompts.json   机器可读的提示词清单，供批量出图脚本消费",
            "  assets/assets.json          完整资产包（含每个资产的提示词与溯源字段）",
            "  assets/refs/                已挂上的参考图",
            "  script/                     剧本原文与 AI 转写稿",
            "  storyboard/                 分镜表（csv / md / txt / json）与每镜起始帧提示词",
            "  video/video-prompts.json    出片提示词（含 preflight 预检结果）",
            "",
            "下面这几条是这套资产包的使用规矩，别跳：",
            "  1. 角色的「固定关键词串」在每个镜头里原样粘贴，禁止重写 —— 一致性全靠它。",
            "  2. 先出 P0 角色的三视图定基准，再铺其他角色，最后补群演。",
            "  3. AI 推断项的 assets.md 里标了来源，出图前请人工过一遍。",
            "  4. 双图输入（线稿 + 色彩参考）当前出片端不支持，只能压成单张参考图。",
            "",
        ]
        if skipped:
            lines.append("以下参考图超过 24MB 未打包（原图太大，压缩后再挂会失真，故跳过）：%s"
                         % "、".join(skipped))
        put("README.txt", "\n".join(lines))

    return buf.getvalue(), "%s_资产与分镜_%s.zip" % (safe, stamp)
