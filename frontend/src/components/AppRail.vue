<script setup>
import { S, ui, goStep, openModal } from "../stores/studio.js";

const steps = [["1", "导入剧本", "粘贴或上传原文"], ["2", "AI 自动拆解", "场次 · 角色 · 体检"], ["3", "分镜表", "改字段 · 导出"]];
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
    <nav class="rail-steps" id="stepper" aria-label="制作步骤">
      <button
        v-for="s in steps" :key="s[0]"
        class="rail-step"
        :class="{ active: Number(s[0]) === S.step, done: Number(s[0]) < S.step }"
        :data-step="s[0]"
        @click="goStep(Number(s[0]))"
      >
        <span class="num">{{ Number(s[0]) < S.step ? "✓" : s[0] }}</span>
        <span class="txt"><b>{{ s[1] }}</b><em>{{ s[2] }}</em></span>
      </button>
    </nav>

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
