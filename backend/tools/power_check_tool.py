"""Inventory power design indicators; never infer electrical adequacy."""

from models.schema import Evidence, PCBContext
from tools import ToolResult


RAIL_HINTS = ("GND", "VCC", "VDD", "VIN", "VBUS", "+5V", "+3V3", "PWR", "12V")
REGULATOR_HINTS = ("BUCK", "LDO", "REGULATOR", "LM2596", "AMS1117", "MP1584", "TPS")


def check_power_design(context: PCBContext) -> ToolResult:
    rails = [net for net in context.nets if any(hint in net.upper() for hint in RAIL_HINTS)]
    regulators = [part.reference for part in context.components if any(
        hint in f"{part.reference} {part.value}".upper() for hint in REGULATOR_HINTS
    )]
    capacitors = [part.reference for part in context.components if part.reference.upper().startswith("C")]
    detail = f"Power nets: {', '.join(rails) or 'none identified'}; regulator hints: {', '.join(regulators) or 'none identified'}; capacitor count: {len(capacitors)}."
    evidence = [Evidence(source="power_check", reason=detail)]
    status = "warning" if regulators and not capacitors else "ok"
    if not rails and not regulators:
        status = "insufficient_data"
    return ToolResult("power_check", status, detail, evidence)
