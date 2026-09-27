import type { Attachment, Board, Draft, Entry, Job, Note, Preview, Provider, ProviderState, Scope, Selection } from './types';
import { api, request } from './notesClient';
import { CACHE, DIRTY, SESSION } from './notesPanel';
import { captureSelection, selectLinked } from './selectionAdapter';

interface Editor {
	selection: Selection;
	board: string;
	note?: Note;
	entry?: Entry;
	append: boolean;
	client_id: string;
	title: string;
	body: string;
	attachments: Attachment[];
}
let current: Selection;
let provider: Provider = 'local';
let board: Board | undefined;
let notes: Note[] = [];
let editor: Editor | undefined;
let dirty = false;
let inputEpoch = 0;
let timer: ReturnType<typeof setTimeout> | undefined;
let pollTimer: ReturnType<typeof setTimeout> | undefined;
let closed = false;
let saving = false;
let currentDraft: Draft | undefined;
const DRAFT_CACHE = 'pcbNotes.draftRecovery.v1';
interface DraftRecovery { id: string; version: number; texts: string[]; human_addition: string; ignored_gaps: boolean }
let draftRecovery: DraftRecovery | undefined;
let draftDirty = false;
const checked = new Set<string>();
const readyNotes = new Set<string>();
const el = (id: string): HTMLElement => document.getElementById(id)!;
const input = (id: string): HTMLInputElement => el(id) as HTMLInputElement;
const body = (): HTMLTextAreaElement => el('body') as HTMLTextAreaElement;
function text(id: string, value: string): void {
	el(id).textContent = value;
}
const status = (message: string): void => text('status', message);
function add<K extends keyof HTMLElementTagNameMap>(parent: HTMLElement, tag: K, value = ''): HTMLElementTagNameMap[K] {
	const node = document.createElement(tag);
	node.textContent = value;
	parent.append(node);
	return node;
}
function button(parent: HTMLElement, label: string, action: () => Promise<void> | void): HTMLButtonElement {
	const b = add(parent, 'button', label);
	b.onclick = () => {
		void safely(action);
	};
	return b;
}
async function safely(action: () => Promise<void> | void): Promise<void> {
	try {
		await action();
	}
	catch (e) {
		status(e instanceof Error ? e.message : String(e));
	}
}
function on(id: string, action: () => Promise<void> | void): void {
	el(id).onclick = () => {
		void safely(action);
	};
}
function syncEditor(): void {
	if (!editor)
		return;
	editor.title = input('title').value;
	editor.body = body().value;
}
async function cache(): Promise<void> {
	syncEditor();
	const saved = await eda.sys_Storage.setExtensionUserConfig(CACHE, editor && dirty ? JSON.stringify(editor) : '');
	await eda.sys_Storage.setExtensionUserConfig(DIRTY, dirty || draftDirty);
	if (draftDirty && draftRecovery)
		await eda.sys_Storage.setExtensionUserConfig(DRAFT_CACHE, JSON.stringify(draftRecovery));
	if (!saved)
		status('恢复副本保存失败，请保存后再关闭。');
}
function changed(): void {
	dirty = true;
	inputEpoch++;
	syncEditor();
	status('尚未保存');
	void eda.sys_Storage.setExtensionUserConfig(DIRTY, true);
	clearTimeout(timer);
	timer = setTimeout(() => {
		void safely(cache);
	}, 350);
}
async function canLeave(): Promise<boolean> {
	if (!dirty && !draftDirty)
		return true;
	await cache();
	const confirmed = await confirmText('当前内容尚未保存。继续切换会放弃当前编辑，是否继续？');
	if (confirmed) {
		dirty = false;
		draftDirty = false;
		await eda.sys_Storage.setExtensionUserConfig(DIRTY, false);
	}
	return confirmed;
}
function confirmText(message: string): Promise<boolean> {
	return new Promise(resolve => eda.sys_Dialog.showConfirmationMessage(message, 'PCB 随手记', '继续', '返回', resolve));
}
async function resolveBoard(selection: Selection, showAll = false): Promise<void> {
	const result = await api<Board | {
		needs_binding: boolean;
		candidates: Board[];
	}>('/note-boards/bind', 'POST', { identity: selection.identity });
	if ('id' in result && !showAll) {
		board = result;
		await loadProvider();
		el('binding').hidden = true;
		await refresh();
		return;
	}
	const target = el('binding');
	target.replaceChildren();
	target.hidden = false;
	add(target, 'p', showAll ? '关联历史便签本只恢复记录，不重新绑定历史对象。' : '尚未确认此工程的便签本，请新建或明确关联历史记录。');
	const bind = async (key?: string): Promise<void> => {
		board = await api<Board>('/note-boards/bind', 'POST', { identity: selection.identity, board_key: key, confirm: true });
		await loadProvider();
		target.hidden = true;
		await refresh();
	};
	button(target, '为当前工程新建便签本', () => bind());
	if ('candidates' in result) {
		for (const candidate of result.candidates)
			button(target, `关联到当前工程：${candidate.name} · ${candidate.id.slice(0, 8)}`, () => bind(candidate.id));
	}
	else {
		add(target, 'p', '当前工程已经关联便签本。请切换到未关联工程后选择历史记录。');
	}
}
async function loadProvider(): Promise<void> {
	const state = await api<ProviderState>(`/notes-provider${board ? `?board_key=${board.id}` : ''}`);
	provider = state.selected;
	(el('provider') as HTMLSelectElement).value = provider;
	const option = state.options.find(item => item.provider === provider);
	text('provider-status', `${provider === 'local' ? '本机服务' : 'DeepSeek'} · ${option?.configured ? '已配置，尚未检查连接' : '尚未配置'}`);
}
async function authorizeCloud(chosen: Provider, boardKey: string): Promise<boolean> {
	if (chosen !== 'deepseek')
		return true;
	// Always read consent for the scope being submitted, including after rebinding.
	const state = await api<ProviderState>(`/notes-provider?board_key=${boardKey}`);
	if (state.cloud_confirmed)
		return true;
	return confirmText('本便签本首次使用 DeepSeek。仅发送本次选择的文字、必要对象标识和图片说明；不发送图片、整板或其他记录。确认本次范围后继续？');
}
async function submitNotes(kind: 'polish' | 'handoff', scope: Scope, hash: string): Promise<Job | undefined> {
	const chosen = provider;
	if (!await authorizeCloud(chosen, scope.board_key))
		return;
	const job = await api<Job>(`/ai-jobs/${kind}`, 'POST', { ...scope, snapshot_hash: hash, provider: chosen, external_confirmed: chosen === 'deepseek' });
	return job;
}
async function refresh(): Promise<void> {
	if (!board)
		return;
	notes = await api<Note[]>(`/notes?board_key=${board.id}`);
	text('board-name', `${current.identity.project_name} / ${current.identity.document_name}`);
	renderList();
	await pollJobs();
}
function renderList(): void {
	const list = el('list');
	const scroll = list.scrollTop;
	list.replaceChildren();
	const search = input('search').value.toLowerCase();
	const filter = (el('filter') as HTMLSelectElement).value;
	const visible = new Set<string>();
	for (const n of notes) {
		if (filter === '已归档' ? !n.archived : n.archived || (filter && n.status !== filter))
			continue;
		const title = n.title || n.entries[0].revisions.at(-1)!.body.split('\n')[0].slice(0, 50);
		if (!JSON.stringify([title, n.entries, n.objects]).toLowerCase().includes(search))
			continue;
		if (n.share_allowed && !n.archived)
			visible.add(n.id);
		const item = add(list, 'article');
		if (editor?.note?.id === n.id)
			item.classList.add('selected');
		const check = add(item, 'input');
		check.type = 'checkbox';
		check.checked = checked.has(n.id);
		check.disabled = !n.share_allowed || n.archived;
		check.onchange = () => {
			if (check.checked)
				checked.add(n.id);
			else
				checked.delete(n.id);
		};
		const open = button(item, title, () => openNote(n));
		open.className = 'note-title';
		open.title = title;
		add(item, 'p', n.objects.map(o => o.label).join('、') || '整板便签');
		add(item, 'small', `${n.status} · ${new Date(n.updated_at).toLocaleString()}${n.share_allowed ? '' : ' · 停止分享'}`);
		const ready = add(item, 'small', readyNotes.has(n.id) ? ' · 草稿就绪' : '');
		ready.dataset.noteReady = n.id;
	}
	for (const key of checked) {
		if (!visible.has(key))
			checked.delete(key);
	}
	list.scrollTop = scroll;
}
async function newNote(): Promise<void> {
	if (!await canLeave())
		return;
	const selection = await captureSelection();
	current = selection;
	await resolveBoard(selection);
	if (!board || !board.bindings.some(i => i.project_id === selection.identity.project_id && i.document_id === selection.identity.document_id)) {
		status('请先确认当前工程的便签本。');
		return;
	}
	editor = { selection, board: board.id, append: false, client_id: crypto.randomUUID(), title: '', body: '', attachments: [] };
	dirty = false;
	inputEpoch++;
	showEditor();
	status('');
}
async function openNote(note: Note, entryId?: string): Promise<void> {
	if (!await canLeave())
		return;
	const entry = note.entries.find(e => e.id === entryId) || note.entries[0];
	editor = { selection: { identity: note.identity, objects: note.objects, unsupported: 0 }, board: note.board_key, note, entry, append: false, client_id: crypto.randomUUID(), title: note.title, body: entry.revisions.at(-1)!.body, attachments: [] };
	const destination = editor;
	for (const key of entry.revisions.at(-1)!.attachment_ids) {
		try {
			destination.attachments.push(await api<Attachment>(`/attachments/${key}`));
		}
		catch {
			destination.attachments.push({ id: key, name: '附件缺失', caption: '', extension: '', revision: 1 });
		}
	}
	if (editor !== destination)
		return;
	dirty = false;
	inputEpoch++;
	await eda.sys_Storage.setExtensionUserConfig(DIRTY, false);
	showEditor();
}
function showEditor(): void {
	if (!editor)
		return;
	el('editor').hidden = false;
	el('preview').hidden = true;
	el('empty').hidden = true;
	input('title').value = editor.title;
	body().value = editor.body;
	text('objects', `${editor.selection.identity.project_name} · ${editor.selection.objects.map(o => o.label).join('、') || '整板便签'}${editor.selection.unsupported ? `（另有 ${editor.selection.unsupported} 个图元暂不支持绑定）` : ''}`);
	el('select').hidden = !editor.selection.objects.length;
	el('link-selection').hidden = !editor.note;
	text('state', editor.note?.status === '已处理' ? '标为待确认' : '标为已处理');
	text('sharing', editor.note?.share_allowed === false ? '恢复分享' : '停止分享');
	text('archive', editor.note?.archived ? '恢复归档' : '归档记录');
	renderAttachments();
	renderEntries();
	renderList();
}
function renderEntries(): void {
	const target = el('entries');
	target.replaceChildren();
	const history = el('versions');
	history.replaceChildren();
	if (!editor?.note)
		return;
	const note = editor.note;
	for (const entry of note.entries) {
		const box = add(target, 'article');
		add(box, 'small', `${entry.kind === 'initial' ? '原始记录' : '进展'} · v${entry.revision}`);
		add(box, 'p', entry.revisions.at(-1)!.body);
		button(box, '编辑此条', () => openNote(note, entry.id));
		const revisions = add(history, 'details');
		add(revisions, 'summary', `记录 ${entry.id.slice(0, 8)} 的版本`);
		for (const rev of entry.revisions) {
			add(revisions, 'small', `v${rev.revision} · ${rev.origin === 'adopted_polish' ? '已采用整理稿' : '编辑记录'}`);
			add(revisions, 'pre', rev.body);
		}
	}
}
function renderAttachments(): void {
	const target = el('attachments');
	target.replaceChildren();
	for (const a of editor?.attachments || []) {
		const item = add(target, 'article');
		add(item, 'small', a.name);
		if (a.data) {
			const img = add(item, 'img');
			img.src = `data:image/${a.extension === 'jpg' ? 'jpeg' : 'png'};base64,${a.data}`;
			img.alt = '附图';
		}
		const caption = add(item, 'textarea');
		caption.value = a.caption;
		caption.placeholder = '图片说明（可选）';
		caption.maxLength = 2000;
		caption.oninput = () => {
			a.caption = caption.value;
			changed();
		};
		button(item, '移除此条附件', () => {
			if (editor)
				editor.attachments = editor.attachments.filter(item => item !== a);
			changed();
			renderAttachments();
		});
	}
}
async function attach(file: File): Promise<void> {
	if (!editor)
		throw new Error('请先新建或打开便签。');
	const destination = editor;
	if (!['image/png', 'image/jpeg'].includes(file.type) || file.size > 6 * 1024 * 1024)
		throw new Error('请使用 6 MB 以内的 PNG/JPEG 图片。');
	if (editor.attachments.length >= 12)
		throw new Error('每条记录最多 12 张图片。');
	const data = await new Promise<string>((resolve, reject) => {
		const reader = new FileReader();
		reader.onload = () => resolve(String(reader.result).split(',')[1]);
		reader.onerror = reject;
		reader.readAsDataURL(file);
	});
	if (destination !== editor)
		throw new Error('读取图片期间切换了便签，请在目标记录重新选择图片。');
	editor.attachments.push({ id: '', name: file.name, extension: file.type === 'image/png' ? 'png' : 'jpg', caption: '', revision: 1, data });
	changed();
	renderAttachments();
}
async function save(): Promise<Note> {
	if (!editor || !editor.body.trim())
		throw new Error('请先填写正文。');
	if (saving)
		throw new Error('正在保存，请稍后再操作。');
	syncEditor();
	const original = editor;
	const copy: Editor = structuredClone(editor);
	const epoch = inputEpoch;
	saving = true;
	try {
		for (let i = 0; i < copy.attachments.length; i++) {
			let a = copy.attachments[i];
			if (!a.id) {
				a = await api<Attachment>('/attachments', 'POST', { name: a.name, data: a.data, caption: a.caption });
			}
			else {
				const server = await api<Attachment>(`/attachments/${a.id}`);
				if (server.caption !== a.caption)
					a = await api<Attachment>(`/attachments/${a.id}`, 'PATCH', { expected_version: a.revision, caption: a.caption });
			}
			copy.attachments[i] = { ...a, data: copy.attachments[i].data };
		}
		const attachment_ids = copy.attachments.map(a => a.id);
		let result: Note;
		if (!copy.note) {
			result = await api<Note>('/notes', 'POST', { board_key: copy.board, identity: copy.selection.identity, objects: copy.selection.objects, title: copy.title, body: copy.body, attachment_ids, client_id: copy.client_id });
		}
		else {
			let note = copy.note;
			if (copy.title !== note.title)
				note = await api<Note>(`/notes/${note.id}`, 'PATCH', { expected_version: note.version, title: copy.title });
			result = await api<Note>(copy.append ? `/notes/${note.id}/entries` : `/entries/${copy.entry!.id}`, copy.append ? 'POST' : 'PATCH', { expected_version: copy.append ? note.version : copy.entry!.revision, body: copy.body, attachment_ids });
		}
		if (editor === original) {
			editor.note = result;
			editor.entry = copy.append || !copy.note ? result.entries.at(-1) : result.entries.find(e => e.id === copy.entry!.id);
			editor.append = false;
			if (inputEpoch === epoch) {
				editor.attachments = copy.attachments;
				dirty = false;
				await eda.sys_Storage.setExtensionUserConfig(DIRTY, false);
				await eda.sys_Storage.setExtensionUserConfig(CACHE, '');
			}
			renderEntries();
		}
		status(inputEpoch === epoch ? '已保存' : '已保存提交时的版本；新输入尚未保存');
		await refresh();
		return result;
	}
	finally {
		saving = false;
	}
}
async function changeNote(fields: Record<string, unknown>): Promise<void> {
	if (!editor?.note)
		throw new Error('请先保存便签。');
	if (dirty)
		throw new Error('请先保存正文，再更新状态。');
	editor.note = await api<Note>(`/notes/${editor.note.id}`, 'PATCH', { expected_version: editor.note.version, ...fields });
	await refresh();
	showEditor();
	status('状态已更新。');
}
async function polish(): Promise<void> {
	await save();
	if (!editor?.entry)
		return;
	const scope: Scope = { board_key: editor.board, entry_ids: [editor.entry.id], attachment_ids: [], purpose: '' };
	const preview = await api<Preview>('/note-snapshots', 'POST', scope);
	const job = await submitNotes('polish', scope, preview.snapshot_hash);
	if (!job)
		return;
	status('正在整理，可继续记事');
	(el('jobs').parentElement as HTMLDetailsElement).open = true;
	await pollJobs();
}
async function scopePreview(useAI: boolean): Promise<void> {
	if (!board || !checked.size)
		throw new Error('请先勾选需要交接的便签。');
	if (!await canLeave())
		return;
	const selected = notes.filter(n => checked.has(n.id) && !n.archived && n.share_allowed);
	const scope: Scope = { board_key: board.id, entry_ids: selected.flatMap(n => n.entries.map(e => e.id)), attachment_ids: [...new Set(selected.flatMap(n => n.entries.flatMap(e => e.revisions.at(-1)!.attachment_ids)))], purpose: '' };
	scope.expected_entries = Object.fromEntries(selected.flatMap(n => n.entries.map(e => [e.id, e.revision])));
	scope.expected_notes = Object.fromEntries(selected.map(n => [n.id, n.version]));
	scope.expected_attachments = {};
	const target = el('preview');
	target.replaceChildren();
	target.hidden = false;
	el('editor').hidden = true;
	el('empty').hidden = true;
	el('detail').scrollTop = 0;
	add(target, 'h2', '确认本次交接范围');
	if (useAI && provider === 'deepseek')
		add(target, 'p', '所选文字和图片说明将发送到 DeepSeek，不发送图片。');
	add(target, 'p', `${selected.length} 条便签 · ${scope.entry_ids.length} 条记录 · ${scope.attachment_ids.length} 张附件`);
	const purpose = add(target, 'textarea');
	purpose.placeholder = '这次希望对方帮忙做什么？（可选）';
	purpose.maxLength = 1000;
	const selectedEntries = new Set(scope.entry_ids);
	const selectedAttachments = new Set(scope.attachment_ids);
	for (const note of selected) {
		for (const e of note.entries) {
			const box = add(target, 'article');
			const check = add(box, 'input');
			check.type = 'checkbox';
			check.checked = true;
			add(box, 'span', `${note.title || '便签'} · ${e.kind === 'initial' ? '原始记录' : '进展'} v${e.revision}`);
			add(box, 'pre', e.revisions.at(-1)!.body);
			if (e.revisions.at(-1)!.origin === 'adopted_polish')
				add(box, 'small', '导出当前版本；更早的版本仍保留在便签历史中。');
			check.onchange = () => {
				if (check.checked)
					selectedEntries.add(e.id);
				else
					selectedEntries.delete(e.id);
			};
		}
	}
	for (const key of scope.attachment_ids) {
		let a: Attachment;
		try {
			a = await api<Attachment>(`/attachments/${key}`);
		}
		catch {
			selectedAttachments.delete(key);
			add(target, 'p', `附件 ${key.slice(0, 8)} 缺失：本次范围不包含此图片。确认范围后将只导出可用内容。`);
			continue;
		}
		scope.expected_attachments![key] = a.revision;
		const box = add(target, 'article');
		const check = add(box, 'input');
		check.type = 'checkbox';
		check.checked = true;
		add(box, 'span', a.name);
		add(box, 'p', a.caption || '未填写图片说明');
		check.onchange = () => {
			if (check.checked)
				selectedAttachments.add(key);
			else
				selectedAttachments.delete(key);
		};
	}
	button(target, useAI ? '整理所选记录' : '按原文生成', async () => {
		scope.entry_ids = [...selectedEntries];
		const allowed = new Set(selected.flatMap(n => n.entries.filter(e => selectedEntries.has(e.id)).flatMap(e => e.revisions.at(-1)!.attachment_ids)));
		scope.attachment_ids = [...selectedAttachments].filter(id => allowed.has(id));
		scope.purpose = purpose.value;
		const preview = await api<Preview>('/note-snapshots', 'POST', scope);
		const command = { ...scope, snapshot_hash: preview.snapshot_hash };
		if (useAI) {
			const job = await submitNotes('handoff', scope, preview.snapshot_hash);
			if (!job)
				return;
			status('已提交交接草稿，可继续工作');
			(el('jobs').parentElement as HTMLDetailsElement).open = true;
			await pollJobs();
		}
		else {
			const draft = await api<Draft>('/handoff-drafts/template', 'POST', command);
			await showDraft(draft.id);
			status('已按原文生成，待核对。');
		}
	});
	status('请核对本次交接范围。');
}
async function pollJobs(): Promise<void> {
	clearTimeout(pollTimer);
	if (!board || closed)
		return;
	const jobs = await api<Job[]>(`/ai-jobs?board_key=${board.id}`);
	// Only retire our own pending banner; never replace unsaved-input or error feedback.
	if (!jobs.some(j => ['queued', 'running'].includes(j.status))
		&& ['正在整理，可继续记事', '已提交交接草稿，可继续工作', '已提交新草稿，旧版本保留。'].includes(el('status').textContent || '')) {
		status('整理已结束，可在整理进度中查看结果。');
	}
	readyNotes.clear();
	for (const job of jobs.filter(j => j.status === 'succeeded')) {
		for (const row of job.snapshot.entries) readyNotes.add(row.note_id);
	}
	for (const marker of Array.from(document.querySelectorAll<HTMLElement>('[data-note-ready]')))
		marker.textContent = readyNotes.has(marker.dataset.noteReady!) ? ' · 草稿就绪' : '';
	const target = el('jobs');
	target.replaceChildren();
	const labels: Record<string, string> = { queued: '排队中', running: '整理中', succeeded: '草稿就绪', failed: '失败', cancelled: '已取消', interrupted: '已中断' };
	for (const job of jobs.slice().reverse().slice(0, 30)) {
		const row = add(target, 'article');
		add(row, 'small', `${job.kind === 'polish' ? '文字整理 · ' : '交接整理 · '}${labels[job.status] || job.status} · ${job.config?.provider === 'deepseek' ? 'DeepSeek' : '本机服务'}`);
		if (job.error)
			add(row, 'p', job.error);
		if (job.draft_id)
			button(row, '查看草稿', () => showDraft(job.draft_id!));
		if (['queued', 'running'].includes(job.status)) {
			button(row, '取消', async () => {
				await api(`/ai-jobs/${job.id}/cancel`, 'POST');
				await pollJobs();
			});
		}
		if (['failed', 'cancelled', 'interrupted'].includes(job.status)) {
			button(row, '重试原版本', async () => {
				await api(`/ai-jobs/${job.id}/retry`, 'POST');
				await pollJobs();
			});
		}
	}
	if (jobs.some(j => ['queued', 'running'].includes(j.status))) {
		pollTimer = setTimeout(() => {
			void safely(pollJobs);
		}, document.hidden ? 12000 : 1800);
	}
}
async function showDraft(key: string): Promise<void> {
	if (!await canLeave())
		return;
	const draft = await api<Draft>(`/handoff-drafts/${key}`);
	currentDraft = draft;
	const target = el('preview');
	target.replaceChildren();
	target.hidden = false;
	el('editor').hidden = true;
	el('empty').hidden = true;
	el('detail').scrollTop = 0;
	add(target, 'h2', draft.kind === 'polish' ? '整理结果' : '交接草稿');
	add(target, 'p', `${draft.adopted ? '已采用' : draft.confirmation ? '已核对' : '待核对'} · 版本 ${draft.version}`);
	if (draft.source_changed && !draft.adopted)
		add(target, 'p', '便签后来有修改。这份草稿仍保留之前的内容，请核对后使用。');
	const content = draft.revisions.at(-1)!.body;
	const recovered = draftRecovery?.id === key ? draftRecovery : undefined;
	if (recovered && recovered.version !== draft.version)
		add(target, 'p', '恢复副本来自较早版本。请保留文字核对后重新打开，保存将检查版本冲突。');
	const edits: HTMLTextAreaElement[] = [];
	for (const block of content.blocks) {
		const box = add(target, 'article');
		if (block.heading)
			add(box, 'h3', block.heading);
		const edit = add(box, 'textarea');
		edit.value = recovered?.texts[edits.length] ?? block.text;
		edit.readOnly = draft.kind === 'polish';
		edits.push(edit);
		if (block.human_edited)
			add(box, 'small', '已编辑，请核对原文');
		for (const ref of block.source_refs) {
			const source = add(box, 'details');
			add(source, 'summary', `${draft.snapshot.entries.find(e => e.entry_id === ref.entry_id)?.title || '查看原文'} · 第 ${ref.revision} 版`);
			add(source, 'pre', ref.quote);
		}
	}
	for (const a of draft.snapshot.attachments)
		add(target, 'p', `图片说明：${a.caption || '未填写图片说明'} · ${a.name}`);
	if (draft.kind === 'polish') {
		const apply = button(target, '采用这版', async () => {
			await api(`/polish-drafts/${key}/apply`, 'POST', { expected_version: draft.version });
			await refresh();
			status('已采用为新版本，原文保留。');
			await showDraft(key);
		});
		apply.disabled = draft.source_changed || draft.adopted;
		button(target, '复制草稿文字', async () => {
			await navigator.clipboard.writeText(content.blocks[0].text);
			status('已复制；请与当前原文核对后使用。');
		});
	}
	const addition = add(target, 'textarea');
	addition.placeholder = '补充交接事项（可选）';
	addition.value = recovered?.human_addition ?? content.human_addition;
	addition.hidden = draft.kind === 'polish';
	if (content.gaps.length) {
		add(target, 'h3', '待补充');
		for (const gap of content.gaps)
			add(target, 'p', gap);
	}
	const ignoreLabel = add(target, 'label');
	const ignore = add(ignoreLabel, 'input');
	ignore.type = 'checkbox';
	ignoreLabel.hidden = draft.kind !== 'handoff' || !content.gaps.length;
	ignore.checked = recovered?.ignored_gaps ?? content.ignored_gaps;
	add(ignoreLabel, 'span', '导出时不附这些问题');
	if (draft.kind === 'handoff') {
		const recoverEdits = (): void => {
			draftDirty = true;
			draftRecovery = { id: key, version: recovered?.version ?? currentDraft!.version, texts: edits.map(e => e.value), human_addition: addition.value, ignored_gaps: ignore.checked };
			void eda.sys_Storage.setExtensionUserConfig(DIRTY, true);
			clearTimeout(timer);
			timer = setTimeout(() => {
				void safely(cache);
			}, 350);
			status('草稿尚未保存');
		};
		for (const edit of edits)
			edit.oninput = recoverEdits;
		addition.oninput = recoverEdits;
		ignore.onchange = recoverEdits;
		const saveEdits = async (): Promise<Draft> => {
			const submitted = { expected_version: recovered?.version ?? currentDraft!.version, texts: edits.map(e => e.value), human_addition: addition.value, ignored_gaps: ignore.checked };
			const saved = await api<Draft>(`/handoff-drafts/${key}`, 'PATCH', submitted);
			currentDraft = saved;
			if (JSON.stringify(submitted.texts) !== JSON.stringify(edits.map(e => e.value)) || submitted.human_addition !== addition.value || submitted.ignored_gaps !== ignore.checked) {
				recoverEdits();
				throw new Error('提交时的草稿已保存；保存期间的新输入仍未提交，请再保存后导出。');
			}
			draftDirty = false;
			draftRecovery = undefined;
			await eda.sys_Storage.setExtensionUserConfig(DRAFT_CACHE, '');
			await eda.sys_Storage.setExtensionUserConfig(DIRTY, dirty);
			return saved;
		};
		button(target, '保存修改', async () => {
			await saveEdits();
			status('修改已保存，请重新核对后导出。');
			await showDraft(key);
		});
		button(target, '重新核对来源', () => showDraft(key));
		button(target, '用当前来源重新生成', async () => {
			const scope: Scope = { board_key: draft.snapshot.board_key, entry_ids: draft.snapshot.entries.map(e => e.entry_id), attachment_ids: draft.snapshot.attachments.map(a => a.id), purpose: draft.snapshot.purpose };
			const preview = await api<Preview>('/note-snapshots', 'POST', scope);
			if (!await submitNotes('handoff', scope, preview.snapshot_hash))
				return;
			status('已提交新草稿，旧版本保留。');
			await pollJobs();
		});
		const exportLabel = add(target, 'label');
		const textOnly = add(exportLabel, 'input');
		textOnly.type = 'checkbox';
		add(exportLabel, 'span', '仅导出文字，不包含图片');
		const exportDraft = async (confirm: boolean): Promise<void> => {
			const updated = await saveEdits();
			if (confirm)
				await api(`/handoff-drafts/${key}/confirm`, 'POST', { expected_version: updated.version });
			const view = await api<Draft>(`/handoff-drafts/${key}`);
			if (view.source_changed && !await confirmText('来源已有更新。是否按预览中的历史版本导出？'))
				return;
			const pkg = await api<{
				id: string;
				filename: string;
			}>('/handoff-packages', 'POST', { draft_id: key, expected_version: updated.version, allow_unconfirmed: !confirm, text_only: textOnly.checked, acknowledge_history: view.source_changed, share_confirmation: true });
			const response = await request(`/handoff-packages/${pkg.id}`);
			if (!response.ok)
				throw new Error('交接包已经保存，下载失败，请稍后重试。');
			await eda.sys_FileSystem.saveFile(await response.blob(), pkg.filename);
			status(`交接包已生成并发起保存：${pkg.filename}`);
		};
		button(target, '确认范围并导出', () => exportDraft(true));
		button(target, '导出未确认草稿', () => exportDraft(false));
	}
	if (draft.ai_original) {
		const old = add(target, 'details');
		add(old, 'summary', '最初草稿');
		for (const b of draft.ai_original.blocks)
			add(old, 'pre', b.text);
	}
}
async function init(): Promise<void> {
	const raw: unknown = eda.sys_Storage.getExtensionUserConfig(SESSION);
	if (typeof raw !== 'string')
		throw new Error('请从 PCB 菜单打开随手记。');
	current = JSON.parse(raw) as Selection;
	text('board-name', current.identity.project_name);
	const rawDraft: unknown = eda.sys_Storage.getExtensionUserConfig(DRAFT_CACHE);
	if (typeof rawDraft === 'string' && rawDraft) {
		draftRecovery = JSON.parse(rawDraft) as DraftRecovery;
		const target = el('recovery');
		target.hidden = false;
		button(target, '恢复未保存的草稿', async () => {
			await showDraft(draftRecovery!.id);
			draftDirty = true;
			target.hidden = true;
		});
	}
	const recovery: unknown = eda.sys_Storage.getExtensionUserConfig(CACHE);
	if (typeof recovery === 'string' && recovery) {
		const target = el('recovery');
		target.hidden = false;
		add(target, 'span', '发现尚未提交的恢复副本。');
		button(target, '恢复编辑', () => {
			editor = JSON.parse(recovery) as Editor;
			dirty = true;
			inputEpoch++;
			showEditor();
			target.hidden = true;
			status('已恢复输入，尚未保存。归属保持原工程。');
		});
		button(target, '放弃恢复副本', async () => {
			await eda.sys_Storage.setExtensionUserConfig(CACHE, '');
			await eda.sys_Storage.setExtensionUserConfig(DIRTY, false);
			target.hidden = true;
		});
	}
	await resolveBoard(current);
	await loadProvider();
	status('可以开始记录');
}
on('new', newNote);
on('provider-check', async () => {
	const result = await api<{ message: string }>('/notes-provider/check', 'POST', { provider });
	text('provider-status', result.message);
});
(el('provider') as HTMLSelectElement).onchange = () => {
	void safely(async () => {
		provider = (el('provider') as HTMLSelectElement).value as Provider;
		await api('/notes-provider', 'PATCH', { provider });
		await loadProvider();
	});
};
on('save', async () => {
	await save();
});
on('polish', polish);
on('refresh', refresh);
on('history', () => resolveBoard(current, true));
on('append', async () => {
	if (!editor?.note)
		throw new Error('请先保存便签。');
	if (!await canLeave())
		return;
	editor.append = true;
	editor.entry = undefined;
	editor.body = '';
	editor.attachments = [];
	inputEpoch++;
	dirty = false;
	showEditor();
	status('正在追加进展，原始记录不会被覆盖。');
});
on('select', async () => {
	if (!editor)
		return;
	await selectLinked(editor.selection.identity, editor.selection.objects);
	status('已选中关联对象。');
});
on('link-selection', async () => {
	if (!editor?.note || !await canLeave())
		return;
	const target = editor;
	const selected = await captureSelection();
	if (editor !== target)
		return;
	if (!selected.objects.length || selected.unsupported)
		throw new Error('请先在 PCB 上选中需要关联的元件或焊盘。');
	const updated = await api<Note>(`/notes/${target.note!.id}/objects`, 'POST', {
		expected_version: target.note!.version,
		identity: selected.identity,
		objects: selected.objects,
	});
	if (editor !== target)
		return;
	await openNote(updated, target.entry?.id);
	status(`已关联：${selected.objects.map(o => o.label).join('、')}`);
});
on('state', () => changeNote({ status: editor?.note?.status === '已处理' ? '待确认' : '已处理' }));
on('archive', () => changeNote({ archived: !editor?.note?.archived }));
on('sharing', () => changeNote({ share_allowed: !editor?.note?.share_allowed }));
on('handoff', () => scopePreview(true));
on('template', () => scopePreview(false));
on('close', async () => {
	await cache();
	await eda.sys_IFrame.closeIFrame('pcbNotesPanel');
});
input('body').oninput = changed;
input('title').oninput = changed;
body().onkeydown = (event) => {
	if (event.ctrlKey && event.key === 'Enter') {
		event.preventDefault();
		void safely(async () => {
			await save();
		});
	}
};
input('file').onchange = () => {
	const file = input('file').files?.[0];
	if (file)
		void safely(() => attach(file));
	input('file').value = '';
};
el('editor').onpaste = (event: ClipboardEvent) => {
	const file = event.clipboardData?.files[0];
	if (file) {
		event.preventDefault();
		void safely(() => attach(file));
	}
};
input('search').oninput = renderList;
el('filter').onchange = renderList;
window.addEventListener('pagehide', () => {
	closed = true;
	clearTimeout(pollTimer);
});
document.addEventListener('visibilitychange', () => {
	if (!document.hidden)
		void safely(pollJobs);
});
void safely(init);
