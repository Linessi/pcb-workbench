"""Report logical net membership and official EDA DRC observations."""

from models.schema import Evidence, PCBContext, PCBContextV2
from tools import ToolResult


def check_connectivity(context: PCBContext) -> ToolResult:
    if not isinstance(context, PCBContextV2):
        return ToolResult("connectivity_check", "insufficient_data", "No pad-level net or EDA DRC data in V1 Context.", [])
    detail = f"{len(context.pads)} pads; {len(context.connections)} shared-net logical edges. Logical edges do not prove routed copper continuity."
    evidence = [Evidence(source="connectivity_check", reason=detail)]
    if not context.drc.available:
        return ToolResult("connectivity_check", "insufficient_data", f"{detail} EDA DRC unavailable: {context.drc.reason or 'no result'}.", evidence)
    if context.drc.errors:
        finding = f"EDA DRC returned {len(context.drc.errors)} result(s). First result: {context.drc.errors[0][:300]}"
        evidence.append(Evidence(source="EDA DRC", reason=finding))
        return ToolResult("connectivity_check", "warning", f"{detail} {finding}", evidence)
    return ToolResult("connectivity_check", "ok", f"{detail} EDA DRC returned no errors.", evidence)
