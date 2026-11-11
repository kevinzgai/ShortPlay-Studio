<script setup>
import { ref, computed, watch, nextTick } from "vue";
import {
  S, ui, goStep, undo, redo, openModal, toast,
  setActiveShot, canUndo, canRedo
} from "../stores/studio.js";
import { fx, togglePalette, setFx, setDark, setMotion } from "./useFx.js";
import { toggleTheme, themeLabel } from "../lib/theme.js";

const q = ref("");
const idx = ref(0);
const inputEl = ref(null);

function jumpToShot(id) {
  if (!S.shots.length) { toast("还没有生成分镜", "warn"); return; }
  if (S.step !== 3) goStep(3);
  setActiveShot(id);
  nextTick(() => {
    const el = document.querySelector('.shot[data-id="' + id + '"]');
    if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
  });
}

const base = computed(() => [
  { id: "s1", group: "导航", icon: "①", label: "改剧本", hint: "剧本阶段 · 1/2", run: () => goStep(1) },
  { id: "s2", group: "导航", icon: "②", label: "AI 拆解确认 · 分集", hint: "剧本阶段 · 2/2", run: () => goStep(2) },
  { id: "s3", group: "导航", icon: "③", label: "分镜表", hint: "制作阶段 · 主流程 3/3", run: () => goStep(3) },
  { id: "s4", group: "导航", icon: "↗", label: "出片工具（可选）", hint: "参考图 / 首帧 / 整包导出", run: () => goStep(4) },
  { id: "undo", group: "编辑", icon: "↶", label: "撤销", hint: "Ctrl + Z", run: () => canUndo.value ? undo() : toast("没有可撤销的操作", "warn") },
  { id: "redo", group: "编辑", icon: "↷", label: "重做", hint: "Ctrl + Shift + Z", run: () => canRedo.value ? redo() : toast("没有可重做的操作", "warn") },
  { id: "export", group: "文件", icon: "⇩", label: "打开导出菜单", hint: "CSV / Markdown / TXT / JSON", run: () => { if (!S.shots.length) { toast("还没有生成分镜", "warn"); return; } if (S.step !== 3) goStep(3); nextTick(() => { ui.exportOpen = true; }); } },
  { id: "settings", group: "文件", icon: "⚙", label: "生成设置", hint: "模型 / 节奏 / 画幅", run: () => openModal("settings") },
  { id: "projects", group: "文件", icon: "◫", label: "切换 / 管理项目", hint: "新建 · 重命名 · 删除 · 副本", run: () => openModal("projects") },
  { id: "help", group: "文件", icon: "?", label: "使用说明", hint: "三步出片 · 出片动作可选", run: () => openModal("help") },
  { id: "theme", group: "外观", icon: "◐", label: "切换外观主题", hint: "浅色 / 暗色 / 跟随系统 · 当前" + themeLabel(), run: () => toggleTheme() },
  { id: "fx-off", group: "特效", icon: "✦", label: "关闭炫酷特效", hint: "回到原始极简界面", run: () => setFx(false) },
  { id: "fx-dark", group: "特效", icon: "◐", label: fx.dark ? "切到极光配色" : "切到霓虹配色", hint: "特效皮肤", run: () => setDark(!fx.dark) },
  { id: "fx-calm", group: "特效", icon: "≋", label: "动效：舒缓", hint: "降低浮动与扫光", run: () => setMotion("calm") },
  { id: "fx-full", group: "特效", icon: "✧", label: "动效：全开", hint: "完整视觉", run: () => setMotion("full") }
]);

const shotCmds = computed(() => (S.shots || []).slice(0, 80).map((s) => ({
  id: "shot-" + s.id,
  group: "镜头",
  icon: "▣",
  label: (s.code || "镜头") + " · " + String(s.visual || "").slice(0, 32),
  hint: String(s.sceneLabel || "") + (s.dialogue ? " · " + String(s.dialogue).slice(0, 16) : ""),
  run: () => jumpToShot(s.id)
})));

const all = computed(() => base.value.concat(shotCmds.value));
const list = computed(() => {
  const k = q.value.trim().toLowerCase();
  if (!k) return all.value.slice(0, 12);
  return all.value
    .filter((c) => (c.label + " " + c.hint + " " + c.group).toLowerCase().indexOf(k) >= 0)
    .slice(0, 30);
});

function exec(c) {
  if (!c) return;
  togglePalette(false);
  try { c.run(); } catch (_) { toast("命令执行失败", "err"); }
}
function onKey(e) {
  if (e.key === "ArrowDown") { e.preventDefault(); idx.value = Math.min(idx.value + 1, list.value.length - 1); }
  else if (e.key === "ArrowUp") { e.preventDefault(); idx.value = Math.max(idx.value - 1, 0); }
  else if (e.key === "Enter") { e.preventDefault(); exec(list.value[idx.value]); }
  else if (e.key === "Escape") { e.preventDefault(); togglePalette(false); }
}
watch(() => fx.palette, async (v) => {
  if (v) { q.value = ""; idx.value = 0; await nextTick(); inputEl.value && inputEl.value.focus(); }
});
watch(q, () => { idx.value = 0; });
</script>

<template>
  <Teleport to="body">
    <div v-if="fx.palette" class="fx-palette-veil" @click.self="togglePalette(false)">
      <div class="fx-palette" role="dialog" aria-label="命令面板" @keydown="onKey">
        <div class="fx-palette-search">
          <span class="fx-palette-mag">⌕</span>
          <input
            ref="inputEl"
            v-model="q"
            class="fx-palette-input"
            type="text"
            placeholder="搜索命令、镜号或画面描述…"
            aria-label="搜索命令"
          >
          <kbd>ESC</kbd>
        </div>
        <div class="fx-palette-list">
          <button
            v-for="(c, i) in list"
            :key="c.id"
            class="fx-palette-item"
            :class="{ on: i === idx }"
            @mousemove="idx = i"
            @click="exec(c)"
          >
            <span class="fx-palette-ico">{{ c.icon }}</span>
            <span class="fx-palette-label">{{ c.label }}</span>
            <span class="fx-palette-hint">{{ c.hint }}</span>
            <span class="fx-palette-group">{{ c.group }}</span>
          </button>
          <div v-if="!list.length" class="fx-palette-empty">没有匹配的命令</div>
        </div>
        <div class="fx-palette-foot">
          <span><kbd>↑</kbd><kbd>↓</kbd> 选择</span>
          <span><kbd>↵</kbd> 执行</span>
          <span><kbd>Ctrl</kbd> + <kbd>K</kbd> 唤起</span>
        </div>
      </div>
    </div>
  </Teleport>
</template>
