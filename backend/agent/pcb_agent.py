"""Context parser -> planner -> Qwen reasoner -> report generator."""

import asyncio
import json
import logging

from openai import AsyncOpenAI

from agent.planner import plan_review, select_tools
from agent.report import InvalidModelReport, generate_report
from config.settings import Settings
from models.schema import PCBContext, PCBReviewReport
from rag.retriever import KnowledgeBaseUnavailable, RuleRetriever, get_retriever
from tools import ToolResult
from tools.clock_check_tool import check_clock_layout
from tools.connectivity_tool import check_connectivity
from tools.pcb_info_tool import get_pcb_summary
from tools.power_check_tool import check_power_design
from tools.rule_search_tool import search_pcb_rule

logger = logging.getLogger("ai_eda_copilot.agent")


SYSTEM_PROMPT = """You are a cautious PCB design review assistant.
Use only the supplied PCB Context as board-specific evidence. Knowledge rules are
general guidance, not proof that this PCB violates a rule. The context contains
board dimensions in mil, configured layer names, component identities and net names.
V2 may also contain component centers, pads, logical net relations, vias, outline and
EDA DRC results. Shared-net relations are not copper continuity. Component-center
distance is not trace length or clearance. No trace widths, stackup, current or
voltages are provided. Tool results report observations, not automatic violations.
Only a literal EDA DRC error may be placed in issues: copy that exact DRC error into
problem. If DRC is unavailable or empty, issues MUST be empty. Any other concern
belongs in recommendations and must state what evidence to collect. Review Power,
Layout, Signal and EMC without inventing board-specific facts.
Use only rule IDs from knowledgeRules. Cite at least one relevant exact rule ID in
the summary, including when issues is empty. Each issue must list one or more
applicable retrieved rule IDs in ruleIds. Never invent a rule ID or source.
Recommendations are evidence-gathering or review actions, not confirmed faults.
Return 2-4 useful recommendations even when issues is empty. Each recommendation
must cite one or more retrieved rule IDs. Prioritize actions without implying
that a missing measurement proves a defect.
Return ONLY a JSON object with exactly this shape:
{"summary":"string","issues":[{"category":"Power|Layout|Signal|EMC",
"severity":"critical|high|medium|low","problem":"string","suggestion":"string",
"ruleIds":["exact retrieved rule ID"]}],"recommendations":[{"priority":
"high|medium|low","action":"string","ruleIds":["exact retrieved rule ID"]}]}
Write summary, problem, suggestion and action in Chinese. No Markdown or code fence."""


class PCBReviewAgent:
    def __init__(
        self,
        settings: Settings,
        client: AsyncOpenAI | None = None,
        retriever: RuleRetriever | None = None,
    ) -> None:
        self.settings = settings
        self.retriever = retriever
        self.client = client or AsyncOpenAI(
            api_key=settings.llm_api_key.get_secret_value(),
            base_url=settings.llm_base_url.strip().rstrip("/"),
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )

    async def analyze(self, context: PCBContext) -> PCBReviewReport:
        plan = plan_review(context)
        chosen = select_tools(context)
        tool_functions = {
            "pcb_info": get_pcb_summary,
            "power_check": check_power_design,
            "clock_check": check_clock_layout,
            "connectivity_check": check_connectivity,
        }
        tool_results: list[ToolResult] = [tool_functions[name](context) for name in chosen if name in tool_functions]
        # Build/load the local FAISS index off the FastAPI event loop.
        try:
            retrieved, rule_result = await asyncio.to_thread(
                search_pcb_rule, context, plan, self.retriever or get_retriever()
            )
            if not retrieved:
                raise ValueError("PCB knowledge retrieval returned no rules")
            tool_results.append(rule_result)
        except Exception as exc:
            await self.client.close()
            raise KnowledgeBaseUnavailable("PCB knowledge retrieval failed") from exc
        user_payload = {
            "reviewPlan": [task.__dict__ for task in plan],
            "pcbContext": context.model_dump(mode="json"),
            "selectedTools": chosen,
            "toolEvidence": [
                {"tool": item.tool, "status": item.status, "detail": item.detail,
                 "evidence": [record.model_dump() for record in item.evidence]}
                for item in tool_results
            ],
            "knowledgeRules": [hit.rule.prompt_payload() for hit in retrieved],
        }
        try:
            completion = await self.client.chat.completions.create(
                model=self.settings.model_name.strip(),
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
                ],
                temperature=0.2,
                max_tokens=self.settings.llm_max_output_tokens,
                # Qwen3.8 on vLLM spends the output budget on hidden reasoning
                # by default. The installed local endpoint accepts this
                # Qwen/vLLM option; other providers can disable it in .env.
                extra_body=(
                    {"chat_template_kwargs": {"enable_thinking": False}}
                    if self.settings.llm_disable_thinking else None
                ),
            )
        finally:
            await self.client.close()
        if not completion.choices:
            raise InvalidModelReport("LLM returned no choices")
        choice = completion.choices[0]
        if choice.finish_reason == "length":
            logger.warning(
                "LLM response truncated, completion_tokens=%s max_output_tokens=%s",
                completion.usage.completion_tokens if completion.usage else "unknown",
                self.settings.llm_max_output_tokens,
            )
            raise InvalidModelReport("LLM response was truncated")
        if not choice.message.content:
            raise InvalidModelReport("LLM returned no report content")
        return generate_report(choice.message.content, retrieved, context, tool_results)
