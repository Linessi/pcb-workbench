"""Read-only review contracts. Natural-language fields are Simplified Chinese."""

from typing import Literal
from pydantic import Field, JsonValue
from models.schema import PCBContextV2, StrictModel


class ObjectLink(StrictModel):
    object_id: str
    kind: Literal["pad", "component", "primitive", "net"]
    primitive_id: str | None = None
    match_basis: str


class DrcIssue(StrictModel):
    id: str
    fingerprint: str
    match_strength: Literal["object", "text", "ambiguous"]
    raw_message: str
    raw: JsonValue
    source_path: str
    category: str
    native_severity: str | None = None
    priority: Literal["high", "medium", "low"]
    priority_reason_zh: str
    net: str | None = None
    objects: list[ObjectLink] = Field(default_factory=list)
    position: dict[str, JsonValue] | None = None
    message_zh: str
    translation_status: Literal["template", "model_validated", "pending", "failed"]
    parse_status: Literal["parsed", "partial"]
    location_scope: Literal["exact", "component", "net", "unavailable"]
    limitations_zh: str


class DrcInventory(StrictModel):
    status: Literal["completed", "error", "not_run", "unavailable"]
    native_count: int | None
    parsed_count: int
    unknown_results: list[dict[str, JsonValue]]
    issues: list[DrcIssue]
    groups: list[dict[str, JsonValue]]
    count_note_zh: str


class ToolTrace(StrictModel):
    tool: str
    display_name_zh: str
    origin: Literal["model_tool_call", "model_json_action", "program", "model_response", "translation"]
    arguments: dict[str, JsonValue]
    status: Literal["ok", "error", "cancelled"]
    duration_ms: float
    summary_zh: str
    evidence_ids: list[str] = Field(default_factory=list)


class ReviewEvidence(StrictModel):
    id: str
    snapshot_id: str
    kind: str
    object_ids: list[str] = Field(default_factory=list)
    issue_ids: list[str] = Field(default_factory=list)
    data: JsonValue
    limitations_zh: str


class Explanation(StrictModel):
    title_zh: str = Field(min_length=1, max_length=240)
    issue_ids: list[str] = Field(default_factory=list, max_length=50)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)
    object_ids: list[str] = Field(default_factory=list, max_length=30)
    explanation_zh: str = Field(min_length=1, max_length=2400)
    steps_zh: list[str] = Field(default_factory=list, max_length=8)
    verification_zh: str = Field(min_length=1, max_length=1200)
    rule_ids: list[str] = Field(default_factory=list, max_length=8)
    uncertainty_zh: str = Field(min_length=1, max_length=1200)


class AgentDraft(StrictModel):
    explanations: list[Explanation] = Field(default_factory=list, max_length=20)
    pending_checks: list[Explanation] = Field(default_factory=list, max_length=20)


class ReviewReport(StrictModel):
    version: Literal["0.7.0"] = "0.7.0"
    snapshot_id: str
    request_id: str
    source_kind: Literal["eda_live", "historical_replay", "synthetic"]
    provenance: dict[str, JsonValue]
    context_hash: str
    hash_scope_zh: str
    summary_zh: str
    drc: DrcInventory
    explanations: list[Explanation] = Field(default_factory=list)
    pending_checks: list[Explanation] = Field(default_factory=list)
    evidence: list[ReviewEvidence] = Field(default_factory=list)
    analysis_trace: list[ToolTrace] = Field(default_factory=list)
    knowledge_references: list[dict[str, JsonValue]] = Field(default_factory=list)
    agent_mode: Literal["not_run", "native_tool_calls", "json_actions", "explanation_only"] = "not_run"
    agent_status: Literal["not_run", "running", "completed", "failed", "cancelled", "limited"] = "not_run"
    agent_message_zh: str = "智能体尚未运行；完整 DRC 清单已独立保留。"
    chinese_status: Literal["passed", "pending", "failed"] = "pending"
    rejected_conclusions: list[dict[str, JsonValue]] = Field(default_factory=list)
    raw_model_draft: JsonValue | None = None
    comparison: dict[str, JsonValue] | None = None


class SnapshotInput(StrictModel):
    context: PCBContextV2
    source_kind: Literal["eda_live", "historical_replay", "synthetic"]
    previous_snapshot_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


class AnalyzeOptions(StrictModel):
    mode: Literal["auto", "native_tool_calls", "json_actions"] = "auto"
