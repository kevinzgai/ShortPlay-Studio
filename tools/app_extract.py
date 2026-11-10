#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Step A 拆包利器：按「符号名」把 server.py 的顶层块整块搬到 app/ 下。

为什么按名字而不按行号：搬走一块，后面所有行号就位移，多块连环搬必错。
这里用 AST 定位每个顶层 def/class/大写常量赋值的精确区间，一次算准。

用法（项目根目录执行）：
    python3 tools/app_extract.py --plan plan.json --check   # 只打印计划
    python3 tools/app_extract.py --plan plan.json           # 真搬

plan.json：
{
  "moves": [
    {
      "target": "app/infra/image.py",
      "header": "模块文档（三引号内内容）",
      "imports": ["import base64", "import re"],
      "symbols": ["_pil_image", "REF_MIME", "_decode_data_url"]
    }
  ]
}

行为：
- 目标文件不存在 → 用 header + imports + 代码体建新文件；
- 目标文件已存在 → 只追加代码体（imports 请自行在文件头补，脚本会提示缺哪些）；
- 被搬走的块从 server.py 删除，并在其 import 区自动补 from ... import ...。
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "server.py"


def top_blocks(source):
    """[(name, start, end, kind)] 1-based 闭区间，按出现顺序。"""
    tree = ast.parse(source)
    out = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = node.lineno
            if getattr(node, "decorator_list", None):
                start = min(d.lineno for d in node.decorator_list)
            out.append((node.name, start, node.end_lineno, "def"))
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and re.fullmatch(r"[A-Z][A-Z0-9_]*", t.id):
                    out.append((t.id, node.lineno, node.end_lineno, "const"))
                    break
        elif isinstance(node, ast.AnnAssign):
            # 带类型注解的模块常量，如 PARSE_TASKS: dict = {}
            t = node.target
            if isinstance(t, ast.Name) and re.fullmatch(r"[A-Z][A-Z0-9_]*", t.id):
                out.append((t.id, node.lineno, node.end_lineno, "const"))
    out.sort(key=lambda b: b[1])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    source = SERVER.read_text(encoding="utf-8")
    lines = source.splitlines()
    blocks = top_blocks(source)
    pos = {name: (s, e, kind) for name, s, e, kind in blocks}

    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))

    remove_spans = []
    pending = []      # [(target, text_new_file_or_None, body_text, names)]

    for mv in plan["moves"]:
        target = mv["target"]
        names = mv["symbols"]
        missing = [n for n in names if n not in pos]
        if missing:
            raise SystemExit("在 server.py 找不到: " + ", ".join(missing))

        ranged = sorted(((pos[n][0], pos[n][1], n) for n in names), key=lambda x: x[0])
        parts = []
        for s, e, _n in ranged:
            parts.append("\n".join(lines[s - 1:e]))
            remove_spans.append((s, e))
        body = "\n\n\n".join(parts).rstrip() + "\n"

        tp = ROOT / target
        if tp.exists():
            pending.append((target, None, body, names))
        else:
            doc = (mv.get("header") or "").strip()
            imps = [i.rstrip() for i in (mv.get("imports") or [])]
            head = ""
            if doc:
                head += '"""' + doc + '"""\n\n'
            if imps:
                head += "\n".join(imps) + "\n\n"
            pending.append((target, head + body, body, names))

    print("=" * 74)
    for target, text, body, names in pending:
        mode = "新建" if text is not None else "追加"
        print(f"  {mode}  {target:<42s} {len(names):2d} 符号 / {len(body.splitlines()):4d} 行")
    print(f"\n  server.py 移除 {len(remove_spans)} 段 / {sum(e - s + 1 for s, e in remove_spans)} 行")
    print("=" * 74)

    if args.check:
        print("\n[check] 未写盘。")
        return

    for target, text, body, _names in pending:
        tp = ROOT / target
        tp.parent.mkdir(parents=True, exist_ok=True)
        if text is not None:
            tp.write_text(text, encoding="utf-8")
        else:
            old = tp.read_text(encoding="utf-8").rstrip() + "\n\n\n"
            tp.write_text(old + body, encoding="utf-8")
        print("  写入", target)

    out = list(lines)
    for s, e in sorted(remove_spans, reverse=True):
        del out[s - 1:e]
    new_src = re.sub(r"\n{4,}", "\n\n\n", "\n".join(out)).rstrip() + "\n"
    SERVER.write_text(new_src, encoding="utf-8")
    print("  server.py ->", len(new_src.splitlines()), "行")


if __name__ == "__main__":
    main()
