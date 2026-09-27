import type { PCBContext } from '../types/pcbContext';
import type { KnowledgeReference, PCBReviewIssue, PCBReviewRecommendation, PCBReviewReport } from '../types/pcbReviewReport';

const BACKEND_URL = 'http://127.0.0.1:8000/api/analyze_pcb';
const CATEGORIES = new Set<PCBReviewIssue['category']>(['Power', 'Layout', 'Signal', 'EMC']);
const SEVERITIES = new Set<PCBReviewIssue['severity']>(['critical', 'high', 'medium', 'low']);
const PRIORITIES = new Set<PCBReviewRecommendation['priority']>(['high', 'medium', 'low']);

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isIssue(value: unknown): value is PCBReviewIssue {
	return isRecord(value)
		&& CATEGORIES.has(value.category as PCBReviewIssue['category'])
		&& SEVERITIES.has(value.severity as PCBReviewIssue['severity'])
		&& typeof value.problem === 'string'
		&& typeof value.suggestion === 'string'
		&& Array.isArray(value.ruleIds)
		&& value.ruleIds.length > 0
		&& value.ruleIds.every((ruleId: unknown) => typeof ruleId === 'string');
}

function isReference(value: unknown): value is KnowledgeReference {
	return isRecord(value)
		&& typeof value.id === 'string'
		&& typeof value.title === 'string'
		&& typeof value.source === 'string';
}

function isRecommendation(value: unknown): value is PCBReviewRecommendation {
	return isRecord(value)
		&& PRIORITIES.has(value.priority as PCBReviewRecommendation['priority'])
		&& typeof value.action === 'string'
		&& Array.isArray(value.ruleIds)
		&& value.ruleIds.length > 0
		&& value.ruleIds.every((ruleId: unknown) => typeof ruleId === 'string');
}

function isTrace(value: unknown): value is PCBReviewReport['analysis_trace'][number] {
	return isRecord(value)
		&& typeof value.tool === 'string'
		&& ['ok', 'warning', 'insufficient_data', 'error'].includes(String(value.result))
		&& typeof value.detail === 'string';
}

function isEvidence(value: unknown): value is PCBReviewReport['evidence'][number] {
	return isRecord(value) && typeof value.source === 'string' && typeof value.reason === 'string';
}

function parseReport(value: unknown): PCBReviewReport {
	if (!isRecord(value)
		|| typeof value.summary !== 'string'
		|| !Array.isArray(value.issues)
		|| !value.issues.every(isIssue)
		|| !Array.isArray(value.recommendations)
		|| !value.recommendations.every(isRecommendation)
		|| !Array.isArray(value.knowledgeReferences)
		|| !value.knowledgeReferences.every(isReference)
		|| (value.analysis_trace !== undefined && (!Array.isArray(value.analysis_trace) || !value.analysis_trace.every(isTrace)))
		|| (value.evidence !== undefined && (!Array.isArray(value.evidence) || !value.evidence.every(isEvidence)))) {
		throw new Error('Backend 返回的 PCBReviewReport 格式无效。');
	}
	const knownIds = new Set(value.knowledgeReferences.map((reference: KnowledgeReference) => reference.id));
	if (!value.issues.every((issue: PCBReviewIssue) => issue.ruleIds.every(ruleId => knownIds.has(ruleId)))) {
		throw new Error('Backend 报告包含未知知识库依据。');
	}
	if (!value.recommendations.every((item: PCBReviewRecommendation) => item.ruleIds.every(ruleId => knownIds.has(ruleId)))) {
		throw new Error('Backend 建议包含未知知识库依据。');
	}
	return {
		summary: value.summary,
		issues: value.issues,
		recommendations: value.recommendations,
		knowledgeReferences: value.knowledgeReferences,
		analysis_trace: value.analysis_trace ?? [],
		evidence: value.evidence ?? [],
	};
}

/**
 * SYS_ClientUrl.request() is declared in the installed pro-api-types SDK.
 * Its documentation requires External Interaction permission and server CORS.
 */
export async function requestPCBReview(context: PCBContext): Promise<PCBReviewReport> {
	let response: Response;
	try {
		response = await eda.sys_ClientUrl.request(
			BACKEND_URL,
			'POST',
			JSON.stringify(context),
			{ headers: { 'Content-Type': 'application/json' } },
		);
	}
	catch (error) {
		console.error('Backend request failed', error);
		throw new Error('无法连接本地 Backend。请确认服务已启动，并为插件启用“允许外部交互”。');
	}
	let body: unknown;
	try {
		body = await response.json();
	}
	catch {
		throw new Error(`Backend 返回了非 JSON 响应（HTTP ${response.status}）。`);
	}
	if (!response.ok) {
		const detail = isRecord(body) && typeof body.detail === 'string'
			? body.detail
			: `HTTP ${response.status}`;
		throw new Error(`Backend 分析失败：${detail}`);
	}
	return parseReport(body);
}
