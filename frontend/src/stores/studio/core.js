/* =========================================================================
 * 分镜工场 · 状态核心（core）
 * 全局响应式状态（S / ui / PROJECT）、撤销栈与图仓、自动保存链、
 * 剧本解析入口（reparse）、toast / busy / modal 等跨域原语。
 * 域拆分（2026-11-11，函数体逐字未动）：session（项目与启动）、
 * steps（分集 / 闸门 / 生成链）、shots（分镜表 / 导出）、assets（资产 / 出图）。
 * 依赖方向恒为 域 → core，绝不反向；studio.js 是对外 barrel。
 * ========================================================================= */
import { computed, reactive } from "vue";
import E from "../../lib/engine.js";
import AI from "../../lib/ai.js";
import Projects from "../../lib/projects.js";

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
    // 当前 unet 的架构：flux / h3-image / h3-video。usable=false 时出图按钮要置灰
    arch: { arch: "flux", label: "Flux 文生图", usable: true, steps: 4, model: "" },
    variants: { character: [], scene: [], prop: [] },
    scope: "one", picked: { character: ["turnaround"], scene: ["concept"], prop: ["prop"] },
    jobId: "", busy: false, done: 0, total: 0, current: "",
    errors: [], results: [], filling: "",
    preview: null, previewBusy: false,
    engine: "comfy", seqN: 1,
    qwen: { online: false, model: "", size: "", detail: "" },
    h3: { online: false, model: "", size: "", detail: "" }
  },
  // 语言模型接入（列表 / 当前生效 / 测试结果）：纯界面态，不进撤销、不落盘
  models: {
    list: [], active: "", env: null, loaded: false,
    busy: "", testing: "", result: null
  },
  // 出图引擎配置（全局单例，与语言模型的分条列表不同）：纯界面态，不进撤销
  engine: {
    loaded: false, busy: "", testing: "", result: null,
    config: {}, models: [], modelsBusy: false, modelsHost: "",
    // models 里每个文件的架构（flux / h3-image / h3-video），换模型时标出哪个能用
    modelArchs: {}, modelCurrent: null
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
  // 主流程到这里就结束了。保留 no=4 只为兼容项目存档与回归锚点（data-step="4" / #view-4），
  // 产品定位是「分镜页里的可选出片工具」，不再是平级工作区。
  { no: 4, stage: "production", stageName: "制作阶段", label: "定妆", optional: true,
    hint: "可选 · 参考图 / 首帧 / 整包导出" }
];
export const STAGES = [
  { key: "script", name: "剧本阶段", note: "把文字整理成结构", steps: [1, 2] },
  { key: "production", name: "制作阶段", note: "主流程 3 步 · 出片可选", steps: [3, 4] }
];
export const stageOf = (n) => (Number(n) <= 2 ? "script" : "production");

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

/** focus 记基线、change 才入栈，和镜头字段一致，避免每敲一个字压一次撤销 */
export function onAssetFocusin(e) {
  if (e.target.matches && e.target.matches("[data-afield]")) pendingBaseline = snapshot();
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

/* ---- 供兄弟域使用的内部原语（仅 stores/studio/* 内部契约，不对外承诺） ---- */
export {
  CACHE_KEY, LAST_KEY, mirrorCache, readCache, restoreCache,
  updateProjectSummary, stalePlanIfAny,
  findAnyAsset, bankNote, bankForget, pushBaseline, dirty, saveTimer,
  blankProjectData, markStale
};
