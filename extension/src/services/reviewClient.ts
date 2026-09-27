import type { PCBContextV2 } from '../types/pcbContext';
import type { SnapshotReport } from '../types/review';
import { record } from '../ui/zh';

const ROOT = 'http://127.0.0.1:8000/api/reviews';
export async function reviewApi(path: string, method: 'GET' | 'POST', payload?: unknown): Promise<unknown> {
	let response: Response;
	try {
		// Installed SDK SYS_ClientUrl.request, same bridge as verified v0.6.2.
		response = await eda.sys_ClientUrl.request(`${ROOT}${path}`, method, payload === undefined ? undefined : JSON.stringify(payload), { headers: { 'Content-Type': 'application/json' } });
	}
	catch { throw new Error('无法连接本机后端，请确认服务启动且扩展已启用“允许外部交互”。'); }
	let body: unknown;
	try {
		body = await response.json();
	}
	catch { throw new Error(`后端响应格式错误（HTTP ${response.status}）。`); }
	if (!response.ok) {
		const detail = record(body) && typeof body.detail === 'string' && /[\u4E00-\u9FFF]/.test(body.detail) ? body.detail : '请求字段或后端状态异常';
		throw new Error(`后端操作失败：${detail}（HTTP ${response.status}）。`);
	}
	return body;
}

export function parseSnapshotReport(body: unknown): SnapshotReport {
	if (!record(body) || typeof body.snapshot_id !== 'string' || !/^[a-f0-9]{32}$/.test(body.snapshot_id)
		|| !record(body.provenance) || typeof body.summary_zh !== 'string'
		|| !record(body.drc) || !Array.isArray(body.drc.issues)
		|| body.drc.parsed_count !== body.drc.issues.length
		|| !body.drc.issues.every((item: unknown) => record(item) && typeof item.id === 'string' && typeof item.message_zh === 'string' && Array.isArray(item.objects))
		|| !Array.isArray(body.drc.groups) || !Array.isArray(body.drc.unknown_results)
		|| !Array.isArray(body.explanations) || !Array.isArray(body.pending_checks)
		|| !Array.isArray(body.evidence) || !Array.isArray(body.analysis_trace)
		|| !Array.isArray(body.knowledge_references) || !Array.isArray(body.rejected_conclusions)
		|| typeof body.agent_status !== 'string' || typeof body.agent_message_zh !== 'string') {
		throw new Error('后端报告结构或全量 DRC 数量核验失败。');
	}
	const ids = new Set(body.drc.issues.map((item: { id: string }) => item.id));
	if (ids.size !== body.drc.issues.length || !body.drc.groups.every((group: unknown) => record(group) && Array.isArray(group.issue_ids) && group.count === group.issue_ids.length && group.issue_ids.every((id: unknown) => typeof id === 'string' && ids.has(id))))
		throw new Error('报告分组与原始明细映射不一致。');
	return body as unknown as SnapshotReport;
}

export async function createReview(context: PCBContextV2, previous?: string): Promise<SnapshotReport> {
	return parseSnapshotReport(await reviewApi('', 'POST', { context, source_kind: 'eda_live', previous_snapshot_id: previous ?? null }));
}

export async function fetchReview(snapshot: string): Promise<SnapshotReport> {
	if (!/^[a-f0-9]{32}$/.test(snapshot))
		throw new Error('快照标识无效。');
	return parseSnapshotReport(await reviewApi(`/${snapshot}`, 'GET'));
}
