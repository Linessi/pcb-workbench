import type { PCBConnection, PCBContext, PCBContextV2, PCBHole, PCBOutlinePrimitive, PCBPad } from '../types/pcbContext';
import {
	readBoardSize,
	readComponentPins,
	readComponents,
	readCurrentPcb,
	readDrc,
	readLayers,
	readNets,
	readOutlinePrimitives,
	readProjectName,
	readVias,
} from '../api/edaAdapter';

/** Collects the current PCB through documented EDA APIs only. */
export async function collectPCBContext(): Promise<PCBContext> {
	const pcb = await readCurrentPcb();
	const projectName = await readProjectName(pcb);
	const board = await readBoardSize();
	const layers = await readLayers();
	const primitives = await readComponents();
	const netNames = await readNets();

	if (!(board.width > 0 && board.height > 0)) {
		throw new Error('板框尺寸无效，未生成 PCB Context。');
	}

	const components = primitives.map((component) => {
		// IPCB_PrimitiveComponent has no getState_Value(). The installed SDK
		// documents both getState_OtherProperty()['Value'] and getState_Name().
		// KiCad-imported footprints in EDA V4.1.60 store fp_text value as Name;
		// use it when the explicit Value property is absent.
		const rawValue = component.getState_OtherProperty()?.Value;
		const value = rawValue === undefined || rawValue === null ? '' : String(rawValue).trim();
		return {
			reference: component.getState_Designator() ?? '',
			value: value || component.getState_Name()?.trim() || '',
			package: component.getState_Footprint()?.name ?? '',
		};
	});
	components.sort((a, b) => a.reference.localeCompare(b.reference, undefined, { numeric: true }));
	const nets = [...new Set(netNames)].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));

	return {
		projectName,
		board: {
			width: board.width,
			height: board.height,
			layers: layers.map(layer => layer.name),
		},
		components,
		nets,
		statistics: {
			componentCount: components.length,
			netCount: nets.length,
		},
	};
}

/** Context V2 preserves the V1 fields and adds SDK-backed board evidence. */
export async function collectPCBContextV2(): Promise<PCBContextV2> {
	// Run native DRC first; all subsequent evidence belongs to this collection.
	const checkedDrc = await readDrc();
	const base = await collectPCBContext();
	const primitives = await readComponents();
	const layerNames = new Map((await readLayers()).map(layer => [layer.id, layer.name]));
	const components = primitives.map((item) => {
		const original = base.components.find(component => component.reference === (item.getState_Designator() ?? ''));
		return {
			primitiveId: item.getState_PrimitiveId(),
			reference: original?.reference ?? item.getState_Designator() ?? '',
			value: original?.value ?? '',
			package: original?.package ?? '',
			x: item.getState_X(),
			y: item.getState_Y(),
			rotation: item.getState_Rotation(),
			layer: layerNames.get(item.getState_Layer()) ?? String(item.getState_Layer()),
		};
	}).sort((a, b) => a.reference.localeCompare(b.reference, undefined, { numeric: true }));
	const padGroups: Array<Array<{ reference: string; pin: IPCB_PrimitiveComponentPad }>> = [];
	for (const component of primitives) {
		const reference = component.getState_Designator() ?? '';
		const pins = await readComponentPins(component);
		padGroups.push(pins.map(pin => ({ reference, pin })));
	}
	const pads: PCBPad[] = [];
	const holes: PCBHole[] = [];
	for (const { reference, pin } of padGroups.flat()) {
		const number = pin.getState_PadNumber();
		const x = pin.getState_X();
		const y = pin.getState_Y();
		pads.push({ primitiveId: pin.getState_PrimitiveId(), component: reference, number, x, y, net: pin.getState_Net() ?? '' });
		const hole = pin.getState_Hole();
		if (hole) {
			holes.push({
				source: 'pad',
				shape: hole[0] === EPCB_PrimitivePadHoleType.ROUND ? 'round' : 'slot',
				width: hole[1],
				height: hole[2] ?? hole[1],
				x: x + pin.getState_HoleOffsetX(),
				y: y + pin.getState_HoleOffsetY(),
				component: reference,
				padNumber: number,
			});
		}
	}
	pads.sort((a, b) => `${a.component}.${a.number}`.localeCompare(`${b.component}.${b.number}`, undefined, { numeric: true }));
	const byNet = new Map<string, PCBPad[]>();
	for (const pad of pads) {
		if (pad.net.trim()) {
			const group = byNet.get(pad.net) ?? [];
			group.push(pad);
			byNet.set(pad.net, group);
		}
	}
	const connections: PCBConnection[] = [];
	for (const [net, group] of byNet) {
		// A spanning star records logical membership without implying every pair is routed.
		for (const target of group.slice(1)) {
			connections.push({ source: `${group[0].component}.${group[0].number}`, target: `${target.component}.${target.number}`, net, basis: 'shared_net_name' });
		}
	}
	const viaPrimitives = await readVias();
	const vias = viaPrimitives.map(item => ({
		x: item.getState_X(),
		y: item.getState_Y(),
		net: item.getState_Net(),
		diameter: item.getState_Diameter(),
		holeDiameter: item.getState_HoleDiameter(),
	}));
	for (const via of vias) {
		if (via.holeDiameter > 0) {
			holes.push({ source: 'via', shape: 'round', x: via.x, y: via.y, width: via.holeDiameter, height: via.holeDiameter });
		}
	}
	const outlinePrimitives = await readOutlinePrimitives();
	const outline: PCBOutlinePrimitive[] = [
		...outlinePrimitives.lines.map(item => ({
			primitiveId: item.getState_PrimitiveId(),
			kind: 'line' as const,
			points: [{ x: item.getState_StartX(), y: item.getState_StartY() }, { x: item.getState_EndX(), y: item.getState_EndY() }],
		})),
		...outlinePrimitives.arcs.map(item => ({
			primitiveId: item.getState_PrimitiveId(),
			kind: 'arc' as const,
			points: [{ x: item.getState_StartX(), y: item.getState_StartY() }, { x: item.getState_EndX(), y: item.getState_EndY() }],
			arcAngle: item.getState_ArcAngle(),
		})),
	];
	for (const item of outlinePrimitives.polylines) {
		// EDA V4.1.60 declares IPCB_Polygon.discretize(), but its runtime
		// throws "Not implemented". getSource() preserves the exact native
		// geometry and is declared in the same installed SDK types.
		const source = item.getState_Polygon().getSource();
		outline.push({ primitiveId: item.getState_PrimitiveId(), kind: 'polyline', source });
	}
	return {
		...base,
		schemaVersion: 2,
		components,
		pads,
		connections,
		drc: checkedDrc,
		geometry: { outline, holes, vias },
	};
}
