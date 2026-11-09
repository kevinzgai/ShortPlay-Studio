<script setup>
/* 制作阶段 · 第 1 步：资产定妆
   把角色 / 场景 / 道具的参考图在这一层定死，分镜的画面描述与参考图槽位
   都从这里取。资产实体全片共享，改一次所有引用它的分镜同步生效。 */
import { computed } from "vue";
import { S, goStep, doGenerate, aiEnabledUi } from "../stores/studio.js";
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
const hasShots = computed(() => (S.shots || []).length > 0);
</script>

<template>
  <div class="view-head row" style="align-items:flex-end">
    <div>
      <h1>资产定妆</h1>
      <p class="sub">先把角色、场景、道具的参考图定下来。分镜的画面描述和参考图槽位都读这一层，改一次全片同步。</p>
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
    <div class="asset-strip-note">
      定妆 = 有参考图或生成图。上传的参考图保留原图不压缩；生成的图可设为主图，导出时进参考图槽位。
    </div>
  </div>

  <AssetPanel />

  <div class="cta-row">
    <button class="btn" id="back-2" @click="goStep(2)">← 回看拆解结果</button>
    <button v-if="hasShots" class="btn primary lg" id="go-step4" @click="goStep(4)">去排分镜 →</button>
    <button v-else class="btn primary lg" id="asset-generate" @click="doGenerate(true)">
      {{ aiEnabledUi ? "生成 " + (S.episodes.length || "") + " 集分镜 →" : "生成分镜 →" }}
    </button>
    <span class="cta-note">
      {{ hasShots ? "分镜表里可以逐镜检查画面、台词与参考图槽位，随时回到这一步改设定" : "还没生成分镜，定妆后直接生成即可" }}
    </span>
  </div>
</template>
