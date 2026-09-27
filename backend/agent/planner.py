"""Deterministic review planning from the available PCB Context fields."""

from dataclasses import dataclass
from typing import Literal

from models.schema import PCBContext, PCBContextV2


ReviewArea = Literal["Power", "Layout", "Signal", "EMC"]


@dataclass(frozen=True)
class ReviewTask:
    area: ReviewArea
    priority: Literal["high", "normal"]
    focus: str
    limitation: str


def plan_review(context: PCBContext) -> list[ReviewTask]:
    """Plan four checks, giving power priority when rail-like nets are present."""
    rail_hints = ("GND", "VCC", "VDD", "VIN", "VBUS", "+5V", "+3V3", "PWR")
    power_nets = [name for name in context.nets if any(hint in name.upper() for hint in rail_hints)]
    board = context.board
    return [
        ReviewTask(
            area="Power",
            priority="high" if power_nets else "normal",
            focus=f"Inspect named supply/ground nets: {', '.join(power_nets[:12]) or 'none identified'}.",
            limitation="Voltage, current and trace width are unavailable; pad nets are logical only." if isinstance(context, PCBContextV2) else "No voltage, current, connectivity, trace width or copper geometry is provided.",
        ),
        ReviewTask(
            area="Layout",
            priority="high" if context.statistics.componentCount else "normal",
            focus=f"Review board size {board.width} × {board.height} mil and {context.statistics.componentCount} component identities.",
            limitation="Component centers are available, but clearances and routing are not proven." if isinstance(context, PCBContextV2) else "No component coordinates, clearances, placement or board-edge distances are provided.",
        ),
        ReviewTask(
            area="Signal",
            priority="high" if context.statistics.netCount else "normal",
            focus=f"Review the {context.statistics.netCount} available net names for design-review questions.",
            limitation="Pad-level logical nets are available; physical routing, impedance and timing are not proven." if isinstance(context, PCBContextV2) else "No pin-level topology, routing, impedance or timing data is provided.",
        ),
        ReviewTask(
            area="EMC",
            priority="normal",
            focus=f"Consider the {len(board.layers)} configured layer names and available net names.",
            limitation="Configured layer names do not describe the stackup, return paths or emissions.",
        ),
    ]


def select_tools(context: PCBContext) -> list[str]:
    """Select deterministic tools from actual component/net evidence."""
    selected = ["pcb_info"]
    signature = " ".join([*(part.value for part in context.components), *context.nets]).upper()
    if any(word in signature for word in ("BUCK", "LDO", "VDD", "GND", "VIN", "POWER", "+5V", "3V3")):
        selected.append("power_check")
    if any(word in signature for word in ("STM32", "MCU", "CRYSTAL", "晶振", "OSC_", "XTAL")):
        selected.append("clock_check")
    if isinstance(context, PCBContextV2) and (context.pads or context.drc.available):
        selected.append("connectivity_check")
    selected.append("rule_search")
    return selected
