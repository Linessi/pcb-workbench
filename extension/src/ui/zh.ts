/** One vocabulary for user-visible labels; protocol IDs remain unchanged. */
export const zh: Record<string, string> = {
	high: '高',
	medium: '中',
	low: '低',
	critical: '紧急',
	completed: '已完成',
	error: '错误',
	not_run: '未运行',
	unavailable: '数据不可用',
	available: '已取得',
	not_collected: '未采集',
	running: '运行中',
	failed: '失败',
	cancelled: '已取消',
	limited: '能力受限',
	ok: '成功',
	passed: '通过',
	pending: '待校验',
	eda_live: '当前 EDA 实时采集',
	historical_replay: '历史快照回放',
	synthetic: '合成测试数据',
	native_tool_calls: '原生工具调用',
	json_actions: 'JSON 动作协议',
	explanation_only: '普通解释',
	model_tool_call: '模型选择工具',
	model_json_action: '模型选择动作',
	program: '程序步骤',
	model_response: '模型生成',
	translation: '翻译校验',
	components: '元件坐标及属性',
	pads: '焊盘坐标及网络',
	nets: '逻辑网络',
	outline: '板框',
	vias: '过孔',
	native_drc: '原生 DRC',
	traces: '完整走线',
	copper: '铜箔与参考平面',
	stackup: '叠层及铜厚',
	design_current: '设计电流',
	impedance: '阻抗约束',
	schematic: '原理图及引脚约束',
	operating_frequency: '工作频率',
	exact: '准确图元',
	component: '所属元件',
	net: '仅网络信息',
	Power: '电源',
	Layout: '布局',
	Signal: '信号',
	EMC: '电磁兼容',
};
export function label(code: string): string {
	return zh[code] ?? '其他类型';
}
export function record(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}
export function errorText(error: unknown): string {
	const message = error instanceof Error ? error.message : '';
	return /[\u4E00-\u9FFF]/.test(message) ? message : '操作未完成，请检查当前文档、后端服务与扩展权限；脱敏详情见日志。';
}
