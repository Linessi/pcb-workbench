import type { PCBContext } from '../types/pcbContext';
import type { PCBReviewReport } from '../types/pcbReviewReport';
import { errorText, label } from './zh';

export function showReviewPanel(context: PCBContext, report: PCBReviewReport): void {
	const lines = [
		`工程：${context.projectName}`,
		`元件：${context.statistics.componentCount}  网络：${context.statistics.netCount}`,
		'',
		'兼容版 PCB 审查摘要（完整 DRC 请打开 AI 设计审查）',
		report.summary,
		'',
		`摘要问题：${report.issues.length}`,
	];
	for (const [index, issue] of report.issues.entries()) {
		lines.push(
			`${index + 1}. [${label(issue.severity)}] ${label(issue.category)}`,
			`原始证据：${issue.problem}`,
			`建议：${issue.suggestion}`,
			`依据: ${issue.ruleIds.join('、')}`,
			'',
		);
	}
	lines.push(`检查建议：${report.recommendations.length}`);
	for (const [index, recommendation] of report.recommendations.entries()) {
		lines.push(`${index + 1}. [${label(recommendation.priority)}] ${recommendation.action}`, `依据: ${recommendation.ruleIds.join('、')}`);
	}
	if (report.knowledgeReferences.length) {
		lines.push('知识规则来源：');
		for (const reference of report.knowledgeReferences) {
			lines.push(`${reference.id} — ${reference.title}`, reference.source);
		}
	}
	// SYS_Dialog.showInformationMessage() supports newline-delimited text.
	eda.sys_Dialog.showInformationMessage(lines.join('\n'), 'AI EDA 设计助手');
}

export function showReviewError(error: unknown, action = 'AI 分析'): void {
	eda.sys_Dialog.showInformationMessage(`${action}未完成：\n${errorText(error)}`, 'AI EDA 设计助手');
}
