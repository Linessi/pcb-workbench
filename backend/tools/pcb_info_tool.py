"""Summarize data that is directly present in a PCB Context."""

from models.schema import Evidence, PCBContext, PCBContextV2
from tools import ToolResult


def get_pcb_summary(context: PCBContext) -> ToolResult:
    extra = ""
    if isinstance(context, PCBContextV2):
        extra = f", {len(context.pads)} pads, {len(context.geometry.vias)} vias"
    detail = (
        f"{context.projectName}: {context.board.width:g} × {context.board.height:g} mil, "
        f"{context.statistics.componentCount} components, {context.statistics.netCount} nets{extra}"
    )
    return ToolResult("pcb_info", "ok", detail, [Evidence(source="pcb_info", reason=detail)])
