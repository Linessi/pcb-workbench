import type { PCBContextV2 } from '../types/pcbContext';
import type { DrcIssue, SnapshotReport } from '../types/review';
import { readComponents, readCurrentPcb } from './edaAdapter';

/** No model names are used: only exact IDs mapped from native DRC and snapshot. */
export async function selectIssueObjects(report: SnapshotReport, context: PCBContextV2, issueId: string): Promise<{ primitive_ids: string[]; detail_zh: string }> {
	if (report.source_kind !== 'eda_live' || report.provenance.document_id !== context.provenance?.document_id)
		throw new Error('历史或不一致快照不能定位，请重新检查当前 PCB。');
	const pcb = await readCurrentPcb();
	if (pcb.uuid !== report.provenance.document_id || pcb.parentProjectUuid !== report.provenance.project_id)
		throw new Error('当前 PCB 与报告不一致，已拒绝跨文档定位。');
	const issue: DrcIssue | undefined = report.drc.issues.find(item => item.id === issueId);
	if (!issue)
		throw new Error('当前快照没有该原生 DRC 标识。');
	const components = await readComponents();
	const liveIds = new Set<string>();
	let changed = components.length !== context.components.length;
	let padCount = 0;
	for (const item of components) {
		liveIds.add(item.getState_PrimitiveId());
		const original = context.components.find(part => part.primitiveId === item.getState_PrimitiveId());
		if (!original || original.x !== item.getState_X() || original.y !== item.getState_Y() || original.rotation !== item.getState_Rotation() || original.reference !== (item.getState_Designator() ?? ''))
			changed = true;
		const pins = await item.getAllPins();
		padCount += pins.length;
		for (const pin of pins) {
			liveIds.add(pin.getState_PrimitiveId());
			const old = context.pads.find(pad => pad.primitiveId === pin.getState_PrimitiveId());
			if (!old || old.x !== pin.getState_X() || old.y !== pin.getState_Y() || old.number !== pin.getState_PadNumber() || old.net !== (pin.getState_Net() ?? ''))
				changed = true;
		}
	}
	if (changed || padCount !== context.pads.length)
		throw new Error('元件或焊盘证据已变化，报告可能过期，请重新检查。当前没有完整文档修订监测。');
	let ids = issue.objects.filter(obj => obj.primitive_id && liveIds.has(obj.primitive_id)).map(obj => obj.primitive_id as string);
	let scope = '原生证据映射的准确对象';
	if (!ids.length) {
		ids = issue.objects.filter(obj => obj.kind === 'pad').flatMap((obj) => {
			const pad = context.pads.find(item => `${item.component}.${item.number}` === obj.object_id);
			const component = context.components.find(item => item.reference === pad?.component);
			return component?.primitiveId && liveIds.has(component.primitiveId) ? [component.primitiveId] : [];
		});
		scope = '相关焊盘所属元件（不是精确焊盘位置）';
	}
	ids = [...new Set(ids)];
	if (!ids.length)
		throw new Error('未取得可靠图元映射，请在原生 DRC 面板按网络和原文定位。');
	// Official PCB_SelectControl.doSelectPrimitives(ids): Promise<boolean>.
	const selected = await eda.pcb_SelectControl.doSelectPrimitives(ids);
	if (selected !== true)
		throw new Error('EDA 未确认选择成功，请使用原生 DRC 面板定位。');
	// Verify the actual selected set; do not equate selection with zooming.
	const actual = await eda.pcb_SelectControl.getAllSelectedPrimitives_PrimitiveId();
	if (!ids.every(id => actual.includes(id)))
		throw new Error('选择返回成功，但当前选中集合未包含所有目标对象，请在原生 DRC 面板复核。');
	return { primitive_ids: ids, detail_zh: `已选择${scope}；未执行缩放。快照时间 ${String(report.provenance.collected_at)}。` };
}
