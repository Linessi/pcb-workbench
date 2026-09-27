/**
 * All EDA calls in stage two live here. Signatures are from the installed
 * @jlceda/pro-api-types index.d.ts (SDK 1.6.27 / types 0.4.23).
 */

export interface BoardSize {
	width: number;
	height: number;
}

export async function readCurrentPcb(): Promise<IDMT_PcbItem> {
	// DMT_Pcb.getCurrentPcbInfo(): Promise<IDMT_PcbItem | undefined>
	const pcb = await eda.dmt_Pcb.getCurrentPcbInfo();
	if (!pcb) {
		throw new Error('未检测到当前 PCB。请先打开 PCB 编辑页，再采集或检查。');
	}
	return pcb;
}

export async function readProjectName(pcb: IDMT_PcbItem): Promise<string> {
	// DMT_Project.getCurrentProjectInfo() and getProjectInfo(uuid) return the
	// documented friendlyName; the UUID check prevents a stale project label.
	const current = await eda.dmt_Project.getCurrentProjectInfo();
	if (current?.uuid === pcb.parentProjectUuid) {
		return current.friendlyName;
	}
	const project = await eda.dmt_Project.getProjectInfo(pcb.parentProjectUuid);
	if (!project) {
		throw new Error('无法读取当前 PCB 所属工程的名称。');
	}
	return project.friendlyName;
}

export async function readBoardSize(): Promise<BoardSize> {
	// The SDK has no direct board width/height API. Read line, arc and
	// polyline objects and use PCB_Primitive.getPrimitivesBBox. In EDA
	// V4.1.60, getAllPrimitiveId('', BOARD_OUTLINE) returned no usable IDs
	// even though getAll() returned a layer-11 polyline; filter the objects.
	const layer = EPCB_LayerId.BOARD_OUTLINE;
	const [lines, arcs, polylines] = await Promise.all([
		eda.pcb_PrimitiveLine.getAll(),
		eda.pcb_PrimitiveArc.getAll(),
		eda.pcb_PrimitivePolyline.getAll(),
	]);
	const outlinePolylines = polylines.filter(primitive => primitive.getState_Layer() === layer);
	const outlineLines = lines.filter(primitive => primitive.getState_Layer() === layer);
	const outlineArcs = arcs.filter(primitive => primitive.getState_Layer() === layer);
	const ids = [...new Set([...outlineLines, ...outlineArcs, ...outlinePolylines]
		.map(primitive => primitive.getState_PrimitiveId()))];
	if (ids.length === 0) {
		throw new Error('当前 PCB 没有可读取的板框图元，无法计算尺寸。');
	}
	if (ids.length === 1 && outlinePolylines.length === 1) {
		// IPCB_PrimitivePolyline.getState_Polygon() and
		// PCB_MathPolygon.calculateWidth/Height() measure its geometry without
		// the line stroke. The sample board is a single outline polyline.
		const polygon = outlinePolylines[0].getState_Polygon();
		return {
			width: eda.pcb_MathPolygon.calculateWidth(polygon),
			height: eda.pcb_MathPolygon.calculateHeight(polygon),
		};
	}
	// For mixed outline primitives, the documented BBox is the only unified
	// geometry API; its dimensions include the drawn stroke width.
	const bounds = await eda.pcb_Primitive.getPrimitivesBBox(ids);
	if (!bounds || ![bounds.minX, bounds.minY, bounds.maxX, bounds.maxY].every(Number.isFinite)) {
		throw new Error('板框图元的包围盒读取失败。');
	}
	return { width: bounds.maxX - bounds.minX, height: bounds.maxY - bounds.minY };
}

export async function readLayers(): Promise<Array<IPCB_LayerItem>> {
	// PCB_Layer.getAllLayers(): Promise<Array<IPCB_LayerItem>>
	// V4.1.60 also returns NOT_USED layer definitions (265 in the sample),
	// so retain only configured, visible or hidden layers.
	return (await eda.pcb_Layer.getAllLayers())
		.filter(layer => layer.layerStatus !== EPCB_LayerStatus.NOT_USED);
}

export async function readComponents(): Promise<Array<IPCB_PrimitiveComponent>> {
	// PCB_PrimitiveComponent.getAll(): Promise<Array<IPCB_PrimitiveComponent>>
	return eda.pcb_PrimitiveComponent.getAll();
}

export async function readNets(): Promise<string[]> {
	// PCB_Net.getAllNetsName(): Promise<Array<string>>
	return eda.pcb_Net.getAllNetsName();
}

export async function readComponentPins(component: IPCB_PrimitiveComponent): Promise<Array<IPCB_PrimitiveComponentPad>> {
	// IPCB_PrimitiveComponent.getAllPins(): Promise<Array<IPCB_PrimitiveComponentPad>>.
	return component.getAllPins();
}

export async function readVias(): Promise<Array<IPCB_PrimitiveVia>> {
	// PCB_PrimitiveVia.getAll(): Promise<Array<IPCB_PrimitiveVia>>.
	return eda.pcb_PrimitiveVia.getAll();
}

export async function readOutlinePrimitives(): Promise<{
	lines: IPCB_PrimitiveLine[];
	arcs: IPCB_PrimitiveArc[];
	polylines: IPCB_PrimitivePolyline[];
}> {
	// getAll() on each primitive class is declared in installed pro-api-types.
	const [lines, arcs, polylines] = await Promise.all([
		eda.pcb_PrimitiveLine.getAll(),
		eda.pcb_PrimitiveArc.getAll(),
		eda.pcb_PrimitivePolyline.getAll(),
	]);
	const layer = EPCB_LayerId.BOARD_OUTLINE;
	return {
		lines: lines.filter(item => item.getState_Layer() === layer),
		arcs: arcs.filter(item => item.getState_Layer() === layer),
		polylines: polylines.filter(item => item.getState_Layer() === layer),
	};
}

function isDrcRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** The beta DRC API returns nested groups in V4.1.60; keep leaf errors. */
function normalizeDrcDetails(details: unknown[]): string[] {
	const errors: string[] = [];
	function visit(value: unknown): void {
		if (Array.isArray(value)) {
			value.forEach(visit);
			return;
		}
		if (typeof value === 'string') {
			if (value.trim())
				errors.push(value);
			return;
		}
		if (!isDrcRecord(value))
			return;
		if (Array.isArray(value.list)) {
			value.list.forEach(visit);
			return;
		}
		if (typeof value.errorType !== 'string') {
			errors.push(JSON.stringify(value));
			return;
		}
		const objectLabel = (candidate: unknown): string => {
			if (!isDrcRecord(candidate))
				return '';
			return [candidate.typeName, candidate.suffix]
				.filter((part): part is string => typeof part === 'string' && part.length > 0)
				.join(' ');
		};
		const first = objectLabel(value.obj1);
		const second = objectLabel(value.obj2);
		const template = isDrcRecord(value.explanation) && typeof value.explanation.str === 'string'
			? value.explanation.str
			: '';
		const detail = template
			.replaceAll('{obj1}', first || 'object 1')
			.replaceAll('{obj2}', second || 'object 2');
		const net = typeof value.net === 'string' && value.net ? ` (net=${value.net})` : '';
		errors.push(`${value.errorType}${net}: ${detail || [first, second].filter(Boolean).join(' → ')}`);
	}
	visit(details);
	return errors;
}

export async function readDrc(): Promise<{ available: boolean; errors: string[]; reason?: string; raw?: unknown; execution?: Record<string, unknown> }> {
	const started = new Date().toISOString();
	let ruleConfiguration: unknown;
	let ruleName: string | undefined;
	let configurationStatus = 'unavailable';
	try {
		// Verified in types and installed V4.1.60 API runtime; optional read only.
		ruleName = await eda.pcb_Drc.getCurrentRuleConfigurationName();
		ruleConfiguration = await eda.pcb_Drc.getCurrentRuleConfiguration();
		if (isDrcRecord(ruleConfiguration) && isDrcRecord(ruleConfiguration.config) && Object.keys(ruleConfiguration.config).length > 0)
			configurationStatus = 'available';
	}
	catch { /* Missing optional rule read does not block DRC. */ }
	const execution = { started_at: started, scope: 'pcb_Drc.check(strict=true,includeVerboseError=true)', strict: true, rule_configuration: ruleConfiguration ?? null, rule_config_name: ruleName ?? null, rule_config_status: configurationStatus };
	try {
		// PCB_Drc.check(strict, userInterface, includeVerboseError), SDK 1.6.27.
		// Its detailed return type is Array<any>, so normalize at this boundary.
		const details: unknown[] = await eda.pcb_Drc.check(true, true, true);
		if (configurationStatus === 'available') {
			try {
				const afterRules: unknown = await eda.pcb_Drc.getCurrentRuleConfiguration();
				if (JSON.stringify(afterRules) !== JSON.stringify(ruleConfiguration)) {
					execution.rule_config_status = 'error';
					execution.rule_configuration = null;
				}
			}
			catch {
				execution.rule_config_status = 'unavailable';
				execution.rule_configuration = null;
			}
		}
		if (!Array.isArray(details)) {
			return { available: false, errors: [], raw: details, execution: { ...execution, status: 'error', finished_at: new Date().toISOString() }, reason: '原生 DRC 未返回错误列表，不能视为检查通过。' };
		}
		return {
			available: true,
			errors: normalizeDrcDetails(details),
			raw: details,
			execution: { ...execution, status: 'completed', finished_at: new Date().toISOString() },
		};
	}
	catch (error) {
		console.warn('EDA DRC unavailable', error);
		const elapsedMs = Date.now() - Date.parse(started);
		const message = error instanceof Error ? error.message : typeof error === 'string' ? error : '';
		const timedOut = /timeout|timed out|超时/i.test(message) || elapsedMs >= 299_000;
		return {
			available: false,
			errors: [],
			execution: { ...execution, status: 'error', finished_at: new Date().toISOString(), elapsed_ms: elapsedMs, failure_kind: timedOut ? 'timeout' : 'native_error' },
			reason: timedOut
				? 'EDA 原生 DRC 长时间未返回结果。请先关闭本窗口，在 EDA 中取消停滞的检查，再从“设计 → 检查DRC”重试；原生检查仍停滞时，保存工程并重启 EDA。'
				: 'EDA 原生 DRC 调用失败。请先从“设计 → 检查DRC”确认原生检查可完成，再点击“重新检查”。',
		};
	}
}
