"""Use the existing BGE/FAISS retriever as an explicit Agent tool."""

from agent.planner import ReviewTask
from models.schema import Evidence, PCBContext
from rag.retriever import RetrievedRule, RuleRetriever
from tools import ToolResult


def search_pcb_rule(
    context: PCBContext, plan: list[ReviewTask], retriever: RuleRetriever,
) -> tuple[list[RetrievedRule], ToolResult]:
    hits = retriever.retrieve(context, plan)
    evidence = [Evidence(source=hit.rule.rule_id, reason=f"{hit.rule.title}; source: {hit.rule.source}") for hit in hits]
    detail = f"Retrieved {len(hits)} knowledge rules: {', '.join(hit.rule.rule_id for hit in hits)}"
    return hits, ToolResult("rule_search", "ok" if hits else "warning", detail, evidence)
