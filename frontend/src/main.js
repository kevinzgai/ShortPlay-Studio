import { createApp } from "vue";
import App from "./App.vue";
import { boot } from "./stores/studio.js";
import "./assets/styles.css";
import "./assets/controls.css";
import "./assets/agents.css";
import "./assets/assets.css";
import "./assets/projects.css";
import "./assets/parse.css";
import "./assets/models.css";

createApp(App).mount("#app");
boot();
