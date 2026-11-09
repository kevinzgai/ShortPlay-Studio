<script setup>
import { computed } from "vue";
import { S, E, ui, toggleExport, exportAs } from "../stores/studio.js";

/** 导出只有这一份实现：步骤 2 与步骤 3 都挂它，不再各自摆一套按钮。 */

const exportItems = [
  ["csv", "Excel 表格 · CSV"],
  ["md", "分镜表 · Markdown"],
  ["txt", "拍摄清单 · TXT"],
  ["json", "完整数据 · JSON"],
  ["video-prompts", "视频提示词 · 对接出片"],
  ["zip", "整包导出 · ZIP（剧本 + 分镜 + 资产 + 参考图）"]
];

// 出片端预检：画幅会被换成哪个合法宽高、时长吸附后成片多少秒。
// 这些数字对用户是硬信息（成片会变长），所以摊在菜单里，别藏着。
const h3Hint = computed(() => {
  if (!S.shots.length) return "";
  const f = E.h3Frame(S.config.aspect, S.config.videoQuality);
  let snapped = 0, seconds = 0;
  S.shots.forEach((s) => {
    const d = E.h3Duration(s.duration);
    if (d.snapped) snapped += 1;
    seconds += d.seconds;
  });
  const base = "出片 " + f.width + "×" + f.height;
  return snapped
    ? base + " · 时长吸附到 5/8/10 秒后约 " + seconds + " 秒"
    : base + " · 时长已落在 5/8/10 秒档位上";
});
</script>

<template>
  <div class="export-wrap">
    <button class="btn sm" id="export-btn" :title="'导出当前项目的分镜 / 资产'" @click="toggleExport">
      导出{{ S.shots.length ? "" : "资产包" }} ▾
    </button>
    <div class="export-menu" id="export-menu" :class="{ hidden: !ui.exportOpen }">
      <div class="em-note">导出当前分镜表（含所有手动修改）</div>
      <div v-if="h3Hint" class="em-note em-h3" id="h3-note">{{ h3Hint }}</div>
      <button v-for="it in exportItems" :key="it[0]" :data-export="it[0]" @click="exportAs(it[0])">{{ it[1] }}</button>
    </div>
  </div>
</template>
