/* =========================================================================
 * 分镜工场 · 流程与生成链（steps）
 * 剧本导入 / 改稿 / 体检（第 1 步）、分集与逐集闸门（第 2/3 步）、
 * AI 全链路生成与后端拆解任务进度、四步导航。
 * ========================================================================= */
import { GUIHUN_SCRIPT } from "../../lib/sampleGuihun.js";
import {
  S, ui, PROJECT, E, AI, FORCE_LOCAL,
  busy, toast, begin, undo, save, reparse, markStale, stalePlanIfAny
} from "./core.js";

export function doGenerate(goStep3) {
  if (S.aiBusy) { toast("AI 正在生成，等这一轮结束再操作", "warn"); return; }
  if (!S.script.replace(/\s/g, "")) { toast("先放一段剧本文字进来", "warn"); return; }
  reparse();
  const errs = S.issues.filter((i) => i.level === "error" && i.code !== "no-scene");
  if (errs.length && goStep3 !== "force") {
    S.step = 2; window.scrollTo(0, 0);
    toast("有 " + errs.length + " 处需要先补全，已在体检卡标出", "warn");
    return;
  }
  // 暂时移除「AI 一键分集 + 分镜」：后端 7 阶段流水线（/api/parse/start）休眠，
  // 不再从任何 UI 入口触发。S4 会用「逐集闸门」替换；当前只保留离线规则兜底。
  return localGenerate();
}

/** 离线规则引擎：分集 + 分镜，完全可用、可复现 */
export function localGenerate() {
  busy(true, "正在按剧情顺序拆解场次…");
  setTimeout(() => { ui.busyText = "正在编排镜头与景别…"; }, 260);
  setTimeout(() => {
    begin();
    // S3：分集已是独立的第 2 步，排分镜时沿用已确认的方案，别把手调结果悄悄覆盖。
    if (S.episodeMode === "none") S.episodes = [];
    else if (!S.episodes.length) S.episodes = E.localEpisodes(S.parsed, S.episodeMode);
    const local = E.buildStoryboard(S.parsed, S.config, S.variant);
    S.shots = E.bindAssets(E.renumberShots(E.assignEpisodes(local, S.episodes), S.episodes), S.assets);
    S.shots.forEach((s) => { s.originCode = s.code; s.ai = false; });
    S.selected = [];
    S.activeEpisode = "all";
    S.activeId = S.shots.length ? S.shots[0].id : null;
    S.aiSource = "local"; S.episodeSource = "local"; S.aiModel = "";
    S.aiDegraded = []; S.aiWarnings = [];
    S.stale = ""; S.step = 3;
    busy(false); window.scrollTo(0, 0); save();
    toast("已生成 " + (S.episodes.length ? S.episodes.length + " 集 / " : "") + S.shots.length +
      " 个分镜，约 " + E.totalDuration(S.shots) + " 秒", "ok", "撤销", undo);
  }, 620);
}

/* ---------------------- 后端拆解任务：进度 / 回填 / 恢复 ---------------------- */
/* 进度只放 ui：不进撤销快照、不落盘。任务在后端跑，刷新页面靠 /api/parse/latest 接回来。 */
const PARSE_BLANK = () => ({
  visible: false, id: "", project: "", status: "queued", percent: 0, done: 0, total: 7,
  stage: "", stageLabel: "", stages: [], events: [],
  error: "", hint: "", startedAt: 0, elapsed: 0, live: "", result: null
});

/* 点击后到后端回包之间那一小段：先用骨架占位，start 返回的真实阶段会把它覆盖掉 */
const PARSE_STAGES_SKELETON = [
  ["detect", "识别剧本格式"], ["adapt", "忠实转写"], ["assets", "资产分解"],
  ["plan", "自动分集"], ["storyboard", "逐集分镜"], ["frames", "起始帧提示词"],
  ["verify", "覆盖校验"]
].map(([key, label]) => ({ key, label, status: "pending", detail: "", ms: 0, weight: 0 }));

export function resetParseProgress() {
  Object.assign(ui.parse, PARSE_BLANK());
  ui.parse.stages = PARSE_STAGES_SKELETON.map((x) => ({ ...x }));
  ui.parse.total = ui.parse.stages.length;
  ui.parse.startedAt = Date.now();
  ui.parse.visible = true;
}
export function hideParseProgress() { ui.parse.visible = false; }
export function cancelParse() {
  if (!ui.parse.id) return;
  AI.cancelParseTask(ui.parse.id)
    .then(() => toast("已请求取消，当前阶段跑完就停", "warn"))
    .catch(() => toast("取消失败，任务可能已经结束", "warn"));
}
export function retryParse() { hideParseProgress(); return aiGenerate(); }
export function useLocalInstead() { hideParseProgress(); return localGenerate(); }

/* 阶段 key → 第 1 步那条「自动流程」的 key，两边命名不同，映射一下让旧流程条也跟着走 */
const PARSE_TO_FLOW = { detect: "detect", adapt: "adapt", assets: "check", plan: "plan",
                        storyboard: "shots", frames: "verify", verify: "verify" };

/** 一条事件 → 进度态。事件是增量（seq 单调），这里只做幂等覆盖。 */
function applyParseEvent(ev) {
  if (!ev || ev.seq == null) return;
  const p = ui.parse;
  if (ev.status) p.status = ev.status;
  if (ev.percent != null) p.percent = ev.percent;
  if (ev.done != null) p.done = ev.done;
  if (ev.total != null) p.total = ev.total;
  if (ev.stage) {
    p.stage = ev.stage;
    p.stageLabel = ev.stageLabel || p.stageLabel;
    if (PARSE_TO_FLOW[ev.stage]) S.aiStage = PARSE_TO_FLOW[ev.stage];
  }
  if (ev.type === "stage") {
    const st = p.stages.find((x) => x.key === ev.stage);
    if (st) {
      st.status = ev.state || st.status;
      if (ev.detail) st.detail = ev.detail;
      if (ev.ms) st.ms = ev.ms;
    }
  } else if (ev.type === "tool") {
    const cid = ev.callId || ev.stage;
    let row = p.events.find((x) => x.callId === cid);
    if (!row) {
      row = { callId: cid, tool: ev.tool || "", label: ev.label || ev.stageLabel || cid,
              detail: "", ms: 0, state: "running" };
      p.events.push(row);
      if (p.events.length > 80) p.events.shift();
    }
    if (ev.phase === "end") { row.state = ev.state || "ok"; row.ms = ev.ms || 0; }
    if (ev.detail) row.detail = ev.detail;
    if (ev.label && ev.phase === "start") row.label = ev.label;
  } else if (ev.type === "done") {
    p.status = "done"; p.percent = 100;
  } else if (ev.type === "error") {
    p.error = ev.detail || "拆解失败";
    p.hint = ev.hint || p.hint;
  }
}

/** 整份快照（任务结束后 / 恢复时）覆盖进度态 */
function applyParseSnapshot(snap) {
  if (!snap) return;
  const p = ui.parse;
  if (snap.status) p.status = snap.status;
  if (snap.percent != null) p.percent = snap.percent;
  if (snap.done != null) p.done = snap.done;
  if (snap.total != null) p.total = snap.total;
  if (snap.stages && snap.stages.length) p.stages = snap.stages;
  if (snap.elapsed) p.elapsed = snap.elapsed;
  if (snap.project) p.project = snap.project;
  const e = (snap.errors || [])[0];
  if (e) { p.error = e.message || p.error; p.hint = e.hint || p.hint; }
}

/** 后端结果 → 界面状态。编号 / 场景标签 / 资产绑定仍由本地确定性生成，不信任模型输出。 */
function applyAiResult(result) {
  begin();
  const groups = (result.groups || []).slice();
  const episodes = result.episodes || [];
  // 工作流 stage 1 的转写产物回填：基线快照已存小说原文，撤销即可回退
  if (result.adapted && result.script && result.script !== S.script) {
    S.script = result.script;
    reparse();
  }
  if (result.assetPack) {
    S.assetPack = result.assetPack;
    S.assetModel = result.assetModel || result.assetPack.model || "";
    S.assets = E.applyAssetPack(S.assets, result.assetPack, S.parsed);
  }
  S.assetWarnings = result.assetWarnings || [];
  S.frames = result.frames || [];
  S.frameStats = result.frameStats || null;
  S.episodes = episodes;

  // 模型整集失败时后端返回空数组：这一集按本地规则补，别让成片缺一段
  const degraded = result.degraded || [];
  if (degraded.length) {
    const localAll = E.buildStoryboard(S.parsed, S.config, S.variant);
    episodes.forEach((ep, i) => {
      if ((groups[i] || []).length) return;
      groups[i] = localAll
        .filter((x) => x.sceneNo >= ep.sceneFrom && x.sceneNo <= ep.sceneTo)
        .map((x) => ({
          sceneNo: x.sceneNo, kind: x.kind, visual: x.visual, size: x.size,
          duration: x.duration, dialogue: x.dialogue, speaker: x.speaker, notes: x.notes,
          ai: false, detail: E.normalizeDetail(x.detail)
        }));
    });
  }

  S.shots = E.bindAssets(AI.toShots(groups, episodes, S.parsed, S.config), S.assets);
  S.selected = []; S.activeEpisode = "all";
  S.activeId = S.shots.length ? S.shots[0].id : null;
  S.aiSource = (episodes.length && degraded.length >= episodes.length) ? "local" : "ai";
  S.aiModel = result.model || "";
  S.episodeSource = (episodes.length && episodes.every((e) => e.source === "local")) ? "local" : "ai";
  S.aiDegraded = degraded;
  S.aiWarnings = result.warnings || [];
  S.stale = ""; S.step = 3;
  window.scrollTo(0, 0); save();

  const head = (S.episodes.length ? S.episodes.length + " 集 / " : "") + S.shots.length + " 镜";
  const adaptNote = result.adapted
    ? "（小说体已自动转写成 " + (S.parsed ? S.parsed.stats.scenes : 0) + " 场剧本，撤销可回原文）" : "";
  if (S.aiSource === "local") {
    toast("AI 没成功，已用本地规则生成 " + head + adaptNote + "，可重试", "warn", "撤销", undo);
  } else if (S.aiDegraded.length) {
    toast("AI 已生成 " + head + "；其中 " + S.aiDegraded.length + " 集模型失败，已用本地规则补齐" + adaptNote,
      "warn", "撤销", undo);
  } else {
    toast("AI 已自动分成 " + head + "，约 " + E.totalDuration(S.shots) + " 秒" + adaptNote,
      "ok", "撤销", undo);
  }
}

/** AI 全链路：后端任务执行，事件流推进度；失败保留原有内容，给重试入口。 */
export function aiGenerate() {
  if (S.aiBusy) return Promise.resolve();
  S.aiBusy = true;
  S.aiStage = "detect";
  resetParseProgress();
  let taskId = "";
  return AI.startParseTask({
    projectId: S.projectId || "",
    script: S.script,
    scenes: (S.parsed && S.parsed.scenes) || [],
    novel: AI.isNovelScript(S.script),
    episodes: S.episodeMode === "none" ? 1 : S.episodeMode,
    config: S.config
  }).then((started) => {
    taskId = started.taskId || "";
    ui.parse.id = taskId;
    ui.parse.project = S.projectId || "";
    ui.parse.stages = started.stages || [];
    ui.parse.total = started.total || ui.parse.stages.length || 7;
    ui.parse.status = "queued";
    return AI.watchParseTask(taskId, (ev, meta) => {
      if (meta && meta.live) ui.parse.live = meta.live;
      applyParseEvent(ev);
    });
  }).then((snap) => {
    applyParseSnapshot(snap);
    S.aiBusy = false; S.aiStage = "";
    if (!snap || !snap.result) throw new Error("任务结束了但没有返回拆解结果");
    applyAiResult(snap.result);
  }).catch((err) => {
    S.aiBusy = false; S.aiStage = "";
    if (err && err.snapshot) applyParseSnapshot(err.snapshot);
    ui.parse.visible = true;
    if (ui.parse.status !== "cancelled") ui.parse.status = "failed";
    ui.parse.error = (err && err.message) || "拆解失败";
    if (ui.parse.status !== "cancelled") {
      ui.parse.hint = ui.parse.hint ||
        "失败不会改动你现有的剧本与分镜：可以直接重试，或用本地规则生成。";
    }
    if (ui.parse.status === "cancelled") toast("已取消拆解，内容未改动", "warn");
    else toast("拆解失败：" + ui.parse.error, "err");
  });
}

/** 刷新 / 重开页面：后端还有同项目的任务在跑就接上，别让进度停在旧画面 */
export function resumeParseTask() {
  if (PROJECT.server === false || location.protocol === "file:") return;
  AI.parseTaskLatest().then((res) => {
    const task = res && res.task;
    if (!task) return;
    if (task.status !== "running" && task.status !== "queued") return;
    if (task.project && S.projectId && task.project !== S.projectId) return;  // 别的项目的任务不接管
    if (ui.parse.id === task.id) return;
    S.aiBusy = true;
    resetParseProgress();
    ui.parse.id = task.id;
    ui.parse.project = task.project || S.projectId || "";
    applyParseSnapshot(task);
    (task.events || []).forEach(applyParseEvent);
    AI.watchParseTask(task.id, (ev, meta) => {
      if (meta && meta.live) ui.parse.live = meta.live;
      applyParseEvent(ev);
    }).then((snap) => {
      applyParseSnapshot(snap);
      S.aiBusy = false; S.aiStage = "";
      if (snap && snap.result) applyAiResult(snap.result);
    }).catch((err) => {
      S.aiBusy = false;
      if (err && err.snapshot) applyParseSnapshot(err.snapshot);
      ui.parse.status = "failed";
      ui.parse.error = (err && err.message) || "拆解失败";
    });
  }).catch(() => { /* 没有任务或服务不支持：什么都不做 */ });
}

/* ---------------------- S3 · 分集独立成步 ----------------------
   分集不再由「进第 2 步」自动附带：只认按钮。重算走 AI.plan，失败降级本地规则；
   重算或手改后把 steps.shots.byEp 全标 stale（D2 整步作废），但绝不删 S.shots。 */

/** 手调过的集数，二次确认文案用。 */
export function manualEpisodeCount() {
  return S.episodes.filter((ep) => ep && ep.source === "manual").length;
}

/** 只标 stale，不动 S.shots：镜头留在表里，等 S4 逐集重跑后归位。 */
function invalidateShotsForPlan() {
  const byEp = {};
  S.episodes.forEach((ep) => { byEp[ep.no] = "stale"; });
  if (!S.episodes.length) byEp.all = "stale";
  S.steps.shots.byEp = byEp;
  if (S.shots.length) S.steps.shots.status = "stale";
}

/** 显式重算分集：按钮触发；已有方案时先二次确认并列出将覆盖的手调结果。 */
export function planStep(opts) {
  const skipConfirm = !!(opts && opts.skipConfirm);
  if (S.planBusy || S.aiBusy) { toast("分集正在生成，等这一轮结束再操作", "warn"); return Promise.resolve(false); }
  if (!S.script.replace(/\s/g, "")) { toast("先放一段剧本文字进来", "warn"); return Promise.resolve(false); }
  if (!S.parsed) reparse();
  if (!S.parsed || !S.parsed.scenes.length) { toast("剧本还没解析出场次，先整理稿子", "warn"); return Promise.resolve(false); }
  const manual = manualEpisodeCount();
  if (!skipConfirm && S.episodes.length) {
    const msg = "重算分集会覆盖当前 " + S.episodes.length + " 集方案，其中 " + manual + " 集是你手调过的。\n"
      + "将覆盖 " + manual + " 集手调结果；已排好的镜头不会删除，但会全部标记「需重算」。\n确定继续吗？";
    if (!window.confirm(msg)) return Promise.resolve(false);
  }
  S.planBusy = true;
  S.steps.plan.status = "running";
  S.steps.plan.at = Date.now();
  const wanted = S.episodeMode === "none" ? 1 : S.episodeMode;
  const useAI = !FORCE_LOCAL && S.llmAvailable && S.aiEnabled;
  const apply = (episodes, engine, model) => {
    begin();
    S.episodes = episodes.map((ep, i) => Object.assign({}, ep, { no: i + 1 }));
    S.episodes.forEach((ep) => { ep.source = engine === "ai" ? "ai" : "local"; });
    S.episodeSource = engine === "ai" ? "ai" : "local";
    if (model) S.aiModel = model;
    S.steps.plan = { status: "ready", at: Date.now(), engine: engine, model: model || "" };
    invalidateShotsForPlan();
    S.activeEpisode = "all";
    S.planBusy = false;
    save();
    toast((engine === "ai" ? "AI 已重新分成 " : "已按本地规则分成 ") + S.episodes.length + " 集；第 3 步需逐集重排镜头",
      engine === "ai" ? "ok" : "warn");
  };
  if (!useAI) {
    // 离线 / 无模型：本地规则兜底，第 2 步照样能出方案
    setTimeout(() => {
      try { apply(E.localEpisodes(S.parsed, wanted), "local", ""); }
      catch (err) {
        S.planBusy = false;
        S.steps.plan.status = S.episodes.length ? "ready" : "idle";
        toast("分集失败：" + err.message, "err");
      }
    }, 0);
    return Promise.resolve(true);
  }
  return AI.plan(S.script, S.parsed, wanted)
    .then((p) => {
      const eps = (p && p.episodes) || [];
      if (!eps.length) throw new Error("AI 没有给出有效的分集方案");
      apply(eps, "ai", (p && p.model) || S.llmModel || "");
      return true;
    })
    .catch((err) => {
      // AI 失败降级本地规则：不发第二次请求，也不改引擎的分集规则
      apply(E.localEpisodes(S.parsed, wanted), "local", "");
      toast("AI 分集失败，已降级本地规则：" + ((err && err.message) || "未知原因"), "warn");
      return false;
    });
}

/** 分集表编辑：集号重排 + 作废下游；镜头一个不删、一个不改。 */
function commitEpisodeEdit() {
  S.episodes.forEach((ep, i) => { ep.no = i + 1; });
  S.episodeSource = "manual";
  invalidateShotsForPlan();
  save();
}
export function editEpisode(no, patch) {
  const ep = S.episodes.find((e) => Number(e.no) === Number(no));
  if (!ep) return;
  begin();
  if (patch.title !== undefined) ep.title = String(patch.title).slice(0, 40);
  if (patch.sceneFrom !== undefined) {
    ep.sceneFrom = Math.max(1, Number(patch.sceneFrom) || 1);
    if (ep.sceneFrom > Number(ep.sceneTo)) ep.sceneTo = ep.sceneFrom;
  }
  if (patch.sceneTo !== undefined) {
    ep.sceneTo = Math.max(1, Number(patch.sceneTo) || 1);
    if (ep.sceneTo < Number(ep.sceneFrom)) ep.sceneFrom = ep.sceneTo;
  }
  ep.source = "manual";
  commitEpisodeEdit();
}
export function splitEpisode(no) {
  const idx = S.episodes.findIndex((e) => Number(e.no) === Number(no));
  if (idx < 0) return;
  const ep = S.episodes[idx];
  if (Number(ep.sceneTo) <= Number(ep.sceneFrom)) { toast("这一集只有一场，没法再拆", "warn"); return; }
  const mid = Math.floor((Number(ep.sceneFrom) + Number(ep.sceneTo)) / 2);
  begin();
  const base = ep.title || ("第" + ep.no + "集");
  const tail = Object.assign({}, ep, {
    sceneFrom: mid + 1, sceneTo: Number(ep.sceneTo), title: (base + " · 后半").slice(0, 40)
  });
  ep.sceneTo = mid; ep.title = (base + " · 前半").slice(0, 40);
  ep.source = "manual"; tail.source = "manual";
  S.episodes.splice(idx + 1, 0, tail);
  commitEpisodeEdit();
  toast("已拆成两集；第 3 步镜头需重排", "ok");
}
export function mergeEpisode(no) {
  const idx = S.episodes.findIndex((e) => Number(e.no) === Number(no));
  if (idx < 0 || idx + 1 >= S.episodes.length) { toast("已经是最后一集了", "warn"); return; }
  begin();
  const a = S.episodes[idx], b = S.episodes[idx + 1];
  a.sceneFrom = Math.min(Number(a.sceneFrom), Number(b.sceneFrom));
  a.sceneTo = Math.max(Number(a.sceneTo), Number(b.sceneTo));
  a.title = ((a.title || "第" + a.no + "集") + " + " + (b.title || "第" + b.no + "集")).slice(0, 40);
  a.source = "manual";
  S.episodes.splice(idx + 1, 1);
  commitEpisodeEdit();
  toast("已与下一集合并；第 3 步镜头需重排", "ok");
}
export function deleteEpisode(no) {
  const idx = S.episodes.findIndex((e) => Number(e.no) === Number(no));
  if (idx < 0) return;
  if (S.episodes.length <= 1) { toast("至少保留一集", "warn"); return; }
  begin();
  S.episodes.splice(idx, 1);
  S.episodes.forEach((ep) => { ep.source = "manual"; });
  commitEpisodeEdit();
  toast("已删掉一集；镜头仍在表里，第 3 步逐集重排后归位", "ok");
}

/* ---------------------- S4 · 分镜逐集闸门 ----------------------
   只请求一集（复用 AI.storyboard 本来的按集切片）；成功只替换 shots[].key 属于该集的镜头，
   其它集一个不动；失败只把该集标 failed，不弹全屏遮罩、不降级覆盖别人的镜头。
   D4：没有「剩余全部 / 全部生成」入口，一次点击只推进一集。 */

/** 未分集时整部片子当作一个隐式闸门，key 用 "all"，集号记 0（保持全局镜号）。 */
function shotGateEp(key) {
  if (String(key) === "all") {
    const nos = ((S.parsed && S.parsed.scenes) || []).map((s) => Number(s.no) || 0);
    return { no: 0, title: "本片", sceneFrom: nos.length ? Math.min(...nos) : 1,
             sceneTo: nos.length ? Math.max(...nos) : 1 };
  }
  return S.episodes.find((e) => String(e.no) === String(key)) || null;
}

/** 离线规则：只取这一集场次范围内的镜头，字段与 AI 回包对齐后交给 AI.toShots。 */
function localGateShots(ep) {
  const all = E.buildStoryboard(S.parsed, S.config, S.variant);
  const picked = ep.no ? all.filter((s) => s.sceneNo >= ep.sceneFrom && s.sceneNo <= ep.sceneTo) : all;
  return picked.map((s) => ({
    sceneNo: s.sceneNo, kind: s.kind, visual: s.visual, size: s.size,
    duration: s.duration, dialogue: s.dialogue, speaker: s.speaker,
    notes: s.notes, ai: false, detail: E.normalizeDetail(s.detail)
  }));
}

/** 该集镜头的归属：优先用稳定键前缀，旧数据退回 episode 字段。 */
function shotBelongsToGate(shot, key, ep) {
  if (String(key) === "all") return true;
  const prefix = "e" + E.pad2(Number(ep.no)) + "-";
  const k = String(shot.key || "");
  return k ? k.indexOf(prefix) === 0 : String(shot.episode) === String(ep.no);
}

/** 逐集闸门：一次只处理一集，返回 Promise<boolean>。 */
export function storyboardStep(epKey) {
  const key = String(epKey);
  const byEp = S.steps.shots.byEp;
  if (Object.keys(byEp).some((k) => byEp[k] === "running")) {
    toast("有一集正在生成，等这一集结束再点", "warn"); return Promise.resolve(false);
  }
  if (!S.script.replace(/\s/g, "")) { toast("先放一段剧本文字进来", "warn"); return Promise.resolve(false); }
  if (!S.parsed) reparse();
  if (!S.parsed || !S.parsed.scenes.length) { toast("剧本还没解析出场次，先整理稿子", "warn"); return Promise.resolve(false); }
  const ep = shotGateEp(key);
  if (!ep) { toast("找不到这一集，可能分集方案已改", "warn"); return Promise.resolve(false); }
  begin();
  byEp[key] = "running";
  S.steps.shots.at = Date.now();
  if (!S.steps.shots.errors) S.steps.shots.errors = {};
  delete S.steps.shots.errors[key];
  save();

  const apply = (raws, engine, model) => {
    const fresh = E.bindAssets(AI.toShots([raws], [ep], S.parsed, S.config), S.assets);
    const kept = S.shots.filter((s) => !shotBelongsToGate(s, key, ep));
    let at = kept.length;
    if (ep.no) {
      const later = kept.findIndex((s) => Number(s.episode) > Number(ep.no));
      if (later >= 0) at = later;
    }
    const merged = kept.slice(0, at).concat(fresh, kept.slice(at));
    S.shots = E.renumberShots(merged, S.episodes);   // 统一重排镜号与稳定键
    S.shots.forEach((s) => { s.originCode = s.code; });
    const ids = {};
    S.shots.forEach((s) => { ids[s.id] = 1; });
    S.selected = (S.selected || []).filter((id) => ids[id]);
    S.activeId = ids[S.activeId] ? S.activeId : (S.shots.length ? S.shots[0].id : null);
    S.activeEpisode = "all";
    byEp[key] = "ready";
    delete S.steps.shots.errors[key];
    S.steps.shots.status = "ready";
    S.steps.shots.at = Date.now();
    if (engine === "ai") { S.aiSource = "ai"; if (model) S.aiModel = model; }
    else if (!S.aiSource) S.aiSource = "local";
    save();
    toast((ep.no ? "第 " + ep.no + " 集" : "本片") + "已生成 " + fresh.length +
      " 镜；其它集未改动", "ok", "撤销", undo);
  };
  const fail = (err) => {
    byEp[key] = "failed";
    S.steps.shots.errors[key] = (err && err.message) || "生成失败";
    save();
    toast((ep.no ? "第 " + ep.no + " 集" : "本片") + "生成失败，可单独重试：" +
      S.steps.shots.errors[key], "warn");
    return false;
  };
  const useAI = !FORCE_LOCAL && S.llmAvailable && S.aiEnabled;
  if (!useAI) {
    // 离线 / 没配模型：本地规则只排这一集，仍然是一集一个闸门
    return new Promise((resolve) => setTimeout(() => {
      try { apply(localGateShots(ep), "local", ""); resolve(true); }
      catch (err) { resolve(fail(err)); }
    }, 0));
  }
  return AI.storyboard(S.script, S.parsed, ep, S.config)
    .then((r) => {
      const raws = (r && r.shots) || [];
      if (!raws.length) throw new Error("AI 没有给出这一集的镜头");
      apply(raws, "ai", (r && r.model) || S.llmModel || "");
      return true;
    })
    .catch(fail);
}

/* --------------------------- 导航 / 输入 --------------------------- */
export function goStep(n) {
  n = Math.max(1, Math.min(4, Number(n) || 1));
  if (n > 1 && !S.script.replace(/\s/g, "")) { toast("先导入剧本文字", "warn"); return; }
  if (n >= 3 && !S.parsed) { toast("先在第 2 步完成 AI 拆解", "warn"); return; }
  if (n === 4 && !S.shots.length) { toast("还没有镜头，先在第 3 步排分镜，再来定妆", "warn"); return; }
  S.step = n; window.scrollTo(0, 0); save();
  // S3：进第 2 步不再自动附带分集，方案一律由「生成 / 重算分集」按钮显式产出。
}
export function goStep2() {
  if (!S.script.replace(/\s/g, "")) { toast("先放一段剧本文字进来", "warn"); return; }
  reparse(); S.step = 2; window.scrollTo(0, 0); save();
}
export function setInputTab(tab) { S.inputTab = tab; }
export function onScriptInput(e) {
  S.script = e.target.value;
  S.sourceKind = E.classifySource(S.script).kind;
  S.normReport = null;
  reparse(); markStale("script"); save();
}

export function setScript(text, note) {
  begin();
  S.script = text;
  reparse();
  markStale("script");
  save();
  toast(note, "ok", "撤销", undo);
}
export const loadSample = () => setScript(E.SAMPLE_SCRIPT, "已载入《雨夜便利店》示例剧本");
export const loadProblem = () => setScript(E.SAMPLE_PROBLEM_SCRIPT, "已载入待补全示例，去第 2 步看体检卡");
export const loadGuihun = () => setScript(GUIHUN_SCRIPT, "已载入《鬼婚，逃命》第一章 · 10 场 19 句对白");
export const clearScript = () => setScript("", "已清空剧本");

/* --------------------------- 第一步：改剧本 --------------------------- */
export const KIND_LABEL = { scene: "标准场次剧本", simple: "简易剧本", prose: "小说 / 散文体", empty: "空稿" };

/** 导入一份新稿子：记原文、判类型、清掉上一份的规范化报告。 */
export function setSource(text, note) {
  begin();
  S.script = String(text || "");
  S.rawSource = S.script;
  S.sourceKind = E.classifySource(S.script).kind;
  S.normReport = null;
  reparse();
  markStale("script");
  save();
  if (note) toast(note, "ok", "撤销", undo);
}

/** 本地补场次头：只补「第N场」，不编内外景/地点/时间，零 AI 成本。 */
export function normalizeNow() {
  if (!S.script.trim()) { toast("先把稿子放进来", "warn"); return; }
  const r = E.normalizeLocal(S.script);
  if (!r.changed) {
    toast(r.reason === "already" ? "已经有场次头了，不用再补" : "没识别到可切分的段落，先按空行分段", "warn");
    return;
  }
  begin();
  S.script = r.script;
  S.sourceKind = E.classifySource(r.script).kind;
  S.normReport = { mode: "local", scenes: r.scenes, at: Date.now() };
  reparse(); markStale("script"); save();
  toast("已按空行补出 " + r.scenes + " 个场次头；缺的内外景 / 地点 / 时间去第 2 步体检补",
    "ok", "撤销", undo);
}

/** 还原到导入时的原文（转写 / 本地规范化之后想重来）。 */
export function restoreRawSource() {
  if (!S.rawSource || !S.rawSource.trim()) { toast("没有保留的原文", "warn"); return; }
  begin();
  S.script = S.rawSource;
  S.sourceKind = E.classifySource(S.rawSource).kind;
  S.normReport = null;
  reparse(); markStale("script"); save();
  toast("已还原到导入时的原文", "ok", "撤销", undo);
}

/**
 * AI 忠实转写：把小说 / 散文体变成标准场次剧本。
 * 服务端只让模型输出「哪几句属于哪一场」的结构，正文由原句逐字拼回，
 * 所以这里能给出「句子保留 X/Y、引语保留 A/B」的可验证覆盖率。
 */
export function adaptNovel() {
  if (!S.script.trim()) { toast("先粘贴一段小说 / 散文原文", "warn"); return; }
  if (FORCE_LOCAL || !S.llmAvailable || !S.aiEnabled) {
    toast("小说转写需要开启 AI 模式（当前是离线规则引擎）", "err"); return;
  }
  if (S.aiBusy) return;
  const src = S.script;
  const keepRaw = S.rawSource && S.rawSource.trim() ? S.rawSource : src;
  S.aiBusy = true; S.aiStage = "adapt";
  busy(true, "AI 正在忠实转写成场次剧本…");
  AI.adaptNovel(src).then((r) => {
    busy(false); S.aiBusy = false; S.aiStage = "";
    if (!r.script || r.script.length < 40) throw new Error("转写结果为空");
    const cv = r.coverage || {};
    begin();
    S.script = r.script;
    S.rawSource = keepRaw;
    S.sourceKind = E.classifySource(r.script).kind;
    S.normReport = {
      mode: "ai", at: Date.now(),
      scenes: cv.sceneHeads || 0,
      sentencesTotal: cv.sentencesTotal || 0,
      sentencesCovered: cv.sentencesCovered || 0,
      quotesTotal: cv.quotesTotal || 0,
      quotesCovered: cv.quotesCovered || 0,
      fromChars: src.replace(/\s/g, "").length,
      toChars: r.script.replace(/\s/g, "").length,
      warnings: (r.warnings || []).slice(0, 5)
    };
    reparse(); markStale("script"); save();
    toast("已转成 " + (cv.sceneHeads || 0) + " 场剧本；原文可用「撤销」或「还原原文」找回", "ok");
    (r.warnings || []).forEach((w) => toast("转写校验：" + w, "warn"));
  }).catch((err) => {
    busy(false); S.aiBusy = false; S.aiStage = "";
    toast("转写失败：" + err.message + "，原文未改动", "err");
  });
}

/** 上传：.txt/.md 走浏览器直读；.docx 交后端用标准库解 OOXML；.doc 明确拒绝并给出路。 */
export function readScriptFile(file) {
  if (!file) return;
  const name = String(file.name || "");
  const lower = name.toLowerCase();

  if (/\.docx$/.test(lower)) {
    if (ui.importBusy) return;
    ui.importBusy = true;
    const reader = new FileReader();
    reader.onload = () => {
      const bytes = new Uint8Array(reader.result || new ArrayBuffer(0));
      let bin = "";
      for (let i = 0; i < bytes.length; i += 0x8000) {
        bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
      }
      AI.importDocx(name, btoa(bin)).then((r) => {
        ui.importBusy = false;
        S.inputTab = "paste";
        setSource(r.text, "已从 " + name + " 读出 " + r.chars + " 字 · " + (KIND_LABEL[r.kind] || ""));
      }).catch((err) => {
        ui.importBusy = false;
        toast("读 " + name + " 失败：" + err.message, "err");
      });
    };
    reader.onerror = () => { ui.importBusy = false; toast("读文件失败，请重试", "err"); };
    reader.readAsArrayBuffer(file);
    return;
  }

  if (/\.(doc|wps|wpt)$/.test(lower)) {
    toast("老式 .doc / .wps 是二进制格式，读不了。请在 Word 里「另存为」.docx 或 .txt 再上传", "warn");
    return;
  }
  if (!/\.(txt|md|text|markdown)$/.test(lower) && file.type && !/^text\//.test(file.type)) {
    toast("只支持 .txt / .md / .docx；其他格式请先另存为 .txt", "warn");
    return;
  }

  const reader = new FileReader();
  reader.onload = () => {
    S.inputTab = "paste";
    setSource(String(reader.result || ""), "已读取 " + name);
  };
  reader.onerror = () => toast("读文件失败，请换一个 .txt 试试", "err");
  reader.readAsText(file, "utf-8");
}

/* --------------------------- 配置 / 模型 --------------------------- */
export function onConfigChange(e) {
  const t = e.target;
  if (t.dataset.episodes !== undefined) {
    begin();
    S.episodeMode = t.value === "none" ? "none" : (Number(t.value) > 0 ? Number(t.value) : "auto");
    markStale("config"); stalePlanIfAny(); save();
    toast("分集方式已更新，点「重算分集」后生效", "ok");
    return;
  }
  if (t.dataset.cfg !== undefined) {
    const k = t.dataset.cfg;
    const v = t.type === "number" ? Number(t.value) : t.value;
    if (k === "defaultDuration" && (isNaN(v) || v < 2 || v > 12)) {
      t.value = S.config[k]; toast("时长请填 2–12 秒", "warn"); return;
    }
    // 画质只影响导出宽高，不改分镜，别把整片标成过期
    if (k === "videoQuality") {
      begin(); S.config[k] = v; save();
      toast("出片画质已切到 " + v + "，下次导出按新宽高计算", "ok");
      return;
    }
    begin(); S.config[k] = v; markStale("config"); save();
    toast("设置已更新，可点「按当前设置重排」生效", "ok");
  } else if (t.dataset.cfgToggle !== undefined) {
    begin(); S.config[t.dataset.cfgToggle] = t.checked; markStale("config"); save();
  } else if (t.dataset.uiToggle !== undefined) {
    S[t.dataset.uiToggle] = t.checked; save();
  }
}

export function llmParse() {
  busy(true, "大模型正在理解剧本…");
  fetch("api/llm/parse", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ script: S.script })
  }).then((r) => r.json().then((j) => ({ ok: r.ok, j })))
    .then((res) => {
      busy(false);
      if (!res.ok || !res.j || !Array.isArray(res.j.scenes)) throw new Error((res.j && res.j.detail) || "大模型返回格式不对");
      begin();
      const remote = res.j.scenes;
      S.parsed.scenes.forEach((sc, i) => {
        const r = remote[i]; if (!r) return;
        ["intExt", "location", "time"].forEach((k) => { if (r[k]) sc[k] = String(r[k]); });
        if (Array.isArray(r.characters) && r.characters.length) sc.characters = r.characters.map(String);
      });
      S.issues = E.diagnose(S.script, S.parsed);
      markStale("script"); save();
      toast("大模型理解完成，场景信息已更新；分镜编排仍由规则引擎完成", "ok", "撤销", undo);
    })
    .catch((err) => { busy(false); toast("LLM 没成功：" + err.message + "。已保留本地拆解结果，不影响继续使用。", "err"); });
}

export function aiRedo() {
  if (S.aiBusy) { toast("AI 正在生成，稍等一下", "warn"); return; }
  if (FORCE_LOCAL) { toast("当前是 ?ai=0 离线对比模式，去掉参数即可启用 AI", "warn"); return; }
  if (!S.llmAvailable) { toast("AI 需要本机服务，双击 start.bat 启动后再试", "warn"); return; }
  if (!S.aiEnabled) { S.aiEnabled = true; save(); }
  doGenerate("force");
}

/* --------------------------- Step 2 --------------------------- */
export function applyFix(idx) {
  const issue = S.issues[idx]; if (!issue || !issue.fix) return;
  const fix = Object.assign({}, issue.fix);
  if (fix.type === "input") {
    const val = String(ui.fixInputs[idx] || "").trim();
    if (!val) { toast("先填一个地点再点应用", "warn"); return; }
    fix.value = val;
  }
  begin();
  S.script = E.applyFix(S.script, fix, S.parsed);
  reparse(); markStale("script"); save();
  toast("已补全：" + issue.title, "ok", "撤销", undo);
}
export function fixAll() {
  const done = {}; let applied = 0, guard = 0;
  begin();
  while (guard++ < 14) {
    const next = S.issues.filter((i) => i.fix && ["auto", "alias", "clean-head"].includes(i.fix.type) && !done[i.code])[0];
    if (!next) break;
    done[next.code] = 1;
    S.script = E.applyFix(S.script, next.fix, S.parsed);
    reparse(); applied += 1;
  }
  if (!applied) { S.undo.pop(); toast("没有可自动补全的项，地点需要你手动确认", "warn"); return; }
  markStale("script"); save();
  toast("已自动补全 " + applied + " 项，还剩 " + S.issues.length + " 项需人工确认", "ok", "撤销", undo);
}
export function toggleScene(order) { ui.openScenes[order] = !ui.openScenes[order]; }
