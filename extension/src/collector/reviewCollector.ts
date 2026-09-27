import type { PCBContextV2 } from '../types/pcbContext';
import manifest from '../../extension.json';
import { readCurrentPcb } from '../api/edaAdapter';
import { collectPCBContextV2 } from './pcbCollector';

/** Uses only the same SDK APIs as V2 plus documented runtime version read. */
export async function collectReviewContext(): Promise<PCBContextV2> {
	const before = await readCurrentPcb();
	const started = new Date().toISOString();
	const context = await collectPCBContextV2();
	const after = await readCurrentPcb();
	if (before.uuid !== after.uuid || before.parentProjectUuid !== after.parentProjectUuid)
		throw new Error('采集期间 PCB 文档发生切换，请重新检查当前文档。');
	let runtimeVersion = '未取得';
	try {
		// SYS_Environment.getEditorCurrentVersion is declared and present in
		// V4.1.60 runtime; client acceptance records the actual returned string.
		runtimeVersion = eda.sys_Environment.getEditorCurrentVersion();
	}
	catch { /* Optional metadata; never guess a runtime version. */ }
	context.provenance = {
		document_id: after.uuid,
		project_id: after.parentProjectUuid,
		pcb_name: after.name,
		collected_at: new Date().toISOString(),
		collection_started_at: started,
		plugin_version: manifest.version,
		runtime_version: runtimeVersion,
		sdk_types_version: '0.4.23',
		data_source: '嘉立创 EDA 当前 PCB SDK 与原生 DRC',
		coordinate_unit: 'mil',
		display_unit: 'mm',
		consistency_zh: '采集前后核对当前文档；无可靠文档修订号。检查时请暂停编辑，定位前会再次检查对象。',
	};
	context.coverage = {};
	for (const key of ['components', 'pads', 'nets', 'outline', 'vias'])
		context.coverage[key] = { status: 'available' };
	context.coverage.native_drc = { status: context.drc.available ? 'available' : 'error' };
	for (const key of ['traces', 'copper', 'stackup', 'design_current', 'impedance', 'schematic', 'operating_frequency'])
		context.coverage[key] = { status: 'not_collected', reason_zh: '本版本未采集此项，不能解释为真实空集合。' };
	return context;
}
