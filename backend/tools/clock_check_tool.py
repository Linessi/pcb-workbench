"""Measure component-center distance only when positions are supplied."""

from math import hypot

from models.schema import Evidence, PCBContext, PCBContextV2
from tools import ToolResult


def check_clock_layout(context: PCBContext) -> ToolResult:
    mcus = [part for part in context.components if any(token in part.value.upper() for token in ("STM32", "MCU", "ESP32"))]
    crystals = [part for part in context.components if part.reference.upper().startswith("Y") or any(
        token in part.value.upper() for token in ("CRYSTAL", "晶振", "OSCILLATOR")
    )]
    if not mcus or not crystals:
        return ToolResult("clock_check", "insufficient_data", "No MCU/crystal pair identified in component values.", [])
    if not isinstance(context, PCBContextV2):
        return ToolResult("clock_check", "insufficient_data", "MCU and crystal identified, but coordinates are unavailable.", [])
    mcu, crystal = mcus[0], crystals[0]
    distance = hypot(mcu.x - crystal.x, mcu.y - crystal.y)
    detail = f"{crystal.reference} to {mcu.reference} component-center distance: {distance:.1f} mil ({distance * 0.0254:.2f} mm). This is not trace length or clearance."
    return ToolResult("clock_check", "ok", detail, [Evidence(source="clock_check", reason=detail)])
