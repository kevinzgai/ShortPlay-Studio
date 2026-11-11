<script setup>
import {
  ui, S, runToastAction, closeModal, closeExport, doGenerate
} from "../stores/studio.js";
import SettingsFields from "./SettingsFields.vue";
import SystemSettings from "./SystemSettings.vue";
import AgentWorkbench from "./AgentWorkbench.vue";
import ProjectPanel from "./ProjectPanel.vue";

function regenerateFromSettings() {
  closeModal();
  if (S.parsed) doGenerate("force");
}
</script>

<template>
  <div class="toast-wrap" id="toasts" aria-live="polite">
    <div v-for="t in ui.toasts" :key="t.id" class="toast" :class="t.level">
      <span class="t-ico"></span><span>{{ t.msg }}</span>
      <button v-if="t.actionLabel" @click="runToastAction(t)">{{ t.actionLabel }}</button>
    </div>
  </div>

  <div id="modal-root">
    <div v-if="ui.modal" class="modal-veil" @click.self="closeModal">
      <div class="modal" :class="{ 'aw-modal': ui.modal.type === 'agents', 'pp-modal': ui.modal.type === 'projects', 'st-modal': ui.modal.type === 'settings' || ui.modal.type === 'system' }">
        <div class="m-head">
          <h2>{{ ui.modal.type === "settings" ? "生成设置 · 只影响本项目"
            : ui.modal.type === "system" ? "系统设置 · 全局生效"
            : ui.modal.type === "agents" ? "Agent 工作台 · 角色与技能注册表"
            : ui.modal.type === "projects" ? "项目 · 创建 / 打开 / 管理" : "怎么用 · 三步出片" }}</h2>
          <button class="x" data-close @click="closeModal">×</button>
        </div>

        <div class="m-body">
          <template v-if="ui.modal.type === 'projects'">
            <ProjectPanel />
          </template>
          <template v-else-if="ui.modal.type === 'settings'">
            <p class="modal-scope">
              这里只影响<b>当前项目</b>的分集与分镜编排，随项目一起保存。
              换模型 / 换出图引擎请到「系统设置」（全局，不随项目变化）。
            </p>
            <div class="settings-body" style="display:grid;padding:0 20px;border:none">
              <SettingsFields />
            </div>
          </template>
          <template v-else-if="ui.modal.type === 'system'">
            <SystemSettings />
          </template>
          <template v-else-if="ui.modal.type === 'agents'">
            <AgentWorkbench />
          </template>
          <template v-else>
            <h3>阶段一 · 剧本：1. 导入原文</h3>
            <p>直接粘贴文字，或上传 .txt。最简格式也能识别：<code>第1场</code> 分行、<code>角色：台词</code> 写对白、<code>△</code> 开头写动作。带 <code>外景 · 地点 · 夜</code> 会更准。</p>
            <h3>阶段一 · 剧本：2. AI 拆解确认</h3>
            <p>拆出场次、角色、场景、对白与动作；AI 还会给出分集方案（集标题、剧情梗概、集尾钩子）。缺地点、场号重复、角色名前后不一致等问题会列成体检卡，点右侧按钮补全；补全会写回剧本文本，按 Ctrl+Z 可撤销。结构确认没问题，再生成分镜进入制作阶段。</p>
            <h3>阶段二 · 制作：1. 分镜表（主流程终点）</h3>
            <p>大模型按剧情顺序逐集排出镜号（<code>E01-001</code>）、画面描述、景别、时长、台词、备注，台词与剧本逐字一致。点文字直接改，拖 <code>⠿</code> 手柄或点 ↑↓ 排序，顶部可按集筛选，选中多条可批量重生成或删除，改完直接导出。<b>分镜表就是完整交付物</b>，主流程到这一步结束。</p>
            <h3>出片（可选动作，不算工作区）</h3>
            <p>需要参考图、起始帧提示词或整包素材时，在分镜表顶部展开「出片」区，或从侧栏的可选入口打开完整出片工具。角色 / 场景 / 道具的参考图全片共享，改一次同步到所有镜头。<b>全剧视觉风格锚在「生成设置 · 视觉设定」里定一次</b>，不要在每一集里改。支持本地 ComfyUI、通义万相与云端 H3。</p>
            <h3>快捷键与安全</h3>
            <p><code>Ctrl+Z</code> 撤销、<code>Ctrl+Shift+Z</code> 重做。内容按项目存在本机 <code>projects/</code> 目录，改完自动保存，刷新或重开浏览器都会回到上次打开的项目与步骤。顶栏项目胶囊可以新建 / 切换 / 重命名 / 复制 / 删除，删除的项目会移到 <code>projects/.trash/</code>。导出的 CSV / Markdown / 视频提示词都会带上集信息。</p>
            <h3>关于 AI</h3>
            <p>启动本机服务后，到 <b>系统设置 · 文字模型</b> 配一条 Key，AI 就会接手分集与分镜；模型只做创作决策，服务端负责校验与纠正（非法景别、超长时长、场次越界、重复镜头），台词不在原文里会明确标注待核对。没配 Key、断网或模型失败时自动降级到内置规则引擎，核心功能照常可用。</p>
          </template>
        </div>

        <div class="m-foot">
          <template v-if="ui.modal.type === 'settings'">
            <button class="btn" data-close @click="closeModal">关闭</button>
            <button class="btn primary" id="modal-regenerate" @click="regenerateFromSettings">按当前参数重排分镜（本地规则）</button>
          </template>
          <template v-else-if="ui.modal.type === 'system'">
            <span class="inline-note">这里是全局配置，改完立即生效 · 不进撤销栈</span>
            <button class="btn primary" data-close @click="closeModal">关闭</button>
          </template>
          <template v-else-if="ui.modal.type === 'projects'">
            <span class="inline-note">切换项目前会自动保存当前项目 · 删除移到 projects/.trash</span>
            <button class="btn primary" data-close @click="closeModal">关闭</button>
          </template>
          <template v-else-if="ui.modal.type === 'agents'">
            <span class="inline-note">角色与技能都是 agents/ 下的文件，改完保存立即生效 · 不进撤销栈</span>
            <button class="btn primary" data-close @click="closeModal">完成</button>
          </template>
          <template v-else>
            <span class="inline-note">所有改动都可以撤销</span>
            <button class="btn primary" data-close @click="closeModal">知道了</button>
          </template>
        </div>
      </div>
    </div>
  </div>

  <div class="busy-veil" id="busy-veil" :class="{ hidden: !ui.busy }">
    <div class="busy-card"><span class="spinner"></span><span id="busy-text">{{ ui.busyText }}</span></div>
  </div>
</template>
