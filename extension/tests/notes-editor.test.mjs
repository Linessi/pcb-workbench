// Controlled asynchronous UI regression. This does not count as plugin clicking.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { build } from 'esbuild';

const nodes = new Map();
function node() {
	return {
		value: '',
		textContent: '',
		children: [],
		dataset: {},
		scrollTop: 0,
		hidden: false,
		append(n) {
			this.children.push(n);
		},
		replaceChildren() {
			this.children = [];
			this.scrollTop = 0;
		},
		setAttribute() {},
	};
}
function get(id) {
	if (!nodes.has(id))
		nodes.set(id, node());
	return nodes.get(id);
}
let handler;
const calls = [];
let confirmations = 0;
let allowConfirmation = true;
const source = `${fs.readFileSync('src/notes/app.ts', 'utf8').split('on(\'new\', newNote);')[0].replace('import { api, request } from \'./notesClient\';', '')
}\nexport { openNote, authorizeCloud, submitNotes, renderList, scopePreview, pollJobs };
export function inspect() { return {editor, dirty, checked:[...checked]}; }
export function configure(value) { if(value.board)board=value.board;if(value.provider)provider=value.provider;if(value.notes)notes=value.notes;if(value.checked){checked.clear();value.checked.forEach(x=>checked.add(x));} }
`;
const compiled = await build({ stdin: { contents: source, resolveDir: `${process.cwd()}/src/notes`, loader: 'ts' }, bundle: true, write: false, format: 'iife', globalName: 'subject' });
const context = vm.createContext({
	document: { getElementById: get, createElement: node, querySelectorAll: () => [] },
	crypto: { randomUUID: () => 'test-id' },
	structuredClone,
	setTimeout,
	clearTimeout,
	api: async (...args) => {
		calls.push(args);
		return handler(...args);
	},
	eda: { sys_Storage: { setExtensionUserConfig: async () => true }, sys_Dialog: { showConfirmationMessage: (...args) => {
		confirmations++;
		args.at(-1)(allowConfirmation);
	} } },
});
vm.runInContext(compiled.outputFiles[0].text, context);
const a = context.subject;
const identity = { project_id: 'p', document_id: 'd', project_name: 'P', document_name: 'D' };
function note(id, attachments = []) {
	return { id, board_key: 'board', identity, objects: [], title: id, entries: [{ id: `${id}-entry`, kind: 'initial', revision: 1, revisions: [{ body: `${id} text`, attachment_ids: attachments }] }] };
}

// Reproduce late attachment responses after opening another note.
let release;
handler = () => new Promise((resolve) => {
	release = resolve;
});
const opening = a.openNote(note('first', ['photo']));
await new Promise(resolve => setImmediate(resolve));
await a.openNote(note('second'));
release({ id: 'photo', name: 'first.png' });
await opening;
assert.equal(a.inspect().editor.note.id, 'second');
assert.equal(a.inspect().editor.attachments.length, 0);
assert.equal(get('title').value, 'second');

// Saved image rendering must keep the Data URL header on one line.
handler = () => ({ id: 'photo', name: '图片.png', extension: 'png', data: 'YWJj', caption: '' });
await a.openNote(note('with-image', ['photo']));
const renderedImage = get('attachments').children[0].children.find(n => n.src);
assert.equal(renderedImage.src, 'data:image/png;base64,YWJj');
assert.equal(/[\r\n]/.test(renderedImage.src), false);

// Board A's persisted approval must not approve board B.
handler = path => ({ cloud_confirmed: path.endsWith('board-A') });
assert.equal(await a.authorizeCloud('deepseek', 'board-A'), true);
assert.equal(confirmations, 0);
allowConfirmation = false;
assert.equal(await a.authorizeCloud('deepseek', 'board-B'), false);
assert.equal(confirmations, 1);
assert.equal(await a.authorizeCloud('local', 'board-B'), true);

// Selection changed while confirmation is pending must not change submitted provider.
allowConfirmation = true;
handler = (path, method, payload) => {
	if (path.startsWith('/notes-provider')) {
		a.configure({ provider: 'local' });
		return { cloud_confirmed: true };
	}
	return { id: 'job', config: { provider: payload.provider } };
};
a.configure({ provider: 'deepseek' });
const submitted = await a.submitNotes('polish', { board_key: 'board-B' }, 'hash');
assert.equal(submitted.config.provider, 'deepseek');

// Filtering excludes checked hidden notes and revoked notes from later scope.
get('search').value = 'visible';
get('filter').value = '';
a.configure({ notes: [{ ...note('visible'), share_allowed: true }, { ...note('hidden'), share_allowed: true }, { ...note('visible-private'), share_allowed: false }], checked: ['visible', 'hidden', 'visible-private'] });
get('list').scrollTop = 240;
a.renderList();
assert.deepEqual(Array.from(a.inspect().checked), ['visible']);
assert.equal(get('list').scrollTop, 240);
// A recovered preview must not keep the previous conflict/error banner.
get('status').textContent = '内容已被更新，请保留当前输入，重新读取后核对版本。';
a.configure({ board: { id: 'board' } });
await a.scopePreview(false);
assert.equal(get('status').textContent, '请核对本次交接范围。');
// A finished job must retire the pending banner without overwriting newer edits/errors.
handler = () => [{ id: 'done', kind: 'polish', status: 'succeeded', snapshot: { entries: [] } }];
get('status').textContent = '正在整理，可继续记事';
await a.pollJobs();
assert.equal(get('status').textContent, '整理已结束，可在整理进度中查看结果。');
for (const message of ['尚未保存', '保存失败', '已采用为新版本，原文保留。']) {
	get('status').textContent = message;
	await a.pollJobs();
	assert.equal(get('status').textContent, message);
}
console.log('9 controlled editor scenarios passed: late image, image URL, board consent, local scope, frozen selection, hidden scope, scroll preservation, recovered preview status, finished job banner.');
