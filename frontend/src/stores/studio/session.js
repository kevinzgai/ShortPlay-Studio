/* =========================================================================
 * 分镜工场 · 项目与会话（session）
 * 项目 CRUD 与切换、模型 / 出图引擎配置管理、启动引导（boot）、
 * 关页前的强制落盘。依赖 core 的状态与保存链；启动时接回 steps 的拆解任务、
 * 探测 assets 的 ComfyUI 状态。
 * ========================================================================= */
import AI from "../../lib/ai.js";
import Projects from "../../lib/projects.js";
import {
  S, ui, PROJECT, CACHE_KEY, LAST_KEY, FORCE_LOCAL,
  hydrate, blankProjectData, projectData, flushSave,
  toast, readCache, restoreCache, mirrorCache, updateProjectSummary,
  dirty, saveTimer
} from "./core.js";
import { comfyCheck } from "./assets.js";
import { resumeParseTask } from "./steps.js";

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
    qwenSize: draft.qwenSize || "",
    h3Url: draft.h3Url || "", h3Model: draft.h3Model || "", h3Size: draft.h3Size || ""
  };
  if (draft.clearQwenKey) body.clearQwenKey = true;
  else if (draft.qwenKey) body.qwenKey = draft.qwenKey;
  if (draft.clearH3Key) body.clearH3Key = true;
  else if (draft.h3Key) body.h3Key = draft.h3Key;
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
      // 同一个 models/unet/ 里混着 flux / h3-image / h3-video 三种架构，
      // 光给文件名用户选不动（试一次才知道出不来），这里把架构一起存下来
      ui.engine.modelArchs = j.archs || {};
      ui.engine.modelCurrent = j.current || null;
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
