"""Build an exact FAISS cosine index and retrieve rules for a PCB Context."""

from dataclasses import dataclass
from functools import lru_cache

import faiss

from agent.planner import ReviewTask
from models.schema import PCBContext, PCBContextV2
from rag.embedding import BGEEmbedder, EmbeddingBackend
from rag.loader import KnowledgeRule, load_rules


class KnowledgeBaseUnavailable(RuntimeError):
    """The local knowledge corpus or embedding model could not be loaded."""


@dataclass(frozen=True)
class RetrievedRule:
    rule: KnowledgeRule
    score: float


class RuleRetriever:
    def __init__(
        self,
        rules: list[KnowledgeRule] | None = None,
        embedder: EmbeddingBackend | None = None,
    ) -> None:
        self.rules = rules if rules is not None else load_rules()
        if not self.rules:
            raise ValueError("PCB knowledge base is empty")
        self.embedder = embedder if embedder is not None else BGEEmbedder()
        vectors = self.embedder.encode_documents([rule.embedding_text for rule in self.rules])
        if vectors.shape[0] != len(self.rules) or vectors.shape[1] < 1:
            raise ValueError("Invalid knowledge embedding matrix")
        # BGE returns normalized float32 vectors; inner product is cosine similarity.
        self.index = faiss.IndexFlatIP(vectors.shape[1])
        self.index.add(vectors)

    def retrieve(
        self,
        context: PCBContext,
        plan: list[ReviewTask],
        per_query: int = 2,
        max_rules: int = 8,
    ) -> list[RetrievedRule]:
        component_text = "、".join(
            f"{item.reference} {item.value} {item.package}" for item in context.components[:40]
        )
        net_text = "、".join(context.nets[:40])
        queries = [
            f"PCB {task.area} 审查。{task.focus} 元件：{component_text}。网络：{net_text}。"
            for task in plan
        ]
        signature = (component_text + " " + net_text).upper()
        if any(term in signature for term in ("晶振", "晶体", "XTAL", "OSC_", "CRYSTAL")):
            queries.append(f"MCU 外部晶振 OSC XTAL 布局与时钟干扰检查。元件：{component_text}。网络：{net_text}。")
        if any(term in signature for term in ("USB", "CAN_H", "CAN_L", "LVDS")):
            queries.append(f"高速或差分信号参考平面、阻抗与差分对检查。网络：{net_text}。")
        if isinstance(context, PCBContextV2) and context.drc.available and context.drc.errors:
            queries.append("PCB DRC 连接性错误、飞线与未布线网络。依据 EDA DRC 原文核对实际连接。")

        vectors = self.embedder.encode_queries(queries)
        if vectors.shape != (len(queries), self.index.d):
            raise ValueError("Invalid query embedding matrix")
        scores, positions = self.index.search(vectors, min(per_query, len(self.rules)))
        best: dict[int, float] = {}
        for score_row, position_row in zip(scores, positions):
            for score, position in zip(score_row, position_row):
                if position >= 0:
                    best[int(position)] = max(best.get(int(position), -1.0), float(score))
        ranked = sorted(best.items(), key=lambda item: (-item[1], self.rules[item[0]].rule_id))
        return [RetrievedRule(self.rules[index], score) for index, score in ranked[:max_rules]]


@lru_cache(maxsize=1)
def get_retriever() -> RuleRetriever:
    try:
        return RuleRetriever()
    except Exception as exc:
        raise KnowledgeBaseUnavailable("PCB knowledge base or BGE model is unavailable") from exc
