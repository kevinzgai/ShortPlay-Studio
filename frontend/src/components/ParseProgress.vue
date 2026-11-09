<script setup>
/* 剧本拆解进度：后端任务的事件流直接驱动这张卡。
   三段信息 —— 总进度条 / 阶段清单（完成·进行中·剩余）/ 工具调用情节。
   任务在后端跑，所以这张卡刷新页面也能被 resumeParseTask 接回来。 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { ui, cancelParse, hideParseProgress, retryParse, useLocalInstead, S } from "../stores/studio.js";

const p = computed(() => ui.parse);
const now = ref(Date.now());
let timer = null;
onMounted(() => { timer = setInterval(() => { now.value = Date.now(); }, 1000); });
onUnmounted(() => { if (timer) clearInterval(timer); });

const running = computed(() => p.value.status === "running" || p.value.status === "queued");
const pct = computed(() => Math.max(0, Math.min(100, Math.round(p.value.percent || 0))));
const remaining = computed(() => Math.max(0, (p.value.total || 0) - (p.value.done || 0)));

function clock(ms) {
  const s = Math.max(0, Math.round(ms / 1000));
  return String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
}
const elapsed = computed(() => running.value
  ? clock(now.value - (p.value.startedAt || now.value))
  : clock((p.value.elapsed || 0) * 1000));

const statusText = computed(() => ({
  queued: "排队中", running: "进行中", done: "已完成", failed: "失败", cancelled: "已取消"
}[p.value.status] || "进行中"));
const curStage = computed(() => p.value.stages.find((x) => x.key === p.value.stage) || null);

function dotOf(st) {
  return st === "ok" ? "✓" : st === "fail" ? "✕" : st === "skip" ? "–"
    : st === "running" ? "◐" : "·";
}
function msText(ms) {
  if (ms == null) return "";
  return ms >= 1000 ? (ms / 1000).toFixed(1) + "s" : Math.round(ms) + "ms";
}

/* 工具调用日志跟到底：最后一条永远是新进来的那条 */
const logBox = ref(null);
watch(() => p.value.events.length, () => {
  nextTick(() => { if (logBox.value) logBox.value.scrollTop = logBox.value.scrollHeight; });
});

function onClose() { if (running.value) cancelParse(); else hideParseProgress(); }
</script>

<template>
  <section v-if="p.visible" class="card pad pp" :class="'pp-' + p.status" id="parse-progress">
    <header class="pp-head">
      <h2>剧本拆解</h2>
      <span class="pp-badge" :class="'b-' + p.status">{{ statusText }}</span>
      <span v-if="p.live === 'poll' && running" class="pp-live"
        title="实时连接断开，已自动切换为轮询（每 0.9 秒拉一次，进度照常更新）">轮询中</span>
      <span class="spacer"></span>
      <span class="pp-pct">{{ pct }}<i>%</i></span>
      <span class="pp-time" :title="running ? '已用时' : '总用时'">{{ elapsed }}</span>
      <button class="mini pp-x" :title="running ? '取消任务（当前阶段结束后停止）' : '收起'"
        @click="onClose">×</button>
    </header>

    <div class="pp-bar" role="progressbar" :aria-valuenow="pct" aria-valuemin="0" aria-valuemax="100"
      :aria-label="'剧本拆解进度 ' + pct + '%'">
      <div class="pp-fill" :style="{ width: pct + '%' }"></div>
    </div>

    <div class="pp-meta">
      <span>已完成 <b>{{ p.done }}</b> / {{ p.total }} 步</span>
      <span v-if="running">还剩 <b>{{ remaining }}</b> 步</span>
      <span v-if="running && curStage">当前：{{ p.stageLabel }}<template v-if="curStage.detail"> · {{ curStage.detail }}</template></span>
      <span v-if="running && p.stage === 'storyboard'" class="muted">逐集串行，集数越多越久</span>
      <span class="spacer"></span>
      <span v-if="S.aiBusy" class="pp-hint">任务在后端跑，可以直接刷新页面，回来还能接着看</span>
    </div>

    <ol class="pp-stages">
      <li v-for="st in p.stages" :key="st.key" :class="'st-' + st.status" :title="st.detail || st.label">
        <i>{{ dotOf(st.status) }}</i>
        <span class="pp-st-name">{{ st.label }}</span>
        <span class="pp-st-note">{{ st.status === "pending" ? "等待" : (st.detail || "") }}</span>
        <em v-if="st.ms">{{ msText(st.ms) }}</em>
      </li>
    </ol>

    <div v-if="p.events.length" class="pp-log">
      <div class="pp-log-h">工具调用 <span>{{ p.events.length }}</span></div>
      <div class="pp-log-list" ref="logBox">
        <div v-for="e in p.events" :key="e.callId" class="pp-log-row" :class="'st-' + e.state">
          <i>{{ dotOf(e.state) }}</i>
          <code>{{ e.tool }}</code>
          <b>{{ e.label }}</b>
          <span class="pp-log-d">{{ e.detail }}</span>
          <em v-if="e.state !== 'running'">{{ msText(e.ms) }}</em>
        </div>
      </div>
    </div>

    <div v-if="p.error" class="pp-err">
      <div class="pp-err-h">
        <b>{{ p.status === "cancelled" ? "已取消" : "拆解失败" }}</b>
        <span>{{ p.error }}</span>
      </div>
      <p v-if="p.hint">{{ p.hint }}</p>
      <div class="pp-err-act">
        <button class="btn sm" @click="retryParse">重试</button>
        <button class="btn sm quiet" @click="useLocalInstead">用本地规则生成</button>
        <button class="btn sm quiet" @click="hideParseProgress">知道了</button>
      </div>
    </div>
    <div v-else-if="p.status === 'done'" class="pp-finish">
      <b>✓ 拆解完成</b><span>用时 {{ elapsed }}，结果已写进第 3 步，可撤销。</span>
      <button class="btn sm quiet" @click="hideParseProgress">收起</button>
    </div>
  </section>
</template>
