<script setup>
import { computed } from "vue";
import { S, ui, goStep, openModal, STEPS, STAGES } from "../stores/studio.js";

const stepNo = computed(() => Number(S.step) || 1);
const stageOf = (n) => (Number(n) <= 2 ? "script" : "production");
const stepsOf = (key) => STEPS.filter((s) => s.stage === key);
const isDone = (no) => stepNo.value > no;
const stageDone = (key) => stepsOf(key).every((s) => stepNo.value > s.no);
const stageProg = (key) => stepsOf(key).filter((s) => stepNo.value >= s.no).length;
</script>

<template>
  <aside class="rail">
    <div class="rail-brand">
      <span class="brand-mark" aria-hidden="true"><i></i><i></i><i></i></span>
      <span class="rail-brand-txt">
        <b>分镜工场</b>
        <em>ShortPlay Studio</em>
      </span>
    </div>

    <div class="rail-label">工作流</div>
    <div
      v-for="st in STAGES" :key="st.key"
      class="rail-stage"
      :class="{ on: stageOf(stepNo) === st.key, done: stageDone(st.key) }"
    >
      <div class="rail-stage-h">
        <b>{{ st.name }}</b>
        <em>{{ stageProg(st.key) }} / {{ st.steps.length }}</em>
        <span class="rail-stage-note">{{ st.note }}</span>
      </div>
      <nav class="rail-steps" :aria-label="st.name">
        <button
          v-for="s in stepsOf(st.key)" :key="s.no"
          class="rail-step"
          :class="{ active: s.no === stepNo, done: isDone(s.no) }"
          :data-step="s.no"
          @click="goStep(s.no)"
        >
          <span class="num">{{ isDone(s.no) ? "✓" : s.no }}</span>
          <span class="txt"><b>{{ s.label }}</b><em>{{ s.hint }}</em></span>
        </button>
      </nav>
    </div>

    <div class="rail-label">工具</div>
    <div class="rail-tools">
      <button class="rail-tool" id="settings-btn" @click="openModal('settings')"><span class="ico">⚙</span>生成设置</button>
      <button class="rail-tool" id="agents-btn" @click="openModal('agents')"><span class="ico">◈</span>Agent 工作台</button>
      <button class="rail-tool" id="help-btn" @click="openModal('help')"><span class="ico">?</span>使用说明</button>
    </div>

    <div class="rail-foot">
      <span class="rail-dot" :class="ui.saveState"></span>
      <span id="save-note">{{ ui.saveNote }}</span>
    </div>
  </aside>
</template>
