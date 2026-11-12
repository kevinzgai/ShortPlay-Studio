# start_studio.ps1 — 一键拉起 shortplay-studio 后端（8177），进程脱离当前会话
#
# 用法：
#   .\start_studio.ps1            启动（已在跑会跳过）
#   .\start_studio.ps1 -Status    看状态
#   .\start_studio.ps1 -Stop      停止
#
# 为什么用 WMI 而不是 Start-Process：
#   Start-Process 起的是子进程，父会话退出时会被一起回收。
#   Win32_Process.Create 创建的是独立进程，父进程是谁都不影响它存活。

param(
    [switch]$Stop,
    [switch]$Status
)

$ErrorActionPreference = 'Stop'

# 本机代理（Clash 5924）会让 127.0.0.1 的请求走回环失败，直连最省事。
[System.Net.WebRequest]::DefaultWebProxy = New-Object System.Net.WebProxy

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Py   = 'py'                       # py launcher 默认 3.14（依赖已系统级装齐）
$Log  = Join-Path $Root 'backend\server.out.log'

function Get-PortPid([int]$Port) {
    $c = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
         Select-Object -First 1
    if ($c) { return $c.OwningProcess }
    return $null
}

if ($Status) {
    $pid8177 = Get-PortPid 8177
    $gw = Get-PortPid 8000
    "8177 studio : " + $(if ($pid8177) { "RUNNING (pid $pid8177)" } else { "STOPPED" })
    "8000 gateway: " + $(if ($gw) { "RUNNING (pid $gw)" } else { "STOPPED（先跑 comfyui-h3-demo 的 start_all.ps1）" })
    return
}

if ($Stop) {
    $p = Get-PortPid 8177
    if ($p) { Stop-Process -Id $p -Force -Confirm:$false; "stopped pid $p" }
    else { "8177 没在跑" }
    return
}

$p = Get-PortPid 8177
if ($p) { "8177 已在跑（pid $p），跳过启动"; return }

# 清掉代理环境变量（大小写并存会触发 Start-Process/WMI 环境块异常的坑）
Remove-Item Env:HTTP_PROXY -ErrorAction SilentlyContinue
Remove-Item Env:HTTPS_PROXY -ErrorAction SilentlyContinue
Remove-Item Env:http_proxy -ErrorAction SilentlyContinue
Remove-Item Env:https_proxy -ErrorAction SilentlyContinue
Remove-Item Env:NO_PROXY -ErrorAction SilentlyContinue
Remove-Item Env:no_proxy -ErrorAction SilentlyContinue

# WMI 脱离会话启动；cmd /c 保证 py 能在 PATH 里找到
$cmd = "cmd /c cd /d `"$Root\backend`" && $Py server.py --no-browser >> `"$Log`" 2>&1"
$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $cmd }

if ($r.ReturnValue -ne 0) { throw "WMI 启动失败，ReturnValue=$($r.ReturnValue)" }

# 等端口就绪（最长 30s）
for ($i = 0; $i -lt 15; $i++) {
    Start-Sleep 2
    if (Get-PortPid 8177) { break }
}

if (Get-PortPid 8177) {
    "studio 8177 已启动，日志: $Log"
} else {
    throw "8177 没起来，看日志: $Log"
}
