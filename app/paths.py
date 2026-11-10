"""仓库路径。**这里必须是 parent.parent**：模块搬进 app/ 后 __file__ 变了，
若继续用 parent 会把 llm-providers.json / projects/ / dist/ 全部指向 app/ 内部，
而且不会报错，只会静默生成一个空目录——拆包最容易踩的一个坑。
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 前端是 Vue 3 + Vite 工程，构建产物在 dist/；没有构建时回退到项目根便于排查
# 可用 SHORTPLAY_WEB_ROOT 覆盖（拆仓后前端产物在另一个仓库时用）
WEB_ROOT = Path(os.environ["SHORTPLAY_WEB_ROOT"]).expanduser() if os.environ.get("SHORTPLAY_WEB_ROOT") \
    else (ROOT / "dist" if (ROOT / "dist" / "index.html").exists() else ROOT)
PORT = int(os.environ.get("SHORTPLAY_PORT", "8177"))
