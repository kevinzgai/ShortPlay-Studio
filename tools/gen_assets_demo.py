#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用《鬼婚逃命》真跑一遍：剧本/小说 → 资产包 → 关键提示词 → 每镜起始帧提示词。

产物：
  examples/guihun-assets.json          资产包（机器可读，可直接喂前端 buildAssets 消费）
  examples/guihun-asset-prompts.md     三视图 / 概念图提示词（结构复刻《麻衣鬼相》文档）
  examples/guihun-first-frames.json    77 镜起始帧提示词（中文 + 英文 Flux 版）
  examples/guihun-first-frames.md      起始帧提示词样例
"""
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
# 直接引 app/ 下的实现模块，不要 `import server`：
# server.py 已是薄壳（只剩 from app.main import run），不再对外 re-export 业务符号。
# 这里原先靠 server.py 的命名空间顺带拿到这些函数，属于隐式依赖。
from app.constants import SYSTEM_ASSETS  # noqa: E402
from app.services.assets import build_asset_pack, build_frame_prompts  # noqa: E402
from app.services.llm_json import call_llm_json  # noqa: E402

SRC = ROOT / "examples" / "鬼婚逃命-AI转写剧本.txt"
STORYBOARD = ROOT / "examples" / "guihun-storyboard.json"
OUT = ROOT / "examples"


def parse_scenes(text):
    scenes, cur = [], None
    for line in text.splitlines():
        m = re.match(r"^第(\d+)场\s+(\S+)\s*·\s*(\S+)\s*·\s*(\S+)", line.strip())
        if m:
            cur = {"no": int(m.group(1)), "intExt": m.group(2),
                   "location": m.group(3), "time": m.group(4),
                   "characters": [], "lines": [], "actions": []}
            scenes.append(cur)
            continue
        if cur is None:
            continue
        t = line.strip()
        if not t:
            continue
        dm = re.match(r"^([^：:△\s]{1,10})(?:（[^）]*）)?\s*[：:]\s*(.+)$", t)
        if dm:
            name = re.sub(r"[（(].*?[）)]", "", dm.group(1)).strip()
            cur["lines"].append({"speaker": name or "旁白", "text": dm.group(2)})
            if name and name not in ("旁白", "画外音") and name not in cur["characters"]:
                cur["characters"].append(name)
        elif t.startswith("△"):
            cur["actions"].append({"text": t.lstrip("△ ")})
    return scenes


def render_assets_md(pack):
    a, st = pack["assets"], pack["style"]
    L = ["# 《鬼婚，逃命》· 资产包与关键提示词", "",
         "> 由 shortplay-studio 从剧本自动分解生成 · 模型 %s · %s" %
         (pack.get("model", ""), pack.get("generatedAt", "")),
         "> 全局风格锚：**%s**" % st["anchor"], "",
         "## 一、资产清单", "",
         "| 编号 | 资产名 | 类型 | 优先级 | 出场 | 来源 |",
         "|---|---|---|---|---|---|"]
    for c in a["characters"]:
        L.append("| %s | %s | 角色 | %s | %s | %s |" %
                 (c["code"], c["name"], c["priority"], c["visibility"], c["source"]))
    for s in a["scenes"]:
        L.append("| %s | %s | 场景 | %s | 第%s场 | %s |" %
                 (s["code"], s["name"], s["priority"],
                  "、".join(str(n) for n in s["sceneNos"]) or "未注明", s["source"]))
    for p in a["props"]:
        L.append("| %s | %s | 道具 | P1 | %s | %s |" %
                 (p["code"], p["name"], "、".join(p["boundTo"]) or "未绑定", p["source"]))
    L += ["", "## 二、角色一致性锚点（3 个怪特征 + 1 个服装记忆点）", "",
          "| 角色 | 锚点①脸 | 锚点②瑕疵 | 锚点③服装记忆点 | 固定关键词串 |",
          "|---|---|---|---|---|"]
    for c in a["characters"]:
        an = c["anchors"]
        L.append("| %s | %s | %s | %s | `%s` |" %
                 (c["name"], an["face"], an["flaw"], an["wardrobeHook"], c["keyword"]))
    L += ["", "## 三、角色三视图提示词", ""]
    for c in a["characters"]:
        L += ["### %s %s（%s）" % (c["code"], c["name"], c["priority"]), "",
              "```", c["prompts"]["turnaround"], "```", ""]
        if c.get("keywordEn"):
            L += ["英文版（本地 Flux）：`%s`" % c["keywordEn"], ""]
    L += ["", "## 四、场景概念图提示词", ""]
    for s in a["scenes"]:
        L += ["### %s %s（%s）" % (s["code"], s["name"], s["priority"]), "",
              "```", s["prompts"]["concept"], "```", ""]
        if s.get("sceneEn"):
            L += ["英文版（本地 Flux）：`%s`" % s["sceneEn"], ""]
    L += ["", "## 五、生成参数与工作流", "",
          "- 通用负面词：`%s`" % st["negative"],
          "- 画幅：三视图 3:2 / 立绘 3:4 / 概念图 16:9 / 核心场景 2.35:1",
          "- 推荐生成顺序：%s" % " → ".join(st["generationOrder"]),
          "- 四视图与线稿：对每个角色执行 `%s`，再执行 `转彩铅素描` 存档" %
          "生成参照人物面部特写和人物全身三视图",
          "- 一致性铁律：keyword 原样粘进每个镜头，不得重写；同类型角色三锚点不得雷同",
          "", "## 六、覆盖校验", "",
          "```json", json.dumps(pack["coverage"], ensure_ascii=False, indent=2), "```", ""]
    if pack["warnings"]:
        L += ["## 七、待人工核对", ""] + ["- " + w for w in pack["warnings"]] + [""]
    return "\n".join(L)


def render_frames_md(frames, stats):
    L = ["# 《鬼婚，逃命》· 分镜起始帧提示词", "",
         "> 共 %d 镜；带角色 %d 镜；带场景 %d 镜；平均 %d 字。" %
         (stats["total"], stats["withCharacters"], stats["withScene"],
          stats["avgPromptLength"]),
         "> 起始帧 = 该镜第 0 帧画面，可直接作为 i2v 首帧图；不是三视图、不是设定表。", ""]
    for f in frames[:3]:
        L += ["## %s（%s / %s）" % (f["code"], f["size"], f["aspect"]), "",
              "引用资产：%s" % ("、".join(f["refAssets"]) or "无"), "",
              "### 中文提示词（豆包 / 即梦）", "", "```", f["prompt"], "```", "",
              "### 英文提示词（本地 Flux）", "", "```", f["promptEn"], "```", ""]
    L += ["---", "", "其余 %d 镜见 `guihun-first-frames.json`。" %
          max(0, stats["total"] - 3), ""]
    return "\n".join(L)


def main():
    text = SRC.read_text(encoding="utf-8")
    scenes = parse_scenes(text)
    print("场次 %d 个：%s" %
          (len(scenes), " / ".join("S%d %s" % (s["no"], s["location"]) for s in scenes[:12])),
          flush=True)
    scene_list = "\n".join(
        "- 第%(no)d场 [S%(no)d] %(intExt)s %(location)s｜人物：%(cast)s｜画面线索：%(hints)s" % {
            "no": s["no"], "intExt": s["intExt"], "location": s["location"],
            "cast": "、".join(s["characters"]) or "未注明",
            "hints": "；".join(a["text"][:55] for a in s["actions"][:3]) or "无"}
        for s in scenes)
    user = ("场次清单（evidence 只能引用这里的 S 编号，sceneNos 只能填这里的场号）：\n%s\n\n"
            "剧本 / 小说全文：\n%s" % (scene_list, text[:26000]))

    t0 = time.time()
    data, model = call_llm_json(SYSTEM_ASSETS, user, "characters", 240)
    elapsed = time.time() - t0
    print("模型返回 %.1fs / %s" % (elapsed, model), flush=True)
    pack = build_asset_pack(data, scenes)
    pack["model"] = model
    pack["generatedAt"] = datetime.now().isoformat(timespec="seconds")
    pack["elapsedSeconds"] = round(elapsed, 1)

    (OUT / "guihun-assets.json").write_text(
        json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "guihun-asset-prompts.md").write_text(render_assets_md(pack), encoding="utf-8")

    sb = json.loads(STORYBOARD.read_text(encoding="utf-8"))
    shots = sb.get("shots") or []
    frames = build_frame_prompts(shots, pack, sb.get("config", {}).get("aspect", "9:16"))
    (OUT / "guihun-first-frames.json").write_text(
        json.dumps(frames, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "guihun-first-frames.md").write_text(
        render_frames_md(frames["frames"], frames["stats"]), encoding="utf-8")

    print("\n=== 覆盖 ===", flush=True)
    print(json.dumps(pack["coverage"], ensure_ascii=False, indent=2), flush=True)
    print("=== 起始帧 ===", flush=True)
    print(json.dumps(frames["stats"], ensure_ascii=False), flush=True)
    print("=== warnings (%d) ===" % len(pack["warnings"]), flush=True)
    for w in pack["warnings"]:
        print(" - " + w, flush=True)
    print("\n产物：guihun-assets.json / guihun-asset-prompts.md / "
          "guihun-first-frames.json / guihun-first-frames.md", flush=True)


if __name__ == "__main__":
    main()
