/**
 * pro-api-sdk 使用 src/index.ts 作为默认打包入口。
 * 插件逻辑放在 main.ts，保持后续模块可独立扩展。
 */
export { activate, analyzeCurrentPcb, helloWorld, openAIReview, openDesignReview, openLegacyAIReview } from './main';
export { openNotes } from './notes/notesPanel';
