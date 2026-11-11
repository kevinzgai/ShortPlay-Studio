// UnoCSS · 原子化 CSS 引擎
// 策略：新改的组件（AssetPanel 出图工作区）用原子类，老组件继续走 assets/*.css，渐进迁移。
// 主题色对齐「V4 柔和现代」：冷调浅底 + 靛蓝 #4f54e0 只给主按钮与选中态；
// 状态绿只给在线点；无渐变 / 光晕 / 药丸。
import { defineConfig, presetUno, transformerDirectives } from "unocss";

export default defineConfig({
  presets: [presetUno({ dark: "class" })],
  transformers: [transformerDirectives()],
  theme: {
    colors: {
      // V4 冷调墨色
      ink: {
        DEFAULT: "#1c1f2e",
        2: "#4d5266",
        3: "#8d92a6",
        4: "#c3c7d6",
      },
      paper: {
        DEFAULT: "#ffffff",
        soft: "#fafafd",
        dim: "#f5f6fa",
        sel: "#eef0fb",
        line: "#e3e5ee",
        line2: "#edeff6",
      },
      accent: {
        DEFAULT: "#4f54e0",
        deep: "#3c40b8",
        hi: "#6d72f0",
      },
      ok: "#2e9e5b",
      warn: "#b45309",
      err: "#dc2626",
    },
    borderRadius: { none: "0", btn: "8px", card: "14px" },
  },
  shortcuts: {
    // 高频组合（等价原子类的别名，仍然零运行时）
    "btn-ghost":
      "inline-flex items-center gap-1 rounded-btn border border-paper-line bg-paper px-3 py-[5px] text-12px text-ink-2 transition-colors hover:text-ink hover:border-ink-3",
    "btn-primary":
      "inline-flex items-center gap-1 rounded-btn border border-accent bg-accent px-4 py-[6px] text-12px fw6 text-white transition-[filter] hover:brightness-110 disabled:opacity-45 disabled:cursor-not-allowed",
    "seg-box":
      "flex gap-0.5 rounded-btn border border-paper-line bg-paper p-[2px]",
    "seg-btn":
      "rounded-[6px] border border-transparent bg-transparent px-2.5 py-[5px] text-11.5px text-ink-2 whitespace-nowrap transition-colors hover:text-ink hover:bg-paper-dim",
    "seg-on": "bg-paper-sel text-accent-deep fw5 border-[#d8dbf5]",
    "field-input":
      "w-full rounded-btn border border-paper-line bg-paper-soft px-2.5 py-[5px] text-11.5px text-ink placeholder:text-ink-3",
  },
});
