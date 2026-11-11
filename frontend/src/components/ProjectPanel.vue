<script setup>
/* 项目面板（Studio 式）：新建 / 打开 / 重命名 / 复制 / 删除
   列表数据来自服务端 projects/ 目录，切换项目会先把当前项目落盘。 */
import { computed, nextTick, ref } from "vue";
import {
  S, ui, PROJECT, closeModal,
  openProject, newProject, renameProject, duplicateProject, deleteProject
} from "../stores/studio.js";

const draft = ref("");
const keyword = ref("");
const renamingId = ref("");
const renameDraft = ref("");
const confirmId = ref("");
const actId = ref("");

const list = computed(() => {
  const k = keyword.value.trim().toLowerCase();
  if (!k) return ui.projects;
  return ui.projects.filter((p) => (p.name || "").toLowerCase().includes(k));
});
const currentName = computed(() => S.projectName || "未命名项目");

function fmtTime(iso) {
  if (!iso) return "";
  const d = new Date(String(iso).replace(" ", "T"));
  if (isNaN(d.getTime())) return "";
  const now = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  const hm = pad(d.getHours()) + ":" + pad(d.getMinutes());
  if (d.toDateString() === now.toDateString()) return "今天 " + hm;
  const y = new Date(now.getTime() - 86400000);
  if (d.toDateString() === y.toDateString()) return "昨天 " + hm;
  return (d.getMonth() + 1) + "月" + d.getDate() + "日 " + hm;
}
function metaOf(p) {
  const bits = [];
  if (p.episodes) bits.push(p.episodes + " 集");
  if (p.shots) bits.push(p.shots + " 镜");
  if (p.assets) bits.push(p.assets + " 资产");
  if (!bits.length) bits.push(p.scriptChars ? Math.round(p.scriptChars / 100) / 10 + "k 字剧本" : "空项目");
  return bits.join(" · ");
}

async function createProject() {
  if (ui.projectBusy) return;
  const name = draft.value.trim() || "未命名项目";
  actId.value = "__new";
  const p = await newProject(name);
  actId.value = "";
  if (p) { closeModal(); }
}
async function open(id) {
  if (ui.projectBusy || id === S.projectId) { if (id === S.projectId) closeModal(); return; }
  actId.value = id;
  const ok = await openProject(id);
  actId.value = "";
  if (ok) closeModal();
}
function startRename(p) {
  renamingId.value = p.id;
  renameDraft.value = p.name;
  confirmId.value = "";
  nextTick(() => {
    const el = document.querySelector(".pp-rename input");
    if (el) { el.focus(); el.select(); }
  });
}
async function commitRename(p) {
  const nm = renameDraft.value.trim();
  if (!nm || nm === p.name) { renamingId.value = ""; return; }
  actId.value = p.id;
  await renameProject(p.id, nm);
  actId.value = "";
  renamingId.value = "";
}
async function copy(p) {
  actId.value = p.id;
  await duplicateProject(p.id);
  actId.value = "";
}
async function remove(p) {
  if (confirmId.value !== p.id) { confirmId.value = p.id; renamingId.value = ""; return; }
  actId.value = p.id;
  const ok = await deleteProject(p.id);
  actId.value = "";
  confirmId.value = "";
  if (ok && !ui.projects.length) closeModal();
}
</script>

<template>
  <div class="pp">
    <div class="pp-new">
      <input v-model="draft" id="new-project-name" class="pp-input" maxlength="40"
        placeholder="新项目名称，比如「雨夜便利店」"
        @keydown.enter="createProject" />
      <button class="btn primary" id="create-project" :disabled="ui.projectBusy || actId === '__new'"
        @click="createProject">{{ actId === "__new" ? "创建中…" : "＋ 新建项目" }}</button>
    </div>

    <div class="pp-bar">
      <span class="pp-cur">当前：<b>{{ currentName }}</b></span>
      <input v-if="ui.projects.length > 4" v-model="keyword" class="pp-search" placeholder="筛选项目…" />
    </div>

    <div class="pp-list" id="project-list">
      <p v-if="!ui.projects.length" class="pp-empty">
        还没有项目。上面输入名字新建一个，或在第 1 步载入示例剧本开始。
      </p>

      <div v-for="p in list" :key="p.id" class="pp-row"
        :class="{ current: p.id === S.projectId, busy: actId === p.id }">
        <button class="pp-main" :title="'打开「' + p.name + '」'" @click="open(p.id)">
          <span class="pp-dot" aria-hidden="true"></span>
          <span class="pp-txt">
            <span class="pp-name">
              {{ p.name }}
              <em v-if="p.id === S.projectId">当前</em>
            </span>
            <span class="pp-meta">{{ metaOf(p) }} · {{ fmtTime(p.updatedAt) || "尚未保存" }}</span>
          </span>
        </button>

        <div class="pp-rename" v-if="renamingId === p.id">
          <input v-model="renameDraft" class="pp-input sm" maxlength="40"
            @keydown.enter="commitRename(p)" @keydown.esc="renamingId = ''" />
          <button class="mini primary" @click="commitRename(p)">保存</button>
          <button class="mini" @click="renamingId = ''">取消</button>
        </div>
        <div class="pp-acts" v-else>
          <button class="mini" :disabled="ui.projectBusy" title="重命名" @click="startRename(p)">重命名</button>
          <button class="mini" :disabled="ui.projectBusy" title="复制一份（含剧本与资产）" @click="copy(p)">复制</button>
          <button class="mini danger" v-if="confirmId === p.id" :disabled="ui.projectBusy"
            @click="remove(p)">确认删除？</button>
          <button class="mini" v-else :disabled="ui.projectBusy" title="删除（移到 projects/.trash）"
            @click="remove(p)">删除</button>
        </div>
      </div>
    </div>

    <p class="pp-note">
      <template v-if="PROJECT.server">
        项目保存在本机 <code>projects/</code> 目录，每个项目一份 JSON；刷新、关掉浏览器、重新启动服务都会自动回到上次打开的项目。
      </template>
      <template v-else>
        本机服务未连接，内容只缓存在浏览器（5MB 上限）。双击 <code>start.bat</code> 启动后即可按项目管理。
      </template>
      删除会移到 <code>projects/.trash/</code>，需要时可以手动捞回。
    </p>
  </div>
</template>
