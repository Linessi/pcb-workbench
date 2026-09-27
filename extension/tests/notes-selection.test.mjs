// Deterministic adapter tests only; not a substitute for EDA runtime evidence.
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { build } from 'esbuild';

const compiled = await build({ entryPoints: ['src/notes/selectionAdapter.ts'], bundle: true, write: false, format: 'iife', globalName: 'adapter', platform: 'browser' });
let project = 'A';
let duringCapture = false;
let selected = [];
let objects = [];
let lookup = new Map();
let actualSelection = [];
const context = vm.createContext({
	EPCB_PrimitiveType: { COMPONENT: 'Component', PAD: 'Pad', COMPONENT_PAD: 'ComponentPad' },
	eda: {
		dmt_Pcb: { getCurrentPcbInfo: async () => ({ uuid: 'shared-doc', parentProjectUuid: project, name: 'PCB' }) },
		dmt_Project: { getCurrentProjectInfo: async () => ({ uuid: project, friendlyName: 'same-name' }) },
		pcb_SelectControl: {
			getAllSelectedPrimitives: async () => {
				if (duringCapture)
					project = 'B';
				return selected;
			},
			clearSelected: async () => {
				actualSelection = [];
				return true;
			},
			doSelectPrimitives: async (ids) => {
				actualSelection = [...new Set([...actualSelection, ...ids])];
				return true;
			},
			getAllSelectedPrimitives_PrimitiveId: async () => actualSelection,
		},
		pcb_PrimitiveComponent: { get: async id => lookup.get(id) },
		pcb_PrimitivePad: { get: async id => lookup.get(id) },
	},
});
vm.runInContext(compiled.outputFiles[0].text, context);
const a = context.adapter;
function pad(id, number, x = 1) {
	return { getState_PrimitiveType: () => 'Pad', getState_PrimitiveId: () => id, getState_PadNumber: () => number, getState_Net: () => 'GND', getState_X: () => x, getState_Y: () => 2, getState_Rotation: () => 0, getState_Layer: () => 1 };
}
selected = [pad('p1', ''), pad('p2', ''), pad('p3', '1'), pad('p4', '1')];
const captured = await a.captureSelection();
assert.equal(new Set(captured.objects.map(o => o.primitive_id)).size, 4);
lookup = new Map(selected.map(o => [o.getState_PrimitiveId(), o]));
actualSelection = ['unrelated-component'];
await a.selectLinked(captured.identity, captured.objects);
assert.equal(actualSelection.length, 4);
assert.equal(actualSelection.includes('unrelated-component'), false);
lookup.delete('p1');
await assert.rejects(() => a.selectLinked(captured.identity, captured.objects), /删除|变化/);
lookup.set('p1', pad('p1', '', 999));
await assert.rejects(() => a.selectLinked(captured.identity, captured.objects), /变化/);
project = 'B';
await assert.rejects(() => a.selectLinked(captured.identity, captured.objects), /身份/);
project = 'A';
duringCapture = true;
await assert.rejects(() => a.captureSelection(), /采集期间/);
duringCapture = false;
selected = [];
objects = (await a.captureSelection()).objects;
assert.equal(objects.length, 0);
selected = [{ getState_PrimitiveType: () => 'Via', getState_PrimitiveId: () => 'via1' }];
assert.equal((await a.captureSelection()).unsupported, 1);
console.log('8 deterministic selection scenarios passed; EDA runtime remains a separate gate.');
