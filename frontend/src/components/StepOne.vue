<script setup>
import { ref, computed } from "vue";
import {
  S, liveStats, novelLike, aiEnabledUi, setInputTab, onScriptInput, loadSample, loadProblem, loadGuihun,
  clearScript, goStep2, oneClick, readScriptFile, adaptNovel
} from "../stores/studio.js";

const SCRIPT_PLACEHOLDER = "把剧本文字粘贴到这里…\n\n支持这些写法（混用也行）：\n《片名》\n第1场 外景 · 便利店门口 · 夜\n△ 雨下得很急。\n林晚：又是一整夜的雨。\n陈默（压低声音）：你不是第一次来这儿。";
const dragover = ref(false);

/* 自动处理工作流的可见阶段；单独点「只转写」可停在 stage 1 人工确认 */
const STAGES = [
  { key: "detect", name: "识别格式" },
  { key: "adapt", name: "忠实转写" },
  { key: "check", name: "剧本体检" },
  { key: "plan", name: "自动分集" },
  { key: "shots", name: "逐集分镜" },
  { key: "verify", name: "覆盖校验" }
];
const stageIdx = computed(() => {
  if (!S.aiBusy) return novelLike.value ? 1 : 0;
  const i = STAGES.findIndex((s) => s.key === S.aiStage);
  return i < 0 ? 0 : i;
});

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
        <h1>把剧本放进来，剩下的交给我们</h1>
        <p class="sub">不用学格式、不用填表。粘贴一段剧本文字，{{ aiEnabledUi ? "AI 会自动判断该切成几集、每集怎么分镜，" : "系统会" }}拆出场次、角色、对白与动作，并按剧情顺序排好每一镜。</p>
      </div>

      <div class="card script-card">
        <div class="card-top">
          <div class="tabs" id="input-tabs">
            <button class="tab" :class="{ active: S.inputTab === 'paste' }" data-tab="paste" @click="setInputTab('paste')">粘贴文字</button>
            <button class="tab" :class="{ active: S.inputTab === 'file' }" data-tab="file" @click="setInputTab('file')">上传 .txt</button>
          </div>
          <div class="spacer"></div><span class="chip indigo">参数已自动配好</span>
        </div>

        <div id="input-paste" :class="{ hidden: S.inputTab !== 'paste' }">
          <textarea class="script-area" id="script-input" spellcheck="false"
            :placeholder="SCRIPT_PLACEHOLDER" :value="S.script" @input="onScriptInput"></textarea>
        </div>

        <div id="input-file" :class="{ hidden: S.inputTab !== 'file' }" style="padding:18px">
          <div class="drop-hint" id="drop-zone" :class="{ dragover }" @click="chooseFile"
            @dragenter="onDragEnter" @dragover="onDragOver" @dragleave="onDragLeave" @drop="onDrop">
            把 .txt / .md 剧本拖到这里，或点击选择文件<br><small>文件只在本机浏览器读取，不会上传到任何地方</small>
          </div>
          <input type="file" id="file-input" accept=".txt,.md,.text,text/plain" hidden
            @change="readScriptFile($event.target.files[0])">
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

      <div class="flow" id="flow-stages">
        <span class="flow-label">自动流程</span>
        <span v-for="(s, i) in STAGES" :key="s.key" class="flow-step"
          :class="{ done: i < stageIdx, active: i === stageIdx }"><i>{{ i + 1 }}</i>{{ s.name }}</span>
      </div>

      <div v-if="novelLike" class="novel-tip" id="novel-tip">
        <div class="novel-tip-txt">
          <b>检测到小说体 / 散文体</b>
          <span>没有「第N场」场次行，台词散在叙述里，直接拆解只会得到 1 场 / 0 句对白。可以先只转写、确认后再生成；也可以直接点「AI 一键」让整条流程自动跑完。</span>
        </div>
        <button class="btn sm primary" id="adapt-novel" @click="adaptNovel"
          :disabled="S.aiBusy || !aiEnabledUi">{{ S.aiBusy ? "处理中…" : "只转写成场次剧本" }}</button>
      </div>

      <div class="quick-row">
        <button class="btn sm" id="load-sample" @click="loadSample">载入完整示例剧本</button>
        <button class="btn sm" id="load-problem" @click="loadProblem">试试「待补全」示例</button>
        <button class="btn sm" id="load-guihun" @click="loadGuihun">载入《鬼婚，逃命》</button>
        <button class="btn sm" id="clear-script" @click="clearScript">清空</button>
        <span class="cta-note">完整示例：《雨夜便利店》4 场 · 2 角色 · 约 100 秒成片</span>
      </div>

      <div class="cta-row">
        <button class="btn primary lg" id="go-step2" @click="goStep2">AI 自动拆解</button>
        <button class="btn lg" id="one-click" @click="oneClick">{{ aiEnabledUi ? "⚡ AI 一键分集 + 分镜" : "⚡ 一键生成全部分镜" }}</button>
        <span class="cta-note">{{ aiEnabledUi ? "会先由大模型规划分集，再逐集生成分镜；失败自动降级，不改动剧本原文" : "两种方式都不会改动你的剧本原文" }}</span>
      </div>
    </div>

    <aside class="step1-side">
      <div class="how">
        <div class="how-item"><div class="n">阶段一 · 剧本</div><p>小说、散文、场次剧本都能直接粘进来；小说体会先自动转写成场次剧本。</p></div>
        <div class="how-item"><div class="n">阶段一 · 拆解</div><p>自动找出缺场景、角色名不统一、场号重复等问题，再列出分集 / 场次 / 角色给你确认。</p></div>
        <div class="how-item"><div class="n">阶段二 · 定妆</div><p>角色 / 场景 / 道具先出参考图定妆，分镜的参考图槽位都从这一层取，改一次全片同步。</p></div>
        <div class="how-item"><div class="n">阶段二 · 分镜</div><p>按剧情排出镜号、画面、景别、时长、台词、备注，随时可改、可导出。</p></div>
      </div>
    </aside>
  </div>
</template>
