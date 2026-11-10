"""仓库路径。**这里必须是 parent.parent**：模块搬进 app/ 后 __file__ 变了，
若继续用 parent 会把 llm-providers.json / projects/ / dist/ 全部指向 app/ 内部，
而且不会报错，只会静默生成一个空目录——拆包最容易踩的一个坑。
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 前端是 Vue 3 + Vite 工程（独立仓库 shortplay-studio-web），构建产物在它的 dist/；
# 可用 SHORTPLAY_WEB_ROOT 覆盖。解析顺序：环境变量 → 兄弟仓 dist → 本仓 dist（老布局）→ 仓库根。
WEB_ROOT = Path(os.environ["SHORTPLAY_WEB_ROOT"]).expanduser() if os.environ.get("SHORTPLAY_WEB_ROOT") \
    else next((p for p in (
        ROOT.parent / "shortplay-studio-web" / "dist",
        ROOT / "dist",
    ) if (p / "index.html").exists()), ROOT)
PORT = int(os.environ.get("SHORTPLAY_PORT", "8177"))
