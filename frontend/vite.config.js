import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import UnoCSS from "unocss/vite";

const resolve = (p) => fileURLToPath(new URL(p, import.meta.url));

export default defineConfig({
  plugins: [vue(), UnoCSS()],
  // 与后端同源部署：构建产物落到 backend/dist/，backend/server.py 托管它（单端口 8177）
  build: {
    outDir: resolve("../backend/dist"),
    emptyOutDir: true,
  },
  // 开发时把 /api 转发给本机 Python 服务，前端热更新与 AI 接口两不误
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8177",
    },
  },
});
