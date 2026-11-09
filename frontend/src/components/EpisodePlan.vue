<script setup>
import { S, E, aiRedo } from "../stores/studio.js";

function episodeShots(no) { return S.shots.filter((s) => s.episode === no); }
</script>

<template>
  <div class="card pad episode-card">
    <div class="row" style="margin-bottom:12px">
      <h2>AI 分集方案</h2>
      <span class="chip indigo">{{ S.episodes.length }} 集</span>
      <span v-if="S.episodeSource === 'ai'" class="chip ok">大模型生成{{ S.aiModel ? " · " + S.aiModel : "" }}</span>
      <span v-else class="chip">本地规则分集</span>
      <div class="spacer"></div>
      <button class="btn sm" data-ai-redo @click="aiRedo">重新 AI 分集分镜</button>
    </div>
    <div class="episode-grid">
      <div v-for="ep in S.episodes" :key="ep.no" class="episode-item">
        <div class="ep-top">
          <span class="ep-no">E{{ E.pad2(ep.no) }}</span>
          <b>{{ ep.title || ("第" + ep.no + "集") }}</b>
          <span class="muted">第{{ ep.sceneFrom }}–{{ ep.sceneTo }}场</span>
        </div>
        <p v-if="ep.synopsis" class="ep-syn">{{ ep.synopsis }}</p>
        <p v-if="ep.hook" class="ep-hook">集尾钩子：{{ ep.hook }}</p>
        <div class="ep-meta">{{ episodeShots(ep.no).length
          ? episodeShots(ep.no).length + " 镜 · 约 " + E.totalDuration(episodeShots(ep.no)) + " 秒"
          : "待生成分镜" }}</div>
      </div>
    </div>
  </div>
</template>
