<script setup>
import { reactive, computed, ref, onMounted } from "vue";
import {
  ui, saveEngine, testEngine, loadEngine, loadComfyModels, comfyCheck
} from "../stores/studio.js";

/* 出图引擎是「全局单例」，与语言模型的多条列表不同：
   每类只有一份配置，没有 active 的概念。
   三个引擎用标签切换（不再平铺），标签上直接看在线 / Key 状态。 */
const engTab = ref("comfy");

const form = reactive({
  gwUrl: "", comfyHost: "", comfyModel: "", qwenUrl: "", qwenModel: "", qwenSize: "2K",
  qwenKey: "", clearQwenKey: false,
  h3Url: "", h3Model: "", h3Size: "2720x1536",
  h3Key: "", clearH3Key: false
});

const SRC_LABEL = { file: "界面配置", env: "环境变量", default: "内置默认" };

function fill() {
  const c = ui.engine.config || {};
  const v = (k, d) => (c[k] && c[k].value) || d || "";
  form.gwUrl = v("gwUrl", "http://127.0.0.1:8000");
  form.comfyHost = v("comfyHost", "http://127.0.0.1:8188");
  form.comfyModel = v("comfyModel");
  form.qwenUrl = v("qwenUrl");
  form.qwenModel = v("qwenModel", "wan2.7-image-pro");
  form.qwenSize = v("qwenSize", "2K");
  form.qwenKey = "";
  form.clearQwenKey = false;
  form.h3Url = v("h3Url");
  form.h3Model = v("h3Model", "MiniMax-H3-Image");
  form.h3Size = v("h3Size", "2720x1536");
  form.h3Key = "";
  form.clearH3Key = false;
}

onMounted(() => {
  loadEngine(true).then(fill);
  comfyCheck();
  loadComfyModels();
});

const src = (k) => (((ui.engine.config || {})[k] || {}).source || "");
const srcText = (k) => SRC_LABEL[src(k)] || "";
const keySet = computed(() => !!(((ui.engine.config || {}).qwenKey || {}).set));
const keyMask = computed(() => (((ui.engine.config || {}).qwenKey || {}).mask || ""));
const h3KeySet = computed(() => !!(((ui.engine.config || {}).h3Key || {}).set));
const h3KeyMask = computed(() => (((ui.engine.config || {}).h3Key || {}).mask || ""));
const res = computed(() => ui.engine.result);
const saving = computed(() => ui.engine.busy === "save");
const comfyModels = computed(() => ui.engine.models || []);

/* 架构信息全部来自后端 /api/comfy/models（同一个函数 comfy_arch_info 也喂给
   /api/comfy/status 与测试连接），前端不再自行按文件名猜，避免两套判断漂移。
   只在「这个文件名确实在 ComfyUI 列表里」时才有标注；手敲的新名字查不到就不标，
   真错了由「测试连接」兜住。 */
const archOf = (m) => (ui.engine.modelArchs || {})[m] || null;
const curArch = computed(() => archOf(form.comfyModel));
const modelTitle = (m) => {
  const a = archOf(m);
  if (!a) return m;
  return a.usable
    ? m + " · " + a.label + " · 默认 " + a.steps + " 步"
    : m + " · " + a.label + "：出不了静帧，只能做视频";
};
function pickModel(m) { form.comfyModel = m; }

const engTabs = computed(() => [
  { k: "comfy", label: "本地网关（生图 / 生视频）", on: !!ui.comfy.online,
    badge: ui.comfy.online ? "在线" : "离线" },
  { k: "qwen", label: "通义万相", on: keySet.value,
    badge: keySet.value ? (keyMask.value || "已配置") : "未配置" },
  { k: "h3", label: "MiniMax H3（云端）", on: h3KeySet.value,
    badge: h3KeySet.value ? (h3KeyMask.value || "已配置") : "未配置" }
]);

function save() {
  saveEngine({
    gwUrl: form.gwUrl,
    comfyHost: form.comfyHost, comfyModel: form.comfyModel,
    qwenUrl: form.qwenUrl, qwenModel: form.qwenModel, qwenSize: form.qwenSize,
    qwenKey: form.qwenKey, clearQwenKey: form.clearQwenKey,
    h3Url: form.h3Url, h3Model: form.h3Model, h3Size: form.h3Size,
    h3Key: form.h3Key, clearH3Key: form.clearH3Key
  }).then((j) => { if (j) fill(); });
}
function testComfy() { testEngine("comfy"); }
function testQwen() { testEngine("qwen"); }
function testH3() { testEngine("h3"); }
</script>

<template>
  <div class="es">
    <!-- 引擎切换：一次只显示一个引擎的配置，状态直接标在标签上 -->
    <div class="sys-tabs" role="tablist" aria-label="出图引擎">
      <button
        v-for="t in engTabs" :key="t.k"
        class="sys-tab" :class="{ on: engTab === t.k }"
        role="tab" :aria-selected="engTab === t.k"
        :data-eng-tab="t.k" @click="engTab = t.k"
      >
        <span class="sys-dot" :class="t.on ? 'ok' : 'warn'"></span>
        <b>{{ t.label }}</b>
        <em>{{ t.badge }}</em>
      </button>
    </div>

    <!-- 本地 ComfyUI -->
    <section v-if="engTab === 'comfy'" class="es-block" data-eng-panel="comfy">
      <p class="es-note">
        本机出图与出视频，图不出门、不产生调用费。三视图、概念图、组图、镜头视频都走它。
        出图不再直连 ComfyUI，统一交给本地网关排队（24G 显存装不下两套模型，必须串行）。
        <span v-if="curArch" class="es-sub">当前 {{ curArch.label }} · {{ curArch.steps }} 步</span>
        <span v-if="ui.comfy.online" class="es-sub">
          {{ ui.comfy.vramFreeMB }}MB 可用显存 · 队列 {{ ui.comfy.queue || 0 }}
        </span>
      </p>

      <div class="es-f">
        <label>网关地址<span v-if="srcText('gwUrl')" class="es-src">{{ srcText("gwUrl") }}</span></label>
        <input v-model="form.gwUrl" data-eng="gw-url" placeholder="http://127.0.0.1:8000">
        <span class="es-hint">
          H3 + SeedVR2 本地网关（comfyui-h3-demo），没启动时执行其 start_all.ps1；
          模型与工作流模板由网关管理，这里不用选。
        </span>
      </div>

      <div class="es-acts">
        <button class="btn sm" data-eng="test-comfy" :disabled="ui.engine.testing === 'comfy'" @click="testComfy">
          {{ ui.engine.testing === "comfy" ? "探测中…" : "测试连接" }}
        </button>
      </div>
    </section>

    <!-- 通义万相 -->
    <section v-else-if="engTab === 'qwen'" class="es-block" data-eng-panel="qwen">
      <p class="es-note">
        云端组图引擎，一次可出一组风格一致的图。按次计费，只有真正出图才会产生调用。
      </p>

      <div class="es-f">
        <label>
          API Key
          <span v-if="srcText('qwenKey')" class="es-src">{{ srcText("qwenKey") }}</span>
        </label>
        <div class="es-row">
          <input v-model="form.qwenKey" data-eng="qwen-key" type="password" autocomplete="off"
            :placeholder="keySet ? '已保存 ' + keyMask + '，留空 = 不修改' : 'sk-…'">
          <button v-if="keySet" class="btn sm quiet" data-eng="clear-key"
            @click="form.clearQwenKey = !form.clearQwenKey">
            {{ form.clearQwenKey ? "已标记清除" : "清除 Key" }}
          </button>
        </div>
        <span v-if="form.clearQwenKey" class="es-hint warn">保存后会删掉已存的 Key</span>
      </div>

      <div class="es-f">
        <label>模型<span v-if="srcText('qwenModel')" class="es-src">{{ srcText("qwenModel") }}</span></label>
        <input v-model="form.qwenModel" data-eng="qwen-model" placeholder="wan2.7-image-pro">
      </div>
      <div class="es-f">
        <label>出图尺寸</label>
        <select v-model="form.qwenSize" data-eng="qwen-size">
          <option value="1K">1K</option>
          <option value="2K">2K</option>
          <option value="4K">4K</option>
        </select>
      </div>

      <div class="es-acts">
        <button class="btn sm" data-eng="test-qwen" :disabled="ui.engine.testing === 'qwen'" @click="testQwen">
          {{ ui.engine.testing === "qwen" ? "检查中…" : "检查 Key" }}
        </button>
      </div>
    </section>

    <!-- MiniMax H3-Image -->
    <section v-else class="es-block" data-eng-panel="h3">
      <p class="es-note">
        云端生图引擎（api.minimax.cn，一次可出多张）。按次计费，只有真正出图才会产生调用。
      </p>

      <div class="es-f">
        <label>
          API Key
          <span v-if="srcText('h3Key')" class="es-src">{{ srcText("h3Key") }}</span>
        </label>
        <div class="es-row">
          <input v-model="form.h3Key" data-eng="h3-key" type="password" autocomplete="off"
            :placeholder="h3KeySet ? '已保存 ' + h3KeyMask + '，留空 = 不修改' : 'sk-cp-…'">
          <button v-if="h3KeySet" class="btn sm quiet" data-eng="clear-h3-key"
            @click="form.clearH3Key = !form.clearH3Key">
            {{ form.clearH3Key ? "已标记清除" : "清除 Key" }}
          </button>
        </div>
        <span v-if="form.clearH3Key" class="es-hint warn">保存后会删掉已存的 Key</span>
      </div>

      <div class="es-f">
        <label>模型<span v-if="srcText('h3Model')" class="es-src">{{ srcText("h3Model") }}</span></label>
        <input v-model="form.h3Model" data-eng="h3-model" placeholder="MiniMax-H3-Image">
      </div>
      <div class="es-f">
        <label>接口地址<span v-if="srcText('h3Url')" class="es-src">{{ srcText("h3Url") }}</span></label>
        <input v-model="form.h3Url" data-eng="h3-url" placeholder="https://api.minimax.cn/v1/images/generations">
      </div>
      <div class="es-f">
        <label>出图尺寸（宽x高）</label>
        <input v-model="form.h3Size" data-eng="h3-size" placeholder="2720x1536">
      </div>

      <div class="es-acts">
        <button class="btn sm" data-eng="test-h3" :disabled="ui.engine.testing === 'h3'" @click="testH3">
          {{ ui.engine.testing === "h3" ? "检查中…" : "检查 Key" }}
        </button>
      </div>
    </section>

    <div v-if="res" class="ms-result" :class="res.ok ? 'ok' : 'err'" data-eng-result>
      <b>{{ res.ok ? "✓ 通过" : "✗ 不通" }}</b>
      <span>{{ { comfy: "本地 ComfyUI", qwen: "通义万相", h3: "MiniMax H3" }[res.kind] || res.kind }}</span>
      <span>{{ res.detail || (res.host || "") }}</span>
    </div>

    <div class="es-foot">
      <button class="btn sm primary" data-eng="save" :disabled="saving" @click="save">
        {{ saving ? "保存中…" : "保存并生效" }}
      </button>
      <span class="es-hint">存在本机 <code>engine-config.json</code>；环境变量仍可覆盖默认值。</span>
    </div>
  </div>
</template>
