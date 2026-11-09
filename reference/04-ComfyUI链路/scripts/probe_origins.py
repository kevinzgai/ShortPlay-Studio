# -*- coding: utf-8 -*-
"""逐个 origin 在真实浏览器里 fetch ComfyUI，找出哪些被浏览器拦截。"""
import json

from playwright.sync_api import sync_playwright

CHROME = r"<USER_HOME>\AppData\Local\ms-playwright\chromium-1243\chrome-win64\chrome.exe"

JS = """
async (u) => {
  try {
    const t0 = performance.now();
    const r = await fetch(u, { signal: AbortSignal.timeout(4000) });
    const t = await r.text();
    return { ok: r.ok, status: r.status, len: t.length,
             acao: r.headers.get('access-control-allow-origin'),
             ms: Math.round(performance.now() - t0) };
  } catch (e) { return { error: String(e).slice(0,160), name: e.name }; }
}
"""

ORIGINS = [
    "http://127.0.0.1:3000",
    "http://localhost:3000",
    "http://127.0.0.1:8289",
    "http://localhost:8289",
]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, executable_path=CHROME,
                                args=["--no-proxy-server"])
    for origin in ORIGINS:
        ctx = browser.new_context(viewport={"width": 1200, "height": 800},
                                  ignore_https_errors=True)
        page = ctx.new_page()
        try:
            page.goto(origin + "/", wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(1200)
            actual = page.evaluate("location.origin")
            res = page.evaluate(JS, "http://127.0.0.1:8188/system_stats")
            print(f"{origin:32s} 实际origin={actual:26s} -> {json.dumps(res, ensure_ascii=False)}")
        except Exception as e:
            print(f"{origin:32s} 页面打不开: {str(e)[:90]}")
        ctx.close()
    browser.close()
