<script setup>
import {
  S, E, EPISODE_MODES, onConfigChange, llmParse
} from "../stores/studio.js";

const pacing = [["standard", "标准 · 一句台词一镜（推荐）"], ["compact", "紧凑 · 合并同角色台词，镜头更少"], ["cinematic", "电影感 · 增加反应特写与留白"]];
const shotSize = [["auto", "自动 · 按动作与情绪判断（推荐）"], ["dialogue", "对白优先 · 多用中近景"], ["wide", "全景优先 · 多用环境镜头"]];
const aspects = [["16:9", "16:9 横屏（短剧常用）"], ["9:16", "9:16 竖屏（移动端）"], ["1:1", "1:1 方形"], ["2.39:1", "2.39:1 宽银幕"]];
const qualities = [["fast", "快速 · 小画幅（先看节奏）"], ["standard", "标准（推荐）"], ["high", "高清 · 大画幅（成片）"]];
</script>

<template>
  <div class="field">
    <label>镜头节奏</label>
    <select data-cfg="pacing" @change="onConfigChange">
      <option v-for="o in pacing" :key="o[0]" :value="o[0]" :selected="o[0] === S.config.pacing">{{ o[1] }}</option>
    </select>
    <span class="desc">只影响编排，不改你的剧本</span>
  </div>

  <div class="field">
    <label>景别策略</label>
    <select data-cfg="shotSize" @change="onConfigChange">
      <option v-for="o in shotSize" :key="o[0]" :value="o[0]" :selected="o[0] === S.config.shotSize">{{ o[1] }}</option>
    </select>
  </div>

  <div class="field">
    <label>单镜基准时长（秒）</label>
    <input type="number" min="2" max="12" step="0.5" data-cfg="defaultDuration" :value="S.config.defaultDuration" @change="onConfigChange">
    <span class="desc">会按台词长度自动微调，范围 2–10 秒</span>
  </div>

  <div class="field">
    <label>画面比例</label>
    <select data-cfg="aspect" @change="onConfigChange">
      <option v-for="o in aspects" :key="o[0]" :value="o[0]" :selected="o[0] === S.config.aspect">{{ o[1] }}</option>
    </select>
  </div>

  <div class="field">
    <label>出片画质</label>
    <select data-cfg="videoQuality" @change="onConfigChange">
      <option v-for="o in qualities" :key="o[0]" :value="o[0]" :selected="o[0] === S.config.videoQuality">{{ o[1] }}</option>
    </select>
    <span class="desc">只影响导出宽高，不动分镜</span>
  </div>

  <div class="field" style="justify-content:center">
    <div class="switch-row">
      <span>每场加一个建立镜头<span class="inline-note" style="display:block">先交代地点与时间，观众不迷路</span></span>
      <label class="switch"><input type="checkbox" data-cfg-toggle="establishing" :checked="S.config.establishing" @change="onConfigChange"><span></span></label>
    </div>
    <div class="switch-row">
      <span>每场加收束镜头<span class="inline-note" style="display:block">方便剪辑转场</span></span>
      <label class="switch"><input type="checkbox" data-cfg-toggle="closing" :checked="S.config.closing" @change="onConfigChange"><span></span></label>
    </div>
  </div>

  <div class="field" style="justify-content:center">
    <div class="switch-row">
      <span>生成运镜与声音备注<span class="inline-note" style="display:block">写进备注列，可直接给摄影看</span></span>
      <label class="switch"><input type="checkbox" data-cfg-toggle="cameraNotes" :checked="S.config.cameraNotes" @change="onConfigChange"><span></span></label>
    </div>
    <div class="switch-row">
      <span>重生成时覆盖我手改过的内容<span class="inline-note" style="display:block">默认关闭，保护你的修改</span></span>
      <label class="switch"><input type="checkbox" data-ui-toggle="overwriteEdited" :checked="S.overwriteEdited" @change="onConfigChange"><span></span></label>
    </div>
  </div>

  <div class="field" style="grid-column:1/-1">
    <label>AI 自动分集 · 分镜</label>
    <div v-if="S.llmAvailable" class="ai-mode-box">
      <div class="switch-row">
        <span>用大模型拆解分镜（关掉则回到离线规则引擎）
          <span class="inline-note" style="display:block">每镜输出 9 项分镜描述卡并标注剧本行引用；台词与动作漏项自动补镜，建立/收束镜头禁止套话，服务端校验并纠正脏数据</span>
        </span>
        <label class="switch"><input type="checkbox" data-ui-toggle="aiEnabled" :checked="S.aiEnabled" @change="onConfigChange"><span></span></label>
      </div>
      <div class="row-wrap" style="margin-top:10px">
        <span class="chip ok" :title="S.llmProvider ? '当前使用的模型配置：' + S.llmProvider : ''">已接入 {{ S.llmModel || "大模型" }}{{ S.llmProvider ? " · " + S.llmProvider : "" }}</span>
        <label class="inline-note" for="episode-mode" style="display:inline-flex;align-items:center;gap:6px">分集方式</label>
        <select id="episode-mode" data-episodes style="width:auto;min-width:180px" @change="onConfigChange">
          <option v-for="o in EPISODE_MODES" :key="o[0]" :value="o[0]" :selected="String(S.episodeMode) === o[0]">{{ o[1] }}</option>
        </select>
        <button class="btn sm" id="llm-parse" @click="llmParse">让大模型再理解一次剧本</button>
      </div>
      <span class="desc">切集只落在场次之间，不拆散一场；没有网络或模型失败时自动降级到本地规则，核心功能不受影响。</span>
    </div>
    <div v-else class="inline-note">
      当前是 <b>离线模式</b>：分集与分镜由内置规则引擎完成。想要 <b>AI 自动分集 + AI 分镜</b>，请双击 <code>start.bat</code> 启动本机服务并配置模型 Key。
    </div>
  </div>
</template>
