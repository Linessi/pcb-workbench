// Synthetic UI/SDK tests; not evidence of a real EDA client installation.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');
const esbuild = require('esbuild');

class Element {
	constructor(tag) {
		this.tag = tag;
		this.children = [];
		this.listeners = {};
		this.textContent = '';
	}

	append(...nodes) { this.children.push(...nodes); }
	replaceChildren(...nodes) { this.children = nodes; }
	addEventListener(name, listener) { this.listeners[name] = listener; }
	set innerHTML(_value) { throw new Error('Untrusted HTML rendering prohibited'); }
	get innerHTML() { throw new Error('HTML is not used in this synthetic harness'); }
}
function fixture(count = 23) {
	const context = { schemaVersion: 2, projectName: '合成测试板', board: { width: 1000, height: 1000, layers: Array.from({ length: 31 }).fill('测试配置层') }, components: [{ reference: 'U1', primitiveId: 'c1', value: '合成', package: '测试', x: 0, y: 0, rotation: 0, layer: '顶层' }], pads: [{ primitiveId: 'p1', component: 'U1', number: '1', net: 'TEST', x: 0, y: 0 }], nets: ['TEST'], connections: [], drc: { available: true, errors: [] }, provenance: { document_id: 'synthetic-document', project_id: 'synthetic-project', collected_at: '2026-09-26T00:00:00Z', test_type: 'synthetic' }, coverage: { traces: { status: 'not_collected' } } };
	const issues = Array.from({ length: count }, (_, i) => ({ id: `drc-synthetic-${i}`, raw: {}, raw_message: 'original unconnected', source_path: `$.synthetic[${i}]`, category: 'Connection Error', native_severity: null, priority: 'high', priority_reason_zh: '本系统处理优先级', message_zh: `原生检查测试说明 ${i} <img src=x onerror=alert(1)>`, objects: [{ object_id: 'U1.1', primitive_id: 'p1', kind: 'pad' }], net: 'TEST', location_scope: 'exact' }));
	const report = { version: '0.7.0', snapshot_id: 'a'.repeat(32), source_kind: 'synthetic', provenance: context.provenance, summary_zh: '合成测试的完整清单', drc: { status: 'completed', native_count: count, parsed_count: count, issues, groups: [{ category: 'Connection Error', net: 'TEST', issue_ids: issues.map(i => i.id), count }], unknown_results: [], count_note_zh: '完整保留' }, explanations: [], pending_checks: [], evidence: [], analysis_trace: [], knowledge_references: [], agent_status: 'not_run', agent_mode: 'not_run', agent_message_zh: '未运行', chinese_status: 'passed', rejected_conclusions: [], comparison: null };
	return { context, report };
}
function panel(session, request = async () => {
	throw new Error('Unexpected request');
}) {
	const nodes = new Map();
	const sandbox = { document: { getElementById(id) {
		if (!nodes.has(id))
			nodes.set(id, new Element('div'));
		return nodes.get(id);
	}, createElement(tag) { return new Element(tag); } }, eda: { sys_Storage: { getExtensionUserConfig: () => JSON.stringify(session) }, sys_ClientUrl: { request } }, console, setTimeout };
	vm.runInNewContext(fs.readFileSync('dist/panel.js', 'utf8'), sandbox);
	return nodes;
}
function selectionModule(eda) {
	const source = esbuild.buildSync({ entryPoints: ['src/api/selection.ts'], bundle: true, write: false, format: 'iife', globalName: 'selection', platform: 'browser' }).outputFiles[0].text;
	const sandbox = { eda };
	vm.runInNewContext(source, sandbox);
	return sandbox.selection;
}

test('分页覆盖全部原生明细且首屏总数不被分页改变', () => {
	const nodes = panel(fixture());
	assert.equal(nodes.get('native-count').textContent, '23');
	assert.equal(nodes.get('risk-count').textContent, '23');
	assert.equal(nodes.get('risks').children.length, 10);
	nodes.get('next-page').listeners.click();
	assert.equal(nodes.get('risks').children.length, 10);
	nodes.get('next-page').listeners.click();
	assert.equal(nodes.get('risks').children.length, 3);
	assert.equal(nodes.get('native-count').textContent, '23');
	assert.ok(nodes.get('next-page').disabled);
	assert.ok(nodes.get('coverage').children.some(node => /配置图层数量不等于铜层数/.test(node.textContent)));
});
test('DRC 不可信文本只作为字面文本渲染', () => {
	const nodes = panel(fixture(1));
	const card = nodes.get('risks').children[0];
	assert.ok(card.children.some(node => node.textContent.includes('<img src=x')));
	assert.equal(card.children.filter(node => node.tag === 'img').length, 0);
});
test('原生 DRC 失败不显示通过或零问题', () => {
	const session = fixture(0);
	session.report.drc.status = 'error';
	session.report.drc.native_count = null;
	const nodes = panel(session);
	assert.equal(nodes.get('native-count').textContent, '不可确定');
	assert.match(nodes.get('risks').children[0].textContent, /原生 DRC 未完整取得/);
	assert.equal(nodes.get('status').textContent, '检查未完成');
	assert.doesNotMatch(nodes.get('risks').children[0].textContent, /未报告问题/);
});
test('DRC 失败展示具体原因，重新分析不发送模型请求', async () => {
	const session = fixture(0);
	session.report.drc.status = 'error';
	session.report.drc.native_count = null;
	session.context.drc.reason = 'EDA 原生 DRC 长时间未返回结果。';
	let calls = 0;
	const nodes = panel(session, async () => {
		calls++;
		throw new Error('Must not call model');
	});
	assert.equal(nodes.get('risks').children[0].textContent, session.context.drc.reason);
	nodes.get('repeat-button').listeners.click();
	await new Promise(resolve => setImmediate(resolve));
	assert.equal(calls, 0);
	assert.equal(nodes.get('status').textContent, '检查未完成');
});
test('完整且无错误的 DRC 才显示未报告问题', () => {
	const nodes = panel(fixture(0));
	assert.match(nodes.get('risks').children[0].textContent, /检查完成，未报告问题/);
	assert.equal(nodes.get('status').textContent, '检查结果已就绪');
});
test('跨文档与历史快照定位被拒绝', async () => {
	const session = fixture(1);
	session.report.source_kind = 'eda_live';
	let selections = 0;
	const module = selectionModule({ dmt_Pcb: { getCurrentPcbInfo: async () => ({ uuid: 'wrong-document' }) }, pcb_SelectControl: { doSelectPrimitives: async () => {
		selections++;
		return true;
	} } });
	await assert.rejects(module.selectIssueObjects(session.report, session.context, session.report.drc.issues[0].id), /拒绝跨文档/);
	session.report.source_kind = 'historical_replay';
	await assert.rejects(module.selectIssueObjects(session.report, session.context, session.report.drc.issues[0].id), /历史/);
	assert.equal(selections, 0);
});
test('已删除对象被拒绝；选择成功必须核对实际选中集合', async () => {
	const session = fixture(1);
	session.report.source_kind = 'eda_live';
	const pin = { getState_PrimitiveId: () => 'p1', getState_X: () => 0, getState_Y: () => 0, getState_PadNumber: () => '1', getState_Net: () => 'TEST' };
	const part = { getState_PrimitiveId: () => 'c1', getState_X: () => 0, getState_Y: () => 0, getState_Rotation: () => 0, getState_Designator: () => 'U1', getAllPins: async () => [pin] };
	const eda = { dmt_Pcb: { getCurrentPcbInfo: async () => ({ uuid: 'synthetic-document', parentProjectUuid: 'synthetic-project' }) }, pcb_PrimitiveComponent: { getAll: async () => [] }, pcb_SelectControl: { doSelectPrimitives: async () => true, getAllSelectedPrimitives_PrimitiveId: async () => [] } };
	const module = selectionModule(eda);
	await assert.rejects(module.selectIssueObjects(session.report, session.context, session.report.drc.issues[0].id), /过期/);
	eda.pcb_PrimitiveComponent.getAll = async () => [part];
	await assert.rejects(module.selectIssueObjects(session.report, session.context, session.report.drc.issues[0].id), /未包含/);
	eda.pcb_SelectControl.getAllSelectedPrimitives_PrimitiveId = async () => ['p1'];
	const selected = await module.selectIssueObjects(session.report, session.context, session.report.drc.issues[0].id);
	assert.match(selected.detail_zh, /未执行缩放/);
	assert.deepEqual(Array.from(selected.primitive_ids), ['p1']);
});
