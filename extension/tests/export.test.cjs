const assert = require('node:assert/strict');
const test = require('node:test');
const vm = require('node:vm');
const esbuild = require('esbuild');

const source = esbuild.buildSync({ entryPoints: ['src/utils/export.ts'], bundle: true, write: false, format: 'iife', globalName: 'exportsApi', platform: 'browser' }).outputFiles[0].text;
function api(body, ok = true) {
	const sandbox = { eda: { sys_ClientUrl: { request: async () => ({ ok, status: ok ? 200 : 500, json: async () => body }) } } };
	vm.runInNewContext(source, sandbox);
	return sandbox.exportsApi;
}
test('context export accepts the backend location on another machine', async () => {
	const result = await api({ saved: true, path: '/application/output/pcb.json' }).exportPCBContextV2({});
	assert.equal(result.location, '/application/output/pcb.json');
	assert.equal(result.method, 'backend');
});
test('context export rejects missing location or failed save', async () => {
	for (const body of [{ saved: false, path: '/output/a.json' }, { saved: true }, { saved: true, path: '' }])
		await assert.rejects(api(body).exportPCBContextV2({}), /无法自动保存/);
	await assert.rejects(api({ saved: true, path: '/output/a.json' }, false).exportPCBContextV2({}), /无法自动保存/);
});
