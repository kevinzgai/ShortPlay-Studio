<script setup>
/* S3 · 第 2 步：分集方案从只读卡片变成可编辑表。
   所有编辑都走 store，标 source="manual"，下游只标 stale、不删镜头。 */
import {
  S, E, planStep, manualEpisodeCount,
  editEpisode, splitEpisode, mergeEpisode, deleteEpisode
} from "../stores/studio.js";

function episodeShots(no) { return S.shots.filter((s) => s.episode === no); }
function onTitle(e, no) { editEpisode(no, { title: e.target.value }); }
function onFrom(e, no) { editEpisode(no, { sceneFrom: e.target.value }); }
function onTo(e, no) { editEpisode(no, { sceneTo: e.target.value }); }
</script>

<template>
  <div class="card pad episode-card" id="episode-plan">
    <div class="row" style="margin-bottom:12px">
      <h2>分集方案</h2>
      <span class="chip indigo" id="episode-count">{{ S.episodes.length }} 集</span>
      <span v-if="S.steps.plan.engine === 'ai'" class="chip ok">大模型生成{{ S.steps.plan.model ? " · " + S.steps.plan.model : "" }}</span>
      <span v-else-if="manualEpisodeCount()" class="chip warn" id="manual-count">含 {{ manualEpisodeCount() }} 集手调</span>
      <span v-else class="chip">本地规则分集</span>
      <div class="spacer"></div>
      <button class="btn sm" id="replan" @click="planStep()">重算分集</button>
    </div>

    <div class="episode-grid">
      <div v-for="ep in S.episodes" :key="ep.no" class="episode-item" :data-ep-no="ep.no">
        <div class="ep-top">
          <span class="ep-no">E{{ E.pad2(ep.no) }}</span>
          <input class="ep-title" :data-ep-title="ep.no" :value="ep.title || ''" placeholder="集名"
            @change="onTitle($event, ep.no)" />
          <span v-if="ep.source === 'manual'" class="edited-mark">手调</span>
        </div>
        <div class="ep-range">
          <span>第</span>
          <input type="number" min="1" class="ep-num" :data-ep-from="ep.no" :value="ep.sceneFrom"
            @change="onFrom($event, ep.no)" />
          <span>– 第</span>
          <input type="number" min="1" class="ep-num" :data-ep-to="ep.no" :value="ep.sceneTo"
            @change="onTo($event, ep.no)" />
          <span>场</span>
        </div>
        <p v-if="ep.synopsis" class="ep-syn">{{ ep.synopsis }}</p>
        <p v-if="ep.hook" class="ep-hook">集尾钩子：{{ ep.hook }}</p>
        <div class="ep-meta">{{ episodeShots(ep.no).length
          ? episodeShots(ep.no).length + " 镜 · 约 " + E.totalDuration(episodeShots(ep.no)) + " 秒"
          : "待生成分镜" }}</div>
        <div class="ep-actions">
          <button class="btn sm quiet" :data-ep-split="ep.no" @click="splitEpisode(ep.no)">拆成两集</button>
          <button class="btn sm quiet" :data-ep-merge="ep.no" :disabled="ep.no >= S.episodes.length"
            @click="mergeEpisode(ep.no)">合并下一集</button>
          <button class="btn sm danger" :data-ep-del="ep.no" :disabled="S.episodes.length <= 1"
            @click="deleteEpisode(ep.no)">删集</button>
        </div>
      </div>
    </div>

    <div class="inline-note" style="margin-top:10px">
      改过的集会标「手调」；重算会覆盖它们（先二次确认）。已有镜头不会删除，只标第 3 步「需重算」，逐集重排后归位。
    </div>
  </div>
</template>
