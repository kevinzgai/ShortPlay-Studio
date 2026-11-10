#!/usr/bin/env node
/* 清扫回归测试留下的临时项目（默认干跑，只列清单）
 *
 *   node tools/cleanup_test_projects.mjs           # 只看清单，不删
 *   node tools/cleanup_test_projects.mjs --apply   # 真删（走 /api/projects/delete，进 .trash 可捞回）
 *
 * 为什么需要它：cleanup-helper 只清「本次运行新建」的项目，这是防误删真实项目的安全规则；
 * 但一次崩溃/超时跳过清场，那批临时项目下一轮就变成「老项目」，从此没人清，会一直堆。
 * 实测算术：三次崩溃 → projects/ 从 59 涨到 97。
 *
 * 判定口径：只认测试脚本固定使用的两个项目名，别的一律不碰（含 verify_stage_split 的回归夹具）。
 * 删除走服务端接口而不是 rm，是为了保留 .trash 的捞回能力。
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const BASE = process.env.SHORTPLAY_BASE || "http://127.0.0.1:8177";
const APPLY = process.argv.includes("--apply");

// 测试脚本固定用的名字（见 verify_* 里的 createProject/newProject 调用）
const TEST_NAMES = new Set(["雨夜便利店", "未命名项目"]);
// 明确保留：verify_stage_split 优先选用的回归夹具
const KEEP_NAMES = new Set(["回归夹具·含分镜"]);

async function api(p, init) {
  const res = await fetch(BASE + p, { cache: "no-store", ...init });
  const text = await res.text();
  let json = null;
  try { json = JSON.parse(text); } catch (_) {}
  if (!res.ok) throw new Error("HTTP " + res.status + " " + text.slice(0, 120));
  return json;
}

function dirSize(dir) {
  let total = 0;
  try {
    for (const name of readdirSync(dir)) {
      const p = path.join(dir, name);
      let st;
      try { st = statSync(p); } catch (_) { continue; }
      total += st.isDirectory() ? dirSize(p) : st.size;
    }
  } catch (_) {}
  return total;
}

const mb = (n) => (n / 1024 / 1024).toFixed(1) + " MB";

const json = await api("/api/projects");
const rows = (json && json.projects) || [];
console.log("当前项目总数：" + rows.length);

const targets = [];
const kept = [];
for (const p of rows) {
  const name = String(p.name || "");
  if (KEEP_NAMES.has(name)) { kept.push(p); continue; }
  if (TEST_NAMES.has(name)) targets.push(p);
  else kept.push(p);
}

console.log("测试临时项目：" + targets.length + " 个；保留：" + kept.length + " 个");
if (kept.length) {
  console.log("\n保留清单（不删）：");
  kept.forEach((p) => console.log("  " + p.id + "  " + p.name));
}

if (!targets.length) {
  console.log("\n没有需要清理的测试项目。");
  process.exit(0);
}

const byName = new Map();
let bytes = 0;
for (const p of targets) {
  byName.set(p.name || "?", (byName.get(p.name || "?") || 0) + 1);
  bytes += dirSize(path.join(ROOT, "projects", p.id));
}
console.log("\n待清理明细：");
for (const [name, n] of byName) console.log("  " + name + " × " + n);
console.log("  占用磁盘：" + mb(bytes));
console.log("  最早：" + targets.map((p) => p.createdAt).sort()[0]);
console.log("  最晚：" + targets.map((p) => p.createdAt).sort().slice(-1)[0]);

if (!APPLY) {
  console.log("\n[干跑] 未删除任何项目。确认无误后加 --apply 执行（删除进 .trash，可捞回）。");
  process.exit(0);
}

let ok = 0, bad = 0;
for (const p of targets) {
  try {
    await api("/api/projects/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: p.id }),
    });
    ok++;
  } catch (err) {
    bad++;
    if (bad <= 5) console.log("  删除失败 " + p.id + "：" + err.message);
  }
}
const after = ((await api("/api/projects"))?.projects || []).length;
console.log("\n已删除 " + ok + " 个，失败 " + bad + " 个。项目总数 " + rows.length + " → " + after);
console.log("删除的项目都在 projects/.trash/ 里，需要捞回时把目录移回 projects/ 即可。");
process.exit(bad ? 1 : 0);
