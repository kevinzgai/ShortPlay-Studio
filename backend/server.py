#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ShortPlay Studio · 启动入口（薄壳，刻意不实现任何逻辑）。

双击 start.bat 时跑的就是这个文件：`py server.py`。

真正的服务在别处：
  app/main.py     HTTP 服务、静态托管、路由分发、启动横幅、listen backlog
  app/web/        接口路由表（GET / POST / Agent / SSE 四张）
  app/services/   业务实现（AI 调用、分镜、资产、出图、项目、导出）
  app/config/     配置读写（模型供应商、出图引擎）
  app/paths.py    路径、端口、前端产物目录

为什么只留这几行：入口一旦开始长逻辑，start.bat / 部署脚本 / 回归脚本就会各自
依赖不同的一层。压到「只剩一条 import」之后，换 FastAPI 时只需要改 app/main.py，
入口和启动方式完全不动。
"""
from app.main import run

if __name__ == "__main__":
    run()
