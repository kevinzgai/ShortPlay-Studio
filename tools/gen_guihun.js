/* 用与界面完全相同的 AI 编排链路，把《鬼婚，逃命》第一章拆成分镜表。
 * 用法：先启动 server.py（8177），再 node tools/gen_guihun.js
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import E from "../frontend/src/lib/engine.js";
import AI from "../frontend/src/lib/ai.js";
import { GUIHUN_SCRIPT } from "../frontend/src/lib/sampleGuihun.js";

AI.setBase(process.env.SHORTPLAY_URL || "http://127.0.0.1:8177");
const OUT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "examples");
const script = GUIHUN_SCRIPT;
const parsed = E.parseScript(script);
const config = Object.assign({}, E.DEFAULT_CONFIG, { pacing: "cinematic", aspect: "9:16" });

fs.writeFileSync(path.join(OUT, "鬼婚逃命-分镜剧本.txt"), script, "utf-8");
console.log("剧本：" + parsed.title + " · " + parsed.stats.scenes + " 场 / " +
  parsed.stats.lines + " 句对白 / " + parsed.stats.actions + " 条动作");

AI.run({
  script, parsed, config, episodes: "auto",
  onProgress: (stage, text) => console.log("[ai] " + text)
}).then((out) => {
  if (out.source !== "ai") {
    console.error("AI 链路未成功：" + (out.fallbackReason || "unknown"));
    process.exit(1);
  }
  const meta = {
    title: parsed.title,
    source: "第一章 鬼婚，逃命 · 麻衣鬼相关灯",
    generator: "ShortPlay Studio · AI 分集分镜",
    model: out.model,
    generatedAt: new Date().toISOString(),
    episodes: out.episodes.length,
    shots: out.shots.length,
    totalSeconds: E.totalDuration(out.shots)
  };
  const payload = { meta, shots: out.shots, parsed, config, episodes: out.episodes };
  const files = [
    ["guihun-storyboard.json", JSON.stringify({
      meta, config, episodes: out.episodes,
      warnings: out.warnings, degraded: out.degraded,
      coverage: out.coverage, shots: out.shots
    }, null, 2)],
    ["guihun-storyboard.csv", E.formatExport("csv", payload)],
    ["guihun-storyboard.md", E.formatExport("md", payload)],
    ["guihun-storyboard.txt", E.formatExport("txt", payload)],
    ["guihun-video-prompts.json", E.formatExport("video-prompts", payload)]
  ];
  files.forEach(([name, content]) => {
    fs.writeFileSync(path.join(OUT, name), content, "utf-8");
    console.log("  → examples/" + name + " (" + content.length + " chars)");
  });
  console.log("\n完成：" + out.episodes.length + " 集 / " + out.shots.length + " 镜 / " +
    E.totalDuration(out.shots) + " 秒，模型 " + out.model);
  out.episodes.forEach((ep) => {
    const n = out.shots.filter((s) => s.episode === ep.no).length;
    console.log("  第" + ep.no + "集《" + ep.title + "》第" + ep.sceneFrom + "-" + ep.sceneTo + "场 · " + n + " 镜");
  });
  if (out.degraded.length) console.log("  降级集：" + JSON.stringify(out.degraded));
  if (out.warnings.length) console.log("  核对提示：" + JSON.stringify(out.warnings, null, 1));
  console.log("  覆盖情况：" + JSON.stringify(out.coverage));
  const keys = ["subject", "action", "composition", "sizeReason", "camera", "light", "mood", "sound", "transition"];
  console.log("  分镜卡 9/9 全填：" + out.shots.filter((s) => keys.every((k) => (s.detail || {})[k])).length + "/" + out.shots.length);
  console.log("  自动补镜：" + out.shots.filter((s) => s.patched).length);
}).catch((e) => { console.error("生成失败：", e); process.exit(1); });
