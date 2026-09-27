"""Load one citable knowledge entry per Markdown rule heading."""

from dataclasses import dataclass
from pathlib import Path
import re


KNOWLEDGE_PATH = Path(__file__).resolve().parents[2] / "knowledge" / "pcb_rules.md"
HEADING = re.compile(r"^## (?P<rule_id>.+? Rule #\d+) — (?P<title>.+)$", re.MULTILINE)
CATEGORIES = {"Power", "Layout", "Signal", "EMC"}


@dataclass(frozen=True)
class KnowledgeRule:
    rule_id: str
    title: str
    category: str
    keywords: tuple[str, ...]
    source: str
    content: str
    required_evidence: tuple[str, ...] = ()
    applicable_drc_categories: tuple[str, ...] = ()

    @property
    def embedding_text(self) -> str:
        return f"{self.rule_id} {self.title}。关键词：{'、'.join(self.keywords)}。{self.content}"

    def prompt_payload(self) -> dict[str, str]:
        return {
            "id": self.rule_id,
            "title": self.title,
            "category": self.category,
            "rule": self.content,
            "source": self.source,
            "required_evidence": ",".join(self.required_evidence),
            "applicable_drc_categories": ",".join(self.applicable_drc_categories),
        }


def load_rules(path: Path = KNOWLEDGE_PATH) -> list[KnowledgeRule]:
    """Read the local, reviewed Markdown corpus and reject malformed entries."""
    text = path.read_text(encoding="utf-8")
    headings = list(HEADING.finditer(text))
    if not headings:
        raise ValueError(f"No rule headings found in {path}")

    rules: list[KnowledgeRule] = []
    seen: set[str] = set()
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        lines = text[heading.end():end].strip().splitlines()
        metadata: dict[str, str] = {}
        body_start = 0
        for body_start, line in enumerate(lines):
            if not line.strip():
                body_start += 1
                break
            key, separator, value = line.partition(": ")
            if not separator or key not in {"Category", "Keywords", "Source", "RequiredEvidence", "ApplicableDrc"}:
                raise ValueError(f"Invalid metadata for {heading.group('rule_id')}")
            metadata[key] = value.strip()
        content = "\n".join(lines[body_start:]).strip()
        rule_id = heading.group("rule_id")
        if rule_id in seen:
            raise ValueError(f"Duplicate knowledge rule ID: {rule_id}")
        if metadata.get("Category") not in CATEGORIES:
            raise ValueError(f"Invalid category for {rule_id}")
        if not metadata.get("Source", "").startswith("https://") or not content:
            raise ValueError(f"Missing source or content for {rule_id}")
        keywords = tuple(word.strip() for word in metadata.get("Keywords", "").split(",") if word.strip())
        if not keywords:
            raise ValueError(f"Missing keywords for {rule_id}")
        seen.add(rule_id)
        rules.append(KnowledgeRule(
            rule_id=rule_id,
            title=heading.group("title").strip(),
            category=metadata["Category"],
            keywords=keywords,
            source=metadata["Source"],
            content=content,
            required_evidence=tuple(part.strip() for part in metadata.get("RequiredEvidence", "").split(",") if part.strip()),
            applicable_drc_categories=tuple(part.strip() for part in metadata.get("ApplicableDrc", "").split(",") if part.strip()),
        ))
    return rules
