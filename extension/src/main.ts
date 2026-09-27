import type { PCBContext } from './types/pcbContext';
import { readCurrentPcb } from './api/edaAdapter';
import { collectPCBContextV2 } from './collector/pcbCollector';
import { collectReviewContext } from './collector/reviewCollector';
import { requestPCBReview } from './services/backendClient';
import { createReview } from './services/reviewClient';
import { showAnalyzerError, showAnalyzerPanel } from './ui/analyzerPanel';
import { showReviewError, showReviewPanel } from './ui/reviewPanel';
import { exportPCBContextV2 } from './utils/export';

// SYS_IFrame.openIFrame() rejects punctuation such as `.` in window IDs.
const REVIEW_IFRAME_ID = 'aiEdaCopilotDesignReview';
let clientBusy = false;

/** 插件主模块。菜单的 registerFn 名称与这里导出的函数一致。 */

// SDK 约定的生命周期函数；当前阶段无需启动时操作。
export function activate(_status?: 'onStartupFinished', _arg?: string): void {}

/** 点击 Hello World，验证菜单注册与官方对话框 API 调用。 */
export function helloWorld(): void {
	eda.sys_Dialog.showInformationMessage(
		'AI EDA Copilot 插件已加载，兼容诊断功能正常。',
		'AI EDA Copilot',
	);
}

/** PCB 菜单入口。保留 helloWorld 供回退验证。 */
export async function analyzeCurrentPcb(): Promise<void> {
	try {
		const pcb = await readCurrentPcb();
		const context = await collectPCBContextV2();
		const exported = await exportPCBContextV2(context);
		showAnalyzerPanel(pcb.name, context, exported);
	}
	catch (error) {
		console.error('Analyze PCB failed', error);
		showAnalyzerError(error);
	}
}

async function sendContextToAI(context: PCBContext): Promise<void> {
	try {
		const report = await requestPCBReview(context);
		showReviewPanel(context, report);
	}
	catch (error) {
		console.error('Analyze With AI failed', error);
		showReviewError(error);
	}
}

/** PCB menu entry. The native confirmation dialog supplies the requested button. */
export async function openLegacyAIReview(): Promise<void> {
	try {
		const context = await collectPCBContextV2();
		const preview = [
			`工程：${context.projectName}`,
			`元件：${context.statistics.componentCount}`,
			`网络：${context.statistics.netCount}`,
			'使用当前 PCB 数据进行 AI 分析？',
		].join('\n');
		// SYS_Dialog.showConfirmationMessage(): @jlceda/pro-api-types.
		eda.sys_Dialog.showConfirmationMessage(
			preview,
			'AI EDA Copilot',
			'兼容版 AI 分析',
			'取消',
			(confirmed) => {
				if (confirmed) {
					void sendContextToAI(context);
				}
			},
		);
	}
	catch (error) {
		console.error('Analyze With AI preparation failed', error);
		showReviewError(error);
	}
}

/** Old menu callback remains callable, now opens the full Chinese review. */
export async function openAIReview(): Promise<void> {
	await openDesignReview();
}

/**
 * Product demo entry. The installed SDK declares both APIs in SYS_Storage and
 * SYS_IFrame; the iframe reads the stored Context using its own `eda` object.
 */
export async function openDesignReview(): Promise<void> {
	if (clientBusy)
		return;
	clientBusy = true;
	try {
		const context = await collectReviewContext();
		const report = await createReview(context);
		const stored = await eda.sys_Storage.setExtensionUserConfig('aiEdaCopilot.reviewSession.v07', JSON.stringify({ context, report }));
		if (!stored) {
			throw new Error('无法载入 PCB 检查数据，请重新打开分析窗口。');
		}
		const opened = await eda.sys_IFrame.openIFrame('/iframe/index.html', 920, 650, REVIEW_IFRAME_ID, {
			title: 'AI 设计审查',
			maximizeButton: true,
		});
		if (!opened) {
			throw new Error('无法打开 AI 设计审查窗口。');
		}
	}
	catch (error) {
		console.error('AI Design Review failed', error);
		showReviewError(error, 'AI 设计审查');
	}
	finally { clientBusy = false; }
}
