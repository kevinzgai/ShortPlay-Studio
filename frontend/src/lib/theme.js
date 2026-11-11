/* 外观主题：与 FX LAB 的「特效配色」完全独立。
   mode = light | dark | system，落在 <html data-theme> 上，样式由 styles.css 接管。
   CSS 只认 light / dark；system 在这里先解析成具体值再写上去，避免样式层再分叉。 */
import { reactive } from "vue";

const KEY = "shortplay.theme.v1";
const MODES = ["light", "dark", "system"];
const LABEL = { light: "浅色", dark: "暗色", system: "跟随系统" };
const ICON = { light: "☀", dark: "☾", system: "◐" };

function read() {
  try { return localStorage.getItem(KEY) || "light"; } catch (_) { return "light"; }
}

const initial = read();

export const theme = reactive({
  mode: MODES.includes(initial) ? initial : "light",
  systemDark: false
});

export function resolved() {
  return theme.mode === "system" ? (theme.systemDark ? "dark" : "light") : theme.mode;
}

export function themeLabel() { return LABEL[theme.mode]; }
export function themeIcon() { return ICON[theme.mode]; }

export function applyTheme() {
  const v = resolved();
  document.documentElement.dataset.theme = v;
  document.documentElement.style.colorScheme = v;
}

export function setTheme(mode) {
  if (!MODES.includes(mode)) return;
  theme.mode = mode;
  try { localStorage.setItem(KEY, mode); } catch (_) { /* 隐私模式忽略 */ }
  applyTheme();
}

/** 顶栏单键循环：浅色 → 暗色 → 跟随系统 */
export function toggleTheme() {
  setTheme(MODES[(MODES.indexOf(theme.mode) + 1) % MODES.length]);
}

export function initTheme() {
  const mq = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  theme.systemDark = !!(mq && mq.matches);
  if (mq && mq.addEventListener) {
    mq.addEventListener("change", (e) => { theme.systemDark = e.matches; applyTheme(); });
  }
  applyTheme();
}
