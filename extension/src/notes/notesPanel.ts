import { captureSelection } from './selectionAdapter';

export const SESSION = 'pcbNotes.session.v1';
export const CACHE = 'pcbNotes.recovery.v1';
export const DIRTY = 'pcbNotes.unsaved.v1';

export async function openNotes(): Promise<void> {
	try {
		const selection = await captureSelection();
		if (!await eda.sys_Storage.setExtensionUserConfig(SESSION, JSON.stringify(selection)))
			throw new Error('无法保存当前对象快照。');
		const opened = await eda.sys_IFrame.openIFrame('/iframe/notes.html', 980, 680, 'pcbNotesPanel', {
			title: 'PCB 随手记',
			maximizeButton: true,
			minimizeButton: true,
			grayscaleMask: false,
			onBeforeCloseCallFn: async () => {
				if (eda.sys_Storage.getExtensionUserConfig(DIRTY) !== true)
					return true;
				return new Promise<boolean>(resolve => eda.sys_Dialog.showConfirmationMessage('内容尚未保存到本机服务。关闭后可从恢复副本继续，是否关闭？', 'PCB 随手记', '关闭', '继续编辑', resolve));
			},
		});
		if (!opened)
			throw new Error('无法打开 PCB 随手记。');
	}
	catch (error) { eda.sys_Dialog.showInformationMessage(error instanceof Error ? error.message : String(error), 'PCB 随手记'); }
}
