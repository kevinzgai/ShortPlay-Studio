/* 用「与界面完全相同」的 AI 编排链路，生成示例剧本的真·AI 分集分镜结果。
 * 用法：先启动 server.py，再 node tools/gen_ai_example.js
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import E from "../frontend/src/lib/engine.js";
import AI from "../frontend/src/lib/ai.js";

AI.setBase(process.env.SHORTPLAY_URL || "http://127.0.0.1:8177");
const OUT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "examples");
const script = E.SAMPLE_SCRIPT;
const parsed = E.parseScript(script);
const config = Object.assign({}, E.DEFAULT_CONFIG);

AI.run({
  script, parsed, config, episodes: "auto",
  onProgress: (stage, text) => console.log("[ai] " + text)
}).then((out) => {
  if (out.source !== "ai") {
    console.error("AI 链路未成功，未写入示例：" + (out.fallbackReason || "unknown"));
    process.exit(1);
  }
  const meta = {
    title: parsed.title,
    generator: "ShortPlay Studio · AI 分集分镜",
    model: out.model,
    generatedAt: new Date().toISOString(),
    episodes: out.episodes.length,
    shots: out.shots.length,
    totalSeconds: E.totalDuration(out.shots)
  };
  const payload = { meta, shots: out.shots, parsed, config, episodes: out.episodes };
  const files = [
    ["sample-ai-storyboard.json", JSON.stringify({
      meta, config, episodes: out.episodes,
      warnings: out.warnings, degraded: out.degraded,
      shots: out.shots
    }, null, 2)],
    ["sample-ai-storyboard.csv", E.formatExport("csv", payload)],
    ["sample-ai-storyboard.md", E.formatExport("md", payload)],
    ["sample-ai-storyboard.txt", E.formatExport("txt", payload)],
    ["sample-ai-video-prompts.json", E.formatExport("video-prompts", payload)]
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
  if (out.warnings.length) console.log("  核对提示：" + out.warnings.length + " 条");
  console.log("  覆盖情况：" + JSON.stringify(out.coverage));
}).catch((e) => { console.error("生成失败：", e); process.exit(1); });
