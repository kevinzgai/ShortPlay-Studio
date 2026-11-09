#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Toonflow MCP 直连探针（WorkBuddy 尚未 Trust 该 MCP 时的备用通道）。

用法:
    py scripts/mcp_call.py <toolName> [json_args]

示例:
    py scripts/mcp_call.py getAppState
    py scripts/mcp_call.py getCanvas '{"include":["nodeTypes"]}'
    py scripts/mcp_call.py listAppOperations '{"args":{}}'

自动从 data/settings.json 读取 Bearer token，不打印密钥。
"""
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS = os.path.join(
    ROOT, "toonflow", "Toonflow-app-master", "data", "settings.json"
)
TOKEN = json.load(open(SETTINGS, encoding="utf-8"))["settings"]["mcp"]["token"]
ENDPOINT = "http://127.0.0.1:10588/mcp"
BASE = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "Authorization": "Bearer " + TOKEN,
}


def request(method, params, session=""):
    headers = dict(BASE)
    if session:
        headers["mcp-session-id"] = session
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(ENDPOINT, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.headers.get("mcp-session-id") or session, r.read().decode(errors="replace")


def parse(raw):
    if "data: " in raw:
        raw = raw.split("data: ", 1)[-1]
    return json.loads(raw)


def main():
    tool = sys.argv[1]
    args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    sid, _ = request(
        "initialize",
        {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "workbuddy-probe", "version": "1"},
        },
    )
    request("notifications/initialized", {}, sid)
    _, raw = request("tools/call", {"name": tool, "arguments": args}, sid)
    result = parse(raw)
    if "error" in result:
        print(json.dumps(result["error"], ensure_ascii=False, indent=2))
        return
    for c in result.get("result", {}).get("content", []):
        print(c.get("text", json.dumps(c, ensure_ascii=False)))


if __name__ == "__main__":
    main()
