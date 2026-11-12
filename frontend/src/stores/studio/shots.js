/* =========================================================================
 * 分镜工场 · 分镜表（shots）
 * 第 3 步工作区：镜头字段编辑 / 增删排序 / 拖拽 / 批量操作、
 * 分镜相关计算属性、分镜表与整包导出。
 * ========================================================================= */
import { computed } from "vue";
import {
  S, ui, E, AI, busy, toast, begin, undo, save, reparse
} from "./core.js";
import { packWithStyle } from "./assets.js";

function renumber() { S.shots = E.renumberShots(S.shots, S.episodes); }

export const visibleShots = computed(() => {
  if (S.activeEpisode === "all" || !S.episodes || !S.episodes.length) return S.shots;
  return S.shots.filter((s) => String(s.episode) === String(S.activeEpisode));
});
export const totalDuration = computed(() => E.totalDuration(S.shots));
export const staleMsg = computed(() => S.stale === "script"
  ? "剧本已经改过了，下面的分镜还是按旧剧本排的。"
  : (S.stale === "config" ? "生成设置改过了，下面的分镜还是按旧设置排的。" : ""));
export const issueCounts = computed(() => ({
  errs: S.issues.filter((i) => i.level === "error").length,
  warns: S.issues.filter((i) => i.level === "warn").length
}));
export const canUndo = computed(() => S.undo.length > 0);
export const canRedo = computed(() => S.redo.length > 0);
export const allSelected = computed(() => S.shots.length > 0 && S.selected.length === S.shots.length);
export const someSelected = computed(() => S.selected.length > 0 && S.selected.length < S.shots.length);
export const activeShot = computed(() => S.shots.find((x) => x.id === S.activeId) || S.shots[0] || null);
export const maxDuration = computed(() => Math.max(...S.shots.map((x) => Number(x.duration) || 0), 1));
export const shotSegments = computed(() => E.segmentShots(S.shots, 10));
export const activeSegmentOf = computed(() => {
  const segs = shotSegments.value;
  if (!S.activeId || !segs.length) return segs[0] || null;
  return segs.find((s) => s.shots.some((x) => x.shot.id === S.activeId)) || segs[0];
});
export const hasFixable = computed(() => S.issues.some((i) => i.fix));
export const aiEnabledUi = computed(() => S.llmAvailable && S.aiEnabled);
export const episodeTabs = computed(() => S.episodes.map((ep) => ({
  no: ep.no, label: "E" + E.pad2(ep.no) + " · " + (ep.title || ("第" + ep.no + "集")),
  count: S.shots.filter((s) => s.episode === ep.no).length,
  stale: S.steps.shots.byEp[ep.no] === "stale",
  status: S.steps.shots.byEp[ep.no] || "idle"
})));
/** S3：分集改过且已有镜头时，第 3 步给一条「全部需重算」的提示。 */
export const shotsNeedRecalc = computed(() =>
  S.shots.length > 0 && S.episodes.some((ep) => S.steps.shots.byEp[ep.no] === "stale"));

/** S4：每个集一个闸门。没分集时整部片子是一个隐式闸门（key="all"），仍只有一个按钮。 */
export const shotGates = computed(() => {
  const byEp = S.steps.shots.byEp || {};
  const errors = S.steps.shots.errors || {};
  if (!S.episodes.length) {
    return [{ key: "all", no: "all", label: "本片 · 未分集",
      status: byEp.all || (S.shots.length ? "ready" : "idle"),
      count: S.shots.length, error: errors.all || "" }];
  }
  return S.episodes.map((ep) => ({
    key: ep.no, no: ep.no,
    label: "E" + E.pad2(ep.no) + " · " + (ep.title || ("第" + ep.no + "集")),
    status: byEp[ep.no] || "idle",
    count: S.shots.filter((s) => s.episode === ep.no).length,
    error: errors[ep.no] || ""
  }));
});
/** 串行闸门：有一集在跑时其余按钮置灰，避免并发打爆上游限流。 */
export const shotGateRunning = computed(() => shotGates.value.some((g) => g.status === "running"));

/* --------------------------- Step 3 --------------------------- */
export function setActiveEpisode(v) {
  S.activeEpisode = v === "all" ? "all" : Number(v);
  S.selected = [];
  save();
}
export function setView(v) { S.view = v; save(); }
export function toggleExport() { ui.exportOpen = !ui.exportOpen; }
export function closeExport() { ui.exportOpen = false; }
export function selectAll(e) {
  S.selected = e.target.checked ? visibleShots.value.map((s) => s.id) : [];
  save();
}
export function toggleCheck(e, id) {
  const i = S.selected.indexOf(id);
  if (e.target.checked && i < 0) S.selected.push(id);
  if (!e.target.checked && i >= 0) S.selected.splice(i, 1);
  save();
}
export function setActiveShot(id) { S.activeId = id; save(); }

export function moveShot(id, delta) {
  const i = S.shots.findIndex((s) => s.id === id);
  const j = i + delta;
  if (i < 0 || j < 0 || j >= S.shots.length) return;
  begin();
  const tmp = S.shots[i]; S.shots[i] = S.shots[j]; S.shots[j] = tmp;
  renumber(); S.activeId = id; save();
}
export function deleteShots(ids) {
  if (!ids.length) { toast("先勾选要删除的镜头", "warn"); return; }
  begin();
  const set = Object.fromEntries(ids.map((i) => [i, 1]));
  S.shots = S.shots.filter((s) => !set[s.id]);
  S.selected = []; renumber();
  if (!S.shots.some((s) => s.id === S.activeId)) S.activeId = S.shots.length ? S.shots[0].id : null;
  save();
  toast("已删除 " + ids.length + " 个镜头", "ok", "撤销", undo);
}
export function regenerate(ids) {
  if (!S.shots.length) { toast("还没有分镜", "warn"); return; }
  const targets = ids && ids.length ? ids : (S.selected.length ? S.selected : S.shots.map((s) => s.id));
  const lockedN = targets.filter((id) => (S.shots.find((s) => s.id === id) || {}).locked).length;
  begin();
  S.shots = E.regenerateShots(S.shots, targets, S.parsed, S.config, S.variant, S.overwriteEdited);
  S.shots = E.bindAssets(S.shots, S.assets);
  S.variant += 1;
  save();
  toast("已重生成 " + (targets.length - lockedN) + " 个镜头" +
    (lockedN ? "，跳过 " + lockedN + " 个锁定镜头" : "") +
    (S.overwriteEdited ? "（含手改内容）" : "，手改内容已保留"), "ok", "撤销", undo);
}
export function insertShot() {
  begin();
  const at0 = S.shots.findIndex((s) => s.id === S.activeId);
  const at = at0 < 0 ? S.shots.length - 1 : at0;
  const ref = S.shots[Math.max(0, at)];
  const s = E.bindShot({
    id: "manual_" + Date.now(), no: 0, code: "", originCode: "new",
    sceneNo: ref ? ref.sceneNo : 1, sceneLabel: ref ? ref.sceneLabel : "第1场",
    kind: "action", visual: "", size: "中景", duration: S.config.defaultDuration,
    dialogue: "", speaker: "", notes: "", edited: {}, source: "",
    episode: ref ? (ref.episode || 0) : E.episodeOf(S.episodes, 1), ai: false,
    detail: E.normalizeDetail(null), patched: false,
    charIds: [], sceneId: "", propIds: [], assetSig: "", locked: false
  }, S.assets);
  S.shots.splice(at + 1, 0, s);
  renumber(); S.activeId = s.id; S.selected = [];
  save();
  toast("已插入一个空镜头，直接填内容即可", "ok", "撤销", undo);
  setTimeout(() => {
    const el = document.querySelector('.shot[data-id="' + s.id + '"] .cell.visual');
    if (el) el.focus();
  }, 60);
}
export function handleShotOp(op, id) {
  if (op === "up") moveShot(id, -1);
  else if (op === "down") moveShot(id, 1);
  else if (op === "delete") deleteShots([id]);
  else if (op === "regen") regenerate([id]);
}
export function regenBatch() { regenerate(S.selected.length ? S.selected : null); }
export function delSelected() { deleteShots(S.selected.slice()); }

/* --------------------------- 拖拽排序 --------------------------- */
let dragId = null;
export function onDragStart(e) {
  const g = e.target.closest ? e.target.closest(".grab") : null;
  if (!g) { e.preventDefault(); return; }
  const card = g.closest(".shot"); if (!card) return;
  dragId = card.dataset.id; card.classList.add("dragging");
  if (e.dataTransfer) { e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", dragId); }
}
export function onDragOver(e) {
  if (!dragId) return;
  const card = e.target.closest ? e.target.closest(".shot") : null;
  if (!card) return;
  e.preventDefault();
  document.querySelectorAll(".shot.dragover").forEach((c) => c.classList.remove("dragover"));
  if (card.dataset.id !== dragId) card.classList.add("dragover");
}
export function onDrop(e) {
  if (!dragId) return;
  const card = e.target.closest ? e.target.closest(".shot") : null;
  e.preventDefault();
  if (card && card.dataset.id !== dragId) {
    const from = S.shots.findIndex((s) => s.id === dragId);
    const to = S.shots.findIndex((s) => s.id === card.dataset.id);
    if (from >= 0 && to >= 0) {
      begin();
      const item = S.shots.splice(from, 1)[0];
      S.shots.splice(to, 0, item);
      renumber(); S.activeId = dragId;
      save();
      toast("已调整顺序，镜号自动重排", "ok", "撤销", undo);
    }
  }
  dragId = null;
  document.querySelectorAll(".shot.dragover,.shot.dragging").forEach((c) => c.classList.remove("dragover", "dragging"));
}
export function onDragEnd() {
  dragId = null;
  document.querySelectorAll(".shot.dragover,.shot.dragging").forEach((c) => c.classList.remove("dragover", "dragging"));
}

/* ------------------------------ 导出 ------------------------------ */
function download(name, content, mime) {
  const blob = new Blob([content], { type: (mime || "text/plain") + ";charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = name; document.body.appendChild(a); a.click();
  setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 400);
}
export function exportAs(kind) {
  if (kind === "zip") { exportZip(); return; }   // 整包：分镜可以还没有，资产也要能带走
  if (!S.shots.length) { toast("还没有分镜可以导出", "warn"); return; }
  const d = new Date();
  const stamp = d.getFullYear() + String(d.getMonth() + 1).padStart(2, "0") + String(d.getDate()).padStart(2, "0");
  const base = (S.meta.title || "短剧").replace(/[\\/:*?"<>|]/g, "") + "_分镜表_" + stamp;
  if (!S.parsed) reparse();
  const content = E.formatExport(kind, {
    meta: S.meta, shots: S.shots, parsed: S.parsed, config: S.config, episodes: S.episodes,
    assets: S.assets
  });
  const ext = { csv: "csv", md: "md", txt: "txt", json: "json", "video-prompts": "json" }[kind];
  const mime = { csv: "text/csv", md: "text/markdown", txt: "text/plain", json: "application/json" }[kind] || "text/plain";
  download(base + (kind === "video-prompts" ? "_视频提示词" : "") + "." + ext, content, mime);
  if (kind === "video-prompts") {
    // 导出即预检：把对端的硬约束（档位时长、画幅、单张首帧）当场说清，别等提交失败才发现。
    let pf = null;
    try { pf = JSON.parse(content).preflight; } catch (_) { /* 不该发生 */ }
    toast(pf
      ? "已导出视频提示词 · " + pf.i2v + " 镜 i2v / " + pf.t2v + " 镜 t2v"
      : "已导出 JSON 文件", "ok");
    if (pf && pf.warnings.length) {
      pf.warnings.slice(0, 2).forEach((w) => toast("预检 · " + w, "warn"));
    }
  } else {
    toast("已导出 " + ext.toUpperCase() + " 文件", "ok");
  }
  ui.exportOpen = false;
}
export function printPage() { window.print(); }

/* --------------------------- 整包导出 --------------------------- */
function downloadBlob(name, blob) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = name; document.body.appendChild(a); a.click();
  setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 400);
}

/** 起始帧提示词：中文给豆包/即梦，英文给本地 Flux，一镜一段。 */
function framesMarkdown() {
  const rows = S.frames || [];
  if (!rows.length) return "# 起始帧提示词\n\n（本次没有生成，先做一次资产分解并生成分镜）\n";
  const out = ["# 每镜起始帧提示词", "",
    "> 共 " + rows.length + " 镜 ｜ 画幅 " + (S.config.aspect || "16:9") +
    " ｜ 用途：首帧出图，出完直接喂 i2v", ""];
  rows.forEach((f) => {
    out.push("## " + (f.code || "") + " · " + (f.size || "") + " · 引用资产 " + ((f.refAssets || []).join(" / ") || "无"));
    out.push("");
    out.push("**中文（豆包 / 即梦）**");
    out.push("");
    out.push("```");
    out.push(f.prompt || "");
    out.push("```");
    if (f.promptEn) {
      out.push("");
      out.push("**English（本地 Flux / SD）**");
      out.push("");
      out.push("```");
      out.push(f.promptEn);
      out.push("```");
    }
    out.push("");
  });
  return out.join("\n");
}

/** 参考图扩展名：老项目看 dataURL 的 mime，新项目看存盘地址的尾缀 */
function refExt(a) {
  const m1 = /^data:image\/([a-z0-9.+-]+)/i.exec(a.refImage || "");
  if (m1) return m1[1].toLowerCase() === "jpeg" ? "jpg" : m1[1].toLowerCase();
  const m2 = /\.([a-z0-9]{2,5})(?:$|&)/i.exec(a.refImage || "");
  if (m2) return m2[1].toLowerCase();
  const m3 = /\.([a-z0-9]{2,5})$/i.exec(a.refName || "");
  return m3 ? m3[1].toLowerCase() : "png";
}

/**
 * 一键打包：剧本 + 分镜表全套 + 资产包（md/csv/json/提示词）+ 参考图 + README + manifest。
 * 文本在前端渲染（engine 的 formatExport），资产正文由服务端渲染，保证与参考文档结构一致。
 */
export function exportZip() {
  if (!S.script.replace(/\s/g, "")) { toast("先放一段剧本文字进来", "warn"); return; }
  if (!S.parsed) reparse();
  const d = new Date();
  const stamp = d.getFullYear() + String(d.getMonth() + 1).padStart(2, "0") + String(d.getDate()).padStart(2, "0");
  const title = (S.meta.title || S.parsed.title || "短剧").replace(/[\\/:*?"<>|]/g, "");
  const files = [{ name: "script/原始剧本.txt", text: S.script }];
  if (S.shots.length) {
    const payload = {
      meta: { title }, shots: S.shots, parsed: S.parsed, config: S.config,
      episodes: S.episodes, assets: S.assets
    };
    [["csv", "分镜表.csv"], ["md", "分镜表.md"], ["txt", "拍摄清单.txt"],
     ["json", "分镜表.json"], ["video-prompts", "视频提示词.json"]].forEach(([kind, name]) => {
      try { files.push({ name: "storyboard/" + name, text: E.formatExport(kind, payload) }); }
      catch (err) { toast("「" + name + "」生成失败，已跳过：" + err.message, "warn"); }
    });
  }
  if (S.frames.length) {
    files.push({ name: "storyboard/起始帧提示词.md", text: framesMarkdown() });
    files.push({
      name: "storyboard/起始帧提示词.json",
      text: JSON.stringify({ aspect: S.config.aspect, stats: S.frameStats, frames: S.frames }, null, 2)
    });
  }
  const refs = [];
  [].concat(S.assets.characters, S.assets.scenes, S.assets.props).forEach((a) => {
    if (!a.refImage) return;
    refs.push({ name: (a.code ? a.code + "_" : "") + a.name + "." + refExt(a), data: a.refImage });
  });
  const stats = {
    scenes: S.parsed.stats.scenes, lines: S.parsed.stats.lines,
    characters: S.parsed.characters.length, episodes: S.episodes.length,
    shots: S.shots.length, seconds: E.totalDuration(S.shots),
    characters_asset: S.assets.characters.length, scenes_asset: S.assets.scenes.length,
    props_asset: S.assets.props.length, frames: S.frames.length, refs: refs.length
  };
  busy(true, "正在打包剧本、分镜与资产包…");
  AI.exportZip({
    title, stamp, files, refs,
    pack: S.assetPack ? packWithStyle() : S.assetPack, assets: S.assets,
    meta: { title, model: S.aiModel || S.assetModel, mode: S.aiSource || "local" },
    stats
  }).then(({ blob, name }) => {
    busy(false);
    downloadBlob(name, blob);
    ui.exportOpen = false;
    toast("已打包 " + name + "（" + Math.round(blob.size / 1024) + " KB · " + files.length + " 个文件" +
      (refs.length ? " + " + refs.length + " 张参考图" : "") + "）", "ok");
  }).catch((err) => {
    busy(false);
    toast("打包失败：" + err.message, "err");
  });
}

/* =========================================================================
 * 镜头视频（本地网关 /v1/videos）：后端缺首帧时自动文生一张再 i2v，
 * 保证画面与分镜一致；任务状态写 shot.videoJob（不进撤销栈），
 * 产物 URL 写 shot.video，随项目持久化。
 * ========================================================================= */
const VIDEO_POLLS = {};

/** 手动指定首帧：上传任意图片进服务端图库（examples/assets/），
 *  写 shot.frameImage，点 ▶ 时后端直接拿它做 i2v，不再自动出首帧。 */
export function setShotFrame(shotId, file) {
  const shot = S.shots.find((x) => x.id === shotId);
  if (!shot) { toast("找不到这个镜头", "warn"); return; }
  if (!file || !/^image\//.test(file.type)) { toast("选一张图片文件", "warn"); return; }
  const rd = new FileReader();
  rd.onload = () => {
    AI.uploadImage({ name: file.name, data: rd.result }).then((r) => {
      shot.frameImage = r.path;
      save();
      toast("首帧已设，点 ▶ 直接用这张图生成视频", "ok");
    }).catch((e) => {
      toast(String(e.message || e).slice(0, 160), "warn");
    });
  };
  rd.readAsDataURL(file);
}

export function startShotVideo(shotId, opts) {
  const shot = S.shots.find((x) => x.id === shotId);
  if (!shot) { toast("找不到这个镜头", "warn"); return; }
  if (VIDEO_POLLS[shotId]) { toast("这一镜的视频正在生成", "warn"); return; }
  const o = opts || {};
  const d = E.normalizeDetail(shot.detail);
  // 静态画面要素出首帧，运动要素配视频：提示词分工来自导演台字段设计
  const framePrompt = o.framePrompt
    || [d.subject, d.composition, d.light, d.mood].filter(Boolean).join("。")
    || shot.visual || "";
  const motion = o.motionPrompt
    || [d.subject, d.action, d.camera, d.mood, d.sound].filter(Boolean).join("。")
    || shot.visual || "";
  if (!motion.trim()) { toast("这一镜没有画面描述，先补一句再生成视频", "warn"); return; }
  shot.videoJob = { status: "queued", stage: "排队中", progress: 0, error: "" };
  save();
  AI.videoStart({
    shotId: shotId,
    framePrompt: framePrompt,
    motionPrompt: motion,
    quality: o.quality || "standard",
    duration: o.duration || "5s",
    frameFile: shot.frameImage || ""
  }).then((r) => { pollVideo(shotId, r.jobId); }).catch((e) => {
    shot.videoJob = { status: "failed", stage: "", progress: 0,
      error: String(e.message || e).slice(0, 160) };
    save();
  });
}

function pollVideo(shotId, jobId) {
  VIDEO_POLLS[shotId] = setInterval(() => {
    AI.videoJob(jobId).then((j) => {
      const s = S.shots.find((x) => x.id === shotId);
      if (!s) { stopVideoPoll(shotId); return; }
      s.videoJob = { status: j.status, stage: j.stage || "",
        progress: j.progress || 0, error: j.error || "" };
      if (j.status === "done") {
        s.video = j.url;
        if (j.frameFile) s.frameImage = j.frameFile;
        stopVideoPoll(shotId);
        save();
        toast("这一镜的视频出好了", "ok");
      } else if (j.status === "failed") {
        stopVideoPoll(shotId);
        save();
        toast("视频生成失败：" + (j.error || "未知原因"), "warn");
      }
    }).catch(() => { /* 轮询瞬断，下一拍再试 */ });
  }, 3000);
}

function stopVideoPoll(shotId) {
  clearInterval(VIDEO_POLLS[shotId]);
  delete VIDEO_POLLS[shotId];
}
