export interface DrcObject {
	object_id: string;
	kind: 'pad' | 'component' | 'primitive' | 'net';
	primitive_id: string | null;
	match_basis: string;
}

export interface DrcIssue {
	id: string;
	raw_message: string;
	raw: unknown;
	source_path: string;
	category: string;
	native_severity: string | null;
	priority: 'high' | 'medium' | 'low';
	priority_reason_zh: string;
	net: string | null;
	objects: DrcObject[];
	message_zh: string;
	translation_status: string;
	parse_status: string;
	location_scope: 'exact' | 'component' | 'net' | 'unavailable';
	limitations_zh: string;
}

export interface ReviewExplanation {
	title_zh: string;
	issue_ids: string[];
	evidence_ids: string[];
	object_ids: string[];
	explanation_zh: string;
	steps_zh: string[];
	verification_zh: string;
	rule_ids: string[];
	uncertainty_zh: string;
}

export interface SnapshotReport {
	version: string;
	snapshot_id: string;
	request_id: string;
	source_kind: 'eda_live' | 'historical_replay' | 'synthetic';
	provenance: Record<string, unknown>;
	context_hash: string;
	hash_scope_zh: string;
	summary_zh: string;
	drc: {
		status: string;
		native_count: number | null;
		parsed_count: number;
		unknown_results: Array<{ source_path: string; raw: unknown; message_zh: string }>;
		issues: DrcIssue[];
		groups: Array<{ category: string; net: string; issue_ids: string[]; count: number }>;
		count_note_zh: string;
	};
	explanations: ReviewExplanation[];
	pending_checks: ReviewExplanation[];
	evidence: Array<{ id: string; snapshot_id: string; kind: string; object_ids: string[]; issue_ids: string[]; data: unknown; limitations_zh: string }>;
	analysis_trace: Array<{ tool: string; display_name_zh: string; origin: string; arguments: unknown; status: string; duration_ms: number; summary_zh: string; evidence_ids: string[] }>;
	knowledge_references: Array<{ id: string; title_zh: string; source: string; summary_zh: string; acquired_evidence: string[]; missing_evidence: string[]; applicability_zh: string }>;
	agent_mode: string;
	agent_status: string;
	agent_message_zh: string;
	chinese_status: string;
	rejected_conclusions: Array<{ title_zh?: string; reason_zh: string }>;
	comparison: { summary_zh: string; limitations_zh: string[]; newly_reported: string[]; still_reported: string[]; not_reported_again: string[]; eliminated_on_recheck: string[]; unreliably_matched: string[] } | null;
}
