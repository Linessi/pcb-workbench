"""Shared wire format for the EDA plugin and the PCB review API."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Board(StrictModel):
    width: float = Field(gt=0, description="Board outline width in mil")
    height: float = Field(gt=0, description="Board outline height in mil")
    layers: list[str]


class Component(StrictModel):
    reference: str
    value: str
    package: str


class Point(StrictModel):
    x: float
    y: float


class ComponentV2(Component):
    primitiveId: str | None = None
    x: float
    y: float
    rotation: float
    layer: str


class Pad(Point):
    primitiveId: str | None = None
    component: str
    number: str
    net: str


class Connection(StrictModel):
    source: str
    target: str
    net: str
    basis: Literal["shared_net_name"]


class DRCResult(StrictModel):
    available: bool
    errors: list[str]
    reason: str | None = None
    raw: JsonValue | None = None
    execution: dict[str, JsonValue] | None = None


class OutlinePrimitive(StrictModel):
    primitiveId: str
    kind: Literal["polyline", "line", "arc"]
    points: list[Point] = Field(default_factory=list)
    source: list[str | float] | None = None
    arcAngle: float | None = None


class Hole(Point):
    source: Literal["pad", "via"]
    shape: Literal["round", "slot"]
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    component: str | None = None
    padNumber: str | None = None


class Via(Point):
    net: str
    diameter: float = Field(gt=0)
    holeDiameter: float = Field(gt=0)


class BoardGeometry(StrictModel):
    outline: list[OutlinePrimitive]
    holes: list[Hole]
    vias: list[Via]


class Statistics(StrictModel):
    componentCount: int = Field(ge=0)
    netCount: int = Field(ge=0)


class PCBContext(StrictModel):
    projectName: str = Field(min_length=1)
    board: Board
    components: list[Component]
    nets: list[str]
    statistics: Statistics

    @model_validator(mode="after")
    def counts_match_lists(self) -> "PCBContext":
        if self.statistics.componentCount != len(self.components):
            raise ValueError("componentCount does not match components length")
        if self.statistics.netCount != len(self.nets):
            raise ValueError("netCount does not match nets length")
        return self


class PCBContextV2(PCBContext):
    schemaVersion: Literal[2]
    components: list[ComponentV2]
    pads: list[Pad]
    connections: list[Connection]
    drc: DRCResult
    geometry: BoardGeometry
    provenance: dict[str, JsonValue] | None = None
    coverage: dict[str, JsonValue] | None = None

    @model_validator(mode="after")
    def references_are_consistent(self) -> "PCBContextV2":
        references = {component.reference for component in self.components}
        if any(pad.component not in references for pad in self.pads):
            raise ValueError("pad refers to an unknown component")
        pad_ids = {f"{pad.component}.{pad.number}" for pad in self.pads}
        if any(edge.source not in pad_ids or edge.target not in pad_ids for edge in self.connections):
            raise ValueError("connection refers to an unknown pad")
        return self


class ReviewIssue(StrictModel):
    # `issues` are confirmed observations; unverified checks belong in recommendations.
    kind: Literal["confirmed_issue"] = "confirmed_issue"
    category: Literal["Power", "Layout", "Signal", "EMC"]
    severity: Literal["critical", "high", "medium", "low"]
    problem: str = Field(min_length=1)
    suggestion: str = Field(min_length=1)
    ruleIds: list[str] = Field(min_length=1)


class ReviewRecommendation(StrictModel):
    priority: Literal["high", "medium", "low"]
    action: str = Field(min_length=1)
    ruleIds: list[str] = Field(min_length=1)


class PCBReviewDraft(StrictModel):
    summary: str = Field(min_length=1)
    issues: list[ReviewIssue]
    recommendations: list[ReviewRecommendation]


class KnowledgeReference(StrictModel):
    id: str
    title: str
    source: str


class AnalysisTrace(StrictModel):
    tool: str
    result: Literal["ok", "warning", "insufficient_data", "error"]
    detail: str


class Evidence(StrictModel):
    source: str
    reason: str


class PCBReviewReport(PCBReviewDraft):
    knowledgeReferences: list[KnowledgeReference]
    analysis_trace: list[AnalysisTrace] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
