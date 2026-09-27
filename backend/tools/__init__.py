"""Deterministic, read-only PCB review tools."""

from dataclasses import dataclass
from typing import Literal

from models.schema import Evidence


@dataclass(frozen=True)
class ToolResult:
    tool: str
    status: Literal["ok", "warning", "insufficient_data", "error"]
    detail: str
    evidence: list[Evidence]
