<script setup>
import { computed, ref } from "vue";
import {
  S, E, activeShot, maxDuration, FRAME,
  castOf, sceneAssetOf, refsOf, promptOf, shotAssetStale, refreshOneShot, copyText,
  activeSegmentOf
} from "../stores/studio.js";

const shot = activeShot;
const seg = activeSegmentOf;
const h3Expanded = ref(false);
const segPrompt = computed(() => {
  if (!seg.value) return "";
  const first = seg.value.shots[0];
  return E.h3SegmentPrompt(seg.value, S.assets, S.config,
    (E.refsFor(first.shot, S.assets).find((r) => r.image) || {}).image || null);
});
const frame = computed(() => FRAME[shot.value?.size] || FRAME["中景"]);
const frameStyle = computed(() => ({
  "--hw": frame.value[0] + "px", "--hh": frame.value[1] + "px",
  "--bw": frame.value[2] + "px", "--bh": frame.value[3] + "px"
}));
const barWidth = computed(() => shot.value ? Math.round((Number(shot.value.duration) / maxDuration.value) * 100) + "%" : "0%");
const cast = computed(() => (shot.value ? castOf(shot.value) : []));
const sceneAsset = computed(() => (shot.value ? sceneAssetOf(shot.value)[0] || null : null));
const refs = computed(() => (shot.value ? refsOf(shot.value) : []));
const prompt = computed(() => (shot.value ? promptOf(shot.value) : ""));
const stale = computed(() => (shot.value ? shotAssetStale(shot.value) : false));
</script>

<template>
  <template v-if="shot">
    <div class="row" style="margin-bottom:12px">
      <h3>镜头预览</h3><div class="spacer"></div><span class="chip indigo">{{ shot.code }}</span>
    </div>
    <div class="frame" :style="frameStyle">
      <div class="horizon"></div>
      <div class="figure"><div class="head"></div><div v-if="frame[2]" class="body"></div></div>
      <span class="label">{{ shot.size }}示意</span><span class="ratio">{{ S.config.aspect }}</span>
    </div>
    <div class="pv-title">{{ shot.visual || "（还没写画面描述）" }}</div>
    <div v-if="shot.dialogue" class="pv-dialogue">{{ shot.dialogue }}</div>
    <div class="pv-row"><span class="k">场次</span><span class="v">{{ shot.sceneLabel }}</span></div>
    <div class="pv-row"><span class="k">景别</span><span class="v">{{ shot.size }} · {{ E.kindName(shot.kind) }}</span></div>
    <div class="pv-row"><span class="k">时长</span><span class="v">{{ shot.duration }} 秒<div class="timeline"><i :style="{ width: barWidth }"></i></div></span></div>

    <div class="pv-row" v-if="refs.length">
      <span class="k">参考图槽位</span>
      <span class="v">
        <span v-for="r in refs" :key="r.slot" class="slot-chip" :class="{ empty: !r.image }"
          :title="r.image ? '已挂参考图' : '还没有参考图，导出时这个槽位留空'">
          {{ r.slot }} · {{ r.name }}
        </span>
      </span>
    </div>
    <div class="pv-row" v-if="shot.notes"><span class="k">备注</span><span class="v">{{ shot.notes }}</span></div>

    <div class="prompt-box">
      <div class="prompt-head">
        <b>最终提示词</b>
        <span v-if="stale" class="chip warn" style="margin-left:6px">设定已改</span>
        <div class="spacer"></div>
        <button v-if="stale" class="mini" id="pv-refresh" title="按最新角色设定刷新" @click="refreshOneShot(shot.id)">↻</button>
        <button class="btn sm quiet" id="pv-copy" @click="copyText(prompt, '提示词已复制')">复制</button>
      </div>
      <p class="prompt-text" id="pv-prompt">{{ prompt }}</p>
      <div class="inline-note" style="margin-top:0">导出「视频提示词」时就是这个版本，附带槽位表，可直接喂给视频生成工具。</div>
    </div>

    <div class="prompt-box" style="margin-top:10px">
      <div class="prompt-head">
        <b>H3 视频提示词</b>
        <span class="chip indigo" style="margin-left:6px">当前段 S{{ seg?.shots?.[0]?.shot?.code ? "…" : "" }} · {{ seg?.shots?.length || 0 }} 镜</span>
        <div class="spacer"></div>
        <button class="btn sm quiet" id="pv-h3-toggle" @click="h3Expanded = !h3Expanded">{{ h3Expanded ? "收起" : "展开" }}</button>
        <button class="btn sm quiet" id="pv-h3-copy" @click="copyText(segPrompt, 'H3 提示词已复制')">复制</button>
      </div>
      <p v-if="h3Expanded" class="prompt-text" id="pv-h3-prompt">{{ segPrompt }}</p>
      <div v-else class="inline-note" style="margin-top:0">H3 规范：通用身份、禁画风，台词进 &lt;d&gt;[Chinese]…&lt;/d&gt; 块；段内每镜一行带切点时刻。导出含整段可一次提交。</div>
    </div>
    <div class="inline-note">示意框只表示取景范围，不是生成的画面。</div>
  </template>
  <div v-else class="muted">选中左侧任意一镜，这里会显示大图预览。</div>
</template>
