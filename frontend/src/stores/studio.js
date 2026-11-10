/* =========================================================================
 * 分镜工场 · 响应式状态层
 * 只管数据、流程与副作用，不碰 DOM；渲染全部交给 Vue 组件。
 * 引擎（lib/engine.js）与 AI 编排（lib/ai.js）是浏览器 / Node 共用的纯逻辑。
 * ========================================================================= */
import { computed, reactive } from "vue";
import E from "../lib/engine.js";
import AI from "../lib/ai.js";
import Projects from "../lib/projects.js";
import { GUIHUN_SCRIPT } from "../lib/sampleGuihun.js";

export { E, AI };

const CACHE_KEY = "shortplay-project-cache";   // 当前项目缓存（离线兜底）
const LAST_KEY = "shortplay-last-project";     // 上次打开的项目 id
export const FORCE_LOCAL = /[?&]ai=0(?:&|$)/.test(location.search);
const clone = (o) => JSON.parse(JSON.stringify(o));

/* ---------------------- 剧本视觉风格（跨资产 / 出图 / 起始帧） ---------------------- */
/* 英文锚给本地 Flux 用，只写画种 / 材质 / 光线 / 色调，绝不写人物与剧情。
   中文锚给起始帧长提示词与导出文档用。两端默认值必须和 server.py 保持一致。 */
export const STYLE_FALLBACK_CN = "写实电影质感 · 35mm 胶片颗粒 · 冷调 · 无滤镜磨皮";
export const STYLE_FALLBACK_EN = ("photorealistic cinematic film still, 35mm film grain, "
  + "cool desaturated color grade, natural skin texture, no beautification filter");
export const STYLE_PRESETS = [
  { key: "film", label: "写实电影", anchor: STYLE_FALLBACK_CN, anchorEn: STYLE_FALLBACK_EN },
  { key: "folk", label: "中式民俗恐怖",
    anchor: "中式民俗恐怖 · 写实电影质感 · 35mm 胶片颗粒 · 冷调 · 无滤镜磨皮",
    anchorEn: "Chinese folk horror, photorealistic cinematic film still, 35mm film grain, dim cold light, desaturated earthy palette, natural skin texture" },
  { key: "neon", label: "赛博霓虹",
    anchor: "赛博霓虹夜景 · 高对比冷暖撞色 · 湿地面反光 · 电影质感",
    anchorEn: "cyberpunk neon night, high contrast teal and magenta lighting, wet reflective surfaces, cinematic film still" },
  { key: "ink", label: "水墨国风",
    anchor: "水墨国风 · 留白构图 · 淡彩晕染 · 宣纸质地",
    anchorEn: "traditional Chinese ink wash painting, minimalist negative space, soft watercolor washes, rice paper texture" },
  { key: "anime", label: "日系动画",
    anchor: "日系动画赛璐璐 · 平涂色块 · 干净线稿 · 柔和光影",
    anchorEn: "Japanese anime cel shading, flat color blocks, clean line art, soft ambient lighting" },
  { key: "bw", label: "黑白胶片",
    anchor: "黑白胶片 · 高反差硬光 · 粗颗粒 · 纪实感",
    anchorEn: "black and white analog film photography, high contrast hard lighting, heavy grain, documentary realism" },
  { key: "3d", label: "3D 渲染",
    anchor: "3D 渲染 · 全局光照 · 干净材质 · 柔和影棚光",
    anchorEn: "high end 3D render, global illumination, clean PBR materials, soft studio lighting" }
];

/* ------------------------------ 状态 ------------------------------ */
/** 分步流程的每步状态：idle 没做 / running 正在做 / ready 已完成 / stale 上游改过、需重算 */
function defaultSteps() {
  return {
    script: { status: "idle", at: 0 },
    plan:   { status: "idle", at: 0, engine: "", model: "" },
    shots:  { status: "idle", at: 0, byEp: {}, errors: {} },
    assets: { status: "idle", at: 0 }
  };
}
function defaultState() {
  return {
    step: 1, script: "", parsed: null, issues: [], shots: [],
    config: clone(E.DEFAULT_CONFIG), variant: 0,
    selected: [], activeId: null, view: "card", stale: "", steps: defaultSteps(),
    overwriteEdited: false, aiMode: "local", llmAvailable: false, llmModel: "", llmProvider: "",
    meta: { title: "" },
    episodes: [], activeEpisode: "all", episodeMode: "auto",
    aiEnabled: true, aiBusy: false, aiStage: "", planBusy: false,
    aiSource: "", episodeSource: "", aiModel: "", aiDegraded: [], aiWarnings: [],
    undo: [], redo: [], inputTab: "paste",
    assets: { characters: [], scenes: [], props: [] },  // 角色 / 场景 / 道具资产
    assetTab: "character",
    // 资产包（AI 分解产物）：编号 / 优先级 / 三锚点 / 固定关键词串 / 提示词 / 溯源
    assetPack: null, assetWarnings: [], assetBusy: false, assetModel: "",
    frames: [], frameStats: null,     // 每镜起始帧提示词（资产包 + 分镜表 → 出片首帧）
    // 剧本级视觉风格：独立于 assetPack，没跑 AI 分解也能定义；key/anchor/anchorEn 为空 = 跟随 AI 或内置默认
    styleConfig: { key: "", anchor: "", anchorEn: "" },
    // 第一步「改剧本」：导入时的原文 / 稿件类型 / 最近一次规范化报告
    rawSource: "", sourceKind: "", normReport: null,
    // 当前项目（Studio 式）：id 对应服务端 projects/<id>/，name 显示在顶栏
    projectId: "", projectName: ""
  };
}

export const S = reactive(defaultState());

/** 纯 UI 状态：不进撤销快照、不落 localStorage */
export const ui = reactive({
  busy: false, busyText: "正在处理…",
  toasts: [], modal: null,          // modal: { type: "help" | "settings" | "projects" }
  exportOpen: false, saveNote: "正在打开项目…",
  saveState: "idle",                // idle | saving | saved | error | local
  projects: [], projectBusy: false, projectError: "",
  openScenes: {}, fixInputs: {},
  propDraft: "", assetOpen: false, refUpload: "", importBusy: false,
  // 纯 UI 状态：ComfyUI 连接 / 批量出图队列，不进 localStorage
  comfy: {
    online: false, checked: false, checking: false, detail: "",
    version: "", vramFreeMB: 0, host: "", model: "",
    variants: { character: [], scene: [], prop: [] },
    scope: "one", picked: { character: ["turnaround"], scene: ["concept"], prop: ["prop"] },
    jobId: "", busy: false, done: 0, total: 0, current: "",
    errors: [], results: [], filling: "",
    preview: null, previewBusy: false,
    engine: "comfy", seqN: 1,
    qwen: { online: false, model: "", size: "", detail: "" }
  },
  // 语言模型接入（列表 / 当前生效 / 测试结果）：纯界面态，不进撤销、不落盘
  models: {
    list: [], active: "", env: null, loaded: false,
    busy: "", testing: "", result: null
  },
  // 出图引擎配置（全局单例，与语言模型的分条列表不同）：纯界面态，不进撤销
  engine: {
    loaded: false, busy: "", testing: "", result: null,
    config: {}, models: [], modelsBusy: false, modelsHost: ""
  },
  // 后端拆解任务的实时进度（纯界面态：不进撤销快照、不落盘，刷新后由 /api/parse/latest 接回）
  parse: {
    visible: false, id: "", project: "", status: "queued", percent: 0, done: 0, total: 7,
    stage: "", stageLabel: "", stages: [], events: [],
    error: "", hint: "", startedAt: 0, elapsed: 0, live: "", result: null
  }
});

/** 项目库是否连上（file:// 或服务未启动时为 false，走本机缓存兜底） */
export const PROJECT = reactive({ ready: false, server: false, error: "" });

let pendingBaseline = null;
let toastSeq = 0;
let saveTimer = null;

/* --------------------------- 撤销 / 持久化 --------------------------- */
// 参考图是 dataURL，体积大：撤销快照里剔掉，回退时按 id 从当前资产补回来，
// 这样撤销栈不会因为几张图被撑爆，同时又不会因为撤销把图弄丢。
// 生成的多张素材图同样是 dataURI，撤销快照里也要剔掉，否则几张图就把栈撑爆
function stripImg(a) {
  var c = Object.assign({}, a);
  delete c.refImage;
  delete c.genImages;
  return c;
}
function snapshot() {
  return JSON.stringify({
    step: S.step, script: S.script, parsed: S.parsed, issues: S.issues,
    shots: S.shots, config: S.config, variant: S.variant, selected: S.selected,
    styleConfig: S.styleConfig,
    activeId: S.activeId, stale: S.stale, meta: S.meta, steps: S.steps,
    episodes: S.episodes, activeEpisode: S.activeEpisode, aiSource: S.aiSource,
    episodeSource: S.episodeSource, aiModel: S.aiModel,
    aiDegraded: S.aiDegraded, aiWarnings: S.aiWarnings,
    assets: {
      characters: S.assets.characters.map(stripImg),
      scenes: S.assets.scenes.map(stripImg),
      props: S.assets.props.map(stripImg)
    }
  });
}
const REF_KINDS = ["characters", "scenes", "props"];

/* ---------------------- 参考图 / 生成图「图仓」 ----------------------
 * 参考图与生成图都是 dataURI：撤销快照里剔掉了，重新解析剧本 / 资产包合并时也可能
 * 被重建的资产对象洗掉。这里按「资产 id + 名字」另存一份图仓——读项目时灌入，
 * 上传 / 出图 / 设主图时登记，主动移除时注销；每次落盘前把缺图的资产补回来。
 * 目的只有一个：自动保存不可能把已经存在的图写没，刷新丢图从根上堵掉。
 */
const imgBank = Object.create(null);
let bankProject = null;
function bankKeys(a) {
  const out = [String(a.id || "")];
  if (a.name) out.push("n:" + a.name);
  return out.filter(Boolean);
}
function bankNote(a) {
  if (!a) return;
  const ref = a.refImage || "", gen = (a.genImages || []).slice();
  if (!ref && !gen.length) { bankForget(a); return; }
  const ent = { refImage: ref, refName: a.refName || "", genImages: gen };
  bankKeys(a).forEach(function (k) { imgBank[k] = ent; });
}
function bankForget(a) {
  if (!a) return;
  bankKeys(a).forEach(function (k) { delete imgBank[k]; });
}
/** 换项目时必须清仓，否则两个项目的同名角色会串图 */
function bankScope(pid) {
  const id = String(pid || "");
  if (bankProject === id) return false;
  Object.keys(imgBank).forEach(function (k) { delete imgBank[k]; });
  bankProject = id;
  return true;
}
function bankLoad(assets, pid) {
  bankScope(pid);
  if (!assets) return;
  REF_KINDS.forEach(function (k) { (assets[k] || []).forEach(bankNote); });
}
function bankApply(assets, pid) {
  bankScope(pid);
  REF_KINDS.forEach(function (k) {
    (assets[k] || []).forEach(function (a) {
      const ent = imgBank[String(a.id || "")] || imgBank["n:" + (a.name || "")];
      if (!ent) return;
      if (!a.refImage && ent.refImage) {
        a.refImage = ent.refImage;
        a.refName = a.refName || ent.refName;
      }
      if (!(a.genImages || []).length && ent.genImages.length) a.genImages = ent.genImages.slice();
    });
  });
  return assets;
}
function remergeImages(next) {
  var cur = {};
  REF_KINDS.forEach(function (k) {
    (S.assets[k] || []).forEach(function (a) {
      cur[a.id] = { refImage: a.refImage, refName: a.refName, genImages: a.genImages };
    });
  });
  REF_KINDS.forEach(function (k) {
    (next[k] || []).forEach(function (a) {
      if (!cur[a.id]) return;
      if (!a.refImage && cur[a.id].refImage) {
        a.refImage = cur[a.id].refImage;
        a.refName = a.refName || cur[a.id].refName;
      }
      if (!a.genImages && cur[a.id].genImages) a.genImages = cur[a.id].genImages;
    });
  });
  return next;
}
export function begin() {
  S.undo.push(snapshot());
  if (S.undo.length > 60) S.undo.shift();
  S.redo.length = 0;
}
function restore(str) {
  const s = JSON.parse(str);
  // 撤销只回退数据，不把用户当前所在的步骤一起拽走
  Object.keys(s).forEach((k) => { if (k !== "step") S[k] = s[k]; });
  if (s.assets) S.assets = remergeImages(s.assets);
  save();
}
export function undo() {
  if (!S.undo.length) { toast("没有可撤销的操作", "warn"); return; }
  S.redo.push(snapshot()); restore(S.undo.pop()); toast("已撤销", "ok");
}
export function redo() {
  if (!S.redo.length) { toast("没有可重做的操作", "warn"); return; }
  S.undo.push(snapshot()); restore(S.redo.pop()); toast("已重做", "ok");
}

/* ========================= 项目（Studio 式） =========================
 * 真源在服务端：projects/<id>/project.json 存整份状态（剧本 / 分镜 / 资产 /
 * 资产包 / 起始帧 / 风格，含参考图 dataURI）。浏览器只缓存「当前项目」用于
 * 首屏秒开与离线兜底——不再把几 MB 图片塞进 5MB 的 localStorage，
 * 也就不会出现「配额写满 → 刷新后回到空白」。
 * ==================================================================== */

/** 参与持久化的字段；新增状态字段时记得加到这里，否则刷新会丢。 */
const PERSIST_KEYS = [
  "step", "script", "variant", "shots", "selected", "activeId", "view", "stale", "steps",
  "meta", "overwriteEdited", "episodes", "activeEpisode", "episodeMode",
  "aiEnabled", "aiSource", "episodeSource", "aiModel", "aiDegraded", "aiWarnings",
  "assetTab", "assetPack", "assetWarnings", "assetModel", "frames", "frameStats",
  "rawSource", "sourceKind", "normReport"
];

export function projectData() {
  const out = {};
  PERSIST_KEYS.forEach((k) => { out[k] = S[k]; });
  out.config = S.config;
  out.styleConfig = S.styleConfig;
  out.assets = bankApply(S.assets, S.projectId);   // 兜底：缺图的资产先从图仓补回来
  out.stepV = 2;   // 步骤号语义版本：2 = 工作区 3 分镜 / 4 定妆
  return out;
}

function blankProjectData() {
  const b = defaultState();
  const out = {};
  PERSIST_KEYS.forEach((k) => { out[k] = b[k]; });
  out.config = b.config;
  out.styleConfig = b.styleConfig;
  out.assets = b.assets;
  out.episodes = [];
  out.activeEpisode = "all";
  out.aiEnabled = S.aiEnabled;
  out.stepV = 2;
  return out;
}

/** 旧存档没有 steps：补默认值，并把旧 S.stale 字符串翻译成下游 stale。 */
function normalizeSteps(raw, staleText) {
  const out = defaultSteps();
  const d = (raw && typeof raw === "object") ? raw : {};
  Object.keys(out).forEach((k) => {
    const v = (d[k] && typeof d[k] === "object") ? d[k] : {};
    if (["idle", "running", "ready", "stale", "failed"].indexOf(v.status) >= 0) out[k].status = v.status;
    out[k].at = Number(v.at) || 0;
    if (k === "plan") { out[k].engine = String(v.engine || ""); out[k].model = String(v.model || ""); }
    if (k === "shots") {
      if (v.byEp && typeof v.byEp === "object" && !Array.isArray(v.byEp)) {
        out[k].byEp = { ...v.byEp };
      }
      // S4：单集失败原因随项目落盘，刷新后仍能看到「为什么红」和重试入口
      if (v.errors && typeof v.errors === "object" && !Array.isArray(v.errors)) {
        out[k].errors = { ...v.errors };
      }
    }
  });
  if (!raw && staleText === "script") { out.plan.status = "stale"; out.shots.status = "stale"; }
  if (!raw && staleText === "config") out.shots.status = "stale";
  return out;
}

/** 整份状态写回 store：先清空再灌入，避免上一个项目的残留（选中项 / 撤销栈）。 */
export function hydrate(data, info) {
  Object.assign(S, defaultState());
  S.projectId = (info && info.id) || "";
  S.projectName = (info && info.name) || "";
  const d = (data && typeof data === "object") ? data : {};
  PERSIST_KEYS.forEach((k) => { if (d[k] !== undefined) S[k] = d[k]; });
  if (d.config) S.config = Object.assign(clone(E.DEFAULT_CONFIG), d.config);
  if (d.styleConfig) S.styleConfig = Object.assign({ key: "", anchor: "", anchorEn: "" }, d.styleConfig);
  if (d.assets) {
    S.assets = Object.assign({ characters: [], scenes: [], props: [] }, d.assets);
    bankLoad(S.assets, S.projectId);
  } else {
    bankScope(S.projectId);
  }
  if (!S.meta || typeof S.meta !== "object") S.meta = { title: "" };
  if (!Array.isArray(S.shots)) S.shots = [];
  if (!Array.isArray(S.episodes)) S.episodes = [];
  S.steps = normalizeSteps(d.steps, S.stale);
  // S3：running 是瞬时态，刷新后按是否已有方案归一，避免按钮永久卡住
  if (S.steps.plan.status === "running") S.steps.plan.status = S.episodes.length ? "ready" : "idle";
  // 旧存档已有分集方案却没有 steps，按「已就绪」归一，别让第 2 步显示「尚未分集」
  if (S.steps.plan.status === "idle" && S.episodes.length) S.steps.plan.status = "ready";
  // S4：running 是瞬时态。刷新/重开页面一律归一为 failed，避免按钮永久卡在「生成中」；
  // 同时补一句人话原因，用户才知道要重新点一次，而不是以为成功了。
  Object.keys(S.steps.shots.byEp).forEach((k) => {
    if (S.steps.shots.byEp[k] === "running") {
      S.steps.shots.byEp[k] = "failed";
      S.steps.shots.errors[k] = "上次生成被中断，重新点一次即可";
    }
  });
  // 旧存档有镜头但还没有逐集状态：按每集是否已有镜头推断，别把已排好的集显示成「未生成」
  if (S.shots.length && !Object.keys(S.steps.shots.byEp).length) {
    if (S.episodes.length) {
      S.episodes.forEach((ep) => {
        S.steps.shots.byEp[ep.no] = S.shots.some((s) => String(s.episode) === String(ep.no))
          ? "ready" : "idle";
      });
    } else {
      S.steps.shots.byEp.all = "ready";
    }
    S.steps.shots.status = "ready";
  }
  S.shots = E.keyShots(S.shots, S.episodes);   // 旧存档补稳定键，只加字段不改内容
  S.step = Number(S.step) || 1;
  // S2 起 3/4 语义对调（3 分镜 / 4 定妆）。旧存档没有 stepV，按旧含义（3 定妆 / 4 分镜）换回来，
  // 否则 29 个已存项目一打开就落在错的工作区。
  if (Number(d.stepV) !== 2 && (S.step === 3 || S.step === 4)) S.step = S.step === 3 ? 4 : 3;
  S.undo = []; S.redo = [];
  if (S.script) reparse();
  // reparse 会重建资产对象（参考图 / 生成图可能被洗掉），用图仓补回来
  bankApply(S.assets, S.projectId);
  // 选中项可能指向已删除的镜头，恢复时剔除，否则批量操作会报空
  const ids = {};
  S.shots.forEach((s) => { ids[s.id] = 1; });
  S.selected = (Array.isArray(S.selected) ? S.selected : []).filter((id) => ids[id]);
  if (S.activeId && !ids[S.activeId]) S.activeId = S.shots.length ? S.shots[0].id : null;
  if (S.step > 4) S.step = 4;
  if (!S.shots.length && S.step === 4) S.step = S.parsed ? 3 : 1;
  if (!S.script && S.step === 2) S.step = 1;
}

/* ------------------------------ 本机缓存 ------------------------------ */
function mirrorCache(id, name, data) {
  if (!id) return false;
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify({ id: id, name: name, at: Date.now(), data: data }));
    localStorage.setItem(LAST_KEY, id);
    return true;
  } catch (_) {
    // 图太多时只缓存文字部分：服务端才是真源，缓存只负责首屏和离线
    try {
      const lite = JSON.parse(JSON.stringify(data));
      REF_KINDS.forEach((k) => {
        ((lite.assets || {})[k] || []).forEach((a) => {
          delete a.genImages;
          // 参考图现在是服务端地址（几十字节），只有老项目的 dataURI 才需要剔掉
          if (/^data:/.test(a.refImage || "")) delete a.refImage;
        });
      });
      localStorage.setItem(CACHE_KEY, JSON.stringify({ id: id, name: name, at: Date.now(), lite: true, data: lite }));
      localStorage.setItem(LAST_KEY, id);
    } catch (_) { /* 隐私模式：完全依赖服务端 */ }
    return false;
  }
}
function readCache() {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (_) { return null; }
}
function restoreCache() {
  const c = readCache();
  if (!c || !c.data) return false;
  const last = localStorage.getItem(LAST_KEY);
  if (last && c.id && last !== c.id) return false;   // 缓存不是上次那个项目，别乱画
  hydrate(c.data, { id: c.id || "", name: c.name || "" });
  return true;
}

/* ------------------------------ 保存 ------------------------------ */
let dirty = false;
let saveFailNotified = false;
let saveChain = Promise.resolve(true);

function stamp() {
  const d = new Date();
  return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
}

/** 自动保存：默认 800ms 合并；切换项目 / 关页面前用 flushSave() 强制落盘。 */
export function save(opts) {
  dirty = true;
  clearTimeout(saveTimer);
  const wait = (PROJECT.server && S.projectId) ? 800 : 250;
  saveTimer = setTimeout(() => { flushSave(); }, (opts && opts.immediate) ? 0 : wait);
}

/** 立即落盘，返回 Promise（切换项目前必须等它，否则会把旧内容写进新项目）。 */
export function flushSave() {
  clearTimeout(saveTimer);
  if (!S.projectId) return Promise.resolve(false);
  const id = S.projectId, name = S.projectName, data = projectData();
  mirrorCache(id, name, data);
  if (!PROJECT.server) {
    dirty = false;
    ui.saveState = "local"; ui.saveNote = "已存本机缓存" + (ui.projectError ? "（服务未连）" : "");
    return Promise.resolve(true);
  }
  ui.saveState = "saving"; ui.saveNote = "保存中…";
  // 串行写入：上一次还没回来就排到后面，避免慢请求把旧内容盖到新内容上
  saveChain = saveChain.catch(() => true).then(() => Projects.save(id, name, data))
    .then((r) => {
      if (S.projectId !== id) return true;     // 期间切走了，别改当前状态文案
      dirty = false;
      saveFailNotified = false;
      ui.saveState = "saved";
      ui.saveNote = "已保存 · " + stamp();
      if (r && r.summary) updateProjectSummary(r.summary);
      return true;
    })
    .catch((err) => {
      if (S.projectId === id) {
        ui.saveState = "error";
        ui.saveNote = "保存失败 · 本机已缓存";
      }
      if (!saveFailNotified) {
        saveFailNotified = true;
        toast("项目没写进磁盘：" + err.message + "（内容已缓存在浏览器，稍后会自动重试）", "err");
      }
      return false;
    });
  return saveChain;
}

function updateProjectSummary(sum) {
  if (!sum || !sum.id || !Array.isArray(ui.projects)) return;
  const i = ui.projects.findIndex((p) => p.id === sum.id);
  if (i >= 0) ui.projects.splice(i, 1, Object.assign({}, ui.projects[i], sum));
  else ui.projects.unshift(sum);
  ui.projects.sort((a, b) => String(b.updatedAt || "").localeCompare(String(a.updatedAt || "")));
}

/* --------------------------- 项目操作 --------------------------- */
function afterOpen(name, silent, note) {
  if (!silent) toast(note || ("已打开项目「" + name + "」"), "ok");
  ui.saveState = "saved";
  ui.saveNote = "已打开 · " + name;
}

/** 生成中切项目会把 AI 结果写进新项目，直接拦住 */
function generating() {
  return !!(ui.busy || S.aiBusy || S.planBusy || S.assetBusy || ui.comfy.busy);
}

export function refreshProjects() {
  if (!PROJECT.server) return Promise.resolve(ui.projects);
  return Projects.list()
    .then((r) => { ui.projects = r.projects || []; return ui.projects; })
    .catch(() => ui.projects);
}

export function openProject(id, opts) {
  if (!id) return Promise.resolve(false);
  if (id === S.projectId && !(opts && opts.force)) return Promise.resolve(true);
  if (!(opts && opts.silent) && generating()) {
    toast("正在生成内容，等这一轮结束再切换项目", "warn");
    return Promise.resolve(false);
  }
  ui.projectBusy = true;
  const ready = (opts && opts.skipSave) ? Promise.resolve(true) : flushSave();
  return ready
    .then(() => Projects.get(id))
    .then((doc) => {
      hydrate(doc.data, { id: doc.id, name: doc.name });
      localStorage.setItem(LAST_KEY, doc.id);
      mirrorCache(doc.id, doc.name, projectData());
      updateProjectSummary({ id: doc.id, name: S.projectName || doc.name, updatedAt: doc.updatedAt });
      afterOpen(S.projectName || doc.name, opts && opts.silent);
      return true;
    })
    .catch((err) => {
      toast("打开项目失败：" + err.message, "err");
      return false;
    })
    .finally(() => { ui.projectBusy = false; });
}

export function newProject(name, opts) {
  const nm = String(name || "").trim() || "未命名项目";
  if (!(opts && opts.silent) && generating()) {
    toast("正在生成内容，等这一轮结束再新建项目", "warn");
    return Promise.resolve(null);
  }
  ui.projectBusy = true;
  const ready = (opts && opts.skipSave) ? Promise.resolve(true) : flushSave();
  return ready
    .then(() => Projects.create(nm, blankProjectData()))
    .then((r) => {
      const p = r.project;
      hydrate(p.data, { id: p.id, name: p.name });
      localStorage.setItem(LAST_KEY, p.id);
      mirrorCache(p.id, p.name, projectData());
      updateProjectSummary({
        id: p.id, name: p.name, createdAt: p.createdAt, updatedAt: p.updatedAt,
        step: 1, shots: 0, episodes: 0, scriptChars: 0, title: "", assets: 0, genImages: 0
      });
      if (!(opts && opts.silent)) { afterOpen(nm); toast("已新建项目「" + nm + "」", "ok"); }
      else afterOpen(nm, true);
      return p;
    })
    .catch((err) => { toast("新建项目失败：" + err.message, "err"); return null; })
    .finally(() => { ui.projectBusy = false; });
}

export function renameProject(id, name) {
  const nm = String(name || "").trim();
  if (!nm) return Promise.resolve(false);
  if (!PROJECT.server) { toast("服务未连接，暂时不能重命名项目", "warn"); return Promise.resolve(false); }
  return Projects.rename(id, nm).then(() => {
    const row = ui.projects.find((p) => p.id === id);
    if (row) row.name = nm;
    if (id === S.projectId) {
      S.projectName = nm;
      mirrorCache(S.projectId, nm, projectData());
      ui.saveNote = "已重命名 · " + nm;
    }
    toast("项目已重命名为「" + nm + "」", "ok");
    return true;
  }).catch((err) => { toast("重命名失败：" + err.message, "err"); return false; });
}

export function duplicateProject(id) {
  if (!PROJECT.server) return Promise.resolve("");
  return Projects.duplicate(id).then((r) => {
    if (r.summary) updateProjectSummary(r.summary);
    toast("已复制为「" + ((r.summary && r.summary.name) || "副本") + "」", "ok");
    return r.id;
  }).catch((err) => { toast("复制失败：" + err.message, "err"); return ""; });
}

export function deleteProject(id) {
  if (!PROJECT.server) { toast("服务未连接，暂时不能删除项目", "warn"); return Promise.resolve(false); }
  const row = ui.projects.find((p) => p.id === id);
  const nm = row ? row.name : "项目";
  return Projects.remove(id).then(() => {
    ui.projects = ui.projects.filter((p) => p.id !== id);
    if (id !== S.projectId) { toast("已删除「" + nm + "」（可在 projects/.trash 找回）", "ok"); return true; }
    // 删的是当前项目：先断开引用，避免自动保存把内容又写回去
    S.projectId = ""; S.projectName = "";
    try { localStorage.removeItem(CACHE_KEY); localStorage.removeItem(LAST_KEY); } catch (_) {}
    if (ui.projects.length) {
      return openProject(ui.projects[0].id, { silent: true })
        .then(() => { toast("已删除「" + nm + "」，已打开「" + S.projectName + "」", "ok"); return true; });
    }
    return newProject("未命名项目", { silent: true })
      .then(() => { toast("已删除「" + nm + "」，已新建空项目", "ok"); return true; });
  }).catch((err) => { toast("删除失败：" + err.message, "err"); return false; });
}

/* ------------------------------ 反馈 ------------------------------ */
export function toast(msg, level = "ok", actionLabel = "", action = null) {
  const id = ++toastSeq;
  ui.toasts.push({ id, msg, level, actionLabel, action });
  while (ui.toasts.length > 3) ui.toasts.shift();
  setTimeout(() => {
    const i = ui.toasts.findIndex((t) => t.id === id);
    if (i >= 0) ui.toasts.splice(i, 1);
  }, actionLabel ? 7000 : 3600);
}
export function runToastAction(t) {
  if (t.action) t.action();
  const i = ui.toasts.findIndex((x) => x.id === t.id);
  if (i >= 0) ui.toasts.splice(i, 1);
}
export function busy(on, text) {
  ui.busy = on;
  if (text) ui.busyText = text;
}
export function openModal(type) { ui.modal = { type }; }
export function closeModal() { ui.modal = null; }

/* --------------------------- 解析 / 生成 --------------------------- */
/**
 * 分镜上的场次标签是老快照：历史数据里存过「第1场 · 未注明」这种脏标签。
 * 只救含占位词的那些，正常标签一律不动，避免误改。
 */
const PH_LABEL_RE = /(未注明|未指定|未标注|未确定|未知|待定|不详)/;
function syncShotLabels() {
  if (!S.parsed || !Array.isArray(S.shots) || !S.shots.length) return 0;
  const map = {};
  S.parsed.scenes.forEach((sc) => { map[sc.no] = E.sceneLabel(sc); });
  let n = 0;
  S.shots.forEach((sh) => {
    if (!PH_LABEL_RE.test(String(sh.sceneLabel || ""))) return;
    const next = map[sh.sceneNo] || ("第" + (sh.sceneNo || 1) + "场");
    if (next !== sh.sceneLabel) { sh.sceneLabel = next; n += 1; }
  });
  return n;
}

export function reparse(opts) {
  S.parsed = E.parseScript(S.script);
  S.issues = E.diagnose(S.script, S.parsed);
  S.meta.title = S.parsed.title;
  syncShotLabels();
  // S5：资产来源可配置。默认以分镜引用为准（shots），剧本只兜底，
  // 避免改一句剧本就把「只在已删镜头里出现」的资产静默清掉。
  // 传 reparse({ assetsFrom: "script" }) 可退回纯剧本重建，便于对照与排错。
  S.assets = (opts && opts.assetsFrom === "script")
    ? E.buildAssets(S.parsed, S.assets)
    : E.assetsFromShots(S.shots, S.parsed, S.assets);
  // buildAssets 只认规则字段，会把资产包的编号/锚点/关键词串洗掉 —— 有包就叠回去，
  // 否则刷新页面或改一句剧本，资产包就白做了。
  if (S.assetPack) S.assets = E.applyAssetPack(S.assets, S.assetPack, S.parsed);
  autoTitleProject();
}

/** 还没起名的项目跟着剧本标题走；用户自己改过名字就不再动 */
function autoTitleProject() {
  const t = (S.meta && S.meta.title) || "";
  if (!t || !S.projectId) return;
  if (S.projectName && S.projectName !== "未命名项目" && S.projectName !== "旧版存档") return;
  if (S.projectName === t) return;
  S.projectName = t;
  mirrorCache(S.projectId, t, projectData());
}
/** S3：只要已有分集方案，上游一改就标成「基于旧稿」（idle 的旧存档同样算）。 */
function stalePlanIfAny() {
  if (S.episodes.length && S.steps.plan.status !== "running") S.steps.plan.status = "stale";
}
function markStale(reason) {
  S.stale = reason;
  const staleIfReady = (k) => { if (S.steps[k].status === "ready") S.steps[k].status = "stale"; };
  if (reason === "script") { staleIfReady("plan"); staleIfReady("shots"); stalePlanIfAny(); }
  else if (reason === "config") staleIfReady("shots");
  if (S.shots.length) save();
}

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

function renumber() { S.shots = E.renumberShots(S.shots, S.episodes); }

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

/* ------------------------------ 计算属性 ------------------------------ */
export const stats = computed(() => S.parsed ? S.parsed.stats : null);
export const liveStats = computed(() => {
  const t = S.script || "";
  const p = t.replace(/\s/g, "").length ? E.parseScript(t) : null;
  return { chars: t.length, p };
});
/** 工作流第 1 阶段的触发条件：长文本 + 无场次行的散文/小说体 */
export const novelLike = computed(() => {
  const t = S.script || "";
  return t.replace(/\s/g, "").length > 200 && AI.isNovelScript(t);
});
/** 第一步的规范度检查（5 项格式项，和 diagnose 的内容体检互补）。 */
export const sourceSpec = computed(() => E.scriptSpec(S.script, S.parsed));
/** 当前稿件的类型：scene / simple / prose / empty */
export const sourceKind = computed(() => S.sourceKind || E.classifySource(S.script).kind);

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

/* ------------------------------ 资产 ------------------------------ */
export const assetTabs = computed(() => [
  { kind: "character", label: "角色", items: S.assets.characters },
  { kind: "scene", label: "场景", items: S.assets.scenes },
  { kind: "prop", label: "道具", items: S.assets.props }
]);
/** S5：id → { count, episodes, label, short, orphan }。
 *  被引用的资产由 E.assetUsage 统计；零引用的资产按剧本场次换算集号，
 *  给出「曾属哪集 / 剧本兜底」的明确归属，而不是让它在界面上凭空消失。 */
export const assetUsage = computed(() => {
  const u = E.assetUsage(S.shots);
  [].concat(S.assets.characters, S.assets.scenes, S.assets.props).forEach((a) => {
    if (!a || !a.id || u[a.id]) return;
    const eps = [...new Set((a.sceneNos || []).map((n) => E.episodeOf(S.episodes, n)).filter(Boolean))]
      .sort((x, y) => x - y);
    const at = eps.length
      ? "第 " + (eps.length === 1 ? eps[0] : eps[0] + "–" + eps[eps.length - 1]) + " 集"
      : "剧本";
    u[a.id] = {
      count: 0, episodes: eps, orphan: true,
      label: "现无镜头引用 · " + at + " · 剧本兜底保留",
      short: "0镜 · 兜底"
    };
  });
  return u;
});
export const assetSummary = computed(() => ({
  characters: S.assets.characters.length,
  scenes: S.assets.scenes.length,
  props: S.assets.props.length,
  withRef: [].concat(S.assets.characters, S.assets.scenes, S.assets.props).filter((a) => a.refImage).length
}));
/** 出场角色（顺序 = 参考图槽位顺序），界面 chip 用 */
export function castOf(shot) { return E.boundOf(shot, S.assets, "character"); }
export function sceneAssetOf(shot) { return E.boundOf(shot, S.assets, "scene"); }
export function refsOf(shot) { return E.refsFor(shot, S.assets); }
export function promptOf(shot) { return E.assemblePrompt(shot, S.assets, S.config); }
export function shotAssetStale(shot) { return E.assetStale(shot, S.assets); }
export const staleAssetCount = computed(() => S.shots.filter((s) => E.assetStale(s, S.assets)).length);
export const activePrompt = computed(() => (activeShot.value ? E.assemblePrompt(activeShot.value, S.assets, S.config) : ""));

export const FRAME = {
  "远景": [8, 8, 12, 16], "全景": [14, 14, 26, 38], "中景": [22, 22, 38, 52],
  "近景": [34, 34, 56, 68], "特写": [62, 62, 0, 0]
};
export const EPISODE_MODES = [
  ["auto", "自动判断（推荐）"], ["none", "不分集 · 整部一集"],
  ["2", "固定 2 集"], ["3", "固定 3 集"], ["4", "固定 4 集"]
];

/* --------------------------- 两阶段 · 四个工作区 ---------------------------
   剧本阶段：把文字整理成可信的结构（改剧本 → 分集）
   制作阶段：先有镜头再定妆（分镜 → 定妆），因为分组视图与参考图都依赖 shots。
   闸门：没有剧本进不了分集；没有镜头进不了定妆。
   S.step 是对外契约；S2 把 3/4 语义对调，旧存档由 hydrate 的 stepV 迁移。 */
export const STEPS = [
  { no: 1, stage: "script", stageName: "剧本阶段", label: "改剧本", hint: "上传稿子 → 规范成场次剧本" },
  { no: 2, stage: "script", stageName: "剧本阶段", label: "分集", hint: "确认分集方案 · 场次 · 体检" },
  { no: 3, stage: "production", stageName: "制作阶段", label: "分镜", hint: "按集生成 · 改字段 · 导出" },
  { no: 4, stage: "production", stageName: "制作阶段", label: "定妆", hint: "按镜头给角色 / 场景 / 道具出图" }
];
export const STAGES = [
  { key: "script", name: "剧本阶段", note: "把文字整理成结构", steps: [1, 2] },
  { key: "production", name: "制作阶段", note: "把结构做成片子", steps: [3, 4] }
];
export const stageOf = (n) => (Number(n) <= 2 ? "script" : "production");

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

/** focus 记基线，change 才入撤销栈，避免每敲一个字压一次 */
export function onFieldFocusin(e) {
  if (e.target.matches && e.target.matches("[data-field]")) pendingBaseline = snapshot();
}
export function onFieldChange(e) {
  const t = e.target;
  if (!t.matches || !t.matches("[data-field]")) return;
  const id = t.dataset.id, field = t.dataset.field;
  const shot = S.shots.find((s) => s.id === id);
  if (!shot) return;
  let val = field === "duration" ? (Number(t.value) || 2) : t.value;
  if (field === "duration") val = Math.max(1, Math.min(30, val));
  // 支持 data-field="detail.subject" 这类分镜卡字段的点路径
  const path = field.split(".");
  const getVal = (o) => path.reduce((cur, k) => (cur == null ? undefined : cur[k]), o);
  const setVal = (o, v) => {
    let cur = o;
    for (let i = 0; i < path.length - 1; i++) {
      if (!cur[path[i]] || typeof cur[path[i]] !== "object") cur[path[i]] = {};
      cur = cur[path[i]];
    }
    cur[path[path.length - 1]] = v;
  };
  if (String(getVal(shot) ?? "") === String(val)) return;
  if (pendingBaseline) { S.undo.push(pendingBaseline); if (S.undo.length > 60) S.undo.shift(); S.redo.length = 0; pendingBaseline = null; }
  else begin();
  setVal(shot, val);
  shot.edited = shot.edited || {};
  shot.edited[field] = true;
  S.activeId = id;
  save();
}

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

/* --------------------------- 资产层操作 --------------------------- */
function findAnyAsset(id) {
  return [].concat(S.assets.characters, S.assets.scenes, S.assets.props).find((a) => a.id === id) || null;
}
function pushBaseline() {
  if (pendingBaseline) {
    S.undo.push(pendingBaseline);
    if (S.undo.length > 60) S.undo.shift();
    S.redo.length = 0; pendingBaseline = null;
  } else begin();
}
const ASSET_FIELD_LABEL = {
  appearance: "外观描述", wardrobe: "服装", age: "年龄", role: "身份",
  persona: "同一人分组", name: "名称", keyword: "固定关键词串"
};

export function setAssetTab(kind) { S.assetTab = kind; save(); }
/** focus 记基线、change 才入栈，和镜头字段一致，避免每敲一个字压一次撤销 */
export function onAssetFocusin(e) {
  if (e.target.matches && e.target.matches("[data-afield]")) pendingBaseline = snapshot();
}
export function onAssetChange(e) {
  const t = e.target;
  if (!t.matches || !t.matches("[data-afield]")) return;
  const a = findAnyAsset(t.dataset.assetId);
  if (!a) return;
  const field = t.dataset.afield;
  if (String(a[field] ?? "") === String(t.value)) return;
  pushBaseline();
  a[field] = t.value;
  a.touched = a.touched || {};
  a.touched[field] = true;
  save();
}
export function toggleAssetLock(id) {
  const a = findAnyAsset(id);
  if (!a) return;
  begin();
  a.locked = !a.locked;
  save();
  toast(a.locked ? "已锁定「" + a.name + "」，重新解析剧本不会覆盖它" : "已解锁「" + a.name + "」", "ok", "撤销", undo);
}

/** 原样读成 dataURL：不重编码、不缩尺寸，字节和用户选的那张一模一样 */
function readDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("read"));
    reader.onload = () => resolve(String(reader.result));
    reader.readAsDataURL(file);
  });
}

/**
 * 只在「服务没连、只能存浏览器」时才用的降级缩放。
 * 参考图默认走服务端存原文件（见 uploadAssetRef），所以这里只在极端情况下兜底，
 * 参数给得宽松：长边 2048、质量 0.92，肉眼基本看不出区别。
 */
function shrinkImage(file, max, quality) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("read"));
    reader.onload = () => {
      const img = new Image();
      img.onerror = () => reject(new Error("decode"));
      img.onload = () => {
        const scale = Math.min(1, max / Math.max(img.width, img.height));
        const w = Math.max(1, Math.round(img.width * scale));
        const h = Math.max(1, Math.round(img.height * scale));
        const cv = document.createElement("canvas");
        cv.width = w; cv.height = h;
        cv.getContext("2d").drawImage(img, 0, 0, w, h);
        resolve(cv.toDataURL("image/jpeg", quality || 0.92));
      };
      img.src = String(reader.result);
    };
    reader.readAsDataURL(file);
  });
}

function sizeText(bytes) {
  const n = Number(bytes) || 0;
  return n >= 1024 * 1024 ? (Math.round(n / 104857.6) / 10) + "MB" : Math.round(n / 1024) + "KB";
}

/**
 * 挂参考图：**原图不压缩**。
 * 服务端在 → 原文件按内容哈希落到 projects/<id>/refs/，项目里只记一个地址；
 * 这样画质一点不掉，project.json 也不会被 base64 撑大（以前压 512px，糊得没法用）。
 * 服务端不在 / 上传失败 → 退回原始字节的 dataURI（同样不压，只是文件会变大）。
 */
export function uploadAssetRef(e, id) {
  const input = e.target;
  const file = input.files && input.files[0];
  input.value = "";
  if (!file) return;
  const a = findAnyAsset(id);
  if (!a) return;
  if (!/^image\//.test(file.type)) { toast("参考图要选图片（png / jpg / webp）", "warn"); return; }
  if (file.size > 24 * 1024 * 1024) { toast("图片超过 24MB，换一张小一点的（原图不压缩，太大了存不动）", "warn"); return; }
  if (ui.refUpload) { toast("上一张还在上传，稍等一下", "warn"); return; }
  ui.refUpload = id;

  readDataUrl(file).then((dataUrl) => {
    if (PROJECT.server && S.projectId) {
      return AI.uploadProjectRef({ id: S.projectId, name: file.name, data: dataUrl })
        .then((r) => ({ ref: r.url, note: sizeText(file.size) + " · 原图未压缩" }))
        .catch(() => ({ ref: dataUrl, note: sizeText(file.size) + " · 原图直接存进项目" }));
    }
    return shrinkImage(file, 2048, 0.92)
      .then((u) => ({ ref: u, note: "服务未连接 · 已按 2048px 高质量存本机" }));
  }).then((r) => {
    begin();
    a.refImage = r.ref;
    a.refName = file.name;
    bankNote(a);
    save();
    toast("已给「" + a.name + "」挂上参考图（" + r.note + "），导出时会占用一个 refs 槽位", "ok", "撤销", undo);
  }).catch(() => {
    toast("这张图读不出来，换一张试试", "err");
  }).then(() => { ui.refUpload = ""; });
}
export function clearAssetRef(id) {
  const a = findAnyAsset(id);
  if (!a || !a.refImage) return;
  begin();
  a.refImage = ""; a.refName = "";
  bankNote(a);          // 生成图还在就只更新图仓，全空则注销
  save();
  toast("已移除「" + a.name + "」的参考图", "ok", "撤销", undo);
}
export function addProp() {
  const name = (ui.propDraft || "").trim();
  if (!name) { toast("先填一个道具名，比如「热咖啡」", "warn"); return; }
  if (S.assets.props.some((p) => p.name === name)) { toast("这个道具已经在清单里了", "warn"); return; }
  begin();
  S.assets.props.push({
    id: E.assetId("prop", name + "_" + Date.now()), kind: "prop", name: name,
    appearance: "", refImage: "", refName: "", locked: false, starred: false, source: "manual"
  });
  ui.propDraft = "";
  save();
  toast("已加入道具「" + name + "」，画面描述里提到它就会自动绑定", "ok", "撤销", undo);
}
export function delAsset(id) {
  const a = findAnyAsset(id);
  if (!a) return;
  begin();
  bankForget(a);
  ["characters", "scenes", "props"].forEach((k) => {
    const i = S.assets[k].findIndex((x) => x.id === id);
    if (i >= 0) S.assets[k].splice(i, 1);
  });
  S.shots = E.bindAssets(S.shots, S.assets);
  save();
  toast("已删除「" + a.name + "」并解绑相关镜头", "ok", "撤销", undo);
}

/* ---------------------- 资产包（AI 分解 / 起始帧） ---------------------- */
/* 风格唯一出口：手动定义 > 预设 > AI 分解推断 > 内置中性默认。
   出图 / 起始帧 / 导出全走这里，避免各处各读一份默认值。 */
export function currentStyle() {
  const c = S.styleConfig || {};
  const p = (S.assetPack && S.assetPack.style) || {};
  const preset = STYLE_PRESETS.find((x) => x.key === c.key);
  return {
    key: c.key || "",
    anchor: (c.anchor || (preset && preset.anchor) || p.anchor || STYLE_FALLBACK_CN).trim(),
    anchorEn: (c.anchorEn || (preset && preset.anchorEn) || p.anchorEn || STYLE_FALLBACK_EN).trim(),
    source: (c.anchor || c.anchorEn) ? "手动定义" :
      (c.key ? "预设 · " + (preset ? preset.label : c.key) :
        (p.anchor ? "AI 分解推断" : "内置默认"))
  };
}
/** 当前风格注入资产包副本，供 /api/ai/frames 与 zip 导出用（不改原 S.assetPack） */
export function packWithStyle() {
  const st = currentStyle();
  const base = S.assetPack || {};
  return Object.assign({}, base, {
    style: Object.assign({}, base.style || {}, { anchor: st.anchor, anchorEn: st.anchorEn })
  });
}
export function saveStyleConfig(cfg) {
  begin();
  S.styleConfig = {
    key: cfg.key || "",
    anchor: (cfg.anchor || "").trim(),
    anchorEn: (cfg.anchorEn || "").trim()
  };
  save();
  regenFrames(true);   // 已有起始帧提示词立刻按新风格重算（缺资产包 / 分镜时自动跳过）
  toast("剧本视觉风格已更新，起始帧提示词已同步", "ok", "撤销", undo);
}
export function resetStyleConfig() {
  begin();
  S.styleConfig = { key: "", anchor: "", anchorEn: "" };
  save();
  regenFrames(true);
  toast("已恢复跟随 AI 分解 / 内置默认风格", "ok", "撤销", undo);
}

export const assetPackStats = computed(() => {
  const p = S.assetPack || {};
  const a = p.assets || {};
  const cov = p.coverage || {};
  const all = [].concat(a.characters || [], a.scenes || [], a.props || []);
  return {
    ready: !!S.assetPack,
    characters: (a.characters || []).length,
    scenes: (a.scenes || []).length,
    props: (a.props || []).length,
    inferred: all.filter((x) => x.source === "inferred").length,
    warnings: (S.assetWarnings || []).length,
    model: S.assetModel || "",
    charCovered: cov.charactersCovered || 0, charTotal: cov.scriptCharacters || 0,
    sceneCovered: cov.scenesCovered || 0, sceneTotal: cov.scenesTotal || 0,
    frames: (S.frames || []).length,
    style: currentStyle().anchor,
    styleSource: currentStyle().source,
    order: (p.style && p.style.generationOrder) || []
  };
});

/* ------------------------------ S6 · 首帧提示词闸门 ------------------------------
 * 首帧提示词需要 shots + 已定妆资产两者。顺序翻转后第 3 步排分镜时资产还没定妆，
 * 所以在这一层设硬闸门：第 3 步一律不发 /api/ai/frames，只有第 4 步定妆完整才生成。
 * 不新建 AI 接口、不改 server.py、后端 7 阶段流水线保持休眠。
 */
/** 闸门状态：ok / 一句人话原因 / 已定妆资产数 / 镜头数。 */
export const framesGate = computed(() => {
  const all = [].concat(S.assets.characters, S.assets.scenes, S.assets.props);
  const dressed = all.filter((a) => a && (a.refImage || (a.genImages || []).length)).length;
  const shots = S.shots.length;
  if (Number(S.step) !== 4)
    return { ok: false, reason: "先到第 4 步资产定妆", dressed: dressed, shots: shots };
  if (!shots)
    return { ok: false, reason: "先在第 3 步排出镜头", dressed: dressed, shots: shots };
  if (!S.assetPack)
    return { ok: false, reason: "先做一次资产分解（AI 分解资产）", dressed: dressed, shots: shots };
  if (!dressed)
    return { ok: false, reason: "先给至少一条资产挂参考图或出图，再生成首帧提示词", dressed: dressed, shots: shots };
  return { ok: true, reason: "", dressed: dressed, shots: shots };
});
/** 服务端回包里的 refAssets 是资产编号；关联回已定妆资产，写成参考图槽位并追加到提示词。 */
function withRefSlots(f) {
  const all = [].concat(S.assets.characters, S.assets.scenes, S.assets.props);
  const slots = (f.refAssets || []).map((code) => {
    const a = all.find((x) => x && x.code === code);
    return a ? { code: code, name: a.name,
                 ready: !!(a.refImage || (a.genImages || []).length) } : null;
  }).filter(Boolean);
  const line = slots.length
    ? "\n参考图槽位：" + slots.map((s, i) =>
        "[" + (i + 1) + "] " + s.code + " " + s.name + (s.ready ? "（已定妆）" : "（待定妆）")).join("；")
    : "";
  return Object.assign({}, f, { refSlots: slots, prompt: String(f.prompt || "") + line });
}

/** 单独跑一次资产分解（不生成分镜），已有手改 / 锁定会被保留。 */
export function buildAssetPack() {
  if (S.assetBusy) return Promise.resolve();
  if (!S.script.replace(/\s/g, "")) { toast("先放一段剧本文字进来", "warn"); return Promise.resolve(); }
  if (!S.aiEnabled || !S.llmAvailable) {
    toast("资产分解要调大模型；离线时先用规则抽取的设定，配好 Key 再来", "warn");
    return Promise.resolve();
  }
  if (!S.parsed) reparse();
  S.assetBusy = true;
  busy(true, "正在拆解角色 / 场景 / 道具，生成关键提示词…");
  return AI.assets(S.script, S.parsed).then((r) => {
    S.assetBusy = false; busy(false);
    begin();
    S.assetPack = r;
    S.assetModel = r.model || "";
    S.assets = E.applyAssetPack(S.assets, r, S.parsed);
    S.assetWarnings = r.warnings || [];
    if (S.shots.length) S.shots = E.bindAssets(S.shots, S.assets);
    save();
    const st = assetPackStats.value;
    toast("资产包已就绪 · " + st.characters + " 角色 / " + st.scenes + " 场景 / " + st.props + " 道具" +
      (st.warnings ? " · " + st.warnings + " 条待核对" : " · 校验通过"),
      st.warnings ? "warn" : "ok", "撤销", undo);
    if (S.shots.length) regenFrames(true);
  }).catch((err) => {
    S.assetBusy = false; busy(false);
    toast("资产分解失败：" + err.message, "err");
  });
}

/** 资产包 + 分镜表 → 每镜起始帧提示词（纯模板，秒回）。S6：只在第 4 步定妆后可生成。 */
export function regenFrames(silent) {
  // 第 3 步只保留提示词只读预览，任何路径都不在这儿发 /api/ai/frames。
  if (Number(S.step) !== 4) {
    if (!silent) toast("首帧提示词在第 4 步资产定妆后生成；第 3 步只有只读预览", "warn");
    return Promise.resolve();
  }
  // 显式按钮走完整闸门；silent（改风格 / 重新分解）只有已经生成过才重算，
  // 否则「资产刚分解、还没定妆」就会拿空参考图算出一版没用的提示词。
  if (!silent && !framesGate.value.ok) {
    toast(framesGate.value.reason, "warn");
    return Promise.resolve();
  }
  if (silent && !S.frames.length && !framesGate.value.ok) return Promise.resolve();
  if (!S.assetPack) {
    if (!silent) toast("先做一次资产分解，才有资产包可以拼起始帧", "warn");
    return Promise.resolve();
  }
  if (!S.shots.length) {
    if (!silent) toast("先生成分镜", "warn");
    return Promise.resolve();
  }
  return AI.frames(S.shots, packWithStyle(), S.config.aspect).then((r) => {
    if (!silent) begin();
    S.frames = (r.frames || []).map(withRefSlots);
    S.frameStats = r.stats || null;
    save();
    if (!silent) toast("已生成 " + S.frames.length + " 个镜头的起始帧提示词（" + S.config.aspect + "）", "ok", "撤销", undo);
  }).catch((err) => { if (!silent) toast("起始帧提示词生成失败：" + err.message, "err"); });
}

const PROMPT_LABEL = {
  keyword: "固定关键词串", turnaround: "三视图提示词", faceSheet: "面部四视图提示词",
  concept: "场景概念图提示词", wide: "宽幕版提示词"
};
/** 每类资产能复制哪些中文提示词（道具没有预生成提示词，靠名称 + 描述拼一条） */
const ASSET_PROMPT_KEYS = {
  character: [["turnaround", "三视图提示词"], ["faceSheet", "面部四视图提示词"]],
  scene: [["concept", "场景概念图提示词"], ["wide", "宽幕版提示词"]],
  prop: []
};

/** 道具没出图提示词：用名称 + 描述 + 绑定角色拼一句可直接塞进镜头的话 */
function propPromptText(a) {
  const desc = String(a.appearance || "").trim();
  const body = (desc && desc !== a.name) ? desc : "按剧本描述还原材质与磨损";
  const who = (a.boundTo || []).filter(Boolean);
  return a.name + "：" + body + (who.length ? "（出现在 " + who.join("、") + " 的画面里）" : "");
}

/**
 * 一个资产的全部提示词，拆成可单独复制的条目。
 * 英文单独成条：Flux / Midjourney / 即梦这类工具只吃英文，之前英文串存了却拿不出来。
 */
export function assetPromptBlocks(a) {
  if (!a) return [];
  const out = [];
  const prompts = a.prompts || {};
  (ASSET_PROMPT_KEYS[a.kind] || []).forEach(([key, label]) => {
    const text = String(prompts[key] || "").trim();
    if (text) out.push({ key: key, label: label, lang: "cn", text: text });
  });
  if (a.kind === "prop") {
    out.push({ key: "prop", label: "道具描述", lang: "cn", text: propPromptText(a) });
  } else if (String(a.keyword || "").trim()) {
    out.push({ key: "keyword", label: "固定关键词串", lang: "cn", text: String(a.keyword).trim() });
  }
  const en = String(a.kind === "character" ? (a.keywordEn || "") : (a.kind === "scene" ? (a.sceneEn || "") : "")).trim();
  if (en) out.push({ key: "en", label: a.kind === "character" ? "英文关键词（Flux / MJ）" : "英文场景描述（Flux / MJ）", lang: "en", text: en });
  return out;
}

/**
 * 拼成可粘贴文本：只有一条就给原文（直接贴进出图工具），
 * 多条才加【小标题】分段（贴进文档 / 发给协作者）。
 */
export function assetPromptText(a, mode) {
  const blocks = assetPromptBlocks(a);
  const pick = mode === "en" ? blocks.filter((b) => b.lang === "en")
    : mode === "cn" ? blocks.filter((b) => b.lang === "cn")
      : blocks;
  if (!pick.length) return "";
  if (pick.length === 1) return pick[0].text;
  return pick.map((b) => "【" + b.label + "】\n" + b.text).join("\n\n");
}

/** which: all / cn / en 或具体 key（keyword / turnaround / concept …） */
export function copyAssetPrompt(id, which) {
  const a = findAnyAsset(id);
  if (!a) return;
  const mode = which || "all";
  let text = "";
  let label = "提示词";
  if (mode === "all" || mode === "cn" || mode === "en") {
    text = assetPromptText(a, mode);
    label = mode === "en" ? "英文提示词" : (mode === "cn" ? "中文提示词" : "提示词");
  } else {
    const block = assetPromptBlocks(a).find((b) => b.key === mode);
    text = block ? block.text : "";
    label = (block && block.label) || PROMPT_LABEL[mode] || "提示词";
  }
  if (!text) {
    if (mode === "en") toast("「" + a.name + "」还没有英文提示词 —— 先点「✦ AI 补形象」生成", "warn");
    else toast("这一项还没生成，先做一次资产分解", "warn");
    return;
  }
  copyText(text, "已复制「" + a.name + "」的" + label);
}

/** 整个 tab 一次性导出（贴进表格 / 发给协作者）；不带英文时用中文兜底 */
export function copyAllAssetPrompts(kind, mode) {
  const list = (S.assets || {})[kind === "character" ? "characters" : (kind === "scene" ? "scenes" : "props")] || [];
  const parts = [];
  list.forEach((a) => {
    const t = assetPromptText(a, mode || "all");
    if (t) parts.push("◆ " + a.name + (a.code ? "（" + a.code + "）" : "") + "\n" + t);
  });
  if (!parts.length) { toast("这一栏还没有可复制的提示词，先做一次资产分解", "warn"); return; }
  copyText(parts.join("\n\n———\n\n"), "已复制 " + parts.length + " 个资产的提示词");
}
/** 三锚点（面部 / 瑕疵 / 服装记忆点）单独编辑：这套东西决定角色长什么样，改动要立刻生效 */
export function saveAssetAnchor(id, key, value) {
  const a = findAnyAsset(id);
  if (!a) return;
  a.anchors = a.anchors || {};
  const isList = Array.isArray(a.anchors[key]) || key === "props";
  const v = isList
    ? String(value || "").split(/[、,，;；]/).map((x) => x.trim()).filter(Boolean)
    : String(value || "").trim();
  const before = isList ? (a.anchors[key] || []).join("、") : String(a.anchors[key] || "");
  const after = isList ? v.join("、") : v;
  if (before === after) return;
  begin();
  a.anchors[key] = v;
  a.touched = a.touched || {};
  a.touched["anchors." + key] = true;
  if (key === "props" && a.kind === "scene") a.appearance = v.join("；");
  S.shots = E.bindAssets(S.shots, S.assets);
  save();
}

/** 关键词串是唯一一致性真源，改完立刻重绑镜头，让提示词生效。 */
export function saveAssetKeyword(id, value) {
  const a = findAnyAsset(id);
  if (!a) return;
  const v = String(value || "").trim();
  if ((a.keyword || "") === v) return;
  begin();
  a.keyword = v;
  a.touched = a.touched || {};
  a.touched.keyword = true;
  S.shots = E.bindAssets(S.shots, S.assets);
  save();
}

/** 资产改过 → 重新绑定，清掉「设定已改」标记（提示词是派生的，不需要重写分镜） */
export function refreshAssets() {
  if (!S.shots.length) { toast("还没有分镜，先生成", "warn"); return; }
  begin();
  S.shots = E.bindAssets(S.shots, S.assets);
  save();
  toast("已按最新角色设定刷新 " + S.shots.length + " 个镜头的绑定与提示词", "ok", "撤销", undo);
}
export function refreshOneShot(id) {
  const shot = S.shots.find((s) => s.id === id);
  if (!shot) return;
  begin();
  Object.assign(shot, E.bindShot(shot, S.assets));
  save();
  toast("已刷新 " + shot.code + " 的提示词", "ok", "撤销", undo);
}
export function toggleShotLock(id) {
  const shot = S.shots.find((s) => s.id === id);
  if (!shot) return;
  begin();
  shot.locked = !shot.locked;
  save();
  toast(shot.locked ? "已锁定 " + shot.code + "，批量重生成会跳过它" : "已解锁 " + shot.code, "ok", "撤销", undo);
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

export function copyText(text, note) {
  if (!text) return;
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text)
      .then(() => toast(note || "已复制", "ok"))
      .catch(() => toast("复制被浏览器拦了，手动选中复制吧", "warn"));
  } else {
    toast("这个环境不支持自动复制", "warn");
  }
}

/* ------------------- AI 单项形象补全 / 本地 ComfyUI 批量出图 ------------------- */
let comfyTimer = null;

export function comfyCheck() {
  if (ui.comfy.checking) return Promise.resolve(ui.comfy.online);
  ui.comfy.checking = true;
  return AI.comfyStatus().then((s) => {
    if (s.qwen) {
      ui.comfy.qwen.online = !!s.qwen.online;
      ui.comfy.qwen.model = s.qwen.model || "";
      ui.comfy.qwen.size = s.qwen.size || "";
      ui.comfy.qwen.detail = s.qwen.detail || "";
    }
    ui.comfy.online = !!s.online;
    ui.comfy.checked = true;
    ui.comfy.version = s.version || "";
    ui.comfy.vramFreeMB = s.vramFreeMB || 0;
    ui.comfy.host = s.host || "";
    ui.comfy.model = s.model || "";
    ui.comfy.detail = s.online ? "" : (s.detail || "未连接");
    if (s.variants) ui.comfy.variants = s.variants;
    return ui.comfy.online;
  }).catch(() => {
    ui.comfy.online = false; ui.comfy.checked = true;
    ui.comfy.detail = "本机服务 /api/comfy/status 不可达";
    return false;
  }).finally(() => { ui.comfy.checking = false; });
}

/** 只把剧本里提到这个角色的行（±2 行）发给模型，别把整本小说塞进去。 */
function scriptContextFor(name) {
  const lines = String(S.script || "").split(/\r?\n/);
  const hits = [];
  lines.forEach((l, i) => { if (name && l.indexOf(name) >= 0) hits.push(i); });
  if (!hits.length) return String(S.script || "").slice(0, 6000);
  const keep = {};
  hits.slice(0, 14).forEach((i) => {
    for (let j = Math.max(0, i - 2); j <= Math.min(lines.length - 1, i + 2); j++) keep[j] = 1;
  });
  return Object.keys(keep).map(Number).sort((a, b) => a - b)
    .slice(0, 90).map((i) => lines[i]).join("\n").slice(0, 8000);
}

export function fillAssetWithAI(id) {
  const a = findAnyAsset(id);
  if (!a || ui.comfy.filling) return;
  if (!S.llmAvailable) { toast("没配大模型 Key，AI 补形象用不了", "warn"); return; }
  ui.comfy.filling = id;
  const current = {
    name: a.name, kind: a.kind, age: a.age, role: a.role,
    appearance: a.appearance, wardrobe: a.wardrobe,
    keyword: a.keyword, keywordEn: a.keywordEn, sceneEn: a.sceneEn, propEn: a.propEn,
    anchors: a.anchors || {}, intExt: a.intExt, time: a.time
  };
  AI.fillAsset({ kind: a.kind, name: a.name, current, script: scriptContextFor(a.name) })
    .then((r) => {
      begin();
      a.touched = Object.assign({}, a.touched || {});
      if (a.kind === "character") {
        ["age", "role", "wardrobe", "keyword", "keywordEn"].forEach((k) => {
          if (r[k]) { a[k] = r[k]; a.touched[k] = 1; }
        });
        if (r.face) { a.appearance = r.face; a.touched.appearance = 1; }
        a.anchors = Object.assign({}, a.anchors || {});
        ["face", "flaw", "wardrobeHook"].forEach((k) => {
          if (r[k]) { a.anchors[k] = r[k]; a.touched["anchors." + k] = 1; }
        });
      } else if (a.kind === "scene") {
        if (r.appearance) { a.appearance = r.appearance; a.touched.appearance = 1; }
        if (r.sceneEn) { a.sceneEn = r.sceneEn; a.touched.sceneEn = 1; }
        a.anchors = Object.assign({}, a.anchors || {});
        if (r.light) { a.anchors.light = r.light; a.touched["anchors.light"] = 1; }
        if (r.lens) { a.anchors.lens = r.lens; a.touched["anchors.lens"] = 1; }
        if (r.props && r.props.length) a.anchors.props = r.props;
      } else if (a.kind === "prop") {
        if (r.appearance) { a.appearance = r.appearance; a.touched.appearance = 1; }
        if (r.propEn) { a.propEn = r.propEn; a.touched.propEn = 1; }
        if (!r.appearance && !r.propEn) {
          // 以前没有 prop 分支，这里什么都不写却照样弹「已补全」——假成功最难查
          toast("模型没给出道具描述，换个说法再试一次", "warn");
          return;
        }
      }
      save();
      S.shots = E.bindAssets(S.shots, S.assets);
      toast("已用 AI 补全「" + a.name + "」的形象设定（" + (r.model || "模型") + "）", "ok", "撤销", undo);
    })
    .catch((e) => toast("AI 补形象失败：" + e.message, "err"))
    .finally(() => { ui.comfy.filling = ""; });
}

export function comfyToggleVariant(kind, key) {
  const arr = ui.comfy.picked[kind] || (ui.comfy.picked[kind] = []);
  const i = arr.indexOf(key);
  if (i >= 0) arr.splice(i, 1); else arr.push(key);
}
export function comfySetScope(v) { ui.comfy.scope = v; }
export function comfySetEngine(v) {
  ui.comfy.engine = v === "qwen" ? "qwen" : "comfy";
  ui.comfy.preview = null;
}
export function comfySetSeqN(n) { ui.comfy.seqN = Math.max(1, Math.min(4, Number(n) || 1)); }

function comfyApplyResults(full) {
  const items = full.items || [];
  begin();
  let n = 0;
  items.forEach((it) => {
    const a = findAnyAsset(it.assetId);
    if (!a) return;
    if (!Array.isArray(a.genImages)) a.genImages = [];
    const row = {
      variant: it.variant, label: it.variantLabel, dataUri: it.dataUri,
      file: it.file, seed: it.seed, prompt: it.prompt,
      w: it.w, h: it.h, fallbackEn: it.fallbackEn,
      seconds: it.seconds, uncompressed: it.uncompressed
    };
    const k = a.genImages.findIndex((x) => x.variant === it.variant);
    if (k >= 0) a.genImages.splice(k, 1, row); else a.genImages.push(row);
    if (a.genImages.length > 6) a.genImages = a.genImages.slice(-6);
    if (!a.refImage) {
      a.refImage = it.dataUri;
      a.refName = (it.file || "").split("/").pop() || (it.variantLabel + ".png");
    }
    n += 1;
  });
  items.forEach((it) => bankNote(findAnyAsset(it.assetId)));
  ui.comfy.results = items.map((it) => ({
    assetId: it.assetId, assetName: it.assetName, variant: it.variant,
    label: it.variantLabel, file: it.file, seconds: it.seconds, fallbackEn: it.fallbackEn
  }));
  ui.comfy.errors = full.errors || [];
  ui.comfy.busy = false;
  ui.comfy.current = "";
  save();
  S.shots = E.bindAssets(S.shots, S.assets);
  const fb = items.filter((x) => x.fallbackEn).length;
  const big = items.filter((x) => x.uncompressed).length;
  toast("生成了 " + n + " 张素材图，已挂到对应资产" +
    (fb ? "（" + fb + " 张缺英文关键词，画面会打折）" : ""), "ok", "撤销", undo);
  if (big) toast(big + " 张没压成缩略图（服务端缺 Pillow），本地存储会偏大", "warn");
  if ((full.errors || []).length) toast("有 " + full.errors.length + " 张失败，见下方错误列表", "warn");
}

function comfyPollStart() {
  if (comfyTimer) clearInterval(comfyTimer);
  let fails = 0;
  const tick = () => {
    AI.comfyJob(ui.comfy.jobId).then((j) => {
      fails = 0;
      ui.comfy.done = j.done || 0;
      ui.comfy.total = j.total || ui.comfy.total;
      ui.comfy.current = j.current || "";
      ui.comfy.errors = j.errors || [];
      if (j.status === "running") return null;
      clearInterval(comfyTimer); comfyTimer = null;
      return AI.comfyJob(ui.comfy.jobId, true).then(comfyApplyResults);
    }).catch((e) => {
      fails += 1;
      if (fails >= 3) {
        clearInterval(comfyTimer); comfyTimer = null;
        ui.comfy.busy = false;
        toast("查询出图任务失败：" + e.message, "err");
      }
    });
  };
  comfyTimer = setInterval(tick, 1500);
  tick();
}

/** 出图 / 预览共用同一份资产载荷，少一处手抄字段就少一次「界面和实际不一致」 */
function comfyPayload(list) {
  return list.map((a) => ({
    id: a.id, kind: a.kind, name: a.name, code: a.code || "",
    keywordEn: a.keywordEn || "", keyword: a.keyword || "",
    sceneEn: a.sceneEn || "", appearance: a.appearance || "", propEn: a.propEn || ""
  }));
}

/**
 * 看「本地出图到底会发什么」。
 * 以前界面上的提示词是 AI 写的中文可读版，服务端出图却另拼一份英文串，
 * 复制走的和本地真正用的不是同一个描述。这里直接问服务端的拼装器，两边只有一个真相。
 */
export function comfyPreviewPrompts(currentId) {
  if (ui.comfy.previewBusy) return;
  const key = { character: "characters", scene: "scenes", prop: "props" }[S.assetTab] || "characters";
  const all = S.assets[key] || [];
  let list = all;
  if (ui.comfy.scope === "one") list = all.filter((a) => a.id === currentId);
  else if (ui.comfy.scope === "p0") list = all.filter((a) => (a.priority || "P1") === "P0");
  if (!list.length) { toast("这个范围里没有资产", "warn"); return; }
  if (!(ui.comfy.picked[S.assetTab] || []).length) { toast("先勾选至少一种素材类型", "warn"); return; }
  // 服务端按 kind 取变体列表，所以这里传完整的三类映射（与出图请求同构）
  const variants = {};
  ["character", "scene", "prop"].forEach((k) => { variants[k] = (ui.comfy.picked[k] || []).slice(); });
  ui.comfy.previewBusy = true;
  AI.comfyPrompt({ assets: comfyPayload(list.slice(0, 12)), variants: variants, styleEn: currentStyle().anchorEn })
    .then((r) => { ui.comfy.preview = r.rows || []; })
    .catch((e) => toast("读提示词失败：" + e.message, "err"))
    .then(() => { ui.comfy.previewBusy = false; });
}
export function clearComfyPreview() { ui.comfy.preview = null; }

export function comfyGenerateImages(currentId, shotIds) {
  if (ui.comfy.busy) return;
  const engine = ui.comfy.engine;
  const seqN = engine === "qwen" ? (ui.comfy.seqN || 1) : 1;
  if (engine === "qwen" ? !ui.comfy.qwen.online : !ui.comfy.online) {
    toast(engine === "qwen"
      ? "通义万相没配好：" + (ui.comfy.qwen.detail || "缺 API Key")
      : "本地 ComfyUI 没连上，先启动 8188 或切到「通义万相」", "warn");
    return;
  }
  const key = { character: "characters", scene: "scenes", prop: "props" }[S.assetTab] || "characters";
  const all = S.assets[key] || [];
  let list;
  if (ui.comfy.scope === "one") list = all.filter((a) => a.id === currentId);
  else if (ui.comfy.scope === "shot" && Array.isArray(shotIds) && shotIds.length)
    list = all.filter((a) => shotIds.indexOf(a.id) >= 0);
  else if (ui.comfy.scope === "p0") list = all.filter((a) => (a.priority || "P1") === "P0");
  else list = all.slice();
  if (!list.length) { toast("这个范围里没有资产，换个范围或先做资产分解", "warn"); return; }
  const variants = {};
  ["character", "scene", "prop"].forEach((k) => { variants[k] = (ui.comfy.picked[k] || []).slice(); });
  let count = 0;
  ["character", "scene", "prop"].forEach((k) => {
    count += list.filter((a) => a.kind === k).length * variants[k].length;
  });
  count *= seqN;
  if (!count) { toast("先勾选至少一种素材类型", "warn"); return; }
  if (count > 12) {
    toast("一次最多 12 张，缩小范围或少勾几种类型（当前 " + count + " 张）", "warn");
    return;
  }
  const assets = comfyPayload(list);
  ui.comfy.busy = true; ui.comfy.done = 0; ui.comfy.total = count;
  ui.comfy.current = "正在提交任务…";
  ui.comfy.errors = []; ui.comfy.results = [];
  AI.comfyGenerate({ assets, variants, styleEn: currentStyle().anchorEn, engine, n: seqN })
    .then((r) => { ui.comfy.jobId = r.jobId; ui.comfy.total = r.total; comfyPollStart(); })
    .catch((e) => {
      ui.comfy.busy = false; ui.comfy.current = "";
      toast("出图没启动：" + e.message, "err");
    });
}

export function setPrimaryGenImage(id, variant) {
  const a = findAnyAsset(id);
  const row = a && (a.genImages || []).find((x) => x.variant === variant);
  if (!row) return;
  begin();
  a.refImage = row.dataUri;
  a.refName = row.label + " · 本地生成";
  bankNote(a);
  save();
  toast("已把「" + row.label + "」设为主参考图", "ok", "撤销", undo);
}
export function clearGenImages(id) {
  const a = findAnyAsset(id);
  if (!a || !(a.genImages || []).length) return;
  begin(); a.genImages = []; bankNote(a); save();
  toast("已清掉「" + a.name + "」的生成图", "ok", "撤销", undo);
}

/* ------------------------------ 启动 ------------------------------ */
/** 启动时决定打开哪个项目：?project=<id> > 上次打开的 > 最近更新的 > 迁移旧存档 > 新建 */
function bootStore(wantId, fresh) {
  return Projects.list().then((res) => {
    PROJECT.server = true;
    PROJECT.error = "";
    ui.projects = res.projects || [];
    if (fresh) return newProject("未命名项目", { silent: true });
    const has = (id) => !!id && ui.projects.some((p) => p.id === id);
    const last = localStorage.getItem(LAST_KEY) || "";
    // 新浏览器 / 清了缓存时不要凭空建空项目：优先接着最近更新的那个项目
    const target = has(wantId) ? wantId
      : (has(last) ? last
        : (has(S.projectId) ? S.projectId : ((ui.projects[0] && ui.projects[0].id) || "")));
    if (target) {
      return openProject(target, { silent: true, skipSave: true });
    }
    return newProject("未命名项目", { silent: true, skipSave: true });
  });
}

/** 探测当前生效的模型，写完配置 / 切换后调它，界面上的「已接入 xxx」才会跟着变。 */
export function refreshLlmConfig() {
  if (location.protocol === "file:") return Promise.resolve(null);
  return fetch("api/config", { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : null))
    .then((j) => {
      if (!j) return null;
      S.llmAvailable = !!j.llm;
      S.llmModel = j.model || "";
      S.llmProvider = (j.provider && j.provider.name) || "";
      return j;
    })
    .catch(() => null);
}

/** 读取出图引擎配置：每项带 source（file / env / default），界面据此提示从哪生效。 */
export function loadEngine(force) {
  if (location.protocol === "file:") return Promise.resolve(null);
  if (ui.engine.loaded && !force) return Promise.resolve(null);
  ui.engine.busy = "load";
  return AI.engineConfig()
    .then((j) => { ui.engine.config = j || {}; ui.engine.loaded = true; return j; })
    .catch((e) => { toast("读取引擎配置失败：" + e.message, "err"); return null; })
    .finally(() => { ui.engine.busy = ""; });
}

/** 保存引擎配置：Key 留空 = 不改已存的；顺手刷新 ComfyUI 在线状态。 */
export function saveEngine(draft) {
  const body = {
    comfyHost: draft.comfyHost || "", comfyModel: draft.comfyModel || "",
    qwenUrl: draft.qwenUrl || "", qwenModel: draft.qwenModel || "",
    qwenSize: draft.qwenSize || ""
  };
  if (draft.clearQwenKey) body.clearQwenKey = true;
  else if (draft.qwenKey) body.qwenKey = draft.qwenKey;
  ui.engine.busy = "save";
  return AI.engineSave(body)
    .then((j) => {
      ui.engine.config = j || {};
      ui.engine.loaded = true;
      toast("出图引擎配置已保存，立即生效", "ok");
      return comfyCheck().then(() => j);
    })
    .catch((e) => { toast("保存失败：" + e.message, "err"); return null; })
    .finally(() => { ui.engine.busy = ""; });
}

/** 探测某个引擎。ComfyUI 会真连一次并核对 unet 是否真的存在。 */
export function testEngine(kind) {
  const k = kind || "comfy";
  ui.engine.testing = k;
  ui.engine.result = null;
  return AI.engineTest(k)
    .then((r) => { ui.engine.result = Object.assign({ at: Date.now() }, r); return r; })
    .catch((e) => { ui.engine.result = { ok: false, kind: k, detail: e.message }; return null; })
    .finally(() => { ui.engine.testing = ""; });
}

/** 拉 ComfyUI 里实际可用的 unet：换 Flux 版本时直接选，不用猜文件名。 */
export function loadComfyModels(force) {
  if (ui.engine.modelsBusy) return Promise.resolve(ui.engine.models);
  if (ui.engine.models.length && !force) return Promise.resolve(ui.engine.models);
  ui.engine.modelsBusy = true;
  return AI.comfyModels()
    .then((j) => {
      ui.engine.models = j.models || [];
      ui.engine.modelsHost = j.host || "";
      return ui.engine.models;
    })
    .catch(() => [])
    .finally(() => { ui.engine.modelsBusy = false; });
}

export function loadModels(force) {
  if (location.protocol === "file:") return Promise.resolve(null);
  if (ui.models.loaded && !force) return Promise.resolve(null);
  ui.models.busy = "load";
  return AI.llmProviders()
    .then((j) => {
      ui.models.list = j.providers || [];
      ui.models.active = j.active || "";
      ui.models.env = j.env || null;
      ui.models.loaded = true;
      return j;
    })
    .catch((e) => { toast("读取模型配置失败：" + e.message, "err"); return null; })
    .finally(() => { ui.models.busy = ""; });
}

/** 只测试不发配置：地址/Key/模型名三件都真的能用才返回 ok。 */
export function testModel(draft) {
  ui.models.testing = draft.id || "__new__";
  ui.models.result = null;
  return AI.llmTest({
    id: draft.id || "",
    baseUrl: draft.baseUrl, model: draft.model,
    apiKey: draft.apiKey ? draft.apiKey : null,
    maxTokens: draft.maxTokens
  })
    .then((r) => { ui.models.result = Object.assign({ at: Date.now() }, r); return r; })
    .catch((e) => { ui.models.result = { ok: false, detail: e.message, ms: 0 }; return null; })
    .finally(() => { ui.models.testing = ""; });
}

export function saveModel(draft, opts) {
  opts = opts || {};
  const body = {
    id: draft.id || "", name: draft.name || "", baseUrl: draft.baseUrl || "",
    model: draft.model || "", maxTokens: draft.maxTokens || 16384,
    activate: !!opts.activate
  };
  if (draft.apiKey) body.apiKey = draft.apiKey;
  ui.models.busy = "save";
  return AI.llmSave(body)
    .then((j) => {
      ui.models.list = j.providers || [];
      ui.models.active = j.active || "";
      ui.models.loaded = true;
      toast(opts.activate ? "已保存并切换到这个模型" : "模型配置已保存", "ok");
      return refreshLlmConfig().then(() => j);
    })
    .catch((e) => { toast("保存失败：" + e.message, "err"); return null; })
    .finally(() => { ui.models.busy = ""; });
}

export function activateModel(id) {
  ui.models.busy = "activate";
  return AI.llmActivate(id)
    .then((j) => {
      ui.models.list = j.providers || [];
      ui.models.active = j.active || "";
      toast("已切换到「" + ((j.providers || []).find((p) => p.id === id) || {}).name + "」", "ok");
      return refreshLlmConfig().then(() => j);
    })
    .catch((e) => toast("切换失败：" + e.message, "err"))
    .finally(() => { ui.models.busy = ""; });
}

export function removeModel(id) {
  const row = ui.models.list.find((p) => p.id === id);
  if (!row) return Promise.resolve(null);
  if (!confirm("删除模型配置「" + row.name + "」？\n只删这条本地记录，不影响服务端。")) return Promise.resolve(null);
  ui.models.busy = "delete";
  return AI.llmRemove(id)
    .then((j) => {
      ui.models.list = j.providers || [];
      ui.models.active = j.active || "";
      toast("已删除「" + row.name + "」", "ok");
      return refreshLlmConfig();
    })
    .catch((e) => toast("删除失败：" + e.message, "err"))
    .finally(() => { ui.models.busy = ""; });
}

function afterBoot() {
  // ComfyUI 是本地出图，不依赖大模型 Key；?ai=0 强制离线时也要能探测
  if (location.protocol !== "file:") comfyCheck();
  if (FORCE_LOCAL) {
    S.aiEnabled = false; S.llmAvailable = false;
    // 只在空项目上切到「不分集」，别把已有项目的设置改掉
    if (!S.episodes.length && !S.shots.length) S.episodeMode = "none";
    return;
  }
  if (location.protocol === "file:") return;
  // 后端可能还在跑拆解任务：先把进度接回来，再探测模型配置
  resumeParseTask();
  fetch("api/config", { cache: "no-store" }).then((r) => r.ok ? r.json() : null)
    .then((j) => {
      if (j && j.llm) {
        S.llmAvailable = true; S.llmModel = j.model || "";
        // S3：模型可用也不自动分集；刷新后保留旧方案，由用户显式点按钮重算。
      }
    }).catch(() => { /* 服务未启动：离线模式 */ });
}

export function boot() {
  const onFile = location.protocol === "file:";
  const q = new URLSearchParams(location.search);
  saveTimer && clearTimeout(saveTimer);

  // 首屏先用缓存画出来，避免打开项目时白屏；服务端数据回来后再以服务端为准
  if (!onFile) restoreCache();

  if (onFile) {
    PROJECT.server = false; PROJECT.ready = true;
    ui.saveState = "local"; ui.saveNote = "本地文件模式 · 只存浏览器";
    afterBoot();
    return;
  }

  ui.projectBusy = true;
  ui.saveState = "saving"; ui.saveNote = "正在打开项目…";
  bootStore(q.get("project") || "", q.get("fresh") === "1")
    .catch((err) => {
      // 服务没起来 / 项目目录不可写：不白屏，用本机缓存继续（保存会提示「本机已缓存」）
      PROJECT.error = err.message || String(err);
      ui.saveState = "local";
      ui.saveNote = "服务不可用 · 已用本机缓存";
      if (!S.script) {
        const c = readCache();
        if (c && c.data) hydrate(c.data, { id: c.id || "", name: c.name || "" });
      }
    })
    .then(() => {
      PROJECT.ready = true;
      ui.projectBusy = false;
      if (ui.saveState === "saving") {
        ui.saveState = "saved";
        ui.saveNote = S.projectName ? ("已打开 · " + S.projectName) : "已就绪";
      }
      afterBoot();
    });
}

/* 关页 / 切后台时强制落盘：sendBeacon 不阻塞卸载，慢一步也不会丢内容 */
if (typeof window !== "undefined") {
  window.addEventListener("beforeunload", () => {
    if (!PROJECT.server || !S.projectId || !dirty) return;
    Projects.beaconSave(S.projectId, S.projectName, projectData());
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden" && PROJECT.server && S.projectId && dirty) flushSave();
  });
}
