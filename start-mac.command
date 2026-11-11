#!/bin/bash
# ShortPlay Studio · macOS 一键启动（可直接双击，也可在终端 ./start-mac.command）
#
# 固化两个 Mac 上踩过的坑：
#   1. 本机存在 127.0.0.1:7877 代理时，不带 NO_PROXY 启动会让 /api/comfy/status 报 502。
#   2. WideWired / 任意 VPN 的虚拟 IP（如 172.30.242.10）在 macOS 上「本机连自己」
#      会被 NEPacketTunnelProvider 送进 utun 隧道，必然超时。不能当本机地址用：
#      本机固定走 127.0.0.1；虚拟 IP 只给组网里「其他设备」访问用。
#
# 可选环境变量：
#   SHORTPLAY_PORT=8187   换端口
#   SHORTPLAY_NO_OPEN=1   不自动打开浏览器（远程终端 / 自动化用）
#
# 前端（2026-11-11 合仓）：Vue 源码在本仓 frontend/，构建产物落到 backend/dist/，
# 服务端 WEB_ROOT 默认就指向它（可用 SHORTPLAY_WEB_ROOT 覆盖）。
# 本脚本不构建前端，直接用已有的 dist 产物。要重新构建：
#   npm run build        # 等价 cd frontend && npm run build

set -u
cd "$(dirname "$0")" || exit 1

PORT="${SHORTPLAY_PORT:-8177}"
export SHORTPLAY_PORT="$PORT"
export PYTHONUTF8=1
export NO_PROXY="127.0.0.1,localhost${NO_PROXY:+,${NO_PROXY}}"
export no_proxy="$NO_PROXY"

LOCAL_URL="http://127.0.0.1:${PORT}/"
SERVER_PID=""

cleanup() {
  if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null
    wait "$SERVER_PID" 2>/dev/null
  fi
}
trap cleanup EXIT INT TERM

# 只认「首页确实是分镜工场」，避免端口被别的服务占了还误报已就绪
ready() {
  curl -fsS --connect-timeout 1 --max-time 2 "$LOCAL_URL" 2>/dev/null | grep -q "分镜工场"
}

if ready; then
  echo "[OK] 端口 ${PORT} 上已有分镜工场在运行，跳过启动。"
else
  if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "[失败] 端口 ${PORT} 已被其他进程占用："
    lsof -nP -iTCP:"$PORT" -sTCP:LISTEN
    echo "       若是旧版 8177 服务，先停掉它再运行本脚本。"
    exit 1
  fi

  echo "正在启动分镜工场（端口 ${PORT}）..."
  # LangChain 接入（2026-11-11）：后端改走 .venv（requirements.txt 只 2 个依赖）。
  # venv 缺失/损坏时自动引导创建；仍失败则回退系统 python3（AI 调用功能退化但服务能起）。
  PY_BIN="backend/.venv/bin/python"
  if ! "$PY_BIN" -c "import langchain_openai" >/dev/null 2>&1; then
    echo "  首次启动：正在创建 Python 虚拟环境并安装依赖（约 1-2 分钟）..."
    python3 -m venv backend/.venv || echo "  [提示] venv 创建失败，回退系统 Python（AI 调用不可用）"
    if [ -x "$PY_BIN" ]; then
      "$PY_BIN" -m pip install --quiet --disable-pip-version-check -r backend/requirements.txt \
        || echo "  [提示] 依赖安装失败，回退系统 Python（AI 调用不可用）"
    fi
  fi
  if ! "$PY_BIN" -c "import langchain_openai" >/dev/null 2>&1; then
    PY_BIN="python3"
    echo "  [提示] 使用系统 Python 启动（无 LangChain 依赖，AI 调用不可用）"
  fi
  "$PY_BIN" backend/server.py --no-browser &
  SERVER_PID=$!

  ok=0
  for _ in $(seq 1 40); do
    if ready; then ok=1; break; fi
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
      echo "[失败] 服务进程提前退出，请看上方的 Python 报错。"
      exit 1
    fi
    sleep 0.25
  done
  if [ "$ok" -ne 1 ]; then
    echo "[失败] 服务启动超时（10s），未通过首页自检。"
    exit 1
  fi
fi

lan_ip() {
  python3 -c 'import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    s.connect(("8.8.8.8", 80)); print(s.getsockname()[0])
except OSError:
    pass
finally:
    s.close()' 2>/dev/null
}

# 抓 utun 隧道上的第一个非回环 IPv4（WideWired 等组网工具分配的虚拟 IP）
vpn_ip() {
  ifconfig 2>/dev/null | awk '
    /^utun[0-9]+:/ { iface = $1; sub(/:$/, "", iface); next }
    /^[ \t]*inet / && iface ~ /^utun/ {
      for (i = 1; i <= NF; i++)
        if ($i == "inet" && $(i+1) !~ /^127\./) { print $(i+1); exit }
    }'
}

LAN="$(lan_ip)"
VPN="$(vpn_ip)"

echo ""
echo "============================================================"
echo "  分镜工场 · 已就绪"
echo "------------------------------------------------------------"
echo "  本机（这台 Mac）      ${LOCAL_URL}   <= 用这个"
[ -n "$LAN" ] && echo "  同一 WiFi 的其他设备  http://${LAN}:${PORT}/"
if [ -n "$VPN" ]; then
  echo "  组网/WideWired 设备   http://${VPN}:${PORT}/  （只在那台设备上打开）"
  echo ""
  echo "  [注意] 本机浏览器不要填 http://${VPN}:${PORT}/"
  echo "         macOS 会把发往自身虚拟 IP 的包送进 utun 隧道，"
  echo "         结果一定是超时，跟服务有没有起来无关。"
fi
echo "------------------------------------------------------------"
echo "  停止服务：Ctrl+C，或关掉这个终端窗口"
echo "============================================================"
echo ""

if [ "${SHORTPLAY_NO_OPEN:-0}" != "1" ]; then
  open "$LOCAL_URL" 2>/dev/null || true
fi

if [ -n "$SERVER_PID" ]; then
  wait "$SERVER_PID"
else
  echo "服务由已有进程提供，本窗口可关闭。"
fi
