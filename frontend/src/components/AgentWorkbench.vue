<script setup>
/* =========================================================================
 * Agent 工作台 · 角色注册表 / 流水线 / Prompt 与 SKILL.md 在线编辑 / 单角色试跑
 * 架构对照 huobao-drama：Agent = 注册表一条记录 + prompt 文件 + 若干 SKILL.md
 * 这里的状态是纯 UI 态，不进撤销栈，不落 localStorage。
 * ========================================================================= */
import { ref, computed, onMounted } from "vue";
import AgentAPI from "../lib/agents.js";
import { S, toast, busy } from "../stores/studio.js";

const data = ref({ agents: [], pipeline: [], skills: [] });
const sel = ref("");
const tab = ref("prompt");
const promptText = ref("");
const compiled = ref("");
const skillId = ref("");
const skillText = ref("");
const runInput = ref("");
const runResult = ref(null);
const msg = ref("");
const showAdd = ref(false);
const blankSpec = () => ({ id: "", name: "", stage: "", outputKey: "", desc: "", userTemplate: "" });
const newSpec = ref(blankSpec());

const agents = computed(() => data.value.agents || []);
const current = computed(() => agents.value.find(a => a.id === sel.value) || null);
const pipeAgents = computed(() =>
  (data.value.pipeline || []).map(id => agents.value.find(a => a.id === id)).filter(Boolean));
const collabAgents = computed(() =>
  agents.value.filter(a => !(data.value.pipeline || []).includes(a.id)));
const runJSON = computed(() => runResult.value ? JSON.stringify(runResult.value.result, null, 2) : "");

function fail(e) { msg.value = "✗ " + (e && e.message ? e.message : String(e)); }

async function load(keep) {
  try {
    data.value = await AgentAPI.list();
    if (!keep || !agents.value.some(a => a.id === sel.value)) {
      sel.value = (data.value.pipeline || [])[0] || (agents.value[0] && agents.value[0].id) || "";
    }
    await loadSelected();
  } catch (e) { fail(e); }
}

async function loadSelected() {
  msg.value = "";
  runResult.value = null;
  const a = current.value;
  if (!a) return;
  const sid = (a.skillFiles || [])[0] || "";
  try {
    const [p, s] = await Promise.all([
      AgentAPI.prompt(a.id),
      sid ? AgentAPI.skill(sid).catch(() => ({ content: "" })) : Promise.resolve({ content: "" })
    ]);
    promptText.value = p.content || "";
    compiled.value = p.compiled || "";
    skillId.value = sid;
    skillText.value = s.content || "";
  } catch (e) { fail(e); }
  if (!runInput.value) runInput.value = String(S.script || "").slice(0, 3000);
}

function select(id) {
  sel.value = id;
  tab.value = "prompt";
  loadSelected();
}

async function savePrompt() {
  try {
    await AgentAPI.savePrompt(sel.value, promptText.value);
    const p = await AgentAPI.prompt(sel.value);
    compiled.value = p.compiled || "";
    toast("Prompt 已保存，下一次调用立即生效", "ok");
    msg.value = "✓ 已写入 agents/prompts/" + sel.value + ".md";
  } catch (e) { fail(e); }
}

async function saveSkill() {
  if (!skillId.value) { msg.value = "该角色还没有绑定技能"; return; }
  try {
    await AgentAPI.saveSkill(skillId.value, skillText.value);
    toast("技能规范已保存，下一次调用立即生效", "ok");
    msg.value = "✓ 已写入 agents/skills/" + skillId.value + "/SKILL.md";
  } catch (e) { fail(e); }
}

async function patch(p) {
  try {
    await AgentAPI.patch(sel.value, p);
    await load(true);
    toast("角色配置已更新", "ok");
  } catch (e) { fail(e); }
}

async function run() {
  const a = current.value;
  if (!a) return;
  if (!a.generic) { msg.value = "这是流水线内建阶段，请在「导入剧本 → 生成分镜」主流程里运行。"; return; }
  msg.value = "";
  const payload = {};
  const inputs = a.input || ["script"];
  if (inputs.includes("shots")) {
    payload.shots = S.shots || [];
    if (!payload.shots.length) { msg.value = "请先在第 3 步生成分镜表，再试跑导演台。"; return; }
  } else if (inputs.includes("idea")) {
    payload.idea = runInput.value;
  } else {
    payload.script = runInput.value;
  }
  busy(true, "正在运行 " + a.name + "…");
  try {
    runResult.value = await AgentAPI.run(a.id, payload);
    tab.value = "run";
    toast(a.name + " 运行完成", "ok");
  } catch (e) { fail(e); }
  finally { busy(false); }
}

async function addAgent() {
  const spec = newSpec.value;
  if (!spec.id.trim()) { msg.value = "请填写角色 id（小写字母 / 数字 / 下划线）"; return; }
  try {
    await AgentAPI.add(spec);
    showAdd.value = false;
    newSpec.value = blankSpec();
    await load(false);
    toast("新角色已注册，无需改代码、无需重启", "ok");
    msg.value = "✓ 已生成 prompt 与 SKILL.md，可在下方编辑后直接试跑";
  } catch (e) { fail(e); }
}

async function removeAgent() {
  const a = current.value;
  if (!a) return;
  if (!window.confirm("确认删除角色「" + a.name + "」？会同时删掉它的 prompt 文件。")) return;
  try {
    await AgentAPI.remove(a.id);
    await load(false);
    toast("角色已删除", "ok");
  } catch (e) { fail(e); }
}

onMounted(() => load(false));
</script>

<template>
  <div class="aw">
    <div class="aw-flow">
      <span class="aw-flow-label">流水线</span>
      <template v-for="(a, i) in pipeAgents" :key="a.id">
        <span v-if="i" class="aw-arrow">→</span>
        <button class="aw-node" :class="{ on: sel === a.id }" @click="select(a.id)">
          <b>{{ i + 1 }}</b>{{ a.name }}
        </button>
      </template>
      <span class="aw-flow-tip">{{ collabAgents.length }} 个协作角色可随时加入</span>
    </div>

    <div class="aw-grid">
      <aside class="aw-list">
        <div class="aw-group">流水线阶段</div>
        <button v-for="a in pipeAgents" :key="a.id" class="aw-item" :class="{ on: sel === a.id }" @click="select(a.id)">
          <span class="aw-item-name">{{ a.name }}</span>
          <span class="aw-item-id">{{ a.id }}</span>
          <span class="aw-badge" :class="a.engine">{{ a.engine === "local" ? "本地" : "LLM" }}</span>
        </button>

        <div class="aw-group">协作角色 · 可插拔</div>
        <button v-for="a in collabAgents" :key="a.id" class="aw-item" :class="{ on: sel === a.id, off: a.enabled === false }" @click="select(a.id)">
          <span class="aw-item-name">{{ a.name }}</span>
          <span class="aw-item-id">{{ a.id }}</span>
          <span class="aw-badge collab">{{ a.stage }}</span>
        </button>

        <button class="aw-add-trigger" @click="showAdd = !showAdd">{{ showAdd ? "收起" : "+ 新增角色" }}</button>
        <div v-if="showAdd" class="aw-add-form">
          <label>id <input :value="newSpec.id" @input="newSpec.id = $event.target.value" placeholder="script_doctor" /></label>
          <label>名称 <input :value="newSpec.name" @input="newSpec.name = $event.target.value" placeholder="剧本医生" /></label>
          <label>阶段 <input :value="newSpec.stage" @input="newSpec.stage = $event.target.value" placeholder="review" /></label>
          <label>输出根键 <input :value="newSpec.outputKey" @input="newSpec.outputKey = $event.target.value" placeholder="report" /></label>
          <label class="wide">说明 <input :value="newSpec.desc" @input="newSpec.desc = $event.target.value" placeholder="一句话职责" /></label>
          <label class="wide">user 模板 <textarea :value="newSpec.userTemplate" @input="newSpec.userTemplate = $event.target.value" placeholder="按 Skill 规范处理以下输入，只输出一个 JSON 对象。\n\n输入：\n{script}"></textarea></label>
          <button class="btn primary" @click="addAgent">创建角色 + 生成 SKILL.md</button>
          <p>新建角色走 <code>/api/agents/&lt;id&gt;/run</code>，不改 Python 代码；要接进流水线才需要编排。</p>
        </div>
      </aside>

      <section v-if="current" class="aw-detail">
        <div class="aw-head">
          <div>
            <h3>{{ current.name }}</h3>
            <code>{{ current.id }}</code>
            <span class="aw-tag">{{ current.stage }}</span>
          </div>
          <div class="aw-toggles">
            <label class="aw-switch">
              <input type="checkbox" :checked="current.enabled !== false" @change="patch({ enabled: $event.target.checked })" />
              <span>启用</span>
            </label>
            <label class="aw-switch">
              <input type="checkbox" :checked="current.injectSkills !== false" @change="patch({ injectSkills: $event.target.checked })" />
              <span>注入技能</span>
            </label>
          </div>
        </div>
        <p class="aw-desc">{{ current.desc }}</p>
        <div class="aw-meta">
          输出根键 <code>{{ current.outputKey }}</code> · 引擎 <code>{{ current.engine }}</code> ·
          <code>{{ current.endpoint || "/api/agents/" + current.id + "/run" }}</code> ·
          prompt {{ current.promptChars }} 字
        </div>

        <div class="aw-tabs">
          <button :class="{ on: tab === 'prompt' }" @click="tab = 'prompt'">Prompt</button>
          <button :class="{ on: tab === 'skill' }" @click="tab = 'skill'">Skill · {{ (current.skillFiles || []).length }}</button>
          <button :class="{ on: tab === 'run' }" @click="tab = 'run'">试跑</button>
          <button v-if="current.generic && !current.builtin" class="aw-del" @click="removeAgent">删除角色</button>
        </div>

        <div v-if="tab === 'prompt'" class="aw-pane">
          <textarea class="aw-code" :value="promptText" @input="promptText = $event.target.value" spellcheck="false"></textarea>
          <div class="aw-pane-foot">
            <span>拼装后 {{ compiled.length }} 字（已含技能注入与变量替换）· 保存后下一次调用立即生效</span>
            <button class="btn primary" @click="savePrompt">保存 Prompt</button>
          </div>
        </div>

        <div v-else-if="tab === 'skill'" class="aw-pane">
          <div v-if="skillId" class="aw-skill-head">正在编辑 <code>agents/skills/{{ skillId }}/SKILL.md</code></div>
          <textarea class="aw-code" :value="skillText" @input="skillText = $event.target.value" spellcheck="false" placeholder="该角色还没有绑定技能"></textarea>
          <div class="aw-pane-foot">
            <span>SKILL.md 全文会注入该角色的 system prompt；新建的 SKILL.md 无需重启即可被发现</span>
            <button class="btn primary" :disabled="!skillId" @click="saveSkill">保存技能</button>
          </div>
        </div>

        <div v-else class="aw-pane">
          <div class="aw-run-hint" v-if="(current.input || []).includes('shots')">
            导演台读取当前分镜表（{{ (S.shots || []).length }} 镜），逐镜补全机位 / 站位 / 角度 / 光照。
          </div>
          <textarea v-else class="aw-run-input" :value="runInput" @input="runInput = $event.target.value" placeholder="粘贴剧本 / 小说原文，或写一句话创意"></textarea>
          <div class="aw-pane-foot">
            <span>{{ current.generic ? "通用执行器 · 只输出结构 JSON" : "内建阶段请在主流程运行" }}</span>
            <button class="btn primary" :disabled="!current.generic" @click="run">运行这个角色</button>
          </div>
          <div v-if="runResult" class="aw-run-out">
            <div class="aw-run-meta">{{ runResult.agent }} · {{ runResult.model }} · prompt {{ runResult.promptChars }} 字</div>
            <pre>{{ runJSON }}</pre>
          </div>
        </div>
      </section>
    </div>

    <div v-if="msg" class="aw-msg" :class="{ err: msg.startsWith('✗') }">{{ msg }}</div>
  </div>
</template>
