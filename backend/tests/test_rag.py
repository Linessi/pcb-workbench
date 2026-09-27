"""Grounded citation and FAISS retrieval tests for the stage-four corpus."""

import asyncio
import json
from pathlib import Path

import httpx
import numpy as np
import pytest
from openai import AsyncOpenAI
from pydantic import SecretStr

from agent.pcb_agent import PCBReviewAgent
from agent.planner import plan_review
from agent.report import InvalidModelReport, generate_report
from config.settings import Settings
from main import app, get_agent
from models.schema import PCBContext
from rag.loader import load_rules
from rag.retriever import RetrievedRule, RuleRetriever


ROBOT_PATH = Path(__file__).parent / "fixtures" / "robot_context.json"


class TinyEmbedder:
    """Deterministic two-dimensional vectors isolate FAISS and retrieval logic."""

    def encode_documents(self, texts: list[str]) -> np.ndarray:
        return np.asarray(
            [[1.0, 0.0] if "MCU Layout Rule #3" in text else [0.0, 1.0] for text in texts],
            dtype=np.float32,
        )

    def encode_queries(self, texts: list[str]) -> np.ndarray:
        return np.asarray(
            [[1.0, 0.0] if "晶振" in text else [0.0, 1.0] for text in texts],
            dtype=np.float32,
        )


def test_robot_board_retrieves_citable_crystal_rule_via_faiss() -> None:
    context = PCBContext.model_validate(json.loads(ROBOT_PATH.read_text(encoding="utf-8")))
    rules = load_rules()
    assert len(rules) == 16
    retriever = RuleRetriever(rules, TinyEmbedder())
    assert retriever.index.ntotal == len(rules)
    matches = retriever.retrieve(context, plan_review(context))
    assert "MCU Layout Rule #3" in [match.rule.rule_id for match in matches]


def test_report_requires_real_retrieved_rule_id() -> None:
    crystal_rule = next(rule for rule in load_rules() if rule.rule_id == "MCU Layout Rule #3")
    retrieved = [RetrievedRule(crystal_rule, 0.91)]
    good = {
        "summary": "机器人控制板有外部晶振；依据 MCU Layout Rule #3，应核对位置，当前没有坐标。",
        "issues": [],
        "recommendations": [{
            "priority": "high",
            "action": "补充晶振和 MCU 坐标后复核距离。",
            "ruleIds": ["MCU Layout Rule #3"],
        }],
    }
    report = generate_report(json.dumps(good, ensure_ascii=False), retrieved)
    assert report.knowledgeReferences[0].id == "MCU Layout Rule #3"
    assert report.recommendations[0].ruleIds == ["MCU Layout Rule #3"]
    assert report.knowledgeReferences[0].source.startswith("https://www.st.com/")

    with pytest.raises(InvalidModelReport, match="did not cite"):
        generate_report('{"summary":"没有引用","issues":[],"recommendations":[]}', retrieved)

    with pytest.raises(InvalidModelReport, match="not retrieved"):
        generate_report(json.dumps({
            "summary": good["summary"] + " Invented Rule #99",
            "issues": [],
            "recommendations": good["recommendations"],
        }, ensure_ascii=False), retrieved)

    forged = {
        "summary": good["summary"],
        "issues": [{
            "category": "Layout",
            "severity": "medium",
            "problem": "请核对晶振位置",
            "suggestion": "检查坐标与走线",
            "ruleIds": ["Invented Rule #99"],
        }],
        "recommendations": [],
    }
    with pytest.raises(InvalidModelReport, match="not retrieved"):
        generate_report(json.dumps(forged, ensure_ascii=False), retrieved)

    forged_recommendation = {
        "summary": good["summary"],
        "issues": [],
        "recommendations": [{
            "priority": "high",
            "action": "检查晶振位置",
            "ruleIds": ["Invented Rule #99"],
        }],
    }
    with pytest.raises(InvalidModelReport, match="not retrieved"):
        generate_report(json.dumps(forged_recommendation, ensure_ascii=False), retrieved)


def test_robot_board_http_pipeline_includes_knowledge_basis() -> None:
    context = json.loads(ROBOT_PATH.read_text(encoding="utf-8"))
    retriever = RuleRetriever(load_rules(), TinyEmbedder())

    def fake_completion(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        prompt = json.loads(json.loads(request.content)["messages"][1]["content"])
        ids = {rule["id"] for rule in prompt["knowledgeRules"]}
        assert "MCU Layout Rule #3" in ids
        report = {
            "summary": "依据 MCU Layout Rule #3，应检查 MCU 与晶振距离；当前 Context 没有坐标。",
            "issues": [],
            "recommendations": [{
                "priority": "high",
                "action": "读取元件坐标后核对晶振距离。",
                "ruleIds": ["MCU Layout Rule #3"],
            }],
        }
        return httpx.Response(200, json={
            "id": "rag-test-only",
            "object": "chat.completion",
            "created": 0,
            "model": "test-only",
            "choices": [{
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": json.dumps(report, ensure_ascii=False)},
            }],
        })

    async def run() -> httpx.Response:
        settings = Settings(
            _env_file=None,
            llm_base_url="http://llm-test/v1",
            llm_api_key=SecretStr("test-only"),
            model_name="test-only",
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(fake_completion)) as llm_http:
            sdk = AsyncOpenAI(api_key="test-only", base_url="http://llm-test/v1", http_client=llm_http)
            app.dependency_overrides[get_agent] = lambda: PCBReviewAgent(settings, sdk, retriever)
            try:
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://backend-test"
                ) as backend_http:
                    return await backend_http.post("/api/analyze_pcb", json=context)
            finally:
                app.dependency_overrides.clear()

    response = asyncio.run(run())
    assert response.status_code == 200
    body = response.json()
    assert body["issues"] == []
    assert body["recommendations"][0]["priority"] == "high"
    assert "MCU Layout Rule #3" in body["summary"]
    assert body["knowledgeReferences"][0]["id"] == "MCU Layout Rule #3"
