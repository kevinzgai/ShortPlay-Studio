<script setup>
import { reactive, watch, onMounted, onUnmounted } from "vue";
import { S, totalDuration } from "../stores/studio.js";
import { fx, applyFx, setFx, setDark, setMotion, togglePalette, ripple } from "./useFx.js";
import CommandPalette from "./CommandPalette.vue";

/* HUD 数字滚动：独立组件，不碰页面里已有的 .stat 结构 */
const nums = reactive({ shots: 0, dur: 0, eps: 0 });
const running = new Set();
function tween(key, to) {
  if (fx.motion === "off" || running.has(key)) { nums[key] = to; return; }
  const from = nums[key], t0 = performance.now(), D = 620;
  running.add(key);
  const step = (t) => {
    const p = Math.min(1, (t - t0) / D);
    nums[key] = from + (to - from) * (1 - Math.pow(1 - p, 3));
    if (p < 1) requestAnimationFrame(step);
    else { nums[key] = to; running.delete(key); }
  };
  requestAnimationFrame(step);
}
watch(
  [() => S.shots.length, totalDuration, () => S.episodes.length],
  ([a, b, c]) => { tween("shots", a || 0); tween("dur", Number(b) || 0); tween("eps", c || 0); },
  { immediate: true }
);

function onKey(e) {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
    e.preventDefault();
    if (fx.on) togglePalette();
    else { setFx(true); togglePalette(true); }
  } else if (e.key === "Escape" && fx.palette) {
    togglePalette(false);
  }
}
onMounted(() => {
  applyFx();
  document.addEventListener("click", ripple, true);
  document.addEventListener("keydown", onKey);
});
onUnmounted(() => {
  document.removeEventListener("click", ripple, true);
  document.removeEventListener("keydown", onKey);
});
</script>

<template>
  <Teleport to="body">
    <div v-if="fx.on" class="fx-aurora" aria-hidden="true">
      <span class="fx-blob b1"></span>
      <span class="fx-blob b2"></span>
      <span class="fx-blob b3"></span>
      <span class="fx-grid"></span>
    </div>
  </Teleport>

  <div v-if="fx.on" class="fx-dock">
    <div class="fx-hud" :class="{ shimmer: S.step === 2 }">
      <span class="fx-hud-item"><b>{{ Math.round(nums.shots) }}</b><i>镜头</i></span>
      <span class="fx-hud-sep"></span>
      <span class="fx-hud-item"><b>{{ Math.round(nums.dur) }}<em>s</em></b><i>总时长</i></span>
      <span class="fx-hud-sep"></span>
      <span class="fx-hud-item"><b>{{ Math.round(nums.eps) }}</b><i>集</i></span>
    </div>

    <div v-if="fx.orbOpen" class="fx-panel">
      <div class="fx-panel-head"><span>视觉特效</span><em>FX LAB</em></div>
      <div class="fx-row">
        <span>总开关</span>
        <button class="fx-switch" :class="{ on: fx.on }" aria-label="特效总开关" @click="setFx(!fx.on)"><i></i></button>
      </div>
      <div class="fx-row">
        <span>皮肤</span>
        <div class="fx-seg">
          <button :class="{ on: !fx.dark }" @click="setDark(false)">浅色极光</button>
          <button :class="{ on: fx.dark }" @click="setDark(true)">暗夜霓虹</button>
        </div>
      </div>
      <div class="fx-row">
        <span>动效</span>
        <div class="fx-seg sm">
          <button :class="{ on: fx.motion === 'full' }" @click="setMotion('full')">全开</button>
          <button :class="{ on: fx.motion === 'calm' }" @click="setMotion('calm')">舒缓</button>
          <button :class="{ on: fx.motion === 'off' }" @click="setMotion('off')">静止</button>
        </div>
      </div>
      <div class="fx-tip">按 <kbd>Ctrl</kbd> / <kbd>⌘</kbd> + <kbd>K</kbd> 打开命令面板</div>
    </div>

    <button
      class="fx-orb"
      :class="{ open: fx.orbOpen }"
      title="视觉特效 · Ctrl/⌘ + K 命令面板"
      aria-label="视觉特效设置"
      @click="fx.orbOpen = !fx.orbOpen"
    ><span>✦</span></button>
  </div>

  <CommandPalette />
</template>
