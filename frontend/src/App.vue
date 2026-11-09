<script setup>
import { onMounted, onUnmounted } from "vue";
import {
  S, undo, redo, closeModal, closeExport,
  onFieldFocusin, onFieldChange,
  onDragStart, onDragOver, onDrop, onDragEnd
} from "./stores/studio.js";
import TopBar from "./components/TopBar.vue";
import AppRail from "./components/AppRail.vue";
import StepOne from "./components/StepOne.vue";
import StepTwo from "./components/StepTwo.vue";
import ParseProgress from "./components/ParseProgress.vue";
import StepThree from "./components/StepThree.vue";
import FeedbackLayer from "./components/FeedbackLayer.vue";
import FxLayer from "./fx/FxLayer.vue";
import "./fx/fx.css";

function onKeydown(e) {
  const editing = e.target.matches && e.target.matches("input,textarea,select");
  if (editing) return;
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
    e.preventDefault();
    if (e.shiftKey) redo(); else undo();
  } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y") {
    e.preventDefault(); redo();
  } else if (e.key === "Escape") {
    closeModal(); closeExport();
  }
}
function onDocumentClick(e) {
  if (!e.target.closest(".export-wrap")) closeExport();
}

onMounted(() => {
  document.addEventListener("focusin", onFieldFocusin);
  document.addEventListener("change", onFieldChange);
  document.addEventListener("keydown", onKeydown);
  document.addEventListener("click", onDocumentClick);
  document.addEventListener("dragstart", onDragStart);
  document.addEventListener("dragover", onDragOver);
  document.addEventListener("drop", onDrop);
  document.addEventListener("dragend", onDragEnd);
});
onUnmounted(() => {
  document.removeEventListener("focusin", onFieldFocusin);
  document.removeEventListener("change", onFieldChange);
  document.removeEventListener("keydown", onKeydown);
  document.removeEventListener("click", onDocumentClick);
  document.removeEventListener("dragstart", onDragStart);
  document.removeEventListener("dragover", onDragOver);
  document.removeEventListener("drop", onDrop);
  document.removeEventListener("dragend", onDragEnd);
});
</script>

<template>
  <div id="app" class="shell">
    <AppRail />
    <div class="main-col">
      <TopBar />
      <main id="main">
        <!-- 后端拆解任务的实时进度：放在所有视图之上，哪一步都能看到 -->
        <ParseProgress />
        <section class="view" id="view-1" :class="{ hidden: S.step !== 1 }"><StepOne v-if="S.step === 1" /></section>
        <section class="view" id="view-2" :class="{ hidden: S.step !== 2 }"><StepTwo v-if="S.step === 2 && S.parsed" /></section>
        <section class="view" id="view-3" :class="{ hidden: S.step !== 3 }"><StepThree v-if="S.step === 3" /></section>
      </main>
    </div>
    <FeedbackLayer />
    <FxLayer />
  </div>
</template>
