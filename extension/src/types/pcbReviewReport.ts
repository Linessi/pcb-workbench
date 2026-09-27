export interface PCBReviewIssue {
	kind?: 'confirmed_issue';
	category: 'Power' | 'Layout' | 'Signal' | 'EMC';
	severity: 'critical' | 'high' | 'medium' | 'low';
	problem: string;
	suggestion: string;
	ruleIds: string[];
}

export interface KnowledgeReference {
	id: string;
	title: string;
	source: string;
}

export interface PCBReviewRecommendation {
	priority: 'high' | 'medium' | 'low';
	action: string;
	ruleIds: string[];
}

export interface PCBReviewReport {
	summary: string;
	issues: PCBReviewIssue[];
	recommendations: PCBReviewRecommendation[];
	knowledgeReferences: KnowledgeReference[];
	analysis_trace: Array<{ tool: string; result: 'ok' | 'warning' | 'insufficient_data' | 'error'; detail: string }>;
	evidence: Array<{ source: string; reason: string }>;
}
