@echo off
chcp 936 >nul
title 分镜工场 ShortPlay Studio
cd /d "%~dp0"

if exist "llm-config.bat" call "llm-config.bat"

set "SHORTPLAY_PORT=8177"
set "PYTHONUTF8=1"

REM ---- 前端已拆独立仓 shortplay-studio-web（与本仓同级的兄弟目录）----
REM ---- 首次自动装依赖，每次启动重新构建，保证 dist 与源码一致 ----
set "WEB_REPO=%~dp0..\shortplay-studio-web"
if not exist "%WEB_REPO%\package.json" goto NO_NPM
where npm >nul 2>nul
if errorlevel 1 goto NO_NPM
if not exist "%WEB_REPO%\node_modules\vue" (
  echo   首次启动，正在安装前端依赖，请稍候...
  call npm install --prefix "%WEB_REPO%" --no-audit --no-fund
)
echo   正在构建前端 Vue 3 + Vite ...
call npm run build --prefix "%WEB_REPO%" --silent
if errorlevel 1 echo   [提示] 前端构建失败，将使用已有构建产物
goto CHECK_PY

:NO_NPM
echo   [提示] 未检测到 Node.js 或前端仓库不存在，使用已有构建产物

:CHECK_PY
where py >nul 2>nul
if not errorlevel 1 goto RUN_PY
where python >nul 2>nul
if not errorlevel 1 goto RUN_PYTHON

echo.
echo   [提示] 没找到 Python，AI 功能不可用。
echo   请安装 Python 3 之后再运行本脚本。
echo.
pause
exit /b 1

:RUN_PY
py server.py
goto END

:RUN_PYTHON
python server.py
goto END

:END
echo.
echo   服务已停止，按任意键关闭窗口。
pause >nul
