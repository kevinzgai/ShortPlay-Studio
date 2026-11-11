import { reactive } from "vue";

/* 炫酷 UI 层的全局状态。所有增强都挂在 body.fx-on 下，
   关掉开关后页面与原来的分镜工场逐像素一致。 */
const KEY = "shortplay.fx.v2";
const MOTIONS = ["full", "calm", "off"];

function read() {
  try { return JSON.parse(localStorage.getItem(KEY) || "{}") || {}; }
  catch (_) { return {}; }
}
const saved = read();

export const fx = reactive({
  on: saved.on === true,                                    // 默认关闭（Linear 深色为基线）
  dark: saved.dark === true,                                // 默认「极光」特效配色（与外观主题无关）
  motion: MOTIONS.includes(saved.motion) ? saved.motion : "full",
  orbOpen: false,
  palette: false
});

export function saveFx() {
  try {
    localStorage.setItem(KEY, JSON.stringify({ on: fx.on, dark: fx.dark, motion: fx.motion }));
  } catch (_) { /* 隐私模式下忽略 */ }
}

export function applyFx() {
  const b = document.body;
  b.classList.toggle("fx-on", fx.on);
  b.classList.toggle("fx-dark", fx.on && fx.dark);
  b.classList.toggle("fx-calm", fx.on && fx.motion === "calm");
  b.classList.toggle("fx-still", !fx.on || fx.motion === "off");
  b.classList.toggle("fx-palette-open", fx.palette);
  saveFx();
}

export function setFx(on) {
  fx.on = !!on;
  if (!fx.on) { fx.orbOpen = false; fx.palette = false; }
  applyFx();
}
export function setDark(v) { fx.dark = !!v; applyFx(); }
export function setMotion(m) { if (MOTIONS.includes(m)) { fx.motion = m; applyFx(); } }
export function togglePalette(v) { fx.palette = v === undefined ? !fx.palette : !!v; applyFx(); }

/* 全局点击水波纹：只给按钮类元素插一个临时 span，不改任何模板 */
export function ripple(e) {
  if (!fx.on || fx.motion === "off" || !(e.target instanceof Element)) return;
  const t = e.target.closest(".btn, .step-pill, .ghost-btn, .icon-btn, .fx-orb");
  if (!t || t.disabled) return;
  const r = t.getBoundingClientRect();
  const d = Math.max(r.width, r.height) * 1.7;
  const s = document.createElement("span");
  s.className = "fx-ripple";
  s.style.width = s.style.height = d + "px";
  s.style.left = (e.clientX - r.left - d / 2) + "px";
  s.style.top = (e.clientY - r.top - d / 2) + "px";
  t.appendChild(s);
  setTimeout(() => s.remove(), 700);
}
