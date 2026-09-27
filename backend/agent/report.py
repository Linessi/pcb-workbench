"""Validate the model's response against the public report contract."""

import json
import re

from pydantic import ValidationError

from models.schema import AnalysisTrace, Evidence, KnowledgeReference, PCBContext, PCBContextV2, PCBReviewDraft, PCBReviewReport, ReviewIssue
from rag.retriever import RetrievedRule
from tools import ToolResult


class InvalidModelReport(ValueError):
    """The model did not return a usable PCBReviewReport."""


RULE_MENTION = re.compile(r"(?<![A-Za-z])(?:[A-Za-z][A-Za-z-]*\s+){1,3}Rule #\d+")
CONNECTION_NET = re.compile(r"\(net=([^)]+)\)")


def representative_connection_errors(errors: list[str], limit: int) -> list[str]:
    """Prefer distinct affected nets for a concise, DRC-backed risk list."""
    if limit <= 0:
        return []
    selected: list[str] = []
    seen_nets: set[str] = set()
    for error in errors:
        match = CONNECTION_NET.search(error)
        net = match.group(1) if match else error
        if net not in seen_nets:
            selected.append(error)
            seen_nets.add(net)
        if len(selected) == limit:
            return selected
    for error in errors:
        if error not in selected:
            selected.append(error)
        if len(selected) == limit:
            break
    return selected


def generate_report(
    content: str, retrieved: list[RetrievedRule], context: PCBContext | None = None,
    tool_results: list[ToolResult] | None = None,
) -> PCBReviewReport:
    raw = content.strip()
    if raw.startswith("```") and raw.endswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1]).strip()
    try:
        payload = json.loads(raw)
        draft = PCBReviewDraft.model_validate(payload)
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise InvalidModelReport("LLM response is not a valid PCBReviewReport JSON object") from exc

    available = {hit.rule.rule_id: hit.rule for hit in retrieved}
    for mention in RULE_MENTION.findall(draft.summary):
        if not any(mention.endswith(rule_id) for rule_id in available):
            raise InvalidModelReport("LLM cited a rule that was not retrieved")
    for issue in draft.issues:
        unknown = set(issue.ruleIds) - available.keys()
        if unknown:
            raise InvalidModelReport("LLM cited a rule that was not retrieved")
    for recommendation in draft.recommendations:
        unknown = set(recommendation.ruleIds) - available.keys()
        if unknown:
            raise InvalidModelReport("LLM cited a rule that was not retrieved")
    connection_errors = (
        [error for error in context.drc.errors if error.startswith("Connection Error")]
        if isinstance(context, PCBContextV2) and context.drc.available else []
    )

    # A model statement is only a confirmed issue when it quotes a real EDA
    # DRC result. Component proximity and rule guidance alone are not faults.
    issues = list(draft.issues)
    if context is not None:
        errors = context.drc.errors if isinstance(context, PCBContextV2) and context.drc.available else []
        issues = [issue for issue in issues if any(error and error in issue.problem for error in errors)]
    summary = draft.summary
    if len(issues) != len(draft.issues):
        summary = (
            f"依据 {retrieved[0].rule.rule_id}，模型提出的 {len(draft.issues) - len(issues)} 项问题未能"
            "与 EDA DRC 原文对应，已从已确认问题中移除。请根据工具证据复核设计，"
            "并执行报告中的下一步建议。"
        )
    if connection_errors and "Connectivity Rule #1" in available:
        # Use the literal EDA DRC strings for confirmed connection errors.
        # Model-selected connection errors can overlap our examples or attach
        # unsupported claims to their suggestions, so present a bounded,
        # deterministic selection across different affected nets.
        issues = [issue for issue in issues if not issue.problem.startswith("Connection Error")][:3]
        for error in representative_connection_errors(connection_errors, 3 - len(issues)):
            issues.append(ReviewIssue(
                category="Signal",
                severity="high",
                problem=error,
                suggestion="在嘉立创 EDA DRC 面板定位该连接性错误，完成对应网络连接后重新运行 DRC。",
                ruleIds=["Connectivity Rule #1"],
            ))
        summary = (
            f"EDA DRC 返回 {len(connection_errors)} 项连接性错误；风险列表列出 {len(issues)} 项"
            "与 DRC 原文对应的代表性错误。依据 Connectivity Rule #1，请在 EDA 中逐项定位并"
            "完成相应连接后复查；其余布局与布线关注点见建议。"
        )
    cited = {rule_id for rule_id in available if rule_id in summary}
    for issue in issues:
        cited.update(issue.ruleIds)
    for recommendation in draft.recommendations:
        cited.update(recommendation.ruleIds)
    if not cited:
        raise InvalidModelReport("LLM report did not cite a retrieved knowledge rule")
    references = [
        KnowledgeReference(id=rule.rule_id, title=rule.title, source=rule.source)
        for rule_id, rule in available.items() if rule_id in cited
    ]
    trace = [AnalysisTrace(tool=item.tool, result=item.status, detail=item.detail) for item in tool_results or []]
    if tool_results is not None:
        trace.append(AnalysisTrace(tool="qwen_review", result="ok", detail="Structured model report validated against retrieved rule IDs and DRC evidence."))
    evidence: list[Evidence] = [record for item in tool_results or [] for record in item.evidence]
    return PCBReviewReport(
        summary=summary,
        issues=issues,
        recommendations=draft.recommendations,
        knowledgeReferences=references,
        analysis_trace=trace,
        evidence=evidence,
    )
