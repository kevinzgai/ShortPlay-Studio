<script setup>
import { reactive, computed, onMounted } from "vue";
import {
  ui, saveEngine, testEngine, loadEngine, loadComfyModels, comfyCheck
} from "../stores/studio.js";

/* 出图引擎是「全局单例」，与语言模型的多条列表不同：
   每类只有一份配置，没有 active 的概念。 */
const form = reactive({
  comfyHost: "", comfyModel: "", qwenUrl: "", qwenModel: "", qwenSize: "2K",
  qwenKey: "", clearQwenKey: false
});

const SRC_LABEL = { file: "界面配置", env: "环境变量", default: "内置默认" };

function fill() {
  const c = ui.engine.config || {};
  const v = (k, d) => (c[k] && c[k].value) || d || "";
  form.comfyHost = v("comfyHost", "http://127.0.0.1:8188");
  form.comfyModel = v("comfyModel");
  form.qwenUrl = v("qwenUrl");
  form.qwenModel = v("qwenModel", "wan2.7-image-pro");
  form.qwenSize = v("qwenSize", "2K");
  form.qwenKey = "";
  form.clearQwenKey = false;
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
const res = computed(() => ui.engine.result);
const saving = computed(() => ui.engine.busy === "save");
const comfyModels = computed(() => ui.engine.models || []);

function save() {
  saveEngine({
    comfyHost: form.comfyHost, comfyModel: form.comfyModel,
    qwenUrl: form.qwenUrl, qwenModel: form.qwenModel, qwenSize: form.qwenSize,
    qwenKey: form.qwenKey, clearQwenKey: form.clearQwenKey
  }).then((j) => { if (j) fill(); });
}
function testComfy() { testEngine("comfy"); }
function testQwen() { testEngine("qwen"); }
</script>

<template>
  <div class="es">
    <!-- 本地 ComfyUI -->
    <section class="es-block">
      <div class="es-h">
        <b>本地 ComfyUI</b>
        <span class="es-badge" :class="ui.comfy.online ? 'ok' : 'off'" data-eng-state="comfy">
          {{ ui.comfy.online ? "在线 · v" + (ui.comfy.version || "?") : "离线" }}
        </span>
        <span v-if="ui.comfy.online" class="es-sub">{{ ui.comfy.vramFreeMB }}MB 可用显存</span>
      </div>
      <p class="es-note">
        本机跑 Flux，图不出门、不产生调用费。三视图、概念图、组图都走它。
      </p>

      <div class="es-f">
        <label>服务地址<span v-if="srcText('comfyHost')" class="es-src">{{ srcText("comfyHost") }}</span></label>
        <input v-model="form.comfyHost" data-eng="comfy-host" placeholder="http://127.0.0.1:8188">
      </div>
      <div class="es-f">
        <label>Diffusion 模型（unet）<span v-if="srcText('comfyModel')" class="es-src">{{ srcText("comfyModel") }}</span></label>
        <div class="es-row">
          <input v-model="form.comfyModel" data-eng="comfy-model" list="comfy-unets"
            placeholder="flux1-schnell-fp8.safetensors">
          <button class="btn sm quiet" data-eng="reload-models" :disabled="ui.engine.modelsBusy"
            @click="loadComfyModels(true)">{{ ui.engine.modelsBusy ? "读取中…" : "读可用列表" }}</button>
        </div>
        <datalist id="comfy-unets">
          <option v-for="m in comfyModels" :key="m" :value="m"></option>
        </datalist>
        <span v-if="comfyModels.length" class="es-hint" data-eng-models>
          ComfyUI 里现有 {{ comfyModels.length }} 个：{{ comfyModels.join("、") }}
        </span>
        <span v-else-if="!ui.comfy.online" class="es-hint">
          连上 ComfyUI 后可以在这里直接选现有模型，不用猜文件名。
        </span>
      </div>

      <div class="es-acts">
        <button class="btn sm" data-eng="test-comfy" :disabled="ui.engine.testing === 'comfy'" @click="testComfy">
          {{ ui.engine.testing === "comfy" ? "探测中…" : "测试连接" }}
        </button>
      </div>
    </section>

    <!-- 通义万相 -->
    <section class="es-block">
      <div class="es-h">
        <b>通义万相</b>
        <span class="es-badge" :class="ui.comfy.qwen.online ? 'ok' : 'off'" data-eng-state="qwen">
          {{ ui.comfy.qwen.online ? "Key 已配置" : "未配置" }}
        </span>
        <span v-if="keySet" class="es-sub">{{ keyMask }}</span>
      </div>
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

    <div v-if="res" class="ms-result" :class="res.ok ? 'ok' : 'err'" data-eng-result>
      <b>{{ res.ok ? "✓ 通过" : "✗ 不通" }}</b>
      <span>{{ res.kind === "qwen" ? "通义万相" : "本地 ComfyUI" }}</span>
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
