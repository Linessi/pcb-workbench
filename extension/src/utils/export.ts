import type { PCBContext, PCBContextV2 } from '../types/pcbContext';

const OUTPUT_FILENAME = 'pcb_context.json';

export interface ExportResult {
	location: string;
	method: 'direct' | 'save-dialog' | 'backend';
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Write V2 through the local backend's fixed output path; never open Save As. */
export async function exportPCBContextV2(context: PCBContextV2): Promise<ExportResult> {
	let response: Response;
	try {
		// SYS_ClientUrl.request() is declared in installed pro-api-types and
		// requires External Interaction permission, already used for AI review.
		response = await eda.sys_ClientUrl.request(
			'http://127.0.0.1:8000/api/save_context',
			'POST',
			JSON.stringify(context),
			{ headers: { 'Content-Type': 'application/json' } },
		);
	}
	catch (error) {
		const detail = error instanceof Error ? error.message : String(error);
		throw new Error(`无法连接本地 Backend 保存 PCB Context：${detail}。请确认服务已启动，并启用“允许外部交互”。`);
	}
	let body: unknown;
	try {
		body = await response.json();
	}
	catch {
		throw new Error(`保存 PCB Context 时 Backend 返回了非 JSON 响应（HTTP ${response.status}）。`);
	}
	if (!response.ok || !isRecord(body) || body.saved !== true || typeof body.path !== 'string' || !body.path.trim()) {
		const detail = isRecord(body) && typeof body.detail === 'string' ? body.detail : `HTTP ${response.status}`;
		throw new Error(`无法自动保存 PCB 数据：${detail}`);
	}
	return { location: body.path, method: 'backend' };
}

/**
 * The desktop-only file-system API needs the extension's External Interaction
 * permission. If it is unavailable, use the SDK's normal Save As API.
 */
export async function exportPCBContext(context: PCBContext): Promise<ExportResult> {
	const json = `${JSON.stringify(context, null, 2)}\n`;
	const file = new Blob([json], { type: 'application/json;charset=utf-8' });
	// SYS_FileSystem.saveFile: documented browser download / Electron Save As.
	await eda.sys_FileSystem.saveFile(file, OUTPUT_FILENAME);
	return { location: OUTPUT_FILENAME, method: 'save-dialog' };
}
