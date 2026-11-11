<script setup>
/* 制作阶段 · 第 2 步（工作区 4）：资产定妆
   把角色 / 场景 / 道具的参考图在这一层定死，分镜的画面描述与参考图槽位
   都从这里取。资产实体全片共享，改一次所有引用它的分镜同步生效。 */
import { computed } from "vue";
import { S, goStep, framesGate, regenFrames } from "../stores/studio.js";
import AssetPanel from "./AssetPanel.vue";
import ExportMenu from "./ExportMenu.vue";

function hasPic(a) { return !!(a && (a.refImage || (a.genImages || []).length)); }

const packs = computed(() => {
  const a = S.assets || {};
  return [
    ["character", "角色", a.characters],
    ["scene", "场景", a.scenes],
    ["prop", "道具", a.props]
  ].map(([k, label, list]) => {
    const arr = list || [];
    const ready = arr.filter(hasPic).length;
    return { k, label, total: arr.length, ready };
  });
});
const totalCount = computed(() => packs.value.reduce((n, p) => n + p.total, 0));
const readyCount = computed(() => packs.value.reduce((n, p) => n + p.ready, 0));
const allReady = computed(() => totalCount.value > 0 && readyCount.value === totalCount.value);
</script>

<template>
  <div class="view-head row" style="align-items:flex-end">
    <div>
      <h1>资产定妆</h1>
      <p class="sub">先把角色、场景、道具的参考图定下来。分镜的画面描述和参考图槽位都读这一层，改一次全片同步。资产清单以分镜引用为准，剧本只兜底。</p>
    </div>
    <div class="spacer"></div>
    <span class="chip" :class="allReady ? 'ok' : ''">{{ readyCount }} / {{ totalCount }} 已定妆</span>
    <ExportMenu />
  </div>

  <div class="asset-strip">
    <div v-for="p in packs" :key="p.k" class="asset-strip-item" :class="{ done: p.total && p.ready === p.total }">
      <b>{{ p.label }}</b>
      <span>{{ p.ready }} / {{ p.total }}</span>
      <i>{{ !p.total ? "无" : (p.ready === p.total ? "全部就绪" : "差 " + (p.total - p.ready) + " 张") }}</i>
    </div>
    <div class="asset-strip-note" id="asset-source-note">
      定妆 = 有参考图或生成图。上传的参考图保留原图不压缩；生成的图可设为主图，导出时进参考图槽位。
      资产清单以分镜引用为准，剧本只兜底：每条资产都标了「出现在几个镜头 / 第几集」；标「兜底」的是剧本里写过、当前没有镜头引用的资产，不会被自动删除。
    </div>
  </div>

  <AssetPanel />

  <!-- S6：首帧提示词必须在资产定妆之后生成，第 3 步只有只读预览。 -->
  <div id="frames-gate" class="card pad" style="margin-bottom:14px">
    <div class="fg-head">
      <b>首帧提示词 · 定妆后生成</b>
      <span class="chip" :class="S.frames.length ? 'ok' : ''">
        {{ S.frames.length ? S.frames.length + " 镜已生成" : "尚未生成" }}
      </span>
    </div>
    <p class="fg-note" id="frames-gate-reason">
      {{ framesGate.ok ? "资产齐了：" + framesGate.dressed + " 条资产已定妆，可生成 " +
          framesGate.shots + " 镜的首帧提示词" : framesGate.reason }}
    </p>
    <div class="fg-row">
      <button class="btn primary" id="generate-frames" :disabled="!framesGate.ok"
        @click="regenFrames(false)">
        {{ S.frames.length ? "重新生成" : "生成" }} {{ framesGate.shots }} 镜首帧提示词 →
      </button>
      <span class="fg-note">第 3 步只有只读预览，不会发 frames 请求；这里生成时会把已定妆资产的参考图槽位写进提示词。</span>
    </div>
    <div v-if="S.frames.length && S.frames[0].refSlots && S.frames[0].refSlots.length"
      id="frames-slots" class="fg-slots">
      <span v-for="(s, i) in S.frames[0].refSlots" :key="i" class="chip" :class="s.ready ? 'ok' : ''">
        [{{ i + 1 }}] {{ s.code }} {{ s.name }} · {{ s.ready ? "已定妆" : "待定妆" }}
      </span>
    </div>
  </div>

  <div class="cta-row">
    <button class="btn" id="back-3" @click="goStep(3)">← 回分镜表</button>
    <button class="btn" id="back-2" @click="goStep(2)">回分集方案</button>
    <span class="cta-note">这一页的参考图全片共享：改一次，第 3 步里所有引用它的镜头同步生效</span>
  </div>
</template>
