"""图片字节与 dataURL 的通用处理。

被 projects（存参考图）与 export_zip（打包导出）共用，所以下沉到 infra，
避免两个 services 互相 import 形成环。纯转换，不碰项目状态。"""

import base64
import re
import sys

def _pil_image():
    """Pillow 只是可选的加速件：拿不到就返回 None，调用方自己退化。"""
    try:
        from PIL import Image
        return Image
    except ImportError:
        pass
    try:
        # 服务被 start.bat / 托管进程拉起时，user site 可能没进 sys.path
        import site as _site
        p = _site.getusersitepackages()
        if isinstance(p, str) and p and p not in sys.path:
            sys.path.append(p)
        from PIL import Image
        return Image
    except Exception:
        return None


REF_MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "webp": "image/webp", "gif": "image/gif", "bmp": "image/bmp",
            "avif": "image/avif"}


def _decode_data_url(data):
    """data:image/png;base64,xxx → (bytes, ext)；不认识的返回 (b"", "")。"""
    m = re.match(r"^data:image/(png|jpeg|jpg|webp|gif|bmp|avif);base64,([A-Za-z0-9+/=\s]+)$",
                 str(data or "").strip(), re.I)
    if not m:
        return b"", ""
    ext = {"jpeg": "jpg", "jpg": "jpg"}.get(m.group(1).lower(), m.group(1).lower())
    try:
        return base64.b64decode(m.group(2)), ext
    except Exception:
        return b"", ""
