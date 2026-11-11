/* 恐怖故事全链路 v2：走用户真实路径
   粘贴剧本 → AI 分解资产（build-assets）→ AI 补形象（ap-fill）→
   出定妆半身 → 自动设主参考 → 出三视图 → 验证身份一致 */
const HEADLESS = true;
import { chromium } from "file:///Users/kevin/.npm/_npx/dea9475797100b20/node_modules/playwright-core/index.mjs";
import fs from "node:fs";
import path from "node:path";
import { snapshotProjects, cleanupNewProjects, reportBalance } from "./cleanup-helper.mjs";

const SHOT = "screenshots";
const snap = await snapshotProjects({ label: "恐怖故事v2" });
const ok = [], bad = [];
const check = (name, cond, detail = "") => {
  (cond ? ok : bad).push(name);
  console.log((cond ? "  ✓ " : "  ✗ ") + name + (detail ? " → " + detail : ""));
};

const HORROR = `《顶楼病房》

第1场 医院顶楼 病房 夜 内
值班护士小周推门查房，307病房空着，床单却凹陷成人形。输液管自己晃了一下，吊瓶里的药水往上滴。
小周：（对着对讲机）307没人……可这床刚刚有人躺过。
对讲机里只剩电流声。

第2场 医院走廊 夜 内
小周快步走向电梯，走廊尽头的灯一盏接一盏灭。她回头，307的门开了条缝，缝里一片漆黑，门牌在渗水。
护士长：（画外音，沙哑）别回去。她认得穿这身制服的人。

第3场 307病房 夜 内
小周躲在药柜后。床单下的"人形"缓缓坐起，没有头。床头柜上的病历自己翻开，照片上是年轻的护士长，穿着和小周一样的制服。
小周：（颤抖）护士长……三十年前您也值过这个班。
人形转向她，床单滑落——空空的，什么都没有。门缓缓合上。

第4场 医院值班室 晨 内
清晨，小周趴在桌上惊醒，一切如常。她松了口气去整理病历，最后一页夹着一张泛黄的值班表：三十年前的今晚，签名是她自己的名字。`;

const browser = await chromium.launch({ headless: HEADLESS,
  executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  args: ["--no-proxy-server"] });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 960 } });
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));

await page.goto("http://127.0.0.1:8177/?fresh=1", { waitUntil: "networkidle" });
await page.evaluate(() => localStorage.clear());
await page.goto("http://127.0.0.1:8177/", { waitUntil: "networkidle" });
await page.fill("#script-input", HORROR);
await page.click("#go-step2");
await page.waitForTimeout(1200);

/* ① AI 分解资产（真实 LLM） */
await page.waitForSelector("#build-assets", { timeout: 15000 });
const canBuild = await page.evaluate(() => !document.querySelector("#build-assets").disabled);
check("① AI 分解按钮可用（LLM 已配置）", canBuild);
if (canBuild) {
  await page.click("#build-assets");
  /* 等分解完成：按钮文字从「分解中…」回来 */
  const built = await page.waitForFunction(() => {
    const b = document.querySelector("#build-assets");
    return b && !/分解中/.test(b.textContent.trim());
  }, null, { timeout: 180000 }).then(() => true).catch(() => false);
  check("② AI 分解完成", built);
  await page.waitForTimeout(800);
}
const roles = await page.evaluate(() =>
  [...document.querySelectorAll(".ap-row")].map(r => r.textContent.trim().replace(/\s+/g, " ").slice(0, 24)).slice(0, 5));
check("③ 资产面板有角色", roles.length > 0, roles.join(" | "));
await page.evaluate(() => document.querySelector("#asset-panel")?.scrollIntoView({ block: "start" }));
await page.screenshot({ path: path.join(SHOT, "horror2-01-assets.png") });

/* ④ AI 补形象（给选中角色填 keywordEn）——面板当前选中第一个角色 */
await page.waitForSelector(".ap-fill", { timeout: 8000 }).catch(() => {});
const canFill = await page.evaluate(() => {
  const b = document.querySelector(".ap-fill");
  return b ? !b.disabled : false;
});
check("④ AI 补形象按钮可用", canFill);
if (canFill) {
  await page.click(".ap-fill");
  const filled = await page.waitForFunction(() => {
    const b = document.querySelector(".ap-fill");
    return b && !/补全中/.test(b.textContent.trim());
  }, null, { timeout: 120000 }).then(() => true).catch(() => false);
  check("⑤ AI 补形象完成", filled);
  /* 确认 keywordEn 真的填上了：出图请求里应带英文关键词 */
  await page.waitForTimeout(600);
}

/* ⑥ 出定妆半身，同时拦截请求看 prompt */
await page.evaluate(() => {
  const btns = [...document.querySelectorAll(".ap-gen-seg.vars button")];
  btns.find(b => b.textContent.includes("定妆半身"))?.click();
});
const captured1 = await page.evaluate(() => new Promise(resolve => {
  const orig = window.fetch;
  window.fetch = function(url, opts) {
    if (String(url).includes("/api/comfy/generate") && opts?.body) {
      window.fetch = orig;
      resolve(opts.body);
    }
    return orig.apply(this, arguments);
  };
  document.querySelector("#comfy-generate").click();
}));
const body1 = JSON.parse(captured1);
const kw = body1.assets[0]?.keywordEn || "";
check("⑥ 出图请求带英文关键词（AI 补形象生效）",
  /[a-z]{3,}/.test(kw) && kw.length > 30, kw.slice(0, 80));

await page.waitForSelector(".ap-genimgs img", { timeout: 180000 }).catch(() => {});
const gen1 = await page.evaluate(() => ({
  count: document.querySelectorAll(".ap-genimgs img").length,
  status: document.querySelector(".ap-gen-status")?.innerText?.replace(/\s+/g, " ").slice(0, 90) || "",
}));
check("⑦ 定妆半身出图", gen1.count > 0, gen1.status);
await page.waitForTimeout(1500);

/* ⑧ 出三视图（应带主参考 + <Picture 1>） */
await page.evaluate(() => {
  const btns = [...document.querySelectorAll(".ap-gen-seg.vars button")];
  btns.find(b => b.textContent.includes("三视图"))?.click();
});
const captured2 = await page.evaluate(() => new Promise(resolve => {
  const orig = window.fetch;
  window.fetch = function(url, opts) {
    if (String(url).includes("/api/comfy/generate") && opts?.body) {
      window.fetch = orig;
      resolve(opts.body);
    }
    return orig.apply(this, arguments);
  };
  document.querySelector("#comfy-generate").click();
}));
const body2 = JSON.parse(captured2);
check("⑨ 三视图请求带主参考图", !!body2.assets[0]?.refFile, body2.assets[0]?.refFile || "");

await page.waitForFunction(() => {
  const figs = document.querySelectorAll(".ap-genimgs figure").length;
  return figs >= 2;
}, null, { timeout: 180000 }).catch(() => {});
await page.waitForTimeout(1500);
const figs = await page.evaluate(() =>
  [...document.querySelectorAll(".ap-genimgs figcaption span")].map(s => s.textContent.trim()));
check("⑩ 半身+三视图全出", figs.length >= 2, figs.join(" / "));

await page.evaluate(() => document.querySelector(".ap-genimgs")?.scrollIntoView({ block: "center" }));
await page.waitForTimeout(300);
await page.screenshot({ path: path.join(SHOT, "horror2-02-gen.png") });

check("⑪ 无页面 JS 报错", errors.length === 0, errors.slice(0, 2).join(" | "));
await browser.close();
await cleanupNewProjects(snap, { label: "恐怖故事v2" });
await reportBalance(snap);
console.log("\n结果：" + ok.length + " 通过 / " + bad.length + " 失败");
process.exit(bad.length ? 1 : 0);
