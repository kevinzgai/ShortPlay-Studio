/* 用与界面完全相同的引擎，生成示例剧本及对应的批量分镜结果。
 * 运行：node tools/gen_example.js
 * 产出：examples/sample-script.txt、sample-problem-script.txt、
 *       sample-storyboard.json / .csv / .md / .txt / -video-prompts.json
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import E from "../frontend/src/lib/engine.js";

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.join(root, "examples");
fs.mkdirSync(out, { recursive: true });

const script = E.SAMPLE_SCRIPT;
const parsed = E.parseScript(script);
const issues = E.diagnose(script, parsed);
const config = Object.assign({}, E.DEFAULT_CONFIG);
const assets = E.buildAssets(parsed, null);
const shots = E.bindAssets(E.buildStoryboard(parsed, config, 0), assets);

const write = (name, data) => {
  fs.writeFileSync(path.join(out, name), data, "utf8");
  console.log("  -> examples/" + name, "(" + Buffer.byteLength(data, "utf8") + " B)");
};

write("sample-script.txt", script + "\n");
write("sample-problem-script.txt", E.SAMPLE_PROBLEM_SCRIPT + "\n");

const meta = {
  title: parsed.title,
  source: "examples/sample-script.txt",
  generator: "ShortPlay Studio / frontend/src/lib/engine.js (deterministic)",
  note: "本文件由 tools/gen_example.js 生成，与界面「载入完整示例剧本 → 一键生成全部分镜」的结果逐条一致。",
  aspect: config.aspect,
  pacing: config.pacing
};

const payload = {
  meta,
  config,
  stats: Object.assign({}, parsed.stats, {
    shots: shots.length,
    totalDurationSec: E.totalDuration(shots),
    issues: issues.length
  }),
  scenes: parsed.scenes.map(s => ({
    no: s.no, order: s.order, head: s.raw,
    intExt: s.intExt, location: s.location, time: s.time,
    characters: s.characters,
    lines: s.lines.map(l => ({ speaker: l.speaker, stage: l.stage, text: l.text })),
    actions: s.actions.map(a => a.text)
  })),
  issues,
  assets,
  shots
};

const exp = (kind) => E.formatExport(kind, { meta, shots, parsed, config, assets });
write("sample-storyboard.json", JSON.stringify(payload, null, 2) + "\n");
write("sample-storyboard.csv", exp("csv") + "\n");
write("sample-storyboard.md", exp("md") + "\n");
write("sample-storyboard.txt", exp("txt") + "\n");
write("sample-video-prompts.json", exp("video-prompts") + "\n");

console.log("\n" + parsed.title + "：" + parsed.stats.scenes + " 场 / " +
  parsed.stats.characters + " 角色 / " + parsed.stats.lines + " 句对白 / " +
  parsed.stats.actions + " 条动作");
console.log("体检：" + (issues.length ? issues.map(i => i.code).join(", ") : "0 项问题"));
console.log("分镜：" + shots.length + " 镜 / 约 " + E.totalDuration(shots) + " 秒");
console.log("景别分布：" + E.SIZES.map(z => z + " " + shots.filter(s => s.size === z).length).join(" · "));
