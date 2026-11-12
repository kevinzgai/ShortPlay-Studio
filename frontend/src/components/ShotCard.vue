<script setup>
import { ref, computed } from "vue";
import { S, E, toggleCheck, setActiveShot, handleShotOp, castOf, sceneAssetOf, shotAssetStale, refreshOneShot, toggleShotLock, startShotVideo, setShotFrame } from "../stores/studio.js";

const props = defineProps({ shot: { type: Object, required: true } });
const open = ref(false);
const detail = computed(() => E.normalizeDetail(props.shot.detail));
const filled = computed(() => E.DETAIL_FIELDS.filter((k) => detail.value[k]).length);
const cast = computed(() => castOf(props.shot));
const sceneAsset = computed(() => sceneAssetOf(props.shot)[0] || null);
const stale = computed(() => shotAssetStale(props.shot));

function onCardClick(e) {
  if (e.target.closest("input,textarea,select,button,.grab")) return;
  setActiveShot(props.shot.id);
}
const edited = () => Object.keys(props.shot.edited || {}).length;
/* 视频任务状态：queued / running 显示进度条，done 显示播放器，failed 显示原因 */
const frameInput = ref(null);
const frameSet = computed(() => !!props.shot.frameImage);
function pickFrame() { frameInput.value && frameInput.value.click(); }
function onFrameFile(ev) {
  const f = (ev.target.files || [])[0];
  if (f) setShotFrame(props.shot.id, f);
  ev.target.value = "";  // 允许重复选同一张
}
const videoJob = computed(() => props.shot.videoJob || null);
const videoBusy = computed(() => !!videoJob.value
  && (videoJob.value.status === "running" || videoJob.value.status === "queued"));
const videoLabel = computed(() => videoBusy.value
  ? ((videoJob.value.stage || "生成中") + (videoJob.value.progress ? " " + videoJob.value.progress + "%" : ""))
  : "");
</script>

<template>
  <div class="shot" :class="{ active: shot.id === S.activeId, locked: shot.locked }" :data-id="shot.id" @click="onCardClick">
    <span class="grab" draggable="true" title="按住拖动排序">⠿</span>
    <input type="checkbox" class="check" :data-check="shot.id" :checked="S.selected.includes(shot.id)"
      aria-label="选择这一镜" @change="toggleCheck($event, shot.id)">
    <div class="main">
      <div class="top">
        <span class="code">{{ shot.code }}</span>
        <span v-if="shot.ai" class="ai-mark" title="由大模型生成">AI</span>
        <span class="scene-tag">{{ shot.sceneLabel }}</span>
        <span class="kind">{{ E.kindName(shot.kind) }}</span>
        <select class="size-sel" data-field="size" :data-id="shot.id" aria-label="景别">
          <option v-for="z in E.SIZES" :key="z" :value="z" :selected="z === shot.size">{{ z }}</option>
        </select>
        <span class="dur"><input type="number" min="1" max="30" step="0.5" data-field="duration"
          :data-id="shot.id" :value="shot.duration" aria-label="时长">s</span>
        <span v-if="edited()" class="edited-mark">已手改</span>
        <span v-if="shot.originCode !== shot.code" class="chip" title="原始镜号">{{ shot.originCode }}</span>
        <span v-if="shot.patched" class="chip warn" title="AI 漏了这句台词或动作，已按剧本原文自动补镜">补</span>
        <button class="detail-toggle" :class="{ on: open }" @click.stop="open = !open"
          :title="open ? '收起 AI 分镜描述卡' : '展开 AI 分镜描述卡'">
          分镜卡 <b>{{ filled }}/9</b>
        </button>
      </div>
      <div v-if="cast.length || sceneAsset || stale" class="cast-row">
        <span v-for="(c, i) in cast" :key="c.id" class="cast-chip" :data-cast="c.name"
          :title="'参考图槽位 character' + (i + 1)"><i>{{ i + 1 }}</i>{{ c.name }}</span>
        <span v-if="sceneAsset" class="cast-chip scene" :title="'参考图槽位 character' + (cast.length + 1)">
          <i>{{ cast.length + 1 }}</i>{{ sceneAsset.name }}
        </span>
        <template v-if="stale">
          <span class="chip warn" :data-stale="shot.id" title="角色设定改过了，提示词还是旧的">设定已改</span>
          <button class="mini" :data-refresh="shot.id" title="按最新设定刷新这一镜的提示词"
            @click.stop="refreshOneShot(shot.id)">↻</button>
        </template>
      </div>
      <textarea class="cell visual" rows="2" data-field="visual" :data-id="shot.id"
        :value="shot.visual" placeholder="画面描述"></textarea>
      <div v-if="videoBusy" class="video-job" data-video-job>▶ {{ videoLabel }}</div>
      <video v-else-if="shot.video" class="video-prev" data-video-prev
        :src="shot.video" controls preload="metadata"></video>
      <span class="cell-label">台词</span>
      <input class="cell dialogue" data-field="dialogue" :data-id="shot.id" :value="shot.dialogue" placeholder="这一镜的台词（可留空）">
      <span class="cell-label">备注</span>
      <input class="cell notes" data-field="notes" :data-id="shot.id" :value="shot.notes" placeholder="运镜 / 音效 / 剪辑提示">
      <div v-if="open" class="detail-card" @click.stop>
        <div class="detail-head">AI 分镜描述卡 <span>逐项可改 · 改动会进撤销栈 · 空项导出时留空</span></div>
        <div class="detail-grid">
          <label v-for="k in E.DETAIL_FIELDS" :key="k">
            <span>{{ E.DETAIL_LABELS[k] }}</span>
            <input class="cell detail-input" :data-field="'detail.' + k" :data-id="shot.id"
              :value="detail[k]" placeholder="待补充">
          </label>
        </div>
      </div>
    </div>
    <div class="ops">
      <button class="mini" :class="{ on: shot.locked }" data-op="lock" :data-id="shot.id"
        :title="shot.locked ? '解锁（批量重生成会动它）' : '锁定（批量重生成跳过它）'" @click.stop="toggleShotLock(shot.id)">🔒</button>
      <button class="mini" data-op="up" :data-id="shot.id" title="上移" @click.stop="handleShotOp('up', shot.id)">↑</button>
      <button class="mini" data-op="down" :data-id="shot.id" title="下移" @click.stop="handleShotOp('down', shot.id)">↓</button>
      <button class="mini" data-op="regen" :data-id="shot.id" title="重生成这一镜" @click.stop="handleShotOp('regen', shot.id)">↻</button>
      <input ref="frameInput" type="file" accept="image/*" hidden @change="onFrameFile" />
      <button class="mini" data-op="frame" :data-id="shot.id" :class="{ on: frameSet }"
        :title="frameSet ? ('首帧：' + shot.frameImage) : '设首帧：上传一张图，▶ 直接用它生成视频'"
        @click.stop="pickFrame()">🖼</button>
      <button class="mini" data-op="video" :data-id="shot.id" :disabled="videoBusy"
        :title="shot.video ? '重新生成视频（首帧 → i2v）' : '生成视频（缺首帧自动先文生一张，再图生视频）'"
        @click.stop="startShotVideo(shot.id)">▶</button>
      <button class="mini del" data-op="delete" :data-id="shot.id" title="删除" @click.stop="handleShotOp('delete', shot.id)">×</button>
    </div>
  </div>
</template>
