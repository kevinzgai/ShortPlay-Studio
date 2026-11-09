# -*- coding: utf-8 -*-
"""在真实浏览器里完整模拟 comfyuiNode 的 loadInfo，验证 22 个节点是否仍报 missing。"""
import json

from playwright.sync_api import sync_playwright

CHROME = r"<USER_HOME>\AppData\Local\ms-playwright\chromium-1243\chrome-win64\chrome.exe"

TYPES = ["SaveVideo", "LoadImage", "ResolutionSelector", "ImageScaleToTotalPixels",
         "GetImageSize", "VAELoader", "VAEDecodeAudio", "VAEDecode", "KSamplerSelect",
         "BasicScheduler", "SamplerCustomAdvanced", "BasicGuider", "UNETLoader",
         "CLIPLoader", "RandomNoise", "CreateVideo", "MiniMaxH3ImageToVideo",
         "ComfyMathExpression", "PrimitiveFloat", "LoraLoaderModelOnly",
         "ComfySwitchNode", "PrimitiveInt", "PrimitiveBoolean"]

JS = """
async (types) => {
  const url = 'http://127.0.0.1:8188';
  // 第一步：system_stats 探测（前端 loadInfo 的前置）
  try {
    await fetch(url + '/system_stats', { signal: AbortSignal.timeout(3500) });
  } catch (e) {
    return { stage: 'system_stats 失败', error: String(e).slice(0,150) };
  }
  // 第二步：每批 6 个并发拉 object_info
  const infoCache = {}, missing = [];
  for (let i = 0; i < types.length; i += 6) {
    await Promise.all(types.slice(i, i + 6).map(async (t) => {
      const r = await fetch(url + '/object_info/' + encodeURIComponent(t));
      const b = await r.json();
      if (b[t]) infoCache[t] = 1; else missing.push(t);
    }).map(p => p.catch(e => ({ err: String(e) }))));
  }
  return { stage: 'ok', loaded: Object.keys(infoCache).length, missing };
}
"""

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, executable_path=CHROME,
                                args=["--no-proxy-server"])
    ctx = browser.new_context(viewport={"width": 1200, "height": 800},
                              ignore_https_errors=True)
    page = ctx.new_page()
    page.goto("http://127.0.0.1:3000/", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2000)
    print("页面 origin:", page.evaluate("location.origin"))
    res = page.evaluate(JS, TYPES)
    print()
    print(json.dumps(res, ensure_ascii=False, indent=2))
    browser.close()
