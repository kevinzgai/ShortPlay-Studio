<script setup>
import { reactive, computed, onMounted } from "vue";
import {
  ui, S, loadModels, testModel, saveModel, activateModel, removeModel
} from "../stores/studio.js";

const form = reactive({
  id: "", name: "", baseUrl: "", apiKey: "", model: "", maxTokens: 16384
});
const editing = computed(() => !!form.id);
const busyTest = computed(() => !!ui.models.testing);
const res = computed(() => ui.models.result);

function blank() {
  Object.assign(form, { id: "", name: "", baseUrl: "", apiKey: "", model: "", maxTokens: 16384 });
  ui.models.result = null;
}
function edit(p) {
  Object.assign(form, {
    id: p.id, name: p.name, baseUrl: p.baseUrl, apiKey: "",
    model: p.model || "", maxTokens: p.maxTokens || 16384
  });
  ui.models.result = null;
}
function runTest() { testModel({ ...form }); }
function rowTest(p) { testModel({ id: p.id, baseUrl: p.baseUrl, model: p.model, apiKey: "" }); }
function save(activate) {
  saveModel({ ...form }, { activate }).then((j) => { if (j !== null) blank(); });
}

onMounted(() => loadModels());
</script>

<template>
  <div class="ms">
    <div class="ms-head">
      <b>语言模型</b>
      <span v-if="S.llmAvailable" class="ms-now">当前生效 · {{ S.llmModel }}</span>
      <span v-else class="ms-now off">未接入，走离线规则引擎</span>
      <button class="btn sm quiet ms-refresh" data-ms-reload @click="loadModels(true)">刷新</button>
    </div>
    <p class="ms-note">
      可以同时存多条，只有标了「使用中」的那条会被真正调用。地址要填到 <code>/v1</code>（OpenAI 兼容接口），
      改完点「测试连接」确认能通再保存。
    </p>

    <ul class="ms-list">
      <li v-for="p in ui.models.list" :key="p.id" class="ms-row" :class="{ on: p.id === ui.models.active }">
        <span class="ms-dot"></span>
        <div class="ms-meta">
          <b>{{ p.name }}</b>
          <span class="ms-sub">{{ p.baseUrl }} · {{ p.model || "未填模型名" }} · {{ p.keyMask || "未填 Key" }}</span>
        </div>
        <span v-if="p.id === ui.models.active" class="chip ok ms-tag">使用中</span>
        <button class="btn sm quiet" data-ms-test :disabled="busyTest" @click="rowTest(p)">
          {{ ui.models.testing === p.id ? "测试中…" : "测试" }}
        </button>
        <button class="btn sm quiet" data-ms-edit @click="edit(p)">编辑</button>
        <button v-if="p.id !== ui.models.active" class="btn sm" data-ms-use @click="activateModel(p.id)">设为当前</button>
        <button class="mini del" data-ms-del title="删除这条配置" @click="removeModel(p.id)">×</button>
      </li>
      <li v-if="!ui.models.list.length" class="ms-empty">
        还没有配置模型。用下面的表单存一条，或沿用 <code>llm-config.bat</code> 里的配置（保存时会自动带出来）。
      </li>
    </ul>

    <div v-if="res" class="ms-result" :class="res.ok ? 'ok' : 'err'" data-ms-result>
      <b>{{ res.ok ? "✓ 连通" : "✗ 不通" }}</b>
      <span v-if="res.ms">{{ res.ms }}ms</span>
      <span v-if="res.ok">模型回了「{{ res.reply }}」· {{ res.model }}</span>
      <span v-else>{{ res.detail }}</span>
    </div>

    <div class="ms-form">
      <div class="ms-f">
        <label>显示名称</label>
        <input v-model="form.name" data-ms-name placeholder="例如 本机 Trae 网关">
      </div>
      <div class="ms-f">
        <label>接口地址</label>
        <input v-model="form.baseUrl" data-ms-base placeholder="http://127.0.0.1:18900/v1">
      </div>
      <div class="ms-f">
        <label>密钥</label>
        <input v-model="form.apiKey" data-ms-key type="password" autocomplete="off"
          :placeholder="editing ? '留空 = 不修改已存的 Key' : 'sk-… / ofm-…'">
      </div>
      <div class="ms-f">
        <label>模型名称</label>
        <input v-model="form.model" data-ms-model placeholder="trae/DeepSeek-V4-Flash">
      </div>
      <div class="ms-f">
        <label>最大输出 tokens</label>
        <input v-model.number="form.maxTokens" data-ms-max type="number" min="1024" max="64000" step="1024">
      </div>
      <div class="ms-acts">
        <button class="btn sm" data-ms-testnew :disabled="busyTest" @click="runTest">
          {{ ui.models.testing === (form.id || "__new__") ? "测试中…" : "测试连接" }}
        </button>
        <button class="btn sm primary" data-ms-save :disabled="ui.models.busy === 'save'" @click="save(false)">保存</button>
        <button class="btn sm" data-ms-saveuse :disabled="ui.models.busy === 'save'" @click="save(true)">保存并切换</button>
        <button v-if="editing" class="btn sm quiet" @click="blank">取消编辑</button>
        <span v-if="editing" class="ms-editing">正在编辑「{{ form.name || form.id }}」</span>
      </div>
    </div>
  </div>
</template>
