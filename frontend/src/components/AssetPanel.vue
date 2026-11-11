<script setup>
import { computed, ref, watch, nextTick, onMounted, onUnmounted } from "vue";
import {
  S, ui, assetTabs, assetSummary, assetUsage, staleAssetCount, refreshAssets, setAssetTab,
  onAssetFocusin, onAssetChange, toggleAssetLock, uploadAssetRef, clearAssetRef,
  addProp, delAsset, assetPackStats, buildAssetPack, regenFrames,
  copyAssetPrompt, copyAllAssetPrompts, assetPromptBlocks, saveAssetAnchor, saveAssetKeyword, copyText,
  comfyCheck, fillAssetWithAI, comfyGenerateImages, comfyToggleVariant, comfyPreviewPrompts,
  comfySetScope, comfySetEngine, comfySetSeqN, setPrimaryGenImage, clearGenImages,
  STYLE_PRESETS, currentStyle, saveStyleConfig, resetStyleConfig
} from "../stores/studio.js";

const props = defineProps({ collapsible: { type: Boolean, default: false } });

/* ---------------------- 视图：按分镜分组 / 全部资产 ----------------------
   资产实体仍是全片共享（改一次外观全片同步），这里只按 shot.charIds /
   sceneId / propIds 的绑定关系过滤展示，不再跨镜混排。
   默认仍是「全部资产」：tools/verify_* 的 .ap-row / [data-asset-tab] 全靠它。
   用户切换只记本机 localStorage，回归脚本用全新 context，不受影响。 */
const VIEW_KEY = "shortplay.ap.view";
function loadView() {
  try { return localStorage.getItem(VIEW_KEY) === "shot" ? "shot" : "all"; }
  catch (e) { return "all"; }
}
const viewMode = ref(loadView());
function setViewMode(v) {
  viewMode.value = v === "shot" ? "shot" : "all";
  try { localStorage.setItem(VIEW_KEY, viewMode.value); } catch (e) { /* 隐私模式忽略 */ }
  q.value = "";
  if (viewMode.value === "all" && ui.comfy.scope === "shot") comfySetScope("one");
  closePreview();
}
const shotId = ref("");
const shotQuery = ref("");
const epFilter = ref("all");
const detailEl = ref(null);
const shotList = computed(() => S.shots || []);
const episodes = computed(() => [...new Set(shotList.value
  .map((s) => String(s.episode ?? "")).filter(Boolean))].sort((a, b) => Number(a) - Number(b)));
watch(() => shotList.value.map((s) => s.id).join(","), () => {
  if (!shotList.value.some((s) => s.id === shotId.value)) shotId.value = shotList.value[0]?.id || "";
}, { immediate: true });
const curShot = computed(() => shotList.value.find((s) => s.id === shotId.value) || shotList.value[0] || null);
const curShotNo = computed(() => Math.max(1, shotList.value.findIndex((s) => s.id === curShot.value?.id) + 1));
const assetIndex = computed(() => {
  const m = {};
  [].concat(S.assets.characters, S.assets.scenes, S.assets.props)
    .forEach((a) => { if (a && a.id) m[a.id] = a; });
  return m;
});
function groupsOf(shot) {
  const m = assetIndex.value;
  const pick = (ids) => (ids || []).map((id) => m[id]).filter(Boolean);
  return {
    character: pick(shot && shot.charIds),
    scene: pick(shot && shot.sceneId ? [shot.sceneId] : []),
    prop: pick(shot && shot.propIds)
  };
}
const curGroups = computed(() => groupsOf(curShot.value));
const curShotAssets = computed(() => [].concat(
  curGroups.value.character, curGroups.value.scene, curGroups.value.prop));
function hasImage(a) { return !!(a && (a.refImage || (a.genImages || []).length)); }
function shotState(s) {
  const g = groupsOf(s);
  const all = [].concat(g.character, g.scene, g.prop);
  const miss = all.filter((a) => !hasImage(a)).length;
  return { total: all.length, miss, ready: all.length > 0 && !miss, empty: !all.length,
           n: { character: g.character.length, scene: g.scene.length, prop: g.prop.length } };
}
const navStats = computed(() => {
  let ready = 0;
  shotList.value.forEach((s) => { if (shotState(s).ready) ready++; });
  return { total: shotList.value.length, ready, pending: shotList.value.length - ready };
});
const curShotState = computed(() => shotState(curShot.value));
const curFrame = computed(() => (S.frames || []).find((f) => f.code === curShot.value?.code) || null);
const shotRows = computed(() => {
  const k = shotQuery.value.trim().toLowerCase();
  return shotList.value.map((s, i) => ({ shot: s, no: i + 1, st: shotState(s) })).filter((r) => {
    if (epFilter.value !== "all" && String(r.shot.episode) !== epFilter.value) return false;
    if (!k) return true;
    return [r.shot.code, r.shot.visual, r.shot.dialogue, r.shot.speaker, r.shot.sceneLabel, r.shot.notes]
      .join(" ").toLowerCase().includes(k);
  });
});
function stepShot(n) {
  const i = shotRows.value.findIndex((r) => r.shot.id === curShot.value?.id);
  const t = shotRows.value[i + n];
  if (t) { shotId.value = t.shot.id; closePreview(); }
}
function shotLabel(s) { return s.code || ("#" + (s.no ?? "")); }
function shotSub(s) {
  return [s.episode ? "第" + s.episode + "集" : "",
    s.sceneLabel ? String(s.sceneLabel).slice(0, 14) : (s.sceneNo ? "场次" + s.sceneNo : ""),
    s.size, (s.duration || 0) + "s"].filter(Boolean).join(" · ");
}
function shotText(s) { return String(s.visual || s.detail || "（暂无画面描述）"); }
function heroNotes(s) {
  const bits = [s.speaker ? s.speaker + "：" + (s.dialogue || "（无台词内容）") : (s.dialogue || "（无台词）")];
  if (s.notes) bits.push("备注：" + s.notes);
  bits.push("风格锚：" + currentStyle().anchor);
  return bits.join(String.fromCharCode(10));
}
function shotThumb(s) {
  const g = groupsOf(s);
  const a = g.scene[0] || g.character[0] || g.prop[0];
  if (!a) return "";
  return a.refImage ? refSrc(a, 128) : ((a.genImages || [])[0] || {}).dataUri || "";
}
const GROUPS = [
  { kind: "character", label: "角色", cap: "本镜出场角色 · 顺序即参考图槽位" },
  { kind: "scene", label: "场景", cap: "本镜所在场地" },
  { kind: "prop", label: "道具", cap: "本镜出现的关键物件" }
];
function groupItems(kind) {
  const list = (curGroups.value[kind] || []).slice();
  return onlyP0.value ? list.filter((a) => (a.priority || "P1") === "P0") : list;
}
function cardSub(a) {
  if (a.kind === "character") return String(a.role || a.age || "").split(/[，,。;；]/)[0].slice(0, 12) || "角色";
  if (a.kind === "scene") return [metaText(a.intExt), metaText(a.time)].filter(Boolean).join(" · ") || "场景";
  return (a.boundTo || []).join(" / ") || "道具";
}
function cardDesc(a) {
  const t = String(a.keyword || a.appearance || a.wardrobe || a.role || a.name || "").replace(/\s+/g, " ");
  return t.slice(0, 56) || "由剧本分解自动提取设定";
}
function cardVariant(a) {
  const p = a.prompts || {};
  if (p.turnaround) return "三视图";
  if (p.faceSheet) return "面部四视图";
  if (p.concept) return "场景概念图";
  if (p.wide) return "宽幕建立镜";
  return ((a.genImages || [])[0] || {}).label || "设定图";
}
function pickShotAsset(a) {
  if (S.assetTab !== a.kind) setAssetTab(a.kind);
  pick(a.id);
  nextTick(() => detailEl.value?.scrollIntoView({ behavior: "smooth", block: "start" }));
}
function redrawShotAsset(a) {
  if (S.assetTab !== a.kind) setAssetTab(a.kind);
  pick(a.id);
  comfySetScope("one");
  comfyGenerateImages(a.id);
}
function doGenerate() {
  comfyGenerateImages(sel.value && sel.value.id,
    viewMode.value === "shot" && ui.comfy.scope === "shot"
      ? (curGroups.value[S.assetTab] || []).map((a) => a.id) : null);
}
function focusPropDraft() {
  if (S.assetTab !== "prop") setAssetTab("prop");
  nextTick(() => {
    const el = document.getElementById("prop-draft");
    if (el) { el.focus(); el.scrollIntoView({ behavior: "smooth", block: "nearest" }); }
  });
}

const cur = computed(() => assetTabs.value.find((t) => t.kind === S.assetTab) || assetTabs.value[0]);
const open = computed(() => !props.collapsible || ui.assetOpen);
const stats = assetPackStats;
const onlyP0 = ref(false);
const q = ref("");
const selId = ref("");
/** 提示词默认展开：右边一次只看一个资产，收起反而留一块空白 */
const promptsOpen = ref(true);

function toggleOpen() { ui.assetOpen = !ui.assetOpen; }

/** P0 是「必须先出图定基准」的那批，筛出来就是生成顺序的前半段。 */
const items = computed(() => {
  const list = viewMode.value === "shot" ? curShotAssets.value : (cur.value.items || []);
  return onlyP0.value ? list.filter((a) => (a.priority || "P1") === "P0") : list;
});
const p0Count = computed(() => (viewMode.value === "shot" ? curShotAssets.value : (cur.value.items || []))
  .filter((a) => (a.priority || "P1") === "P0").length);

/** 列表里的搜索：名称 / 编号 / 别名 / 固定关键词串都能命中 */
const shown = computed(() => {
  const k = q.value.trim().toLowerCase();
  if (!k) return items.value;
  return items.value.filter((a) =>
    (a.name || "").toLowerCase().includes(k) ||
    (a.code || "").toLowerCase().includes(k) ||
    (a.aliases || []).join(" ").toLowerCase().includes(k) ||
    (a.keyword || "").toLowerCase().includes(k)
  );
});

const idx = computed(() => shown.value.findIndex((a) => a.id === (selId.value || shown.value[0]?.id)));
const sel = computed(() => shown.value[idx.value] || shown.value[0] || null);
function pick(id) { selId.value = id; promptsOpen.value = true; }

// 场景卡的「内外景 · 时间」：老数据里可能存着「未注明」这类占位词，统一走「未标内外景」
const META_PLACEHOLDER = ["未注明", "未指定", "未标注", "未确定", "未知", "待定", "不详"];
function metaText(v) {
  const t = String(v ?? "").trim();
  return META_PLACEHOLDER.includes(t) ? "" : t;
}
const sceneMeta = computed(() => {
  const a = sel.value;
  if (!a || a.kind !== "scene") return "";
  const ext = metaText(a.intExt) || "未标内外景";
  const tm = metaText(a.time);
  return ext + (tm ? " · " + tm : "");
});
function rowCls(a) { return ["ap-row", "k-" + a.kind, a.id === sel.value?.id ? "on" : ""]; }
/* S5 · 资产引用信息：左清单给短徽标（行高不能超 36px，见 verify_asset_layout），
   完整文案放 title 与分组卡。零引用标琥珀色，说明它来自剧本/旧镜头、不会被自动删除。 */
function usageOf(a) { return (a && assetUsage.value[a.id]) || null; }
function usageShort(a) { const u = usageOf(a); return u ? u.short : "0镜 · 兜底"; }
function usageLabel(a) { const u = usageOf(a); return u ? u.label : "现无镜头引用 · 剧本兜底保留"; }
function usageOrphan(a) { const u = usageOf(a); return !!(u && u.orphan); }
function stepBy(n) {
  const t = shown.value[idx.value + n];
  if (t) selId.value = t.id;
}
/** 换 tab / 改筛选后选中项可能不在列表里了，自动落到第一项 */
watch([() => S.assetTab, () => viewMode.value, () => shotId.value,
  () => shown.value.map((a) => a.id).join(",")], () => {
  if (!shown.value.some((a) => a.id === selId.value)) selId.value = shown.value[0]?.id || "";
}, { immediate: true });

const ANCHORS = {
  character: [
    { key: "face", label: "面部", ph: "脸型 / 眼型 / 骨相，例：内双丹凤眼、眼下青黑" },
    { key: "flaw", label: "瑕疵", ph: "一处可辨识的缺点，例：右眉尾 0.5cm 浅疤" },
    { key: "wardrobeHook", label: "记忆点", ph: "服装 / 配饰上的固定件，例：颈挂红绳老青玉牌" }
  ],
  scene: [
    { key: "props", label: "陈设", ph: "用顿号分隔，例：八仙桌、钟馗像、转盘电话" },
    { key: "light", label: "光影", ph: "例：亮瓦斜射暖金色夕光" },
    { key: "lens", label: "镜头", ph: "例：24mm广角" }
  ],
  prop: []
};

function anchorsOf(a) { return ANCHORS[a.kind] || []; }
function anchorValue(a, key) {
  const v = (a.anchors || {})[key];
  return Array.isArray(v) ? v.join("、") : (v || "");
}
const PROMPTS = {
  character: [["turnaround", "三视图"], ["faceSheet", "面部四视图"]],
  scene: [["concept", "场景概念图"], ["wide", "宽幕版"]],
  prop: []
};
function promptsOf(a) {
  const raw = a.prompts || {};
  const list = (PROMPTS[a.kind] || []).filter(([k]) => raw[k]).map(([k, label]) => [k, label, raw[k]]);
  // 道具没有预生成提示词，但「名称 + 描述」这一句本身就能直接塞进镜头，照样给出来可复制
  if (a.kind === "prop") {
    const blk = assetPromptBlocks(a).find((b) => b.key === "prop");
    if (blk) list.push(["prop", "道具描述", blk.text]);
  }
  return list;
}
const SOURCE = { script: "剧本原文", inferred: "AI 推断", manual: "手动新增", user: "手工修改" };

const aiReady = computed(() => S.aiEnabled && S.llmAvailable);
// 道具补的是「中文描述 + 英文道具名」：Flux 只吃英文，中文名等于没写
const fillTitle = computed(() => (sel.value?.kind === "prop"
  ? "只读剧本里提到它的片段，补中文描述与英文道具名（本地出图吃的是英文）"
  : "只读剧本里与这个资产相关的片段，补全脸型 / 瑕疵 / 服装记忆点与英文关键词"));

/* ---------------------- 一键复制提示词（角色 / 场景 / 道具通用） ---------------------- */
/* 之前只有「固定关键词串」旁边一个 ⧉，场景和道具没有入口，英文串更是存了拿不出来。
   现在统一走 copyAssetPrompt(id, 'all' | 'en' | 'keyword' | 具体 key)。 */
const copiedId = ref("");
let copiedTimer = null;
function flashCopied(key) {
  copiedId.value = key;
  clearTimeout(copiedTimer);
  copiedTimer = setTimeout(() => { copiedId.value = ""; }, 1500);
}
function copyOne(id, mode) {
  copyAssetPrompt(id, mode || "all");
  flashCopied(id + ":" + (mode || "all"));
}
function hasEn(a) { return assetPromptBlocks(a).some((b) => b.lang === "en"); }

/* ------------------------ 剧本视觉风格定义 ------------------------ */
const styleOpen = ref(false);
const styleDraft = ref({ key: "", anchor: "", anchorEn: "" });
const curStyle = computed(() => currentStyle());
const styleShort = computed(() => {
  const p = STYLE_PRESETS.find((x) => x.key === curStyle.value.key);
  return (p && curStyle.value.anchor === p.anchor) ? p.label : curStyle.value.anchor.slice(0, 12);
});
function toggleStyleEditor() {
  if (styleOpen.value) { styleOpen.value = false; return; }
  styleDraft.value = {
    key: (S.styleConfig && S.styleConfig.key) || "",
    anchor: curStyle.value.anchor, anchorEn: curStyle.value.anchorEn
  };
  styleOpen.value = true;
}
function pickStylePreset(p) {
  styleDraft.value = { key: p.key, anchor: p.anchor, anchorEn: p.anchorEn };
}
function applyStyle() { saveStyleConfig(styleDraft.value); styleOpen.value = false; }
function clearStyle() { resetStyleConfig(); styleOpen.value = false; }

/* ------------------------ 本地 ComfyUI 批量出图 ------------------------ */
const FALLBACK_VARIANTS = {
  character: [{ key: "turnaround", label: "三视图" }, { key: "faceSheet", label: "面部四视图" }, { key: "portrait", label: "定妆半身" }],
  scene: [{ key: "concept", label: "场景概念图" }, { key: "wide", label: "宽幕建立镜" }],
  prop: [{ key: "prop", label: "道具静物" }]
};
const genVariants = computed(() => {
  const v = ui.comfy.variants[S.assetTab];
  return (v && v.length) ? v : (FALLBACK_VARIANTS[S.assetTab] || []);
});
const TAB_NAME = { character: "角色", scene: "场景", prop: "道具" };
const SCOPES = computed(() => [
  { k: "one", t: "当前资产", h: "只出详情里选中的这一个" },
  ...(viewMode.value === "shot"
    ? [{ k: "shot", t: "本镜资产", h: "只出当前分镜绑定的这一类资产" }] : []),
  { k: "p0", t: "P0 资产", h: "只出标了 P0 的核心资产" },
  { k: "all", t: "本栏全部", h: "这个标签页里的全部资产都出" }
]);
/* 范围 → 具体要出图的资产清单（张数 = 资产数 × 选中的画幅数） */
const scopeList = computed(() => {
  const key = { character: "characters", scene: "scenes", prop: "props" }[S.assetTab] || "characters";
  const all = S.assets[key] || [];
  if (viewMode.value === "shot" && ui.comfy.scope === "shot") return curGroups.value[S.assetTab] || [];
  if (ui.comfy.scope === "one") return all.filter((a) => a.id === (sel.value && sel.value.id));
  if (ui.comfy.scope === "p0") return all.filter((a) => (a.priority || "P1") === "P0");
  return all;
});
const cloudEngine = computed(() => ui.comfy.engine === "qwen" || ui.comfy.engine === "h3");
const genCount = computed(() => scopeList.value.length * (ui.comfy.picked[S.assetTab] || []).length
  * (cloudEngine.value ? (ui.comfy.seqN || 1) : 1));
const engineOnline = computed(() => cloudEngine.value
  ? (ui.comfy.engine === "qwen" ? ui.comfy.qwen.online : ui.comfy.h3.online)
  : ui.comfy.online);
/* 引擎在线 ≠ 能出图：ComfyUI 里若选了视频模型（fl2va 等），提交上去必失败。
   后端 /api/comfy/status 已按模型名判定架构，这里直接用它把按钮置灰。 */
const archBlocked = computed(() => !cloudEngine.value
  && !!ui.comfy.arch && ui.comfy.arch.usable === false);
/* 耗时口径跟着架构说话：换成 H3-Image 还写「Flux 单张 6–12 秒」会误导 */
const localHint = computed(() => {
  const a = (ui.comfy.arch && ui.comfy.arch.arch) || "flux";
  return (a === "h3-image" ? "H3-Image 单张约 6–12 秒" : "Flux 单张约 6–12 秒") + "，别关页面";
});
/* 这一行不是按钮、是「出图参数」：点完只会改这里的一行说明，真正出图在右边那个按钮 */
const genSummary = computed(() => {
  const n = scopeList.value.length;
  const k = (ui.comfy.picked[S.assetTab] || []).length;
  const tab = TAB_NAME[S.assetTab] || "资产";
  if (!k) return "至少选一种画幅";
  if (!n) return ui.comfy.scope === "p0" ? "本栏没有 P0 " + tab
    : ui.comfy.scope === "shot" ? "本镜没有" + tab + "资产" : "先在左侧选一个" + tab;
  const seq = cloudEngine.value ? " × " + (ui.comfy.seqN || 1) + " 张/组" : "";
  const total = n * k * (cloudEngine.value ? (ui.comfy.seqN || 1) : 1);
  return n + " 个" + tab + " × " + k + " 种画幅" + seq + " = " + total + " 张";
});
const genPct = computed(() => ui.comfy.total ? Math.round(ui.comfy.done / ui.comfy.total * 100) : 0);
function vramText(mb) { return (Math.round(mb / 102.4) / 10).toFixed(1) + "G"; }

/* 参考图是原图（不压缩），列表 / 头像没必要解码整张：
   问服务端要一个缩略尺寸即可，下载与打包拿到的仍是原图。老项目的 dataURI 原样用。 */
function refSrc(a, w) {
  const u = String((a && a.refImage) || "");
  if (!u) return "";
  return u.indexOf("/api/projects/ref?") === 0 ? u + "&w=" + w : u;
}

/* 刷新只有一个入口：有镜头提示词过期就刷提示词，否则重算起始帧。
   以前并排两个按钮（刷新 N 镜提示词 / 重算起始帧），看着都像「刷新」，点错了白等一轮。 */
const refreshLabel = computed(() => {
  if (staleAssetCount.value) return "刷新 " + staleAssetCount.value + " 镜提示词";
  if (stats.value.ready && S.shots.length) return "重算起始帧提示词";
  return "";
});
function doRefresh() {
  if (staleAssetCount.value) refreshAssets();
  else regenFrames(false);
}

/* 本地出图真正发出去的英文串：直接问服务端拼装器，不在这里二次拼 */
const flux = computed(() => ui.comfy.preview || []);
function showFlux() { comfyPreviewPrompts(sel.value && sel.value.id); }
function copyFlux() {
  const text = flux.value.map((r) => r.assetName + " · " + r.label + "\n" + r.prompt).join("\n\n");
  copyText(text, "已复制 " + flux.value.length + " 条本地出图提示词");
}

/* ------------------------ 资产图大图预览（灯箱） ------------------------ */
/* 两类图共用一套灯箱：
   - 参考图（ref）：直接吃原图 URL，不带 &w= 缩略参数，看到的是落盘原始像素；
     老项目的 dataURI 也照用，但那种图当年被压过，放大只会更糊。
   - 本地生成图（gen）：一个资产挂多张，可翻页；优先读 examples/assets/ 的原图，
     读不到（服务重启 / 文件被清）才回退缩略 dataURI。 */
const lbKind = ref("");        // "" | "ref" | "gen"
const lbAsset = ref(null);     // 正在预览的资产（从列表点开时可能不是当前选中项）
const previewIdx = ref(-1);
const previewFailed = ref(false);
const zoomed = ref(false);

const previewList = computed(() => {
  const a = lbAsset.value;
  if (!a) return [];
  if (lbKind.value === "ref") return a.refImage ? [{ label: "参考图", src: a.refImage, isRef: true }] : [];
  return a.genImages || [];
});
const previewRow = computed(() => previewList.value[previewIdx.value] || null);
const previewFile = computed(() => {
  const f = previewRow.value && previewRow.value.file;
  return f ? String(f).split("/").pop() : "";
});
const previewImgSrc = computed(() => {
  const row = previewRow.value;
  if (!row) return "";
  if (row.isRef) return row.src;
  return (!previewFailed.value && previewFile.value)
    ? "/api/comfy/image?f=" + encodeURIComponent(previewFile.value)
    : row.dataUri;
});
/* 下载名：落盘图从 URL 的 name= 取，dataURI 只能按 mime 猜扩展名 */
function refDownName(a) {
  const u = String((a && a.refImage) || "");
  const m = /[?&]name=([^&]+)/.exec(u);
  if (m) return decodeURIComponent(m[1]);
  const ext = (u.match(/^data:image\/([a-z0-9+]+)/i) || [])[1] || "png";
  return ((a && a.name) || "参考图") + "." + (ext === "jpeg" ? "jpg" : ext);
}
function openRefLb(a) {
  if (!a || !a.refImage) return;
  lbKind.value = "ref"; lbAsset.value = a; previewIdx.value = 0;
  previewFailed.value = false; zoomed.value = false;
}
function openPreview(i) {
  lbKind.value = "gen"; lbAsset.value = sel.value; previewIdx.value = i;
  previewFailed.value = false; zoomed.value = false;
}
function closePreview() {
  lbKind.value = ""; lbAsset.value = null; previewIdx.value = -1; zoomed.value = false;
}
function previewStep(n) {
  const len = previewList.value.length;
  if (len > 1) previewIdx.value = (previewIdx.value + n + len) % len;
}
function toggleZoom() { if (previewRow.value) zoomed.value = !zoomed.value; }
function onPreviewKey(e) {
  if (!previewRow.value) return;
  if (e.key === "Escape") { e.preventDefault(); closePreview(); }
  else if (e.key === "ArrowLeft") { e.preventDefault(); previewStep(-1); }
  else if (e.key === "ArrowRight") { e.preventDefault(); previewStep(1); }
}
onMounted(() => window.addEventListener("keydown", onPreviewKey));
onUnmounted(() => {
  window.removeEventListener("keydown", onPreviewKey);
  document.body.style.overflow = "";
  clearTimeout(copiedTimer);
});
watch(previewIdx, () => { previewFailed.value = false; zoomed.value = false; });
/* 灯箱开着时锁住底层滚动：不然滚轮一路划到底，背景页面跟着跑 */
watch(previewRow, (row) => { document.body.style.overflow = row ? "hidden" : ""; });
/* 换资产时收起灯箱，免得索引指到另一张资产的图；提示词预览同理清掉，别拿着上一个资产的串 */
watch(() => sel.value && sel.value.id, () => { closePreview(); ui.comfy.preview = null; });
</script>

<template>
  <section class="card pad asset-card ap" id="asset-panel">
    <div class="ap-head">
      <div class="ap-title">
        <h2>资产包</h2>
        <span v-if="stats.ready" class="chip" :class="stats.warnings ? 'warn' : 'ok'">
          {{ stats.warnings ? stats.warnings + " 条待核对" : "校验通过" }}
        </span>
        <span class="chip">{{ assetSummary.characters }} 角色 · {{ assetSummary.scenes }} 场景 · {{ assetSummary.props }} 道具</span>
        <span v-if="stats.frames" class="chip indigo">{{ stats.frames }} 镜起始帧</span>
        <span v-if="assetSummary.withRef" class="chip">{{ assetSummary.withRef }} 张参考图</span>
      </div>
      <div class="ap-actions">
        <button v-if="refreshLabel" class="btn sm" :class="{ quiet: !staleAssetCount }"
          id="refresh-assets" @click="doRefresh">{{ refreshLabel }}</button>
        <button class="btn sm" :class="{ primary: !stats.ready }" id="build-assets"
          :disabled="S.assetBusy || !aiReady" :title="aiReady ? '' : '需要先配置大模型 Key'"
          @click="buildAssetPack">
          {{ S.assetBusy ? "分解中…" : (stats.ready ? "重新分解资产" : "AI 分解资产") }}
        </button>
        <button v-if="collapsible" class="btn sm quiet" id="asset-toggle" @click="toggleOpen">{{ ui.assetOpen ? "收起" : "展开" }}</button>
      </div>
    </div>

    <!-- 本地 ComfyUI 出图工具条：AI 填好的设定 → 一键批量出素材图 -->
    <div v-show="open" v-if="ui.comfy.checked" class="ap-gen">
      <div class="ap-gen-l">
        <span class="ap-gen-dot" :class="engineOnline ? 'on' : 'off'"></span>
        <div class="ap-gen-seg" title="切换出图引擎">
          <button :class="{ on: ui.comfy.engine === 'comfy' }" @click="comfySetEngine('comfy')">本地 ComfyUI</button>
          <button :class="{ on: ui.comfy.engine === 'qwen' }" @click="comfySetEngine('qwen')">通义万相</button>
          <button :class="{ on: ui.comfy.engine === 'h3' }" @click="comfySetEngine('h3')"
            title="云端 MiniMax，要配 API Key；本机那套 H3-Image 在「本地 ComfyUI」里换 unet">MiniMax H3（云端）</button>
        </div>
        <span v-if="ui.comfy.engine === 'qwen'" class="ap-gen-info" :class="{ off: !ui.comfy.qwen.online }">
          {{ ui.comfy.qwen.online ? (ui.comfy.qwen.model + ' · ' + ui.comfy.qwen.size + ' · 云端组图') : ui.comfy.qwen.detail }}
        </span>
        <span v-else-if="ui.comfy.engine === 'h3'" class="ap-gen-info" :class="{ off: !ui.comfy.h3.online }">
          {{ ui.comfy.h3.online ? (ui.comfy.h3.model + ' · ' + ui.comfy.h3.size + ' · 云端生图') : ui.comfy.h3.detail }}
        </span>
        <span v-else-if="ui.comfy.online" class="ap-gen-info" :class="{ off: archBlocked }">
          ComfyUI {{ ui.comfy.version }} · {{ ui.comfy.model }} · 显存空闲 {{ vramText(ui.comfy.vramFreeMB) }}
          <em v-if="ui.comfy.arch && ui.comfy.arch.label" class="ap-gen-arch"
            :title="archBlocked ? '这个模型走视频链路，出不了定妆 / 道具图' : '当前出图架构与默认步数'">
            {{ ui.comfy.arch.label }} · {{ ui.comfy.arch.steps }} 步
          </em>
        </span>
        <span v-else class="ap-gen-info off">{{ ui.comfy.detail }} · 启动 8188 后重试</span>
        <button class="mini" title="重新探测出图引擎" @click="comfyCheck">↻</button>
        <span class="ap-gen-style" :title="'出图风格锚：' + curStyle.anchorEn">风格 · {{ styleShort }}</span>
      </div>
      <div v-if="engineOnline" class="ap-gen-r">
        <div class="ap-gen-grp">
          <span class="ap-gen-cap" title="决定给几个资产出图">出图范围</span>
          <div class="ap-gen-seg">
            <button v-for="s in SCOPES" :key="s.k" :class="{ on: ui.comfy.scope === s.k }"
              :title="s.h" @click="comfySetScope(s.k)">{{ s.t }}</button>
          </div>
        </div>
        <div class="ap-gen-grp">
          <span class="ap-gen-cap" title="同一个资产出几种画幅，可多选">画幅</span>
          <div class="ap-gen-seg vars">
            <button v-for="v in genVariants" :key="v.key"
              :class="{ on: (ui.comfy.picked[S.assetTab] || []).includes(v.key) }"
              :title="'画幅 ' + (v.w || '?') + '×' + (v.h || '?')"
              @click="comfyToggleVariant(S.assetTab, v.key)">{{ v.label }}</button>
          </div>
        </div>
        <div v-if="cloudEngine" class="ap-gen-grp">
          <span class="ap-gen-cap" title="一次生成几张前后一致的组图">组图张数</span>
          <div class="ap-gen-seg">
            <button v-for="k in [1, 2, 3, 4]" :key="k" :class="{ on: ui.comfy.seqN === k }"
              @click="comfySetSeqN(k)">{{ k }}</button>
          </div>
        </div>
        <div class="ap-gen-act">
          <span class="ap-gen-sum" :class="{ warn: !genCount || archBlocked }">
            {{ archBlocked ? "当前模型是视频模型，出不了静帧" : genSummary }}
          </span>
          <button class="btn sm primary" id="comfy-generate"
            :disabled="ui.comfy.busy || !genCount || archBlocked"
            :title="archBlocked ? '到「系统设置 · 出图引擎」把 unet 换成 flux1-schnell-fp8 或 minimax_h3_image' : ''"
            @click="doGenerate">
            {{ ui.comfy.busy ? "生成中…" : "✦ 一键生成 " + genCount + " 张" }}
          </button>
        </div>
      </div>
    </div>

    <div v-show="open" v-if="ui.comfy.busy || ui.comfy.results.length || ui.comfy.errors.length" class="ap-gen-status">
      <template v-if="ui.comfy.busy">
        <div class="ap-gen-bar"><i :style="{ width: genPct + '%' }"></i></div>
        <span>已出 {{ ui.comfy.done }} / {{ ui.comfy.total }} 张</span>
        <span class="ap-gen-cur">{{ ui.comfy.current || "排队中…" }}</span>
        <span class="ap-gen-hint">{{ cloudEngine ? '云端生图单批约 20–60 秒，别关页面' : localHint }}</span>
      </template>
      <template v-else>
        <span class="ok">✓ 完成 {{ ui.comfy.results.length }} 张，已挂到对应资产</span>
        <span v-if="ui.comfy.results.some((r) => r.fallbackEn)" class="warn">
          部分资产缺英文关键词，出图用了中文兜底 → 建议先「AI 补形象」
        </span>
      </template>
      <ul v-if="ui.comfy.errors.length" class="ap-gen-errs">
        <li v-for="(e, i) in ui.comfy.errors" :key="i">{{ e.assetName }} · {{ e.variantLabel }}：{{ e.detail }}</li>
      </ul>
    </div>

    <div v-show="open">
      <!-- 没做过分解：说清楚能拿到什么，而不是只给一个空列表 -->
      <div v-if="!stats.ready" class="ap-intro">
        <div class="ap-intro-t">
          还没做资产分解。这一步会把剧本读一遍，产出<b>角色三视图提示词、场景概念图、固定关键词串</b>和每镜起始帧提示词。
        </div>
        <ul>
          <li><b>编号与优先级</b>：C01 / S01，P0 是必须先生成的那批</li>
          <li><b>3 个锚点</b>：脸型 + 瑕疵 + 服装记忆点，同类型角色靠这个区分，不然会生成同一张脸</li>
          <li><b>固定关键词串</b>：所有镜头原样注入，一处改、全片同步</li>
          <li><b>溯源标记</b>：剧本原文写了的标绿，AI 补的标黄，出来要你过一眼</li>
        </ul>
        <div class="ap-intro-note" v-if="!aiReady">当前没有配置大模型 Key，只能用手工填的设定。配好 Key 后可以一键分解。</div>
      </div>

      <!-- 覆盖统计：一条横带，不占三行 -->
      <div v-if="stats.ready" class="ap-cov">
        <div class="ap-cov-i">
          <b>{{ stats.charCovered }}<i>/{{ stats.charTotal }}</i></b><span>角色覆盖</span>
        </div>
        <div class="ap-cov-i">
          <b>{{ stats.sceneCovered }}<i>/{{ stats.sceneTotal }}</i></b><span>场次覆盖</span>
        </div>
        <div class="ap-cov-i">
          <b>{{ stats.inferred }}</b><span>AI 推断项</span>
        </div>
        <div class="ap-cov-i">
          <b>{{ stats.frames }}</b><span>起始帧提示词</span>
        </div>
      </div>

      <!-- 剧本视觉风格：常驻，不依赖 AI 分解；同时管起始帧提示词与本地出图 -->
      <div class="ap-style-bar">
        <span class="lbl">剧本视觉风格</span>
        <span class="val" :title="curStyle.anchor">{{ curStyle.anchor }}</span>
        <span class="src">{{ curStyle.source }}</span>
        <span v-if="stats.model" class="ap-model">{{ stats.model }}</span>
        <button class="btn sm quiet" @click="toggleStyleEditor">{{ styleOpen ? "收起" : "定义 / 修改" }}</button>
      </div>
      <div v-if="styleOpen" class="ap-style-editor">
        <div class="ap-style-presets">
          <span class="lbl">预设</span>
          <button v-for="p in STYLE_PRESETS" :key="p.key" class="ap-style-chip"
            :class="{ on: styleDraft.key === p.key }" @click="pickStylePreset(p)">{{ p.label }}</button>
        </div>
        <label class="ap-style-f">
          <span>中文风格锚 <i>写进起始帧提示词与导出文档</i></span>
          <input class="ap-input" v-model="styleDraft.anchor"
            placeholder="写实电影质感 · 35mm 胶片颗粒 · 冷调">
        </label>
        <label class="ap-style-f">
          <span>Flux 英文锚 <i>本地出图真正吃的是这一串，只写画种 / 材质 / 光线 / 色调</i></span>
          <input class="ap-input" v-model="styleDraft.anchorEn"
            placeholder="photorealistic cinematic film still, 35mm film grain...">
        </label>
        <div class="ap-style-actions">
          <span class="ap-style-note">「跟随剧本」＝ 用 AI 分解推断的风格，没分解用中性默认；保存后起始帧提示词自动重算</span>
          <button class="btn sm quiet" @click="clearStyle">跟随剧本</button>
          <button class="btn sm primary" @click="applyStyle">保存风格</button>
        </div>
      </div>

      <div v-if="stats.order && stats.order.length" class="ap-order">
        <span class="lbl">建议生成顺序</span>
        <span v-for="(c, i) in stats.order" :key="c" class="ap-order-c">{{ c }}<i v-if="i < stats.order.length - 1">→</i></span>
      </div>

      <div v-if="S.assetWarnings && S.assetWarnings.length" class="ap-warns">
        <div class="ap-warns-t">校验提示 · {{ S.assetWarnings.length }} 条</div>
        <ul><li v-for="(w, i) in S.assetWarnings" :key="i">{{ w }}</li></ul>
      </div>

      <div class="ap-tabs">
        <div class="ap-views" title="切换资产浏览方式">
          <button :class="{ on: viewMode === 'shot' }" @click="setViewMode('shot')">▦ 按分镜</button>
          <button :class="{ on: viewMode === 'all' }" @click="setViewMode('all')">☰ 全部资产</button>
        </div>
        <span class="ap-views-sep"></span>
        <button v-for="t in assetTabs" :key="t.kind" class="ap-tab" v-show="viewMode === 'all'"
          :class="{ active: S.assetTab === t.kind }" :data-asset-tab="t.kind" @click="setAssetTab(t.kind)">
          {{ t.label }}<span>{{ t.items.length }}</span>
        </button>
        <div class="spacer"></div>
        <span v-if="viewMode === 'shot'" class="ap-view-note">共 {{ navStats.total }} 镜 · 资产按绑定关系独立分组</span>
        <button v-if="p0Count" class="ap-filter" :class="{ on: onlyP0 }" @click="onlyP0 = !onlyP0">
          只看 P0 · {{ p0Count }}
        </button>
      </div>

      <!-- 左：密排清单（一屏看全） / 右：当前资产的编辑区 -->
      <div v-if="items.length || viewMode === 'shot'" class="ap-body" :class="{ 'is-shot': viewMode === 'shot' }">
        <aside class="ap-side">
          <template v-if="viewMode === 'shot'">
            <div class="ap-shot-nav-h">
              <b>分镜任务列表</b><span>{{ navStats.total }} 镜</span>
              <div class="ap-shot-nav-stats">
                <span class="ok">● {{ navStats.ready }} 已就绪</span>
                <span class="warn">● {{ navStats.pending }} 待补图</span>
              </div>
              <select v-if="episodes.length > 1" v-model="epFilter" class="ap-input ap-shot-ep" aria-label="按集筛选">
                <option value="all">全部集</option>
                <option v-for="ep in episodes" :key="ep" :value="ep">第 {{ ep }} 集</option>
              </select>
            </div>
            <div class="ap-search">
              <input v-model="shotQuery" class="ap-input" placeholder="搜镜号 / 画面描述" aria-label="搜索分镜">
              <button v-if="shotQuery" class="ap-q-x" title="清空搜索" @click="shotQuery = ''">×</button>
            </div>
            <div class="ap-shot-rows">
              <div v-for="r in shotRows" :key="r.shot.id" class="ap-shot-row"
                :class="{ on: r.shot.id === curShot?.id }" :data-shot="r.shot.id"
                role="button" tabindex="0" @click="shotId = r.shot.id"
                @keydown.enter.prevent="shotId = r.shot.id">
                <span class="ap-shot-row-th">
                  <img v-if="shotThumb(r.shot)" :src="shotThumb(r.shot)" :alt="shotLabel(r.shot)" loading="lazy">
                  <template v-else>🎬</template>
                </span>
                <div class="ap-shot-row-b">
                  <div class="ap-shot-row-t">
                    <b>#{{ String(r.no).padStart(2, "0") }}</b>
                    <span>{{ shotLabel(r.shot) }}</span>
                    <em>{{ r.shot.duration || 0 }}s</em>
                  </div>
                  <div class="ap-shot-row-d">{{ shotText(r.shot) }}</div>
                  <div class="ap-shot-row-f">
                    <span>角 {{ r.st.n.character }}</span><span>景 {{ r.st.n.scene }}</span><span>物 {{ r.st.n.prop }}</span>
                    <i :class="r.st.empty ? 'empty' : (r.st.ready ? 'ok' : 'warn')">
                      {{ r.st.empty ? "无绑定" : (r.st.ready ? "已就绪" : "待补 " + r.st.miss) }}
                    </i>
                  </div>
                </div>
              </div>
              <div v-if="!shotRows.length" class="ap-row-none">
                {{ navStats.total ? "没有匹配的分镜" : "还没有生成分镜，先完成「AI 自动拆解」" }}
              </div>
            </div>
            <div class="ap-side-f">
              <span>{{ curShotNo }} / {{ navStats.total }} 镜</span>
              <button class="ap-side-cp" @click="stepShot(-1)">‹ 上一镜</button>
              <button class="ap-side-cp" @click="stepShot(1)">下一镜 ›</button>
            </div>
          </template>
          <template v-else>
          <div class="ap-search">
            <input v-model="q" class="ap-input" placeholder="搜名称 / 编号 / 关键词" aria-label="搜索资产">
            <button v-if="q" class="ap-q-x" title="清空搜索" @click="q = ''">×</button>
          </div>

          <div class="ap-rows">
            <div v-for="a in shown" :key="a.id" class="ap-row" :class="rowCls(a)"
              :data-asset="a.id" :title="a.name + (a.code ? ' · ' + a.code : '')"
              role="button" tabindex="0"
              @click="pick(a.id)" @keydown.enter.prevent="pick(a.id)" @keydown.space.prevent="pick(a.id)">
              <span class="ap-row-th" :class="{ blank: !a.refImage }">
                <img v-if="a.refImage" :src="refSrc(a, 64)" :alt="a.name" loading="lazy" decoding="async">
                <template v-else>{{ a.name.slice(0, 1) }}</template>
              </span>
              <span class="ap-row-nm">{{ a.name }}</span>
              <span v-if="a.code" class="ap-row-cd">{{ a.code }}</span>
              <span v-if="(a.priority || 'P1') === 'P0'" class="ap-row-dot" title="P0 · 先出图">P0</span>
              <span v-if="a.locked" class="ap-row-lk" title="已锁定">🔒</span>
              <span class="ap-row-us" :class="{ orphan: usageOrphan(a) }"
                :data-asset-usage="a.id" :title="usageLabel(a)">{{ usageShort(a) }}</span>
            </div>

            <div v-if="!shown.length" class="ap-row-none">
              没有匹配「{{ q }}」的资产
            </div>
          </div>

          <div class="ap-side-f">
            <span>{{ shown.length }} / {{ items.length }}</span>
            <button class="ap-side-cp" :disabled="!shown.length"
              :title="'把本栏 ' + shown.length + ' 个资产的提示词复制成一份文本（先出图前对稿用）'"
              @click="copyAllAssetPrompts(S.assetTab, 'all')">⧉ 全部复制</button>
          </div>
          </template>
        </aside>

        <div class="ap-right">
        <template v-if="viewMode === 'shot'">
          <div v-if="curShot" class="ap-shot-main">
            <div class="ap-shot-hero">
              <div class="ap-shot-hero-h">
                <b>分镜 {{ String(curShotNo).padStart(2, "0") }}</b>
                <span class="ap-shot-hero-code">{{ shotLabel(curShot) }}</span>
                <span class="ap-shot-hero-sub">{{ shotSub(curShot) }}</span>
                <span class="ap-shot-hero-state" :class="curShotState.ready ? 'ok' : 'warn'">
                  {{ curShotState.empty ? "未绑定资产" : (curShotState.ready ? "资产已就绪" : "待补 " + curShotState.miss + " 张") }}
                </span>
              </div>
              <div class="ap-shot-hero-grid">
                <div class="ap-shot-hero-box">
                  <h4>画面描述</h4>
                  <p>{{ shotText(curShot) }}</p>
                </div>
                <div class="ap-shot-hero-box muted">
                  <h4>台词 · 备注 · 氛围</h4>
                  <p>{{ heroNotes(curShot) }}</p>
                </div>
              </div>
              <div class="ap-shot-hero-sum">
                <span>本镜资产 <b>{{ curShotState.total }}</b></span>
                <span>角色 <b>{{ curShotState.n.character }}</b></span>
                <span>场景 <b>{{ curShotState.n.scene }}</b></span>
                <span>道具 <b>{{ curShotState.n.prop }}</b></span>
                <span>已有图 <b>{{ curShotState.total - curShotState.miss }}</b></span>
                <span>点卡片进下方详情编辑，改一次全片同步</span>
              </div>
            </div>

            <div v-for="g in GROUPS" :key="g.kind" class="ap-shot-group">
              <div class="ap-shot-group-h">
                <b>{{ g.label }}</b>
                <span class="ap-shot-group-n">{{ groupItems(g.kind).length }}</span>
                <span class="ap-shot-group-cap">{{ g.cap }}</span>
                <button v-if="g.kind === 'prop'" class="mini" @click="focusPropDraft">+ 新增</button>
              </div>
              <div v-if="groupItems(g.kind).length" class="ap-shot-cards">
                <div v-for="a in groupItems(g.kind)" :key="a.id" class="ap-shot-card"
                  :class="{ on: sel?.id === a.id }" :data-shot-asset="a.id"
                  role="button" tabindex="0" @click="pickShotAsset(a)"
                  @keydown.enter.prevent="pickShotAsset(a)">
                  <div class="ap-shot-card-img">
                    <img v-if="a.refImage" :src="refSrc(a, 320)" :alt="a.name" loading="lazy" decoding="async">
                    <div v-else class="ap-shot-card-ph">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4">
                        <circle cx="12" cy="8" r="3.2"/><path d="M5.5 20c.6-3.8 3.1-5.8 6.5-5.8s5.9 2 6.5 5.8"/>
                      </svg>
                    </div>
                    <span class="ap-shot-card-badge" :class="hasImage(a) ? 'ok' : 'off'">
                      {{ a.refImage ? "已定妆" : (hasImage(a) ? "已生成" : "待生成") }}
                    </span>
                    <button v-if="a.refImage" class="ap-shot-card-zoom" title="看参考图原图"
                      @click.stop="openRefLb(a)">⤢</button>
                  </div>
                  <div class="ap-shot-card-b">
                    <div class="ap-shot-card-t"><b>{{ a.name }}</b><span>{{ cardSub(a) }}</span></div>
                    <div class="ap-shot-card-m">{{ a.code || "—" }} · {{ a.priority || "P1" }}</div>
                    <div class="ap-shot-us" :class="{ orphan: usageOrphan(a) }"
                      :title="usageLabel(a)">{{ usageLabel(a) }}</div>
                    <div class="ap-shot-card-d">最终提示词 · {{ cardVariant(a) }}<br>{{ cardDesc(a) }}</div>
                  </div>
                  <div class="ap-shot-card-act">
                    <button class="mini" title="只重绘这一个资产" @click.stop="redrawShotAsset(a)">重绘</button>
                    <label class="mini" title="上传参考图（原图不压缩）" @click.stop>
                      上传<input type="file" class="ap-file"
                        accept="image/png,image/jpeg,image/webp,image/gif,image/bmp,image/avif"
                        :data-ref-for="a.id" @change="uploadAssetRef($event, a.id)">
                    </label>
                  </div>
                </div>
              </div>
              <div v-else class="ap-shot-group-empty">
                本镜没有绑定{{ g.label }}{{ onlyP0 ? "（已开启只看 P0）" : "" }}，切到其他分镜或回「全部资产」查看
              </div>
            </div>

            <div v-if="curFrame" class="ap-shot-frame">
              <details>
                <summary>起始帧提示词 · {{ curFrame.code }}（点开查看，供出图工具复用）</summary>
                <pre>{{ curFrame.prompt }}</pre>
              </details>
            </div>
          </div>
          <div v-else class="ap-shot-none">
            还没有生成分镜，先在第 2 步完成「AI 自动拆解」。<br>
            <button class="btn sm quiet" @click="setViewMode('all')">切到全部资产视图</button>
          </div>
          <div v-if="sel" ref="detailEl" class="ap-shot-detail-h">
            资产详情 · {{ sel.name }}
            <span>沿用原有编辑 / 提示词 / 出图 / 灯箱功能，改动对本片所有引用它的分镜同时生效</span>
          </div>
        </template>

        <article v-if="sel" class="ap-item ap-detail" :class="'k-' + sel.kind" :data-asset="sel.id"
          @focusin="onAssetFocusin" @change="onAssetChange">
          <header class="ap-item-h">
            <span v-if="sel.code" class="ap-code">{{ sel.code }}</span>
            <span v-if="sel.priority" class="ap-pri" :class="sel.priority.toLowerCase()">{{ sel.priority }}</span>
            <b class="ap-name">{{ sel.name }}</b>
            <span v-if="sel.aliases && sel.aliases.length" class="ap-alias">又名 {{ sel.aliases.join(" / ") }}</span>
            <span v-if="sel.source" class="ap-src" :class="sel.source">{{ SOURCE[sel.source] || sel.source }}</span>
            <span v-if="sel.locked" class="chip warn">已锁</span>
            <div class="spacer"></div>
            <span class="ap-nav">
              <button class="mini" :disabled="idx <= 0" title="上一个" @click="stepBy(-1)">‹</button>
              <button class="mini" :disabled="idx >= shown.length - 1" title="下一个" @click="stepBy(1)">›</button>
            </span>
            <span class="ap-cp">
              <button class="btn sm quiet ap-cp-all" :data-copy-all="sel.id"
                :title="'复制「' + sel.name + '」的全部提示词：一条直接给原文，多条带小标题分段'"
                @click="copyOne(sel.id, 'all')">
                {{ copiedId === sel.id + ":all" ? "✓ 已复制" : "⧉ 复制提示词" }}
              </button>
              <button v-if="hasEn(sel)" class="mini ap-cp-en" :data-copy-en="sel.id"
                :title="'只复制英文串，直接贴进 Flux / Midjourney / 即梦'"
                @click="copyOne(sel.id, 'en')">{{ copiedId === sel.id + ":en" ? "✓" : "EN" }}</button>
            </span>
            <button class="btn sm quiet ap-fill"
              :disabled="!!ui.comfy.filling || !aiReady"
              :title="aiReady ? fillTitle : '需要先配置大模型 Key'"
              @click="fillAssetWithAI(sel.id)">
              {{ ui.comfy.filling === sel.id ? "补全中…" : "✦ AI 补形象" }}
            </button>
            <label class="btn sm quiet ap-upload"
              :title="sel.refImage ? '换一张参考图（原图不压缩）' : '挂一张参考图：原图不压缩，会一起打包'">
              {{ ui.refUpload === sel.id ? "上传中…" : (sel.refImage ? "换图" : "参考图") }}
              <input type="file" accept="image/png,image/jpeg,image/webp,image/gif,image/bmp,image/avif"
                class="ap-file" :data-ref-for="sel.id" @change="uploadAssetRef($event, sel.id)">
            </label>
            <button v-if="sel.refImage" class="mini" :data-clear-ref="sel.id" title="移除参考图" @click="clearAssetRef(sel.id)">⊗</button>
            <button class="mini" :class="{ on: sel.locked }" :data-lock-asset="sel.id"
              :title="sel.locked ? '解锁' : '锁定设定（重新分解不覆盖）'" @click="toggleAssetLock(sel.id)">🔒</button>
            <button v-if="sel.kind === 'prop'" class="mini del" :data-del-asset="sel.id" title="删除" @click="delAsset(sel.id)">×</button>
          </header>

          <div class="ap-item-b">
            <button v-if="sel.refImage" type="button" class="ap-ava has" data-ref-lb
              :title="'看原图（' + sel.name + ' 参考图）'"
              @click="openRefLb(sel)">
              <img :src="refSrc(sel, 320)" :alt="sel.name + ' 参考图'" decoding="async">
              <span class="ap-ava-zoom">⤢</span>
            </button>
            <div v-else class="ap-ava blank">
              <span>{{ sel.name.slice(0, 1) }}</span>
            </div>

            <div class="ap-main">
              <!-- 属性压缩成一行纯文字，不再一排 chip 占两行 -->
              <div class="ap-meta">
                <span v-if="sel.age">{{ sel.age }}</span>
                <span v-if="sel.role">{{ sel.role }}</span>
                <span v-if="sel.kind === 'scene'">{{ sceneMeta }}</span>
                <span v-if="sel.kind === 'character'">戏份 {{ sel.weight }}/5</span>
                <span v-if="sel.visibility && sel.visibility !== '未注明'">{{ sel.visibility }}</span>
                <span v-if="sel.kind === 'prop' && sel.boundTo && sel.boundTo.length" class="ap-bound">绑定 {{ sel.boundTo.join(" / ") }}</span>
              </div>

              <div v-if="sel.kind === 'character'" class="ap-kw">
                <span class="lbl">固定关键词串</span>
                <input :value="sel.keyword || ''" :data-asset-id="sel.id"
                  placeholder="例：18岁中国乡村少年，右眉尾浅疤，颈挂红绳青玉牌，浅灰旧T恤"
                  @change="saveAssetKeyword(sel.id, $event.target.value)">
              </div>

              <div v-if="anchorsOf(sel).length" class="ap-anchors">
                <label v-for="f in anchorsOf(sel)" :key="f.key">
                  <span>{{ f.label }}</span>
                  <input :value="anchorValue(sel, f.key)" :placeholder="f.ph"
                    :data-anchor-key="f.key" :data-asset-id="sel.id"
                    @change="saveAssetAnchor(sel.id, f.key, $event.target.value)">
                </label>
              </div>

              <div class="ap-fields">
                <label v-if="sel.kind === 'character'">
                  <span>外观</span>
                  <input class="ap-input" data-afield="appearance" :data-asset-id="sel.id" :value="sel.appearance"
                    placeholder="体型 / 发型 / 面部细节">
                </label>
                <label v-if="sel.kind === 'character'">
                  <span>服装</span>
                  <input class="ap-input" data-afield="wardrobe" :data-asset-id="sel.id" :value="sel.wardrobe"
                    placeholder="例：浅灰旧T恤、深色长裤">
                </label>
                <label v-if="sel.kind === 'scene'">
                  <span>环境</span>
                  <input class="ap-input" data-afield="appearance" :data-asset-id="sel.id" :value="sel.appearance"
                    placeholder="例：冷白灯光，地面反光，货架整齐">
                </label>
                <label v-if="sel.kind === 'prop'">
                  <span>描述</span>
                  <input class="ap-input" data-afield="appearance" :data-asset-id="sel.id" :value="sel.appearance"
                    placeholder="例：黄纸铜钱，边缘毛糙">
                </label>
              </div>

              <div v-if="sel.kind === 'prop'" class="ap-tip">
                道具不单独出图：下面这句会随镜头画面带进提示词，可一键复制给别的工具用；绑定了角色就跟着角色出现。
              </div>

              <details v-if="promptsOf(sel).length" class="ap-prompts" :open="promptsOpen"
                @toggle="promptsOpen = $event.target.open">
                <summary>
                  <span>{{ sel.kind === "prop" ? "道具提示词" : "出图提示词 · 外部工具" }}</span>
                  <span class="ap-prompts-n">{{ promptsOf(sel).length }} 条</span>
                </summary>
                <div v-for="p in promptsOf(sel)" :key="p[0]" class="ap-prompt">
                  <div class="ap-prompt-h">
                    <span>{{ p[1] }}</span>
                    <button class="mini" :class="{ done: copiedId === sel.id + ':' + p[0] }"
                      :data-copy-prompt="sel.id + ':' + p[0]"
                      @click="copyOne(sel.id, p[0])">{{ copiedId === sel.id + ":" + p[0] ? "✓ 已复制" : "复制" }}</button>
                  </div>
                  <pre>{{ p[2] }}</pre>
                </div>
              </details>

              <!-- 本地 Flux 真正吃的英文串：跟上面给即梦 / MJ 的中文提示词是两份东西 -->
              <div class="ap-flux">
                <div class="ap-flux-h">
                  <span>本地 Flux 提示词</span>
                  <span class="ap-flux-note">本地出图真正发给模型的那串英文，和上面的中文提示词不是同一份</span>
                  <div class="spacer"></div>
                  <button class="btn sm quiet" id="ap-flux-btn" :disabled="ui.comfy.previewBusy" @click="showFlux">
                    {{ ui.comfy.previewBusy ? "读取中…" : (flux.length ? "刷新" : "查看") }}</button>
                  <button v-if="flux.length" class="mini" id="ap-flux-copy" title="复制全部" @click="copyFlux">⧉</button>
                </div>
                <div v-if="flux.length" class="ap-flux-list">
                  <div v-for="(r, i) in flux" :key="i" class="ap-flux-row">
                    <b>{{ r.assetName }} · {{ r.label }}</b>
                    <em>{{ r.w }}×{{ r.h }}</em>
                    <span v-if="r.fallbackEn" class="warn">缺英文关键词</span>
                    <pre>{{ r.prompt }}</pre>
                  </div>
                </div>
              </div>

              <!-- 本地 ComfyUI 生成的素材图：一个资产可以挂多张，选一张当主参考图 -->
              <div v-if="sel.genImages && sel.genImages.length" class="ap-genimgs">
                <div class="ap-genimgs-h">
                  <span>本地生成素材 · {{ sel.genImages.length }} 张</span>
                  <span class="ap-genimgs-note">H3-Image 下先出定妆半身，四视图和三视图照它的脸出</span>
                  <button class="mini" @click="clearGenImages(sel.id)">清空</button>
                </div>
                <div class="ap-genimgs-grid">
                  <figure v-for="(g, gi) in sel.genImages" :key="g.variant"
                    :class="{ primary: sel.refImage === g.dataUri }">
                    <button type="button" class="ap-genimgs-shot"
                      :title="'放大预览 · ' + g.label + '（点开后 ← → 切换、Esc 关闭）'"
                      @click="openPreview(gi)">
                      <img :src="g.dataUri" :alt="sel.name + ' · ' + g.label"
                        :style="{ aspectRatio: (g.w || 4) + ' / ' + (g.h || 3) }">
                      <span class="ap-genimgs-zoom">⤢ 放大预览</span>
                    </button>
                    <figcaption>
                      <span>{{ g.label }}<i v-if="g.fallbackEn" title="缺英文关键词，效果会打折">!</i></span>
                      <a v-if="g.file" :href="'/api/comfy/image?f=' + g.file.split('/').pop()"
                        target="_blank" rel="noopener" title="新标签打开原图">↗</a>
                    </figcaption>
                    <span class="ap-genimgs-meta">{{ g.w }}×{{ g.h }} · {{ g.seconds }}s<span
                      v-if="g.refOf"> · 脸部参考：{{ g.refOf }}</span></span>
                    <button v-if="sel.refImage !== g.dataUri" class="mini wide"
                      @click="setPrimaryGenImage(sel.id, g.variant)">设为主参考图</button>
                    <span v-else class="ap-genimgs-primary">✓ 主参考图</span>
                  </figure>
                </div>
              </div>
            </div>
          </div>
        </article>
        <div v-else-if="viewMode === 'shot'" class="ap-empty">
          本镜还没有可编辑的资产。切到其他分镜，或回「全部资产」视图新增 / 分解资产。
        </div>
        </div>
      </div>
      <div v-else class="ap-empty">
        {{ onlyP0 ? "这一栏没有 P0 资产，取消筛选看全部。" :
          (S.assetTab === "prop" ? "还没有道具。画面里值得强调的物件（黄纸铜钱、老青玉牌）加进来，绑定后提示词会带上它。"
            : "剧本里还没识别到这一类的资产。") }}
      </div>

      <div v-if="S.assetTab === 'prop'" class="ap-add">
        <input class="ap-input" id="prop-draft" :value="ui.propDraft" placeholder="道具名，如「黄纸铜钱」"
          @input="ui.propDraft = $event.target.value" @keyup.enter="addProp">
        <button class="btn sm" id="add-prop" @click="addProp">加入道具</button>
      </div>
    </div>

    <!-- 大图预览：Teleport 出 .ap-detail 的 overflow，否则弹层会被裁掉 -->
    <Teleport to="body">
      <div v-if="previewRow" class="ap-lb" @click.self="closePreview">
        <div class="ap-lb-head">
          <span class="ap-lb-title">{{ lbAsset.name }} · {{ previewRow.label }}</span>
          <span v-if="previewList.length > 1" class="ap-lb-sub">{{ previewIdx + 1 }} / {{ previewList.length }}</span>
          <div class="ap-lb-tools">
            <template v-if="lbKind === 'gen'">
              <button v-if="lbAsset.refImage !== previewRow.dataUri" class="btn sm"
                @click="setPrimaryGenImage(lbAsset.id, previewRow.variant)">设为主参考图</button>
              <span v-else class="ap-lb-primary">✓ 主参考图</span>
              <a class="btn sm quiet" :href="previewImgSrc"
                :download="previewFile || (previewRow.label + '.png')">下载原图</a>
            </template>
            <a v-else class="btn sm quiet" :href="previewImgSrc"
              :download="refDownName(lbAsset)">下载原图</a>
            <button class="ap-lb-zoom" :class="{ on: zoomed }"
              :title="zoomed ? '缩回适应窗口（点图也可切）' : '放大到 2×（点图也可切）'"
              @click="toggleZoom">⤢ {{ zoomed ? "1×" : "2×" }}</button>
            <button class="ap-lb-close" title="关闭（Esc）" @click="closePreview">×</button>
          </div>
        </div>
        <div class="ap-lb-stage" :class="{ zoomed }" @click.self="closePreview">
          <button v-if="previewList.length > 1" class="ap-lb-nav prev" title="上一张（←）"
            @click="previewStep(-1)">‹</button>
          <img :src="previewImgSrc" :alt="lbAsset.name + ' · ' + previewRow.label"
            @click="toggleZoom" @error="previewFailed = true">
          <button v-if="previewList.length > 1" class="ap-lb-nav next" title="下一张（→）"
            @click="previewStep(1)">›</button>
        </div>
        <div class="ap-lb-foot">
          <div class="ap-lb-meta">
            <template v-if="lbKind === 'gen'">
              <span>{{ previewRow.w }}×{{ previewRow.h }}</span>
              <span>{{ previewRow.seconds }}s</span>
              <span>seed {{ previewRow.seed }}</span>
              <span v-if="previewRow.fallbackEn" class="warn">缺英文关键词，效果会打折</span>
              <span v-if="previewFailed" class="warn">原图读不到，已回退缩略图</span>
            </template>
            <template v-else>
              <span>参考图 · 原始文件，未压缩</span>
              <span v-if="String(previewRow.src).indexOf('data:') === 0" class="warn">老项目内联图，可能是压过的旧图</span>
              <span v-if="previewFailed" class="warn">原图读不到，可能已被清理</span>
            </template>
            <span class="ap-lb-tip">{{ previewList.length > 1 ? "← → 切换 · " : "" }}点图放大 / 缩回 · Esc 关闭 · 点空白处收起</span>
          </div>
          <div v-if="lbKind === 'gen'" class="ap-lb-prompt">{{ previewRow.prompt }}</div>
        </div>
      </div>
    </Teleport>
  </section>
</template>
