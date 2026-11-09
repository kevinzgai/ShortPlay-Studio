#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""画布把关快照（只读）。用法: py scripts/check_canvas.py
一次输出：节点配置 / 连线 / 生成任务状态 / 本地成片归档情况 / 风险提示。
"""
import glob
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mcp_call as m

W = os.path.join(m.ROOT, "toonflow", "Toonflow-app-master", "data", "workspaces", "鬼新娘")


def main():
    sid, _ = m.request("initialize", {
        "protocolVersion": "2025-03-26", "capabilities": {},
        "clientInfo": {"name": "workbuddy-audit", "version": "1"},
    })
    m.request("notifications/initialized", {}, sid)

    def call(name, args):
        _, raw = m.request("tools/call", {"name": name, "arguments": args}, sid)
        obj = m.parse(raw)
        if "error" in obj:
            return {"_error": obj["error"]}
        txt = obj["result"]["content"][0]["text"]
        try:
            return json.loads(txt)
        except Exception:
            return {"_text": txt}

    found = call("findCanvasNodes", {"args": {"limit": 100}})["nodes"]
    meta = {n["id"]: n for n in found}
    edges = call("getCanvasEdges", {"args": {"limit": 200}})["edges"]
    indeg, sources = {}, {}
    for e in edges:
        indeg[e["target"]] = indeg.get(e["target"], 0) + 1
        sources.setdefault(e["target"], []).append(meta.get(e["source"], {}).get("label", "?"))

    nodes = []
    for i in range(0, len(found), 20):
        batch = [n["id"] for n in found[i:i + 20]]
        nodes += call("getCanvasNodes", {
            "args": {"nodeIds": batch, "fields": ["data", "outputs", "ports"]}
        })["nodes"]

    print("画布:", call("getAppState", {}).get("canvasId") or "画布1.json", "| 节点", len(found), "| 连线", len(edges))
    print("-" * 128)
    print("%-24s %-10s %-11s %-9s %-11s %-9s %s" % ("标签", "类型", "供应商/模型", "时长/分辨", "比例/音频", "任务", "入边"))
    print("-" * 128)
    risks = []
    for n in nodes:
        d, nid = n["data"], n["id"]
        label = d.get("label", "?")
        typ = meta.get(nid, {}).get("type", "?").replace("remote-", "")
        try:
            pm = json.loads(d.get("model") or "[]")
        except Exception:
            pm = []
        pv = "/".join(pm)[:11] if isinstance(pm, list) else str(pm)[:11]
        task = d.get("mediaTask") or {}
        state = task.get("state", "-")
        if task.get("providerId"):
            state += "@" + task["providerId"][:8]
        conf = "%s/%s" % (d.get("duration", "-"), d.get("resolution") or d.get("size", "-"))
        rr = "%s/%s" % (d.get("ratio", "-"), str(d.get("generateAudio", "-"))[:1])
        print("%-24s %-10s %-11s %-9s %-11s %-9s %d %s" % (
            label[:24], typ[:10], pv, conf[:9], rr[:11], state[:9],
            indeg.get(nid, 0), ",".join(sources.get(nid, []))[:28]))

        if "video" in typ.lower() and "generation" in typ.lower():
            s = call("nodeTools", {"args": {"nodeId": nid, "name": "node:getGenerationStatus", "args": {}}})
            out = (s.get("outputs") or {}).get("video", {}).get("value", {}).get("url", "")
            print("     实时状态: %-10s 输出: %s" % (s.get("status", "?"), out.split("/")[-1] if out else "无"))
            if s.get("status") == "running" and out:
                risks.append("「%s」仍在 running，outputs 里的 mp4 是上一段的残留，不能当本段成片" % label)
            folder = os.path.join(W, "assets", nid)
            files = sorted(glob.glob(os.path.join(folder, "*.mp4")))
            if len(files) > 1:
                print("     本地成片 %d 个: %s" % (len(files), ", ".join(
                    "%s(%s)" % (os.path.basename(f)[5:13], time.strftime("%H:%M", time.localtime(os.path.getmtime(f))))
                    for f in files)))
                risks.append("「%s」目录已堆 %d 个 mp4，逐段生成必须另存归档成 S01..S15，否则最后无法按序拼接" % (label, len(files)))
            if indeg.get(nid, 0) == 0:
                risks.append("「%s」无任何入边 = 纯文生视频，角色定妆图没接进来，跨段长相会漂" % label)
        if state and ("failed" in state or "interrupted" in state):
            risks.append("「%s」残留 %s 任务，建议清理或重试" % (label, state))
        if d.get("workflowText") and '"frame_load_cap": 0' in d["workflowText"]:
            risks.append("「%s」超分工作流 frame_load_cap=0（整片载入），长片会 OOM" % label)

    print("\n=== 把关提示 ===")
    for r in dict.fromkeys(risks):
        print(" -", r)
    if not risks:
        print(" - 无")


if __name__ == "__main__":
    main()
