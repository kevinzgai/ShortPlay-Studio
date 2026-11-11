"""配置地基：从 llm-config.bat 载入环境变量。

**本模块在 import 时就执行 load_local_config()**，并由 app/config/__init__.py
先于 llm_store / engine_store 导入，保证读取配置时环境变量已经就位。
"""
import os
import re

from app.paths import ROOT


def load_local_config():
    f = ROOT / "llm-config.bat"
    if not f.exists():
        return
    try:
        text = f.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return
    for m in re.finditer(r'(?im)^\s*set\s+"?([A-Z0-9_]+)=([^"\r\n]*)"?\s*$', text):
        k, v = m.group(1).strip(), m.group(2).strip().strip('"')
        ok = (k.startswith("SHORTPLAY_LLM_") or k.startswith("SHORTPLAY_QWEN_IMAGE_")
              or k in ("SHORTPLAY_DASHSCOPE_API_KEY", "SHORTPLAY_COMFY", "SHORTPLAY_COMFY_MODEL"))
        if ok and v and not os.environ.get(k):
            os.environ[k] = v


load_local_config()
