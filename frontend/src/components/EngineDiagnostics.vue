<script setup>
import { computed } from "vue";
import { S, ui, PROJECT, comfyCheck } from "../stores/studio.js";

/* 诊断栏只做一件事：回答「为什么我这个按钮点了没反应」，并给出下一步。
   不堆日志、不拼报告——那是运维工具，对使用者没价值。
   三态：ok / warn（可选能力未启用，不告警）/ bad（关键能力缺失）。 */
const emit = defineEmits(["go"]);

const comfyDetail = computed(() => ui.comfy.detail || "");
const qwenDetail = computed(() => (ui.comfy.qwen && ui.comfy.qwen.detail) || "");
const checked = computed(() => !!ui.comfy.checked);

/* macOS 上踩过的坑：localhost 探测被系统代理带走，直连 200、服务端却 502。
   这个提示只在真的命中特征时才出现，不当成通用兜底。 */
const proxyHit = computed(() =>
  !ui.comfy.online && /502|proxy|tunnel|ProxyError|代理/i.test(comfyDetail.value));

const rows = computed(() => {
  const serverOk = !!PROJECT.server;
  const llmOk = !!S.llmAvailable;
  const comfyOk = !!ui.comfy.online;
  const qwenOk = !!(ui.comfy.qwen && ui.comfy.qwen.online);
  const h3Ok = !!(ui.comfy.h3 && ui.comfy.h3.online);

  return [
    {
      key: "server", name: "本机服务", level: serverOk ? "ok" : "bad", go: "",
      value: serverOk ? "已连接 · 项目自动落盘 projects/" : (PROJECT.error || "未连接"),
      why: serverOk ? "" : "此时内容只缓存在浏览器，关掉页面就没了",
      fix: serverOk ? "" : "双击 start.bat，或运行 python3 server.py --no-browser"
    },
    {
      key: "llm", name: "文字模型", level: llmOk ? "ok" : "bad", go: "llm", goLabel: "去配置",
      value: llmOk
        ? (S.llmModel || "已接入") + (S.llmProvider ? " · " + S.llmProvider : "")
        : "未接入",
      why: llmOk ? "" : "现在走的是内置规则引擎",
      fix: llmOk ? "" : "转写、体检、分集、分镜、Agent 全部降级；配一条 Key 即可恢复"
    },
    {
      key: "comfy", name: "本地 ComfyUI",
      level: !checked.value ? "warn" : (comfyOk ? "ok" : "bad"),
      go: "engine", goLabel: "去配置",
      value: !checked.value ? "检测中…"
        : comfyOk ? "在线 · v" + (ui.comfy.version || "?") + " · " + (ui.comfy.model || "")
        : (comfyDetail.value || "未连接"),
      why: comfyOk ? "" : "出片工具的三视图 / 概念图出不来",
      fix: !checked.value ? "" : comfyOk ? "" : (proxyHit.value
        ? "本机探测被系统代理拦了：带 NO_PROXY=127.0.0.1,localhost 重启服务"
        : "确认 ComfyUI 已在 8188 启动，地址与「出图引擎」里填的一致")
    },
    {
      key: "qwen", name: "通义万相", level: qwenOk ? "ok" : "warn",
      go: "engine", goLabel: "去配置",
      value: qwenOk
        ? ((ui.comfy.qwen.model || "") + " · " + (ui.comfy.qwen.size || "") + " · 云端组图")
        : "未启用（可选引擎）",
      why: qwenOk ? "" : "不影响出图：本地 ComfyUI 在线时照常可用",
      fix: qwenOk ? "" : "想用云端组图再填一条 DashScope Key，保存即生效"
    },
    {
      key: "h3", name: "MiniMax H3", level: h3Ok ? "ok" : "warn",
      go: "engine", goLabel: "去配置",
      value: h3Ok
        ? ((ui.comfy.h3.model || "") + " · " + (ui.comfy.h3.size || "") + " · 云端生图")
        : "未启用（可选引擎）",
      why: h3Ok ? "" : "不影响出图：本地 ComfyUI 或通义万相可用时照常工作",
      fix: h3Ok ? "" : "想用 MiniMax 生图再填一条 API Key，保存即生效"
    }
  ];
});

const badCount = computed(() => rows.value.filter((r) => r.level === "bad").length);
const warnCount = computed(() => rows.value.filter((r) => r.level === "warn").length);
const headline = computed(() => {
  if (badCount.value) return { cls: "warn", text: badCount.value + " 项不可用" };
  if (warnCount.value) return { cls: "ok", text: "核心能力就绪 · " + warnCount.value + " 项可选未启用" };
  return { cls: "ok", text: "全部就绪" };
});
</script>

<template>
  <div class="dg">
    <div class="dg-top">
      <b :class="headline.cls" data-dg-head>{{ headline.text }}</b>
      <span>核心功能不会因为这些离线而中断，只影响对应能力。</span>
      <button class="btn sm quiet" data-dg-recheck @click="comfyCheck()">重新检测</button>
    </div>

    <ul class="dg-list">
      <li v-for="r in rows" :key="r.key" class="dg-row" :class="r.level" :data-dg-row="r.key">
        <span class="dg-dot"></span>
        <div class="dg-main">
          <div class="dg-line">
            <b>{{ r.name }}</b>
            <span class="dg-val">{{ r.value }}</span>
          </div>
          <span v-if="r.why" class="dg-why">{{ r.why }}</span>
          <span v-if="r.fix" class="dg-fix">{{ r.fix }}</span>
        </div>
        <button v-if="r.go" class="btn sm quiet dg-go" @click="emit('go', r.go)">{{ r.goLabel }}</button>
      </li>
    </ul>

    <p class="dg-note">
      想换文字模型去「文字模型」页；换出图引擎地址或模型去「出图引擎」页。
      这两类配置都是全局的，不随项目切换而变。
    </p>
  </div>
</template>
