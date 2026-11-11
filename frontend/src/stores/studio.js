/* =========================================================================
 * 分镜工场 · 状态层 barrel
 * 25 个组件文件从这里 import，路径保持 stores/studio 不变。
 * 实现按域拆在 ./studio/ 下（2026-11-11，函数体逐字未动）：
 *   core    状态 / 撤销 / 图仓 / 自动保存 / 跨域原语
 *   session 项目 CRUD / 模型与引擎配置 / boot
 *   steps   改稿 / 分集 / 逐集闸门 / AI 生成链
 *   shots   分镜表编辑 / 计算属性 / 导出
 *   assets  资产 / 资产包 / 起始帧 / ComfyUI 出图
 * ========================================================================= */
export * from "./studio/core.js";
export * from "./studio/session.js";
export * from "./studio/steps.js";
export * from "./studio/shots.js";
export * from "./studio/assets.js";
