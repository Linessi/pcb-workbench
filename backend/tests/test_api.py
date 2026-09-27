"""Contract tests using a synthetic context with the same count invariants and an in-memory LLM transport."""

import asyncio
import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from openai import AsyncOpenAI
from pydantic import SecretStr
import pytest

from agent.pcb_agent import PCBReviewAgent
from agent.planner import plan_review
from config.settings import Settings
from main import app, get_agent
from models.schema import PCBContext, PCBReviewReport
from rag.loader import load_rules
from rag.retriever import RetrievedRule


CONTEXT_PATH = Path(__file__).parent / "fixtures" / "contract.json"
SAMPLE_CONTEXT = json.loads(CONTEXT_PATH.read_text(encoding="utf-8"))


def test_stage_two_context_parses_and_plans_four_directions() -> None:
    context = PCBContext.model_validate(SAMPLE_CONTEXT)
    plan = plan_review(context)
    assert [task.area for task in plan] == ["Power", "Layout", "Signal", "EMC"]
    assert context.statistics.componentCount == 33
    assert context.statistics.netCount == 17


def test_http_contract_and_cors() -> None:
    class StubAgent:
        async def analyze(self, context: PCBContext) -> PCBReviewReport:
            return PCBReviewReport(
                summary=f"已读取 {context.projectName}",
                issues=[],
                recommendations=[],
                knowledgeReferences=[],
            )

    app.dependency_overrides[get_agent] = lambda: StubAgent()
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/analyze_pcb",
                json=SAMPLE_CONTEXT,
                headers={"Origin": "https://pro.lceda.cn"},
            )
            assert response.status_code == 200
            assert response.json() == {
                "summary": "已读取 合成接口测试夹具",
                "issues": [],
                "recommendations": [],
                "knowledgeReferences": [],
                "analysis_trace": [],
                "evidence": [],
            }
            assert response.headers["access-control-allow-origin"] == "*"
            assert len(response.headers["x-request-id"]) == 12

            invalid = dict(SAMPLE_CONTEXT)
            invalid["statistics"] = {"componentCount": 0, "netCount": 17}
            assert client.post("/api/analyze_pcb", json=invalid).status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_missing_model_config_and_unexpected_error_are_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    empty_settings = Settings(
        _env_file=None,
        llm_base_url="",
        llm_api_key=SecretStr(""),
        model_name="",
    )
    monkeypatch.setattr("main.Settings", lambda: empty_settings)
    with TestClient(app) as client:
        missing = client.post("/api/analyze_pcb", json=SAMPLE_CONTEXT)
        assert missing.status_code == 503
        assert "LLM_API_KEY" in missing.json()["detail"]
        assert "x-request-id" in missing.headers

        class BrokenAgent:
            async def analyze(self, _context: PCBContext) -> PCBReviewReport:
                raise RuntimeError("secret-like provider detail")

        app.dependency_overrides[get_agent] = lambda: BrokenAgent()
        try:
            broken = client.post("/api/analyze_pcb", json=SAMPLE_CONTEXT)
            assert broken.status_code == 500
            assert broken.json() == {"detail": "Internal backend error"}
            assert "secret-like" not in broken.text
        finally:
            app.dependency_overrides.clear()


def test_agent_calls_openai_compatible_chat_completion_and_validates_report() -> None:
    requests: list[dict[str, object]] = []
    rule = load_rules()[0]

    class StubRetriever:
        def retrieve(self, _context: PCBContext, _plan: object) -> list[RetrievedRule]:
            return [RetrievedRule(rule, 0.9)]

    def fake_completion(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        payload = json.loads(request.content)
        requests.append(payload)
        return httpx.Response(
            200,
            json={
                "id": "test-completion",
                "object": "chat.completion",
                "created": 0,
                "model": "Qwen3.8-test",
                "choices": [{
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": json.dumps({
                            "summary": f"当前数据不足以确认布线问题；参考 {rule.rule_id}。",
                            "issues": [],
                            "recommendations": [{
                                "priority": "high",
                                "action": "补充元件坐标以核对布局。",
                                "ruleIds": [rule.rule_id],
                            }],
                        }, ensure_ascii=False),
                    },
                }],
            },
        )

    async def run() -> PCBReviewReport:
        settings = Settings(
            _env_file=None,
            llm_base_url="http://testserver/v1",
            llm_api_key=SecretStr("test-only"),
            model_name="Qwen3.8-test",
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(fake_completion)) as http_client:
            sdk_client = AsyncOpenAI(
                api_key="test-only",
                base_url="http://testserver/v1",
                http_client=http_client,
            )
            agent = PCBReviewAgent(settings, client=sdk_client, retriever=StubRetriever())
            return await agent.analyze(PCBContext.model_validate(SAMPLE_CONTEXT))

    report = asyncio.run(run())
    assert report.issues == []
    assert report.recommendations[0].priority == "high"
    assert [reference.id for reference in report.knowledgeReferences] == [rule.rule_id]
    assert requests[0]["model"] == "Qwen3.8-test"
    assert requests[0]["max_tokens"] == 4096
    assert requests[0]["chat_template_kwargs"] == {"enable_thinking": False}
    user_message = requests[0]["messages"][1]["content"]
    assert json.loads(user_message)["pcbContext"]["statistics"]["componentCount"] == 33
    assert json.loads(user_message)["knowledgeRules"][0]["id"] == rule.rule_id
