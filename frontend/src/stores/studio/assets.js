/* =========================================================================
 * 分镜工场 · 资产（assets）
 * 第 4 步工作区：角色 / 场景 / 道具编辑与参考图、资产包（AI 分解）、
 * 起始帧提示词闸门、提示词复制、本地 ComfyUI / 万相批量出图。
 * ========================================================================= */
import { computed } from "vue";
import {
  S, ui, E, AI, PROJECT, toast, begin, undo, save, busy, reparse,
  findAnyAsset, bankNote, bankForget, pushBaseline, copyText,
  STYLE_FALLBACK_CN, STYLE_FALLBACK_EN, STYLE_PRESETS
} from "./core.js";

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

/* --------------------------- 资产层操作 --------------------------- */

const ASSET_FIELD_LABEL = {
  appearance: "外观描述", wardrobe: "服装", age: "年龄", role: "身份",
  persona: "同一人分组", name: "名称", keyword: "固定关键词串"
};

export function setAssetTab(kind) { S.assetTab = kind; save(); }

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
    return { ok: false, reason: "打开出片工具完成定妆", dressed: dressed, shots: shots };
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
  keyword: "固定关键词串", main: "出图提示词",
  turnaround: "出图提示词", faceSheet: "出图提示词", concept: "场景概念图提示词",
  wide: "宽幕版提示词"
};
/** 每类资产能复制哪些中文提示词。
 *  【一资产一组】角色 / 场景只有一条出图提示词（main，兼容旧包的
 *  turnaround / faceSheet / concept 取一条），英文单独成条与它成对；
 *  道具没有预生成提示词，靠名称 + 描述拼一条。多视角按规则拆独立资产。 */
const ASSET_PROMPT_KEYS = {
  character: [["main", "出图提示词"]],
  scene: [["main", "场景概念图提示词"]],
  prop: []
};
/** 旧资产包里的多组提示词按优先级收敛成一条，避免同一资产挂两组。 */
function mainPromptText(a) {
  const p = a.prompts || {};
  return String(p.main || p.turnaround || p.faceSheet || p.concept || p.wide || "").trim();
}

/** 道具没出图提示词：用名称 + 描述 + 绑定角色拼一句可直接塞进镜头的话 */
function propPromptText(a) {
  const desc = String(a.appearance || "").trim();
  const body = (desc && desc !== a.name) ? desc : "按剧本描述还原材质与磨损";
  const who = (a.boundTo || []).filter(Boolean);
  return a.name + "：" + body + (who.length ? "（出现在 " + who.join("、") + " 的画面里）" : "");
}

/**
 * 一个资产的提示词 = 一条中文出图提示词 + 一条英文（成对，同一视角）。
 * 固定关键词串是镜头一致性锚点，不算出图提示词，单独一条给出（角色）。
 * 英文单独成条：Flux / Midjourney / 即梦这类工具只吃英文。
 */
export function assetPromptBlocks(a) {
  if (!a) return [];
  const out = [];
  const main = mainPromptText(a);
  if (a.kind === "prop") {
    out.push({ key: "prop", label: "道具描述", lang: "cn", text: propPromptText(a) });
  } else if (main) {
    out.push({ key: "main", label: a.kind === "scene" ? "场景概念图提示词" : "出图提示词",
      lang: "cn", text: main });
  }
  if (a.kind !== "prop" && String(a.keyword || "").trim()) {
    out.push({ key: "keyword", label: "固定关键词串", lang: "cn", text: String(a.keyword).trim() });
  }
  const en = String(a.kind === "character" ? (a.keywordEn || a.promptEn || "")
    : (a.kind === "scene" ? (a.promptEn || a.sceneEn || "") : "")).trim();
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
    if (mode === "en") toast("「" + a.name + "」还没有英文提示词 —— 先点「AI 补形象」生成", "warn");
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

/** 提示词正文直接编辑：出图提示词（main）与英文串（promptEn，兼容旧 keywordEn/sceneEn 读）。
 *  这些字段不进镜头签名（assetSignature 只看外观/参考图），改完不用重绑镜头；
 *  hasAuthored 会把它们算作手工痕迹，重新解析剧本不会丢。 */
export function saveAssetPrompt(id, key, value) {
  const a = findAnyAsset(id);
  if (!a) return;
  const v = String(value ?? "").trim();
  const cur = key === "promptEn" ? enOf(a)
    : String((a.prompts || {})[key] || "");
  if (cur === v) return;
  begin();
  if (key === "promptEn") a.promptEn = v;
  else { a.prompts = a.prompts || {}; a.prompts[key] = v; }
  a.touched = a.touched || {};
  a.touched["prompts." + key] = true;
  save();
}

/** 英文提示词唯一读取口：新字段 promptEn 优先，老项目的 keywordEn / sceneEn 兜底。 */
function enOf(a) {
  return String((a && (a.promptEn || a.keywordEn || a.sceneEn)) || "").trim();
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
    if (s.h3) {
      ui.comfy.h3.online = !!s.h3.online;
      ui.comfy.h3.model = s.h3.model || "";
      ui.comfy.h3.size = s.h3.size || "";
      ui.comfy.h3.detail = s.h3.detail || "";
    }
    ui.comfy.online = !!s.online;
    ui.comfy.checked = true;
    ui.comfy.version = s.version || "";
    ui.comfy.vramFreeMB = s.vramFreeMB || 0;
    ui.comfy.host = s.host || "";
    ui.comfy.model = s.model || "";
    ui.comfy.detail = s.online ? "" : (s.detail || "未连接");
    // 架构由后端按 comfyModel 判定（flux / h3-image / h3-video）：
    // 界面靠它决定能不能出图，不再出现「点了才发现模型不对」
    if (s.arch && s.arch.arch) ui.comfy.arch = s.arch;
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
        // 英文唯一出口 promptEn：AI 返回的 keywordEn 同步写进来，读侧才不用分叉
        if (r.keywordEn) { a.promptEn = r.keywordEn; a.touched.promptEn = 1; }
        if (r.face) { a.appearance = r.face; a.touched.appearance = 1; }
        a.anchors = Object.assign({}, a.anchors || {});
        ["face", "flaw", "wardrobeHook"].forEach((k) => {
          if (r[k]) { a.anchors[k] = r[k]; a.touched["anchors." + k] = 1; }
        });
      } else if (a.kind === "scene") {
        if (r.appearance) { a.appearance = r.appearance; a.touched.appearance = 1; }
        if (r.sceneEn) {
          a.sceneEn = r.sceneEn;
          a.promptEn = r.sceneEn;
          a.touched.sceneEn = 1; a.touched.promptEn = 1;
        }
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
  ui.comfy.engine = v === "qwen" ? "qwen" : v === "h3" ? "h3" : "comfy";
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
      seconds: it.seconds, uncompressed: it.uncompressed,
      /* 这一张是照着哪张脸出的。空串 = 它就是本批的锚（纯文生图） */
      refOf: it.refOf || ""
    };
    const k = a.genImages.findIndex((x) => x.variant === it.variant);
    if (k >= 0) a.genImages.splice(k, 1, row); else a.genImages.push(row);
    if (a.genImages.length > 6) a.genImages = a.genImages.slice(-6);
    /* 主参考图约定：资产只有一张生成图时，第一张就是默认图——
       包括「重新生成把多张变成一张」「旧主图已被替换」的情况，
       refImage 必须跟唯一那张对齐，不能指向已经不存在的旧图。
       多张时才留给用户手选；用户手动上传的参考图（非生成图）不在这条路径里，不会被动。 */
    if (a.genImages.length === 1) {
      const only = a.genImages[0];
      if (a.refImage !== only.dataUri) {
        a.refImage = only.dataUri;
        a.refName = only.label + " · 本地生成";
      }
    } else if (!a.refImage) {
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
  return list.map((a) => {
    /* 身份锚的传给方式：
       主参考图若指向某张本地生成图，就把它的文件名交给后端 —— 后端在磁盘上
       读原图、推到 ComfyUI 当 image_1，后续变体都照着这张脸出。
       纯上传的参考图只有 dataURI，后端没有磁盘路径，这里不传（那一张退回纯文生图）。
       没有生成图的资产也不传：本批会按「定妆半身 → 四视图 → 三视图」的顺序，
       让脸最大的先出、再给后面的当锚，见后端 _identity_refs。 */
    const hit = (a.genImages || []).find((x) => x.dataUri && x.dataUri === a.refImage);
    return {
      id: a.id, kind: a.kind, name: a.name, code: a.code || "",
      // 英文串读写统一 promptEn，老数据 keywordEn / sceneEn 兜底（出图后端仍吃这两个旧键）
      keywordEn: a.promptEn || a.keywordEn || "",
      keyword: a.keyword || "",
      sceneEn: a.promptEn || a.sceneEn || "",
      appearance: a.appearance || "", propEn: a.propEn || "",
      refFile: (hit && hit.file) ? String(hit.file).split("/").pop() : ""
    };
  });
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
  const cloud = engine === "qwen" || engine === "h3";
  const seqN = cloud ? (ui.comfy.seqN || 1) : 1;
  const online = cloud
    ? (engine === "qwen" ? ui.comfy.qwen.online : ui.comfy.h3.online)
    : ui.comfy.online;
  if (!online) {
    toast(cloud
      ? (engine === "qwen"
          ? "通义万相没配好：" + (ui.comfy.qwen.detail || "缺 API Key")
          : "MiniMax 没配好：" + (ui.comfy.h3.detail || "缺 API Key"))
      : "本地 ComfyUI 没连上，先启动 8188 或切到云端引擎", "warn");
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
