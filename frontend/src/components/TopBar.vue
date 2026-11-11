<script setup>
import { computed } from "vue";
import { S, ui, PROJECT, canUndo, canRedo, undo, redo, openModal, STEPS } from "../stores/studio.js";
import { themeLabel, themeIcon, toggleTheme } from "../lib/theme.js";

const cur = computed(() => STEPS.find((s) => s.no === Number(S.step)) || STEPS[0]);
const siblings = computed(() => STEPS.filter((s) => s.stage === cur.value.stage));
const subNo = computed(() => siblings.value.findIndex((s) => s.no === cur.value.no) + 1);
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
      <span class="crumb-stage">{{ cur.stageName }}</span>
      <span class="crumb-sep">·</span>
      <span class="crumb-step">0{{ subNo }} / 0{{ siblings.length }}</span>
      <span class="crumb-sep">/</span>
      <span class="crumb-cur">{{ cur.label }}</span>
      <span v-if="cur.optional" class="crumb-opt">可选动作</span>
      <span v-else class="crumb-main">主流程 {{ cur.no }}/3</span>
    </div>

    <div class="top-actions">
      <button class="icon-btn theme-btn" id="theme-btn"
        :title="'外观：' + themeLabel() + '（点击切换浅色 / 暗色 / 跟随系统）'"
        aria-label="切换外观主题" @click="toggleTheme">{{ themeIcon() }}</button>
      <button class="icon-btn" id="undo-btn" title="撤销 (Ctrl+Z)" aria-label="撤销" :disabled="!canUndo" @click="undo">↶</button>
      <button class="icon-btn" id="redo-btn" title="重做 (Ctrl+Shift+Z)" aria-label="重做" :disabled="!canRedo" @click="redo">↷</button>
    </div>
  </header>
</template>
