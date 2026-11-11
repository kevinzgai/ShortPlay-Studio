<script setup>
import {
  S, E, ui, stats, issueCounts, hasFixable,
  applyFix, fixAll, toggleScene, goStep, toast, planStep
} from "../stores/studio.js";
import EpisodePlan from "./EpisodePlan.vue";
import AssetPanel from "./AssetPanel.vue";
import ExportMenu from "./ExportMenu.vue";

function gotoScript() {
  goStep(1);
  toast("已回到剧本，改完再点「下一步」", "ok");
}
</script>

<template>
  <div class="view-head row" style="align-items:flex-end">
    <div>
      <h1>剧本拆好了 · 确认分集方案</h1>
      <p class="sub">先看分集怎么切、场次和角色有没有漏，体检问题在这里补。确认后到第 3 步排分镜，最后第 4 步定妆。</p>
    </div>
    <div class="spacer"></div>
    <ExportMenu />
  </div>

  <div class="stat-grid">
    <div class="stat"><div class="v">{{ stats.scenes }}</div><div class="k">场次</div></div>
    <div class="stat"><div class="v">{{ stats.characters }}</div><div class="k">角色 · {{ S.parsed.characters.slice(0, 3).join("、") || "无" }}</div></div>
    <div class="stat"><div class="v">{{ stats.lines }}</div><div class="k">对白</div></div>
    <div class="stat"><div class="v">{{ stats.actions }}</div><div class="k">动作 / 画面描述</div></div>
  </div>

  <!-- S3：剧本改过但没点重算 → 明确告诉用户当前方案基于旧稿（重算入口在分集方案卡片头部，不重复放按钮） -->
  <div v-if="S.steps.plan.status === 'stale' && S.episodes.length" id="plan-stale-bar"
    class="card pad plan-stale-bar">
    <span>⚠️ 剧本改过，现有分集基于旧稿（共 {{ S.episodes.length }} 集）。不重算就沿用旧方案。</span>
  </div>

  <!-- S3：分集只由按钮产出；有方案时入口在「分集方案」卡片头部，这里只兜空状态 -->
  <EpisodePlan v-if="S.episodes.length" />
  <div v-else id="plan-empty" class="card pad plan-empty">
    <span>还没有分集方案。</span>
    <button class="btn sm primary" id="plan-step-btn" :disabled="S.planBusy" @click="planStep()">
      <span v-if="S.planBusy" class="spinner"></span>
      {{ S.planBusy ? "生成中…" : "生成分集" }}
    </button>
    <span class="muted" style="font-size:12px">AI 优先，模型不可用或失败时降级本地规则；确认后第 3 步按集排镜头</span>
  </div>

  <div class="card pad" style="margin-bottom:18px">
    <div class="row" style="margin-bottom:14px">
      <h2>剧本体检</h2>
      <span v-if="S.issues.length" class="chip" :class="issueCounts.errs ? 'err' : 'warn'">{{ issueCounts.errs }} 处需处理 · {{ issueCounts.warns }} 项建议</span>
      <span v-else class="chip ok">全部通过</span>
      <div class="spacer"></div>
      <button v-if="hasFixable" class="btn sm" id="fix-all" @click="fixAll">一键补全可自动处理的项</button>
    </div>

    <div v-if="S.issues.length" class="issue-list">
      <div v-for="(i, idx) in S.issues" :key="idx" class="issue" :class="i.level">
        <span class="dot"></span>
        <div class="body"><div class="t">{{ i.title }}</div><div class="d">{{ i.detail }}</div></div>
        <div class="act">
          <template v-if="i.fix && i.fix.type === 'input'">
            <input class="fix-input" :data-fix-input="idx" :placeholder="i.fix.placeholder || '填写内容'"
              :value="ui.fixInputs[idx] || ''" @input="ui.fixInputs[idx] = $event.target.value">
            <button class="btn sm" :data-fix="idx" @click="applyFix(idx)">{{ i.fix.label }}</button>
          </template>
          <button v-else-if="i.fix" class="btn sm" :data-fix="idx" @click="applyFix(idx)">{{ i.fix.label }}</button>
          <button v-else class="btn quiet" data-goto-script @click="gotoScript">回剧本里改 →</button>
        </div>
      </div>
    </div>
    <div v-else class="all-clear">✓ 场次、角色、场景与对白都识别完整，可以直接生成分镜了。</div>
    <div class="inline-note">场景地点需要你确认才算准确；其余缺失项都能一键补全，补全会写回剧本文本，随时可撤销。</div>
  </div>

  <div class="inline-note" style="margin-bottom:8px">
    这一层的资产清单用来核对 AI 拆得全不全（漏人漏物在这里补）；真正出图定妆在制作阶段的「资产定妆」。
  </div>
  <AssetPanel style="margin-bottom:18px" />

  <div class="card pad" style="margin-bottom:18px">
    <div class="row" style="margin-bottom:12px">
      <h2>拆解结果</h2><span class="muted" style="font-size:12px">按剧情顺序 · 点开场次看逐条内容</span>
    </div>
    <div id="scene-list">
      <div v-for="s in S.parsed.scenes" :key="s.order" class="scene-acc">
        <button class="scene-head" :data-scene="s.order" @click="toggleScene(s.order)">
          <span class="no">{{ s.no }}</span>
          <span class="title">{{ E.sceneLabel(s) }}</span>
          <span class="spacer"></span>
          <span class="chip">{{ s.intExt || "未标内外景" }}</span>
          <span class="chip">{{ s.lines.length }} 句对白</span>
          <span class="chip">{{ s.actions.length }} 条动作</span>
          <span class="muted" style="font-size:11px">▾</span>
        </button>
        <div class="scene-detail" :class="{ hidden: !ui.openScenes[s.order] }" :data-scene-detail="s.order">
          <h4>出场角色</h4>
          <ul><li v-if="s.characters.length">{{ s.characters.join("、") }}</li><li v-else class="muted">未识别到角色</li></ul>
          <h4>对白</h4>
          <ul>
            <li v-for="(l, li) in s.lines" :key="li"><span class="speaker">{{ l.speaker }}{{ l.stage ? "（" + l.stage + "）" : "" }}：</span>{{ l.text }}</li>
            <li v-if="!s.lines.length" class="muted">本场没有对白</li>
          </ul>
          <h4>动作 / 画面描述</h4>
          <ul>
            <li v-for="(a, ai) in s.actions" :key="ai">{{ a.text }}</li>
            <li v-if="!s.actions.length" class="muted">本场没有动作描述</li>
          </ul>
        </div>
      </div>
    </div>
  </div>

  <div class="cta-row">
    <button class="btn" id="back-1" @click="goStep(1)">← 返回改剧本</button>
    <button class="btn primary lg" id="generate" @click="goStep(3)">去第 3 步逐集排分镜 →</button>
    <span class="cta-note">确认分集后进第 3 步：每集一个闸门，点一次只生成一集，出完即停；失败可单独重试，再去第 4 步定妆</span>
  </div>
</template>
