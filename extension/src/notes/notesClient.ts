const ROOT = 'http://127.0.0.1:8000/api';
export async function request(path: string, method: 'GET' | 'POST' | 'PATCH' = 'GET', body?: unknown): Promise<Response> {
	try {
		// Verified SYS_ClientUrl request bridge, not browser fetch/CORS wildcard.
		return await eda.sys_ClientUrl.request(`${ROOT}${path}`, method, body === undefined ? undefined : JSON.stringify(body), { headers: { 'Content-Type': 'application/json', 'X-PCB-Notes': '1' } });
	}
	catch { throw new Error('尚未保存到本机服务：请检查后端与外部交互权限。当前输入仍保留。'); }
}
export async function api<T>(path: string, method: 'GET' | 'POST' | 'PATCH' = 'GET', body?: unknown): Promise<T> {
	const response = await request(path, method, body);
	const data: unknown = await response.json();
	if (!response.ok) {
		const detail = data && typeof data === 'object' && 'detail' in data ? String(data.detail) : '本机服务返回异常';
		throw new Error(detail);
	}
	return data as T;
}
