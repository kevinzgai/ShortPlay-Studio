<script setup>
import { ref, computed } from "vue";
import {
  S, ui, liveStats, aiEnabledUi, setInputTab, onScriptInput, loadSample, loadProblem, loadGuihun,
  clearScript, goStep2, readScriptFile, adaptNovel, normalizeNow, restoreRawSource,
  sourceSpec, sourceKind, KIND_LABEL
} from "../stores/studio.js";

const SCRIPT_PLACEHOLDER = "把剧本文字粘贴到这里…\n\n支持这些写法（混用也行）：\n《片名》\n第1场 外景 · 便利店门口 · 夜\n△ 雨下得很急。\n林晚：又是一整夜的雨。\n陈默（压低声音）：你不是第一次来这儿。";
const dragover = ref(false);

/* 建议动作：按稿件类型给唯一一条最省力的路 */
const advice = computed(() => {
  const k = sourceKind.value;
  if (k === "scene") return {
    k, title: "格式已合规", act: "", btn: "",
    text: "已经有场次头，AI 能直接按场拆解，不需要再加工。"
  };
  if (k === "simple") return {
    k, title: "缺场次头 · 简易剧本", act: "local", btn: "本地补场次头",
    text: "对白已经标了说话人，只是没有「第N场」。按空行补场次号就行，不调 AI、不改一个字。"
  };
  if (k === "prose") return {
    k, title: "小说 / 散文体", act: "ai", btn: "AI 忠实转写",
    text: "没有场次行、台词散在叙述里，直接拆只能得到 1 场 0 句对白。先让 AI 转写成场次剧本。"
  };
  return { k: "empty", title: "还没有稿子", act: "", btn: "", text: "粘贴文字或上传 .txt / .md / .docx 开始。" };
});

function runAdvice() {
  if (advice.value.act === "local") normalizeNow();
  else if (advice.value.act === "ai") adaptNovel();
}

const pct = (a, b) => (b ? Math.round(a / b * 100) : 0);
const report = computed(() => S.normReport || null);

function chooseFile() { document.querySelector("#file-input").click(); }
function onDragEnter(e) { e.preventDefault(); dragover.value = true; }
function onDragOver(e) { e.preventDefault(); dragover.value = true; }
function onDragLeave(e) { if (!e.currentTarget.contains(e.relatedTarget)) dragover.value = false; }
function onDrop(e) {
  e.preventDefault(); dragover.value = false;
  readScriptFile(e.dataTransfer.files[0]);
}
</script>

<template>
  <div class="step1-wrap">
    <div class="step1-main">
      <div class="view-head">
        <h1>改剧本，把它改成能拍的场次剧本</h1>
        <p class="sub">粘进来的可能是一篇小说、一份微信文章、一个 Word 稿子——这一步负责把它们变成 AI 能读懂的标准剧本：场次头、说话人、动作分行。<b>不上传原件，内容只在这台电脑</b>。</p>
      </div>

      <div class="card script-card">
        <div class="card-top">
          <div class="tabs" id="input-tabs">
            <button class="tab" :class="{ active: S.inputTab === 'paste' }" data-tab="paste" @click="setInputTab('paste')">粘贴文字</button>
            <button class="tab" :class="{ active: S.inputTab === 'file' }" data-tab="file" @click="setInputTab('file')">上传文件</button>
          </div>
          <div class="spacer"></div>
          <span v-if="ui.importBusy" class="chip">正在解析文件…</span>
          <span v-else-if="S.script" class="kind-chip" :class="'k-' + sourceKind">{{ KIND_LABEL[sourceKind] }}</span>
          <span v-else class="chip indigo">参数已自动配好</span>
        </div>

        <div id="input-paste" :class="{ hidden: S.inputTab !== 'paste' }">
          <textarea class="script-area" id="script-input" spellcheck="false"
            :placeholder="SCRIPT_PLACEHOLDER" :value="S.script" @input="onScriptInput"></textarea>
        </div>

        <div id="input-file" :class="{ hidden: S.inputTab !== 'file' }" style="padding:18px">
          <div class="drop-hint" id="drop-zone" :class="{ dragover }" @click="chooseFile"
            @dragenter="onDragEnter" @dragover="onDragOver" @dragleave="onDragLeave" @drop="onDrop">
            把 .txt / .md / .docx 拖到这里，或点击选择文件<br>
            <small>.docx 只取正文文字、自动跳过页眉页脚与图片；文件不上传，也不留在磁盘上</small>
          </div>
          <input type="file" id="file-input" accept=".txt,.md,.markdown,.text,.docx,text/plain" hidden
            @change="readScriptFile($event.target.files[0])">
          <div class="file-note">
            老式 <code>.doc</code> / <code>.wps</code> 是二进制格式读不了，先在 Word 里「另存为」<code>.docx</code> 或 <code>.txt</code>。PDF 请复制文字粘贴。
          </div>
        </div>

        <div class="script-foot">
          <div class="live-stats" id="live-stats">
            <span><b>{{ liveStats.chars }}</b> 字</span>
            <template v-if="liveStats.p">
              <span><b>{{ liveStats.p.stats.scenes }}</b> 场</span>
              <span><b>{{ liveStats.p.stats.characters }}</b> 角色</span>
              <span><b>{{ liveStats.p.stats.lines }}</b> 句对白</span>
              <span><b>{{ liveStats.p.stats.actions }}</b> 条动作</span>
            </template>
            <span v-else class="muted">还没识别到剧本</span>
          </div>
          <div class="spacer"></div><span>内容只存在这台电脑</span>
        </div>
      </div>

      <!-- 规范度：这份稿子离「AI 能正确拆解」还差什么 -->
      <div v-if="S.script" class="spec-card" id="spec-card">
        <div class="spec-head">
          <b>规范度</b>
          <span class="spec-score" :class="{ full: sourceSpec.ok === sourceSpec.items.length }">
            {{ sourceSpec.ok }} / {{ sourceSpec.items.length }}
          </span>
          <span class="spec-bar"><i :style="{ width: sourceSpec.score + '%' }"></i></span>
          <span class="spec-note">{{ sourceSpec.score >= 100 ? "五项都齐了，可以直接交给 AI" : "不齐也能生成，只是拆解精度会打折" }}</span>
        </div>
        <ul class="spec-list">
          <li v-for="it in sourceSpec.items" :key="it.key" :class="it.state" :data-spec="it.key">
            <i></i><b>{{ it.label }}</b><span>{{ it.detail }}</span>
          </li>
        </ul>
      </div>

      <!-- 建议动作：按类型只给一条最省力的路 -->
      <div v-if="S.script" class="norm-bar" :class="'k-' + advice.k"
        :id="sourceKind === 'prose' ? 'novel-tip' : undefined">
        <div class="nb-txt">
          <b>{{ advice.title }}</b>
          <span>{{ advice.text }}</span>
        </div>
        <button v-if="advice.act" class="btn sm primary" :id="advice.act === 'ai' ? 'adapt-novel' : 'normalize-local'"
          @click="runAdvice" :disabled="S.aiBusy || (advice.act === 'ai' && !aiEnabledUi)">
          {{ S.aiBusy ? "处理中…" : advice.btn }}
        </button>
        <span v-else class="nb-ok">✓ 可以直接往下走</span>
      </div>

      <!-- 规范化结果：可验证的覆盖率，而不是「已处理」三个字 -->
      <div v-if="report" class="norm-report" id="norm-report">
        <div class="nr-h">
          <b>{{ report.mode === "ai" ? "AI 忠实转写完成" : "已本地补场次头" }}</b>
          <span>{{ report.scenes }} 场</span>
          <span v-if="report.fromChars">{{ report.fromChars }} 字 → {{ report.toChars }} 字</span>
          <div class="spacer"></div>
          <button v-if="S.rawSource" class="mini" id="restore-raw" @click="restoreRawSource">还原原文</button>
        </div>
        <div v-if="report.mode === 'ai'" class="nr-grid">
          <div>
            <b>{{ report.sentencesCovered }}<em>/{{ report.sentencesTotal }}</em></b>
            <span>句子逐字保留 · {{ pct(report.sentencesCovered, report.sentencesTotal) }}%</span>
          </div>
          <div>
            <b>{{ report.quotesCovered }}<em>/{{ report.quotesTotal }}</em></b>
            <span>引语逐字保留 · {{ pct(report.quotesCovered, report.quotesTotal) }}%</span>
          </div>
          <div>
            <b>{{ report.scenes }}</b>
            <span>场次头</span>
          </div>
        </div>
        <div v-else class="nr-local">
          只补了场号，内外景 / 地点 / 时间没有编——编错会污染参考图和提示词，缺的去第 2 步体检卡一键补。
        </div>
        <ul v-if="(report.warnings || []).length" class="nr-warn">
          <li v-for="(w, i) in report.warnings" :key="i">{{ w }}</li>
        </ul>
      </div>

      <div class="quick-row">
        <button class="btn sm" id="load-sample" @click="loadSample">载入完整示例剧本</button>
        <button class="btn sm" id="load-problem" @click="loadProblem">试试「待补全」示例</button>
        <button class="btn sm" id="load-guihun" @click="loadGuihun">载入《鬼婚，逃命》</button>
        <button class="btn sm" id="clear-script" @click="clearScript">清空</button>
        <span class="cta-note">完整示例：《雨夜便利店》4 场 · 2 角色 · 约 100 秒成片</span>
      </div>

      <div class="cta-row">
        <button class="btn primary lg" id="go-step2" @click="goStep2">去分集 →</button>
        <span class="cta-note">下一步只看分集方案、确认切法；分镜在第 3 步按集生成，不再一把梭</span>
      </div>
    </div>

    <aside class="step1-side">
      <div class="how">
        <div class="how-item">
          <div class="n">规范剧本只有 4 种行</div>
          <pre class="fmt">《片名》

第1场 外景 · 便利店门口 · 夜
△ 雨下得很急。
林晚：又是一整夜的雨。
陈默（压低声音）：你不是第一次来。</pre>
          <p>片名、场次头、<code>角色（提示）：台词</code>、<code>△ 动作</code>。四种行写对了，后面每一步都稳。</p>
        </div>
        <div class="how-item"><div class="n">三种稿子 · 三条路</div><p><b>已有场次头</b>：直接拆解，零成本。<b>简易剧本</b>（有对白没场次头）：本地按空行补场号，不改字。<b>小说 / 散文</b>：AI 忠实转写，模型只判断「哪几句属于哪一场」，正文逐字拼回。</p></div>
        <div class="how-item"><div class="n">转写为什么可信</div><p>不让模型重写长文（会被 max_tokens 截断）。它只输出结构 JSON，正文由原句拼装，转完再按句比对：句子保留率、引语保留率都列出来，低于 90% 会直接告警。</p></div>
        <div class="how-item"><div class="n">下一步做什么</div><p>格式齐了就去「分集」，看分集方案、场次清单和体检问题；确认后第 3 步排镜头，分镜表就是完整交付物，出片可选。</p></div>
      </div>
    </aside>
  </div>
</template>
