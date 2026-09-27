"""Test-only OpenAI-compatible server for desktop integration checks.

Run on 127.0.0.1:8001. Its output is explicitly marked as a test response and
must never be presented as a real Qwen design assessment.
"""

import json

from fastapi import FastAPI


app = FastAPI()


@app.post("/v1/chat/completions")
def complete(payload: dict[str, object]) -> dict[str, object]:
    messages = payload["messages"]
    assert isinstance(messages, list)
    user_message = messages[-1]
    assert isinstance(user_message, dict)
    content = user_message["content"]
    assert isinstance(content, str)
    request_data = json.loads(content)
    context = request_data["pcbContext"]
    rules = request_data["knowledgeRules"]
    assert rules
    rule_id = next(
        (rule["id"] for rule in rules if rule["id"] == "MCU Layout Rule #3"),
        rules[0]["id"],
    )
    count = context["statistics"]["componentCount"]
    report = {
        "summary": f"[测试响应] 已通过完整插件链路接收 {count} 个元件；依据 {rule_id}。这不是 Qwen 审查结论。",
        "issues": [],
        "recommendations": [{
            "priority": "high",
            "action": f"[测试响应] 补充晶振与 MCU 坐标，再依据 {rule_id} 核对距离。",
            "ruleIds": [rule_id],
        }],
    }
    return {
        "id": "integration-test-only",
        "object": "chat.completion",
        "created": 0,
        "model": payload["model"],
        "choices": [{
            "index": 0,
            "finish_reason": "stop",
            "message": {"role": "assistant", "content": json.dumps(report, ensure_ascii=False)},
        }],
    }
