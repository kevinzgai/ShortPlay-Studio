"""项目落盘：一个项目 = projects/<id>/project.json。

为什么放本机磁盘而不是 localStorage：生成几张素材图就能把 5MB 配额撑爆，
写失败后刷新页面就「项目没了」——这是原来丢数据的根因。

删除一律走软删（移到 projects/.trash/），手滑还能捞回来。"""

import datetime as _dt
import hashlib
import io
import json
import os
import random
import re
import threading
import time

from app.infra.coerce import _as
from app.infra.image import REF_MIME, _decode_data_url, _pil_image
from app.paths import ROOT

PROJECTS_DIR = ROOT / "projects"


PROJECT_TRASH_DIR = PROJECTS_DIR / ".trash"


PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")


PROJECT_LOCK = threading.Lock()


PROJECT_MAX_BYTES = 64 * 1024 * 1024     # 单项目上限，防止异常请求把磁盘写满


def _project_now():
    return _dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _project_path(pid):
    if not PROJECT_ID_RE.match(str(pid or "")):
        raise ValueError("非法项目 id")
    return PROJECTS_DIR / pid / "project.json"


PROJECT_REF_MAX_BYTES = 24 * 1024 * 1024    # 单张参考图上限（存原文件，不压缩）


PROJECT_REF_NAME_RE = re.compile(r"^[A-Za-z0-9]{8,40}\.(png|jpg|jpeg|webp|gif|bmp|avif)$")


PROJECT_REF_URL_RE = re.compile(r"/api/projects/ref\?id=[A-Za-z0-9_-]+&f=([A-Za-z0-9]+\.[a-z0-9]+)")


def _project_ref_dir(pid):
    return PROJECTS_DIR / pid / "refs"


def project_ref_save(payload):
    """上传的参考图落盘存原文件，返回一个 URL。

    以前参考图会被前端压成 512px JPEG 再塞进 project.json 的 dataURI —— 画质有损，
    而且 base64 会把项目文件撑大。现在原图按内容哈希存到 projects/<id>/refs/，
    项目里只留一个 URL：画质不动，project.json 也不再随图片膨胀。
    """
    pid = str(payload.get("id") or "").strip()
    if not PROJECT_ID_RE.match(pid) or not (PROJECTS_DIR / pid).is_dir():
        raise ValueError("项目不存在或已被删除")
    raw, ext = _decode_data_url(payload.get("data"))
    if not raw:
        raise ValueError("这不是一张能识别的图片（支持 png / jpg / webp / gif / bmp / avif）")
    if len(raw) > PROJECT_REF_MAX_BYTES:
        raise ValueError("图片超过 24MB，换一张小一点的")
    d = _project_ref_dir(pid)
    d.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha1(raw).hexdigest()[:20] + "." + ext
    f = d / name
    if not f.is_file():                      # 同一张图重复上传只留一份
        tmp = d / (name + ".tmp")
        tmp.write_bytes(raw)
        os.replace(tmp, f)
    return {"ok": True, "file": name, "bytes": len(raw), "ext": ext,
            "originalName": _as(payload.get("name"), "", 120),
            "url": "/api/projects/ref?id=" + pid + "&f=" + name}


def project_ref_read(pid, name):
    pid = str(pid or "")
    name = str(name or "")
    if not PROJECT_ID_RE.match(pid) or not PROJECT_REF_NAME_RE.match(name):
        raise ValueError("非法图片路径")
    f = _project_ref_dir(pid) / name
    if not f.is_file():
        raise ValueError("图片不存在")
    return f.read_bytes(), REF_MIME.get(name.rsplit(".", 1)[-1].lower(), "application/octet-stream")


def project_ref_thumb(pid, name, raw, width):
    """按宽度要一张缩略图（缓存到 refs/.thumb/），拿不到 Pillow 就返回 None。

    原图是几千万像素的照片，列表里 22px 的缩略图没必要解码整张 —— 那会白吃几百 MB
    内存。缩略图只用于界面显示，落盘的原图一点不动，下载 / 打包拿到的还是原图。
    """
    try:
        w = int(str(width or "0"))
    except (TypeError, ValueError):
        return None
    if w < 16 or w > 640:
        return None
    d = _project_ref_dir(pid) / ".thumb"
    f = d / ("%s_w%d.jpg" % (name.rsplit(".", 1)[0], w))
    if f.is_file():
        try:
            return f.read_bytes()
        except OSError:
            return None
    Image = _pil_image()
    if Image is None:
        return None
    try:
        im = Image.open(io.BytesIO(raw))
        im = im.convert("RGB")
        im.thumbnail((w, w), getattr(getattr(Image, "Resampling", Image), "LANCZOS"))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=82, optimize=True)
        out = buf.getvalue()
        d.mkdir(parents=True, exist_ok=True)
        (d / f.name).write_bytes(out)
        return out
    except Exception:
        return None


def _sweep_project_refs(pid, doc):
    """删掉项目里已经没人引用的参考图（换图 / 删资产留下的孤儿）。

    刚写入不足 1 小时的文件不动：上传和保存是两次请求，中间那一小段时间
    文件还没被 project.json 引用，扫掉就把用户刚传的图删了。
    """
    d = _project_ref_dir(pid)
    if not d.is_dir():
        return
    try:
        keep = set(PROJECT_REF_URL_RE.findall(json.dumps(doc, ensure_ascii=False)))
    except (TypeError, ValueError):
        return
    now = time.time()
    for f in d.iterdir():
        if not f.is_file() or f.name in keep:
            continue
        try:
            if now - f.stat().st_mtime < 3600:
                continue
            f.unlink()
        except OSError:
            pass


def _project_summary(pid, doc):
    """列表只回摘要，不回整份 data——否则项目一多，列表接口就变成几 MB。"""
    data = doc.get("data") if isinstance(doc.get("data"), dict) else {}
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    assets = data.get("assets") if isinstance(data.get("assets"), dict) else {}
    return {
        "id": doc.get("id") or pid,
        "name": doc.get("name") or "未命名项目",
        "createdAt": doc.get("createdAt") or "",
        "updatedAt": doc.get("updatedAt") or "",
        "step": int(data.get("step") or 1),
        "shots": len(data.get("shots") or []),
        "episodes": len(data.get("episodes") or []),
        "scriptChars": len(data.get("script") or ""),
        "title": (meta.get("title") or "")[:80],
        "assets": sum(len(assets.get(k) or []) for k in ("characters", "scenes", "props")),
        "genImages": sum(len(a.get("genImages") or [])
                         for k in ("characters", "scenes", "props")
                         for a in (assets.get(k) or []) if isinstance(a, dict)),
    }


def project_list():
    items = []
    if PROJECTS_DIR.is_dir():
        for d in PROJECTS_DIR.iterdir():
            if not d.is_dir() or d.name.startswith(".") or not PROJECT_ID_RE.match(d.name):
                continue
            f = d / "project.json"
            if not f.is_file():
                continue
            try:
                doc = json.loads(f.read_text("utf-8"))
            except Exception:
                continue          # 单个项目损坏不影响整个列表
            items.append(_project_summary(d.name, doc))
    items.sort(key=lambda x: x.get("updatedAt") or "", reverse=True)
    return items


def project_get(pid):
    f = _project_path(pid)
    if not f.is_file():
        raise ValueError("项目不存在或已被删除")
    try:
        doc = json.loads(f.read_text("utf-8"))
    except Exception as exc:
        raise ValueError("项目文件损坏：" + str(exc)[:120])
    return doc


def _project_write(pid, doc):
    d = PROJECTS_DIR / pid
    d.mkdir(parents=True, exist_ok=True)
    body = json.dumps(doc, ensure_ascii=False).encode("utf-8")
    if len(body) > PROJECT_MAX_BYTES:
        raise ValueError("项目太大（%.1f MB），请先清掉一些生成图"
                         % (len(body) / 1024 / 1024))
    f = d / "project.json"
    tmp = d / "project.json.tmp"
    tmp.write_bytes(body)
    os.replace(tmp, f)        # 原子替换：写到一半断电/崩溃不会留下半份项目
    _sweep_project_refs(pid, doc)
    return len(body)


def project_save(payload):
    pid = str(payload.get("id") or "").strip()
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("缺少项目数据")
    if not PROJECT_ID_RE.match(pid):
        raise ValueError("非法项目 id")
    name = _as(payload.get("name") or data.get("name"), "未命名项目", 80)
    with PROJECT_LOCK:
        f = _project_path(pid)
        created = _project_now()
        if f.is_file():
            try:
                created = json.loads(f.read_text("utf-8")).get("createdAt") or created
            except Exception:
                pass
        now = _project_now()
        doc = {"id": pid, "name": name, "createdAt": created,
               "updatedAt": now, "schema": 2, "data": data}
        size = _project_write(pid, doc)
    return {"ok": True, "id": pid, "name": name, "createdAt": created,
            "updatedAt": now, "bytes": size, "summary": _project_summary(pid, doc)}


def project_create(payload):
    name = _as(payload.get("name"), "未命名项目", 80)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    now = _dt.datetime.now()
    pid = "p_%s_%04x" % (now.strftime("%Y%m%d_%H%M%S"), random.randint(0, 0xffff))
    with PROJECT_LOCK:
        doc = {"id": pid, "name": name, "createdAt": _project_now(),
               "updatedAt": _project_now(), "schema": 2, "data": data}
        _project_write(pid, doc)
    return {"ok": True, "project": {"id": pid, "name": name, "createdAt": doc["createdAt"],
                                    "updatedAt": doc["updatedAt"], "data": data}}


def project_rename(payload):
    pid = str(payload.get("id") or "").strip()
    name = _as(payload.get("name"), "", 80)
    if not name:
        raise ValueError("项目名不能为空")
    with PROJECT_LOCK:
        f = _project_path(pid)
        if not f.is_file():
            raise ValueError("项目不存在")
        try:
            doc = json.loads(f.read_text("utf-8"))
        except Exception as exc:
            raise ValueError("项目文件损坏：" + str(exc)[:120])
        doc["name"] = name
        doc["updatedAt"] = _project_now()
        _project_write(pid, doc)
    return {"ok": True, "id": pid, "name": name, "updatedAt": doc["updatedAt"]}


def project_duplicate(payload):
    pid = str(payload.get("id") or "").strip()
    src = project_get(pid)
    now = _dt.datetime.now()
    nid = "p_%s_%04x" % (now.strftime("%Y%m%d_%H%M%S"), random.randint(0, 0xffff))
    with PROJECT_LOCK:
        # 参考图存的是 .../ref?id=<项目>&f=<文件>，副本得指向自己的目录，
        # 否则一改原项目的图，副本跟着变；删了原项目，副本全是裂图。
        data = json.loads(json.dumps(src.get("data") or {}, ensure_ascii=False)
                          .replace("/api/projects/ref?id=" + pid + "&",
                                   "/api/projects/ref?id=" + nid + "&"))
        doc = {"id": nid, "name": (_as(src.get("name"), "未命名项目", 70) + " 副本")[:80],
               "createdAt": _project_now(), "updatedAt": _project_now(), "schema": 2,
               "data": data}
        _project_write(nid, doc)
        srcdir, dstdir = _project_ref_dir(pid), _project_ref_dir(nid)
        if srcdir.is_dir():
            dstdir.mkdir(parents=True, exist_ok=True)
            for f in srcdir.iterdir():
                if f.is_file() and PROJECT_REF_NAME_RE.match(f.name):
                    (dstdir / f.name).write_bytes(f.read_bytes())
    return {"ok": True, "id": nid, "summary": _project_summary(nid, doc)}


def project_delete(payload):
    """不真删：移到 projects/.trash/，手滑还能捞回来。"""
    pid = str(payload.get("id") or "").strip()
    d = PROJECTS_DIR / pid
    if not PROJECT_ID_RE.match(pid) or not d.is_dir():
        raise ValueError("项目不存在")
    with PROJECT_LOCK:
        PROJECT_TRASH_DIR.mkdir(parents=True, exist_ok=True)
        target = PROJECT_TRASH_DIR / (pid + "_" + _dt.datetime.now().strftime("%Y%m%d_%H%M%S"))
        os.replace(d, target)
    return {"ok": True, "id": pid, "trashedTo": str(target.name)}
