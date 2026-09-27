import type { Identity, ObjectRef, Selection } from './types';
import { readCurrentPcb, readProjectName } from '../api/edaAdapter';

export function sameIdentity(a: Identity, b: Identity): boolean {
	return a.project_id === b.project_id && a.document_id === b.document_id;
}
export async function identity(): Promise<Identity> {
	const pcb = await readCurrentPcb();
	return { project_id: pcb.parentProjectUuid, document_id: pcb.uuid, project_name: await readProjectName(pcb), document_name: pcb.name };
}

/**
 * Installed types 0.4.23: PCB_SelectControl.getAllSelectedPrimitives();
 * IPCB_PrimitiveComponent / IPCB_Primitive(Component)Pad state getters.
 * Reads selected primitives only: no full PCB collection or DRC.
 */
export function objectRef(p: IPCB_Primitive): ObjectRef | undefined {
	const kind = p.getState_PrimitiveType();
	if (kind === EPCB_PrimitiveType.COMPONENT) {
		const c = p as IPCB_PrimitiveComponent;
		const label = c.getState_Designator() || c.getState_Name() || p.getState_PrimitiveId();
		return { primitive_id: p.getState_PrimitiveId(), kind: 'component', label, fingerprint: JSON.stringify([kind, label, c.getState_Component(), c.getState_X(), c.getState_Y(), c.getState_Rotation(), c.getState_Layer()]) };
	}
	if (kind === EPCB_PrimitiveType.PAD || kind === EPCB_PrimitiveType.COMPONENT_PAD) {
		const pad = p as IPCB_PrimitivePad;
		const parent = kind === EPCB_PrimitiveType.COMPONENT_PAD ? (p as IPCB_PrimitiveComponentPad).getState_ParentComponentPrimitiveId() : '';
		return { primitive_id: p.getState_PrimitiveId(), kind: 'pad', label: `焊盘 ${pad.getState_PadNumber() || '空编号'} · ${p.getState_PrimitiveId()}`, fingerprint: JSON.stringify([kind, parent, pad.getState_PadNumber(), pad.getState_Net(), pad.getState_X(), pad.getState_Y(), pad.getState_Rotation(), pad.getState_Layer()]) };
	}
	return undefined;
}

export async function captureSelection(): Promise<Selection> {
	const before = await identity();
	const primitives = await eda.pcb_SelectControl.getAllSelectedPrimitives();
	const objects = primitives.map(objectRef).filter((p): p is ObjectRef => p !== undefined);
	const after = await identity();
	if (!sameIdentity(before, after))
		throw new Error('采集期间切换了工程，请回到目标 PCB 后重新新建便签。');
	return { identity: before, objects, unsupported: primitives.length - objects.length };
}

export async function selectLinked(source: Identity, objects: ObjectRef[]): Promise<void> {
	if (!sameIdentity(source, await identity()))
		throw new Error('当前工程身份与记录来源不同，拒绝选择。手工关联便签本不会自动重新绑定对象。');
	if (!objects.length)
		throw new Error('这是整板便签。可在“更多”中关联当前选中的元件或焊盘。');
	for (const old of objects) {
		// Installed get(id) methods. Component pad resolution must return the real
		// primitive ID; no designator/pad-number fallback (numbers can be empty).
		const p = old.kind === 'component' ? await eda.pcb_PrimitiveComponent.get(old.primitive_id) : await eda.pcb_PrimitivePad.get(old.primitive_id);
		const live = p ? objectRef(p) : undefined;
		if (!live || live.primitive_id !== old.primitive_id || live.kind !== old.kind || live.fingerprint !== old.fingerprint)
			throw new Error('关联对象已变化、已删除或无法可靠映射，已拒绝选择；历史记录仍保留。');
	}
	if (!sameIdentity(source, await identity()))
		throw new Error('选择前工程发生变化，已拒绝选择。');
	const ids = objects.map(o => o.primitive_id);
	// pro-api-types 0.4.23: doSelectPrimitives adds to the selection;
	// clearSelected() must precede it so unrelated parts are not left selected.
	if (!await eda.pcb_SelectControl.clearSelected())
		throw new Error('未能清除原选区，请重试。');
	if (!sameIdentity(source, await identity()))
		throw new Error('选择前工程发生变化，已拒绝选择。');
	if (!await eda.pcb_SelectControl.doSelectPrimitives(ids))
		throw new Error('EDA 未确认选择成功。');
	const selected = await eda.pcb_SelectControl.getAllSelectedPrimitives_PrimitiveId();
	if (!sameIdentity(source, await identity()) || selected.length !== new Set(ids).size || !ids.every(id => selected.includes(id)))
		throw new Error('实际选中集合核验未通过。');
}
