<script setup>
import { S, E, toggleCheck, setActiveShot, handleShotOp, visibleShots } from "../stores/studio.js";

function onRowClick(e, id) {
  if (e.target.closest("input,select,button")) return;
  setActiveShot(id);
}
const brief = (s) => {
  const t = E.detailText(s.detail);
  return t ? (t.length > 72 ? t.slice(0, 72) + "…" : t) : "—";
};
</script>

<template>
  <div class="table-wrap">
    <table class="shots">
      <thead><tr><th></th><th>镜号</th><th>场次</th><th>景别</th><th>时长</th><th>画面描述</th><th>台词</th><th>备注</th><th>分镜卡</th><th></th></tr></thead>
      <tbody>
        <tr v-for="s in visibleShots" :key="s.id" :data-id="s.id" :class="{ active: s.id === S.activeId }" @click="onRowClick($event, s.id)">
          <td><input type="checkbox" :data-check="s.id" :checked="S.selected.includes(s.id)" @change="toggleCheck($event, s.id)"></td>
          <td><span class="code">{{ s.code }}</span></td>
          <td>{{ s.sceneLabel }}</td>
          <td>
            <select class="size-sel" data-field="size" :data-id="s.id">
              <option v-for="z in E.SIZES" :key="z" :value="z" :selected="z === s.size">{{ z }}</option>
            </select>
          </td>
          <td><input type="number" data-field="duration" :data-id="s.id" :value="s.duration" step="0.5"></td>
          <td><input class="cell visual" data-field="visual" :data-id="s.id" :value="s.visual"></td>
          <td><input class="cell dialogue" data-field="dialogue" :data-id="s.id" :value="s.dialogue"></td>
          <td><input class="cell notes" data-field="notes" :data-id="s.id" :value="s.notes"></td>
          <td class="detail-brief" :title="E.detailText(s.detail)">{{ brief(s) }}</td>
          <td><button class="mini del" data-op="delete" :data-id="s.id" @click.stop="handleShotOp('delete', s.id)">×</button></td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
