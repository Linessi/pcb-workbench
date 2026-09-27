/** Incremental v0.7 IFrame. All untrusted text uses textContent, never HTML. */
import type { PCBContextV2 } from '../types/pcbContext';
import type { DrcIssue, ReviewExplanation, SnapshotReport } from '../types/review';
import { selectIssueObjects } from '../api/selection';
import { collectReviewContext } from '../collector/reviewCollector';
import { createReview, fetchReview, parseSnapshotReport, reviewApi } from '../services/reviewClient';
import { errorText, label, record } from './zh';

const SESSION_KEY = 'aiEdaCopilot.reviewSession.v07';
let context: PCBContextV2;
let report: SnapshotReport;
let busy = false;
let generation = 0;
let page = 0;
const PAGE_SIZE = 10;

function element(id: string): HTMLElement {
	const found = document.getElementById(id);
	if (!found)
		throw new Error(`审查窗口缺少元素 ${id}。`);
	return found;
}
function setText(id: string, value: string | number): void {
	element(id).textContent = String(value);
}
function add(parent: HTMLElement, tag: keyof HTMLElementTagNameMap, value: string, className = ''): HTMLElement {
	const node = document.createElement(tag);
	node.className = className;
	node.textContent = value;
	parent.append(node);
	return node;
}
function status(title: string, detail: string): void {
	setText('status', title);
	setText('status-detail', detail);
	element('status-detail').hidden = !detail;
}
function setBusy(value: boolean): void {
	busy = value;
	for (const id of ['analyze-button', 'recheck-button', 'repeat-button']) (element(id) as HTMLButtonElement).disabled = value;
	(element('cancel-button') as HTMLButtonElement).disabled = !value;
}
function rawDetails(parent: HTMLElement, title: string, value: unknown): void {
	const details = document.createElement('details');
	add(details, 'summary', title);
	add(details, 'pre', typeof value === 'string' ? value : JSON.stringify(value, null, 2), 'raw-evidence');
	parent.append(details);
}
function button(parent: HTMLElement, title: string, action: () => Promise<void>): void {
	const node = document.createElement('button');
	node.type = 'button';
	node.className = 'small-button';
	node.textContent = title;
	node.addEventListener('click', () => {
		void action();
	});
	parent.append(node);
}

async function select(issue: DrcIssue): Promise<void> {
	if (busy) {
		status('操作正在进行', '请等待当前客户端操作完成或取消审查。');
		return;
	}
	setBusy(true);
	try {
		const result = await selectIssueObjects(report, context, issue.id);
		status(result.detail_zh.includes('所属元件') ? '已选择所属元件' : '已选择相关对象', result.detail_zh.includes('所属元件') ? '此问题暂不支持精确焊盘定位。' : '');
		await reviewApi(`/${report.snapshot_id}/client_event`, 'POST', { action: 'select_related_objects', document_id: report.provenance.document_id, status: 'verified', ...result });
	}
	catch (error) { status('无法定位', errorText(error)); }
	finally { setBusy(false); }
}

function issueCard(issue: DrcIssue): HTMLElement {
	const card = document.createElement('article');
	card.className = 'item';
	const head = add(card, 'div', '', 'item-head');
	add(head, 'span', `${label(issue.priority)}优先级`, `badge ${issue.priority}`);
	add(head, 'strong', issue.net ? `网络 ${issue.net}` : '原生检查项目');
	const message = issue.translation_status === 'template'
		? issue.message_zh.replace(/^原生 DRC 报告连接性错误：/, '连接性错误：').replace(/需在原生 DRC 面板核对连接位置。$/, '')
		: issue.message_zh;
	add(card, 'p', message);
	add(card, 'div', `相关对象：${issue.objects.filter(obj => obj.kind !== 'net').map(obj => obj.object_id).join('、') || '未取得可靠映射'}`, 'rule');
	button(card, '选择对象', () => select(issue));
	button(card, '查看证据', async () => {
		const evidence = report.evidence.filter(item => item.issue_ids.includes(issue.id));
		rawDetails(card, '快照证据与来源（原始数据）', evidence);
	});
	button(card, '查看规则', async () => {
		const ids = new Set(report.explanations.filter(item => item.issue_ids.includes(issue.id)).flatMap(item => item.rule_ids));
		const rules = report.knowledge_references.filter(item => ids.has(item.id));
		if (!rules.length)
			add(card, 'p', '此项尚无 AI 规则解释；原生 DRC 证据独立有效。');
		for (const rule of rules) add(card, 'p', `${rule.title_zh}：${rule.summary_zh}`);
	});
	rawDetails(card, '原始检查记录', { id: issue.id, source_path: issue.source_path, raw_message: issue.raw_message, raw: issue.raw, priority_reason_zh: issue.priority_reason_zh, native_severity: issue.native_severity, location_scope: issue.location_scope });
	return card;
}

function renderDrc(): void {
	const count = report.drc.issues.length;
	page = Math.min(page, Math.max(0, Math.ceil(count / PAGE_SIZE) - 1));
	element('risks').replaceChildren(...report.drc.issues.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE).map(issueCard));
	setText('page-label', `${page + 1} / ${Math.max(1, Math.ceil(count / PAGE_SIZE))} 页 · 共 ${count} 条`);
	(element('previous-page') as HTMLButtonElement).disabled = page === 0;
	(element('next-page') as HTMLButtonElement).disabled = (page + 1) * PAGE_SIZE >= count;
	if (!count)
		add(element('risks'), 'p', report.drc.status === 'completed' && report.drc.native_count === 0 ? '本次原生 DRC 检查完成，未报告问题。' : drcFailureMessage());
	for (const unknown of report.drc.unknown_results) rawDetails(element('risks'), '存在尚未完整解析的检查结果', unknown);
	element('groups').replaceChildren();
	for (const group of report.drc.groups) {
		const details = document.createElement('details');
		add(details, 'summary', `${group.net || '未提供网络'} · ${group.count} 项`);
		add(details, 'p', `全部成员：${group.issue_ids.join('、')}`, 'subtle');
		element('groups').append(details);
	}
}

function drcFailureMessage(): string {
	return context.drc.reason || '原生 DRC 未完整取得。请先在 EDA 的“设计 → 检查DRC”完成检查，再点击“重新检查”。';
}

function drcReady(): boolean {
	return report.drc.status === 'completed' && report.drc.native_count !== null && report.drc.unknown_results.length === 0;
}

function explanationCard(item: ReviewExplanation): HTMLElement {
	const card = document.createElement('article');
	card.className = 'item';
	add(card, 'h4', item.title_zh);
	add(card, 'p', item.explanation_zh);
	const steps = document.createElement('ol');
	for (const step of item.steps_zh) add(steps, 'li', step);
	card.append(steps);
	add(card, 'p', `验证：${item.verification_zh}`, 'suggestion');
	add(card, 'p', `待确认：${item.uncertainty_zh}`, 'subtle');
	const rules = report.knowledge_references.filter(rule => item.rule_ids.includes(rule.id));
	if (rules.length)
		add(card, 'p', `依据：${rules.map(rule => rule.title_zh).join('、')}`, 'rule');
	rawDetails(card, '查看引用证据', report.evidence.filter(evidence => item.evidence_ids.includes(evidence.id)));
	return card;
}

function render(): void {
	element('report').hidden = false;
	setText('project-name', context.projectName);
	setText('component-count', context.components.length);
	setText('net-count', context.nets.length);
	setText('layer-count', context.board.layers.length);
	setText('board-size', `${(context.board.width * 0.0254).toFixed(2)} × ${(context.board.height * 0.0254).toFixed(2)} mm`);
	const collected = new Date(String(report.provenance.collected_at));
	const time = Number.isNaN(collected.getTime()) ? '时间未取得' : collected.toLocaleString('zh-CN', { hour12: false });
	setText('snapshot-meta', `${label(report.source_kind)} · ${time} · ${label(report.drc.status)}`);
	setText('summary', report.summary_zh);
	setText('native-count', report.drc.native_count ?? '不可确定');
	setText('risk-count', report.drc.parsed_count);
	setText('group-count', report.drc.groups.length);
	setText('explained-count', new Set(report.explanations.flatMap(item => item.issue_ids)).size);
	setText('pending-count', report.pending_checks.length);
	setText('drc-note', report.drc.count_note_zh);
	element('coverage').replaceChildren();
	for (const [name, entry] of Object.entries(context.coverage ?? {})) add(element('coverage'), 'span', `${label(name)}：${label(entry.status)}`, 'coverage-item');
	add(element('coverage'), 'p', '配置图层数量不等于铜层数。未采集不等于真实空集合；共享网络名不证明物理连通。');
	add(element('coverage'), 'p', '本工具检查 EDA 文档，不替代实体板电气、信号完整性或 EMC 测试。');
	rawDetails(element('coverage'), '版本与数据来源', report.provenance);
	renderDrc();
	element('explanations').replaceChildren(...report.explanations.map(explanationCard));
	if (!report.explanations.length)
		add(element('explanations'), 'p', '暂无通过校验的分析结果。');
	element('recommendations').replaceChildren(...report.pending_checks.map(explanationCard));
	element('references').replaceChildren();
	element('references-panel').hidden = report.knowledge_references.length === 0;
	for (const rule of report.knowledge_references) {
		const box = add(element('references'), 'div', '', 'item');
		add(box, 'strong', rule.title_zh);
		add(box, 'p', rule.summary_zh);
		add(box, 'p', `已取得：${rule.acquired_evidence.map(label).join('、') || '无'}；缺少：${rule.missing_evidence.map(label).join('、') || '需核对具体适用条件'}。${rule.applicability_zh}`);
		const link = document.createElement('a');
		link.textContent = '查看原始来源';
		if (rule.source.startsWith('https://')) {
			link.href = rule.source;
			link.target = '_blank';
			link.rel = 'noopener noreferrer';
		}
		box.append(link);
		rawDetails(box, '规则详情', { id: rule.id, source: rule.source, note_zh: '中文摘要为本项目整理，不是厂商原文逐字翻译。规则不替代本板证据。' });
	}
	element('analysis-process').replaceChildren();
	rawDetails(element('analysis-process'), '运行详情', { mode_zh: label(report.agent_mode), chinese_status_zh: label(report.chinese_status) });
	for (const step of report.analysis_trace) {
		const item = add(element('analysis-process'), 'div', `${step.display_name_zh} · ${label(step.origin)} · ${label(step.status)} · ${step.duration_ms.toFixed(1)} 毫秒：${step.summary_zh}`, 'process-step');
		rawDetails(item, '查看协议参数与证据标识', { tool: step.tool, arguments: step.arguments, evidence_ids: step.evidence_ids });
	}
	element('evidence').replaceChildren();
	rawDetails(element('evidence'), '查看全部快照证据（原始数据）', report.evidence);
	for (const rejected of report.rejected_conclusions) add(element('evidence'), 'p', `未采纳模型结论：${rejected.reason_zh}`);
	setText('comparison', report.comparison ? `${report.comparison.summary_zh} ${report.comparison.limitations_zh.join('；')}` : '暂无复查记录。');
	if (report.comparison)
		rawDetails(element('comparison'), '查看完整差异 ID 清单', report.comparison);
}

async function capture(token: number): Promise<void> {
	const fresh = await collectReviewContext();
	if (token !== generation)
		return;
	const previous = report?.provenance.document_id === fresh.provenance?.document_id ? report.snapshot_id : undefined;
	const next = await createReview(fresh, previous);
	if (token !== generation)
		return;
	context = fresh;
	report = next;
	page = 0;
	await eda.sys_Storage.setExtensionUserConfig(SESSION_KEY, JSON.stringify({ context, report }));
	if (token !== generation)
		return;
	render();
}

async function run(recheckOnly = false, repeat = false): Promise<void> {
	if (busy)
		return;
	setBusy(true);
	const token = ++generation;
	status(repeat ? '正在分析已保存数据' : '正在检查当前 PCB', repeat ? '使用上次检查结果，未重新运行 DRC。' : '');
	try {
		if (!repeat)
			await capture(token);
		if (token !== generation)
			return;
		if (!drcReady()) {
			status('检查未完成', drcFailureMessage());
			return;
		}
		if (recheckOnly) {
			status('复查已完成', report.comparison?.summary_zh ?? '');
			return;
		}
		const snapshot = report.snapshot_id;
		const started = parseSnapshotReport(await reviewApi(`/${snapshot}/analyze`, 'POST', { mode: 'auto' }));
		if (token !== generation) {
			await reviewApi(`/${snapshot}/cancel`, 'POST');
			return;
		}
		report = started;
		render();
		status('正在分析', '');
		while (report.agent_status === 'running') {
			if (token !== generation)
				return;
			await new Promise(resolve => setTimeout(resolve, 1200));
			const updated = await fetchReview(snapshot);
			if (token !== generation || report.snapshot_id !== snapshot)
				return;
			report = updated;
			render();
			status(report.agent_status === 'completed' ? '分析已完成' : report.agent_status === 'running' ? '正在分析' : label(report.agent_status), ['running', 'completed', 'cancelled'].includes(report.agent_status) ? '' : report.agent_message_zh);
		}
	}
	catch (error) {
		if (token === generation)
			status('检查未完成', errorText(error));
	}
	finally { setBusy(false); }
}

async function cancel(): Promise<void> {
	++generation;
	status('正在取消', 'DRC 检查进行中时，需等待检查结束。');
	try {
		if (report?.agent_status === 'running')
			await reviewApi(`/${report.snapshot_id}/cancel`, 'POST');
	}
	catch (error) {
		status('取消请求未确认', errorText(error));
		return;
	}
	status('分析已取消', '');
}

async function exportReport(): Promise<void> {
	try {
		const result = await reviewApi(`/${report.snapshot_id}/export`, 'POST');
		if (!record(result) || result.saved !== true || result.parsed_count !== report.drc.parsed_count)
			throw new Error('导出结果未通过文件与数量核验。');
		status('报告已导出', `保存位置：${String(result.directory)}`);
	}
	catch (error) { status('导出失败', errorText(error)); }
}

function initialize(): void {
	try {
		const stored: unknown = eda.sys_Storage.getExtensionUserConfig(SESSION_KEY);
		if (typeof stored !== 'string')
			throw new Error('没有当前实时快照，请从 PCB 菜单重新打开 AI 设计审查。');
		const session: unknown = JSON.parse(stored);
		if (!record(session) || !record(session.context) || session.context.schemaVersion !== 2)
			throw new Error('快照格式错误，请重新采集。');
		context = session.context as unknown as PCBContextV2;
		report = parseSnapshotReport(session.report);
		render();
		setBusy(false);
		status(drcReady() ? '检查结果已就绪' : '检查未完成', drcReady() ? '' : drcFailureMessage());
		element('analyze-button').addEventListener('click', () => {
			void run();
		});
		element('recheck-button').addEventListener('click', () => {
			void run(true);
		});
		element('repeat-button').addEventListener('click', () => {
			void run(false, true);
		});
		element('cancel-button').addEventListener('click', () => {
			void cancel();
		});
		element('export-button').addEventListener('click', () => {
			void exportReport();
		});
		element('previous-page').addEventListener('click', () => {
			page--;
			renderDrc();
		});
		element('next-page').addEventListener('click', () => {
			page++;
			renderDrc();
		});
	}
	catch (error) { status('加载失败', errorText(error)); }
}
initialize();
