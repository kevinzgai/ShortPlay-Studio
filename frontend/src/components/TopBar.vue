<script setup>
import { computed } from "vue";
import { S, ui, PROJECT, canUndo, canRedo, undo, redo, openModal } from "../stores/studio.js";

const steps = [["1", "导入剧本"], ["2", "AI 自动拆解"], ["3", "分镜表"]];
const cur = computed(() => steps.find((s) => Number(s[0]) === S.step) || steps[0]);
const projName = computed(() => S.projectName || "未命名项目");
const saveTitle = computed(() => (PROJECT.server
  ? "项目保存在本机 projects/ 目录，改动自动落盘"
  : "本机服务未连接，内容只缓存在浏览器"));
</script>

<template>
  <header class="topbar">
    <div class="tb-project">
      <button class="proj-chip" id="project-btn" :title="'切换 / 管理项目 · ' + saveTitle"
        @click="openModal('projects')">
        <span class="proj-ico" aria-hidden="true">◫</span>
        <span class="proj-name">{{ projName }}</span>
        <span class="proj-count" v-if="ui.projects.length">{{ ui.projects.length }}</span>
        <span class="proj-caret" aria-hidden="true">▾</span>
      </button>
      <span class="save-pill" :class="ui.saveState" id="save-state" :title="ui.saveNote">
        <i aria-hidden="true"></i>{{ ui.saveNote }}
      </span>
    </div>

    <div class="crumb">
      <span class="crumb-step">STEP 0{{ cur[0] }} / 03</span>
      <span class="crumb-sep">/</span>
      <span class="crumb-cur">{{ cur[1] }}</span>
    </div>

    <div class="top-actions">
      <button class="icon-btn" id="undo-btn" title="撤销 (Ctrl+Z)" aria-label="撤销" :disabled="!canUndo" @click="undo">↶</button>
      <button class="icon-btn" id="redo-btn" title="重做 (Ctrl+Shift+Z)" aria-label="重做" :disabled="!canRedo" @click="redo">↷</button>
    </div>
  </header>
</template>
