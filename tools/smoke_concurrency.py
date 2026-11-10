#!/usr/bin/env python3
"""并发连接回归：确认服务端 backlog 够大，浏览器并发的资源请求不会被内核 reset。

【为什么需要这个测试】
TCPServer.request_queue_size 默认只有 5。浏览器打开一次页面会并发拉几十个静态
资源，超过 5 个的连接会被内核直接 RST，客户端看到 Connection reset by peer ——
不进服务端日志、不抛异常，表现为「偶发失败」：
  · /api/comfy/status 偶发拿不到 → 界面误判 ComfyUI 离线，禁用出图按钮
  · /api/comfy/generate 偶发 503 → 出图静默不触发

这个 bug 在单线程串行测试里永远不会出现，只有真并发才暴露。实测 backlog=5 时
20 路并发有 12 路被 reset，改成 128 后 60 路全通。

用法：
    python3 tools/smoke_concurrency.py [并发数]
"""

import concurrent.futures
import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8177"

# 本地请求必须绕过代理，否则会被系统代理接管（本机回环地址走代理必失败）
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def hit(path, timeout=25):
    """发一个请求，返回 (状态码, 错误类型或 None)。"""
    try:
        with _OPENER.open(BASE + path, timeout=timeout) as r:
            r.read()
            return r.status, None
    except urllib.error.HTTPError as exc:
        exc.read()
        return exc.code, None
    except Exception as exc:
        return None, type(exc).__name__ + ": " + str(exc)[:70]


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    bad = []

    print("=== A. %d 路并发打 /api/config（静态轻量，专测连接层） ===" % n)
    with concurrent.futures.ThreadPoolExecutor(max_workers=n) as ex:
        res = list(ex.map(lambda _: hit("/api/config"), range(n)))
    failed = [r for r in res if r[0] != 200]
    reset = [r for r in failed if r[1] and "reset" in r[1].lower()]
    print("  成功 %d / %d" % (len(res) - len(failed), len(res)))
    if reset:
        print("  ✗ 连接被重置 %d 次 —— backlog 太小（应为 128）" % len(reset))
        bad.append("并发连接被重置")
    elif failed:
        for r in set(failed):
            print("  ✗ 失败：", r)
        bad.append("并发请求失败")
    else:
        print("  ✓ 全部成功，无连接重置")

    print()
    print("=== B. %d 路并发打 /api/comfy/status（每路都会去探测 ComfyUI） ===" % n)
    with concurrent.futures.ThreadPoolExecutor(max_workers=n) as ex:
        res = list(ex.map(lambda _: hit("/api/comfy/status"), range(n)))
    failed = [r for r in res if r[0] != 200]
    reset = [r for r in failed if r[1] and "reset" in r[1].lower()]
    print("  成功 %d / %d" % (len(res) - len(failed), len(res)))
    if reset:
        print("  ✗ 连接被重置 %d 次" % len(reset))
        bad.append("status 并发连接被重置")
    elif failed:
        for r in set(failed):
            print("  ✗ 失败：", r)
        bad.append("status 并发请求失败")
    else:
        print("  ✓ 全部成功")

    # 探测返回体里的 online 只做观察，不作为失败判据：
    # ComfyUI 本身不是并发友好的服务，N 路同时探测会有部分被判离线，
    # 但真实前端只发 1~2 个请求，不会触发这个场景。
    print()
    print("=== C. 单路 status 返回体（确认真实可用） ===")
    with _OPENER.open(BASE + "/api/comfy/status", timeout=25) as r:
        st = json.load(r)
    print("  online=%s  host=%s  model=%s" % (st.get("online"), st.get("host"), st.get("model")))
    if not st.get("online"):
        print("  ✗ ComfyUI 不在线：", st.get("detail", ""))
        bad.append("ComfyUI 离线")
    else:
        print("  ✓ ComfyUI 在线")

    print()
    if bad:
        print("结果：失败 —— " + "；".join(bad))
        return 1
    print("结果：全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
