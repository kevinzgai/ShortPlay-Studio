#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""未定义名字静态检查（py_compile 抓不到的那一类）。

为什么需要它：py_compile 只查语法，import 只查模块级加载。
方法体里写漏 self. 前缀、或引用了搬走时丢掉的常量，两者都能过，
只有真发一次请求才会炸成 NameError —— AGENT_POST_PATHS 就这么漏过一次。

做法：逐个作用域（模块 / 类 / 函数）收集可解析的名字，再找裸引用里没有来源的。
不是完整的类型检查，但足够抓住「忘了 self.」这类致命错误。

用法：python3 tools/check_names.py
"""

import ast
import builtins
import sys
from pathlib import Path

# Windows GBK 控制台打不出 ✓ / ✗，先切 UTF-8（start.bat 本来就设了 PYTHONUTF8=1，这里双保险）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
# 2026-11-11 目录重构：后端代码收进 backend/（server.py 薄壳 + app/ 包）
BACKEND = ROOT / "backend"
FILES = sorted([BACKEND / "server.py"]) + sorted((BACKEND / "app").rglob("*.py"))

BUILTINS = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__package__"}


class Scope:
    def __init__(self, node, parent=None, kind="module"):
        self.node = node
        self.parent = parent
        self.kind = kind            # module | class | function
        self.names = set()
        self.class_attrs = set()    # 供子作用域判断「该写 self.」的名字


def collect_bindings(node, scope):
    """收集本作用域内所有会「绑定名字」的语法结构。"""
    for child in ast.walk(node):
        if isinstance(child, ast.Import):
            for a in child.names:
                scope.names.add((a.asname or a.name).split(".")[0])
        elif isinstance(child, ast.ImportFrom):
            for a in child.names:
                if a.name != "*":
                    scope.names.add(a.asname or a.name)
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if scope.kind == "class" and child is not node:
                scope.class_attrs.add(child.name)
            scope.names.add(child.name)
        elif isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
            scope.names.add(child.id)
        elif isinstance(child, (ast.arg,)):
            scope.names.add(child.arg)
        elif isinstance(child, ast.ExceptHandler) and child.name:
            scope.names.add(child.name)
        elif isinstance(child, ast.Global):
            scope.names.update(child.names)
        elif isinstance(child, ast.Nonlocal):
            scope.names.update(child.names)


def walk_scope(node, parent, kind, path, out):
    sc = Scope(node, parent, kind)
    collect_bindings(node, sc)
    out.append((sc, path))
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            walk_scope(child, sc, "function", path, out)
        elif isinstance(child, ast.ClassDef):
            walk_scope(child, sc, "class", path, out)


def resolvable(name, sc):
    cur = sc
    while cur is not None:
        if name in cur.names:
            return True
        # 类作用域内的名字，在方法里必须写 self.xxx 才能拿到
        if cur.kind == "class" and name in cur.class_attrs:
            return "needs_self"
        cur = cur.parent
    return False


def check(path):
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    scopes = []
    walk_scope(tree, None, "module", str(path), scopes)

    problems = []
    for sc, p in scopes:
        for node in ast.walk(sc.node):
            if not isinstance(node, ast.Name) or not isinstance(node.ctx, ast.Load):
                continue
            nm = node.id
            if nm in BUILTINS:
                continue
            r = resolvable(nm, sc)
            if r is True:
                continue
            if r == "needs_self":
                problems.append((p, node.lineno, nm, "类属性忘了 self. 前缀"))
            else:
                problems.append((p, node.lineno, nm, "未定义"))
    return problems


def main():
    total = 0
    for f in FILES:
        rel = f.relative_to(ROOT)
        for p, line, nm, why in check(f):
            print("  ✗ %s:%d  %s → %s" % (rel, line, nm, why))
            total += 1
    if total:
        print("\n发现 %d 处未定义引用" % total)
        return 1
    print("✓ %d 个文件，无未定义引用" % len(FILES))
    return 0


if __name__ == "__main__":
    sys.exit(main())
