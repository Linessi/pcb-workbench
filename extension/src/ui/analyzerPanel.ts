import type { PCBContext } from '../types/pcbContext';
import type { ExportResult } from '../utils/export';

/** A small native EDA dialog; showInformationMessage supports newlines. */
export function showAnalyzerPanel(pcbName: string, context: PCBContext, exported: ExportResult): void {
	const content = [
		`当前 PCB：${pcbName}`,
		`工程：${context.projectName}`,
		`板框：${context.board.width} × ${context.board.height} mil`,
		`元件：${context.statistics.componentCount}`,
		`网络：${context.statistics.netCount}`,
		`配置图层：${context.board.layers.length}`,
		'',
		'PCB 上下文已取得并保存',
		`保存路径：${exported.location}`,
	].join('\n');
	// SYS_Dialog.showInformationMessage(): @jlceda/pro-api-types.
	eda.sys_Dialog.showInformationMessage(content, 'AI EDA 设计助手');
}

export function showAnalyzerError(error: unknown): void {
	const message = error instanceof Error ? error.message : String(error);
	eda.sys_Dialog.showInformationMessage(`采集未完成：\n${message}`, 'AI EDA 设计助手');
}
