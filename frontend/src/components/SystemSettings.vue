<script setup>
import { ref, computed, onMounted } from "vue";
import { S, ui, PROJECT, loadModels, loadEngine, comfyCheck } from "../stores/studio.js";
import ModelSettings from "./ModelSettings.vue";
import EngineSettings from "./EngineSettings.vue";
import EngineDiagnostics from "./EngineDiagnostics.vue";

/* 三个分区共用一屏，用顶部 tab 切换：模型配置天然比生成参数长，
   并列摊开会让弹窗变成长滚动条。tab 上带状态灯，红了一眼就能看出来。 */
const TAB_KEY = "sp-sys-tab";
const tab = ref("llm");
try {
  const last = sessionStorage.getItem(TAB_KEY);
  if (last === "llm" || last === "engine" || last === "diag") tab.value = last;
} catch (e) { /* 隐私模式下 sessionStorage 不可用，退回默认 tab */ }

function go(k) {
  tab.value = k;
  try { sessionStorage.setItem(TAB_KEY, k); } catch (e) { /* 忽略 */ }
}

const llmOn = computed(() => !!S.llmAvailable);
const comfyOn = computed(() => !!ui.comfy.online);
const qwenOn = computed(() => !!ui.comfy.qwen.online);
const engineOn = computed(() => comfyOn.value || qwenOn.value);
const checked = computed(() => !!ui.comfy.checked);
/* 口径必须与诊断页一致，否则 tab 说「正常」、点进去说「1 项不可用」：
   通义万相是可选引擎，没配 Key 只算「未启用」，不算不可用。 */
const badCount = computed(() =>
  (PROJECT.server ? 0 : 1) + (llmOn.value ? 0 : 1) + (comfyOn.value ? 0 : 1));
const warnCount = computed(() => (qwenOn.value ? 0 : 1));
const diagBadge = computed(() => {
  if (badCount.value) return badCount.value + " 项不可用";
  if (warnCount.value) return warnCount.value + " 项可选未启用";
  return "全部就绪";
});

const tabs = computed(() => [
  { k: "llm", label: "文字模型", on: llmOn.value,
    badge: llmOn.value ? (S.llmModel || "已接入") : "未接入" },
  { k: "engine", label: "出图引擎", on: engineOn.value,
    badge: !checked.value ? "检测中…"
      : comfyOn.value ? "ComfyUI" : (qwenOn.value ? "通义万相" : "都不可用") },
  { k: "diag", label: "连接与诊断", on: badCount.value === 0, badge: diagBadge.value }
]);

onMounted(() => {
  loadModels();
  loadEngine();
  comfyCheck();
});
</script>

<template>
  <div class="sys">
    <div class="sys-tabs" role="tablist" aria-label="系统设置">
      <button
        v-for="t in tabs" :key="t.k"
        class="sys-tab" :class="{ on: tab === t.k }"
        role="tab" :aria-selected="tab === t.k"
        :data-sys-tab="t.k" @click="go(t.k)"
      >
        <span class="sys-dot" :class="t.on ? 'ok' : 'warn'"></span>
        <b>{{ t.label }}</b>
        <em>{{ t.badge }}</em>
      </button>
    </div>

    <div class="sys-body">
      <p v-if="tab === 'llm'" class="sys-scope">
        全局生效，<b>不随项目变化</b>。所有步骤（转写、体检、分集、分镜、资产、Agent）都用这一条。
      </p>
      <p v-else-if="tab === 'engine'" class="sys-scope">
        全局生效，<b>不随项目变化</b>。改完点保存立即生效，不用改 <code>.bat</code>、不用重启服务。
      </p>

      <ModelSettings v-if="tab === 'llm'" />
      <EngineSettings v-else-if="tab === 'engine'" />
      <EngineDiagnostics v-else @go="go" />
    </div>
  </div>
</template>
