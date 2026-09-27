const assert = require('node:assert/strict');
const test = require('node:test');
const vm = require('node:vm');
const esbuild = require('esbuild');

const source = esbuild.buildSync({ entryPoints: ['src/api/edaAdapter.ts'], bundle: true, write: false, format: 'iife', globalName: 'adapter', platform: 'browser' }).outputFiles[0].text;
function adapter(check) {
	const sandbox = {
		console: { warn() {} },
		eda: { pcb_Drc: {
			getCurrentRuleConfigurationName: async () => 'test',
			getCurrentRuleConfiguration: async () => ({ config: { clearance: 6 } }),
			check,
		} },
	};
	vm.runInNewContext(source, sandbox);
	return sandbox.adapter;
}
test('native timeout remains unavailable and gives recovery steps', async () => {
	let calls = 0;
	const result = await adapter(async (...args) => {
		calls++;
		assert.deepEqual(args, [true, true, true]);
		// SDK failures can reject with a string; exercise that boundary explicitly.
		// eslint-disable-next-line prefer-promise-reject-errors
		return Promise.reject('Request timeout');
	}).readDrc();
	assert.equal(result.available, false);
	assert.equal(result.execution.failure_kind, 'timeout');
	assert.match(result.reason, /重启 EDA/);
	assert.equal(calls, 1);
});
test('native zero errors must come from a successful array response', async () => {
	const result = await adapter(async () => []).readDrc();
	assert.equal(result.available, true);
	assert.equal(result.execution.status, 'completed');
	assert.equal(result.errors.length, 0);
	const malformed = await adapter(async () => true).readDrc();
	assert.equal(malformed.available, false);
	assert.equal(malformed.execution.status, 'error');
});
test('other native failures do not become zero errors or timeout', async () => {
	const result = await adapter(async () => Promise.reject(new Error('native engine failed'))).readDrc();
	assert.equal(result.available, false);
	assert.equal(result.execution.failure_kind, 'native_error');
	assert.match(result.reason, /重新检查/);
});
