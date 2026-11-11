<script setup>
/* 制作阶段 · 第 1 步（工作区 3）：分镜表
   资产定妆在下一步，这里只负责镜头本身：画面 / 景别 / 时长 / 台词 / 备注。 */
import { computed } from "vue";
import {
  S, totalDuration, staleMsg, visibleShots, episodeTabs, shotsNeedRecalc,
  shotGates, shotGateRunning, storyboardStep,
  allSelected, someSelected, aiRedo, setActiveEpisode, setView, selectAll,
  printPage, doGenerate, goStep, regenBatch,
  delSelected, insertShot
} from "../stores/studio.js";
import ShotCard from "./ShotCard.vue";
import ShotsTable from "./ShotsTable.vue";
import PreviewPanel from "./PreviewPanel.vue";
import ExportMenu from "./ExportMenu.vue";

const showAiStatus = computed(() => S.episodes.length > 0 || S.aiSource === "local");
const degradedNos = computed(() => S.aiDegraded.map((d) => d.no).join("、"));

function hasPic(a) { return !!(a && (a.refImage || (a.genImages || []).length)); }
const assetStat = computed(() => {
  const a = S.assets || {};
  const all = [].concat(a.characters || [], a.scenes || [], a.props || []);
  return { total: all.length, ready: all.filter(hasPic).length };
});
const assetTip = computed(() => {
  const s = assetStat.value;
  if (!s.total) return "本片还没有资产，去第 4 步定妆页从剧本分解";
  if (s.ready === s.total) return "资产已全部定妆";
  return "还有 " + (s.total - s.ready) + " 个资产没定妆，参考图槽位会空着";
});

/* S4：每集一个闸门，按钮三态；没有任何「剩余」批量入口。 */
const SG_STATUS = { idle: "未生成", running: "生成中…", ready: "已生成", stale: "需重算", failed: "生成失败" };
function sgStatus(s) { return SG_STATUS[s] || "未生成"; }
function sgButton(s) {
  if (s === "running") return "生成中…";
  if (s === "ready") return "重跑本集";
  if (s === "failed") return "重试";
  if (s === "stale") return "重排本集";
  return "生成本集";
}
</script>

<template>
  <div class="view-head row" style="align-items:flex-end">
    <div>
      <h1>{{ S.meta.title || "短剧" }} · 分镜表</h1>
      <p class="sub">点文字直接改，拖左侧手柄排序；改动都会自动保存，也能随时撤销。</p>
    </div>
    <div class="spacer"></div>
    <span v-if="S.episodes.length" class="chip indigo">{{ S.episodes.length }} 集</span>
    <span class="chip">{{ S.shots.length }} 镜</span>
    <span class="chip">约 {{ totalDuration }} 秒</span>
    <span class="chip">{{ S.config.aspect }}</span>
  </div>

  <div class="shot-asset-bar" :class="{ ready: assetStat.total && assetStat.ready === assetStat.total }">
    <span class="sab-dot" aria-hidden="true"></span>
    <span class="sab-txt"><b>资产</b> {{ assetStat.ready }} / {{ assetStat.total }} 已定妆</span>
    <span class="sab-note">{{ assetTip }}</span>
    <button class="btn sm quiet" id="to-assets" @click="goStep(4)">去定妆 / 改设定 →</button>
  </div>

  <!-- S4：逐集闸门。一次点击只排一集，出完即停；失败只影响这一集 -->
  <div id="shot-gates" class="card pad" style="margin-bottom:14px">
    <div class="row">
      <b>逐集闸门</b>
      <span class="muted" style="font-size:11px">一次点击只排一集，出完即停；失败只影响这一集</span>
      <div class="spacer"></div>
      <span v-if="S.episodes.length > 8" class="chip warn">需逐集确认，共 {{ S.episodes.length }} 集</span>
    </div>
    <div class="sg-list">
      <div v-for="g in shotGates" :key="g.key" class="sg-item" :class="'sg-' + g.status"
        :data-gate="g.key" :data-gate-status="g.status">
        <span class="sg-dot" aria-hidden="true"></span>
        <span class="sg-name">{{ g.label }}</span>
        <span class="sg-status">{{ sgStatus(g.status) }}</span>
        <span class="sg-count">{{ g.count }} 镜</span>
        <button class="btn sm" :class="{ primary: g.status === 'idle' || g.status === 'stale' }"
          :data-shot-gate="g.key" :disabled="shotGateRunning"
          @click="storyboardStep(g.key)">{{ sgButton(g.status) }}</button>
        <div v-if="g.status === 'failed' && g.error" class="sg-error">{{ g.error }}</div>
      </div>
    </div>
  </div>

  <!-- S3：分集改过 → 所有集需重算，但镜头仍在表里 -->
  <div v-if="shotsNeedRecalc" id="plan-recalc-bar" class="card pad"
    style="margin-bottom:14px;background:var(--warn-soft);border-color:var(--warn-line)">
    <div class="row"><span>⚠️ 分集方案已变更：全部 {{ S.episodes.length }} 集需重算；
      已生成的 {{ S.shots.length }} 个镜头仍在表里，逐集重排后才会归位。</span></div>
  </div>

  <div v-if="staleMsg" class="card pad" style="margin-bottom:14px;background:var(--warn-soft);border-color:#f0e2c4">
    <div class="row"><span>⚠️ {{ staleMsg }}</span><div class="spacer"></div>
      <button class="btn sm" id="regenerate-from-script" @click="doGenerate('force')">按当前剧本 / 设置重排</button></div>
  </div>

  <div v-if="showAiStatus" class="ai-status" :class="{ local: S.aiSource !== 'ai' }">
    <template v-if="S.aiSource !== 'ai'">
      <span v-if="S.aiSource === 'local'">⚙️ 当前分镜由<b>离线规则引擎</b>生成</span>
      <span v-else-if="S.episodeSource === 'ai'">📋 已有 AI 分集方案，分镜尚未按 AI 生成</span>
      <span v-else>⚙️ 当前使用本地规则分集</span>
      <span v-if="S.llmAvailable" class="spacer"></span>
      <button v-if="S.llmAvailable" class="btn sm" data-ai-redo @click="aiRedo">改用 AI 重新分集分镜</button>
    </template>
    <template v-else>
      <span>✨ <b>AI 生成</b> · {{ S.aiModel || "大模型" }} · {{ S.episodes.length }} 集</span>
      <span v-if="S.aiDegraded.length" class="warn-bit">⚠️ 第 {{ degradedNos }} 集模型失败，已用本地规则补齐</span>
      <span v-if="S.aiWarnings.length" class="warn-bit">⚠️ {{ S.aiWarnings.length }} 条台词建议人工核对（见对应镜头备注）</span>
      <span class="spacer"></span>
      <button class="btn sm" data-ai-redo @click="aiRedo">AI 重新分集分镜</button>
    </template>
  </div>

  <div class="workspace" :class="{ solo: S.view === 'table' }">
    <div>
      <div v-if="S.episodes.length" class="episode-filter">
        <span class="ef-label">分集</span>
        <button class="ep-tab" :class="{ active: String(S.activeEpisode) === 'all' }" data-episode="all" @click="setActiveEpisode('all')">
          全部<span class="ep-count">{{ S.shots.length }}</span>
        </button>
        <button v-for="ep in episodeTabs" :key="ep.no" class="ep-tab"
          :class="{ active: String(S.activeEpisode) === String(ep.no), 'needs-recalc': ep.stale }"
          :data-episode="ep.no" :data-recalc="ep.stale ? '1' : null"
          :data-shot-status="ep.status"
          :title="ep.stale ? '需重算' : ''" @click="setActiveEpisode(ep.no)">
          <span class="ep-gate-dot" :class="'ep-gate-' + ep.status" aria-hidden="true"></span>
          {{ ep.label }}<span class="ep-count">{{ ep.count }}</span>
        </button>
      </div>

      <div class="toolbar">
        <div class="tabs" id="view-tabs">
          <button class="tab" :class="{ active: S.view === 'card' }" data-view="card" @click="setView('card')">卡片</button>
          <button class="tab" :class="{ active: S.view === 'table' }" data-view="table" @click="setView('table')">表格</button>
        </div>
        <div class="divider"></div>
        <label class="btn quiet" style="cursor:pointer">
          <input type="checkbox" id="select-all"
            :checked="allSelected" :indeterminate.prop="someSelected" @change="selectAll">全选
        </label>
        <span class="muted" id="sel-count" style="font-size:12px">已选 {{ S.selected.length }}</span>
        <div class="divider"></div>
        <button class="btn sm" id="regen-batch" @click="regenBatch">批量重生成</button>
        <button class="btn sm" id="insert-shot" @click="insertShot">+ 插入镜头</button>
        <button class="btn sm danger" id="del-selected" :disabled="!S.selected.length" @click="delSelected">删除所选</button>
        <div class="spacer"></div>
        <ExportMenu />
        <button class="btn sm" id="print-btn" @click="printPage">打印</button>
      </div>

      <div id="shot-container">
        <div v-if="visibleShots.length && S.view === 'card'" class="shot-list">
          <ShotCard v-for="s in visibleShots" :key="s.id" :shot="s" />
        </div>
        <ShotsTable v-else-if="visibleShots.length" />
        <div v-else-if="S.shots.length" class="empty">
          <div class="big">▤</div><p>这一集还没有镜头，切到「全部」看看其它集。</p>
          <button class="btn" data-episode="all" @click="setActiveEpisode('all')">查看全部</button>
        </div>
        <div v-else class="empty">
          <div class="big">▤</div><p>还没有分镜。先在第 2 步确认分集方案，再回来排镜头。</p>
          <button class="btn primary" id="empty-back" @click="goStep(2)">去确认分集</button>
        </div>
      </div>
    </div>

    <aside class="preview card" :class="{ hidden: S.view === 'table' }"><div class="pad" id="preview-body"><PreviewPanel /></div></aside>
  </div>

  <div class="cta-row">
    <button class="btn" id="back-2" @click="goStep(2)">← 回分集方案</button>
    <button class="btn" id="back-1b" @click="goStep(1)">改剧本</button>
    <button class="btn primary" id="go-assets" @click="goStep(4)">去资产定妆 →</button>
    <span class="cta-note">Ctrl+Z 撤销 · Ctrl+Shift+Z 重做 · 数据只存在本机</span>
  </div>
</template>
