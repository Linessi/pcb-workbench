"""V2 schema and actual evidence-dependent tool selection."""

import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

import main
from agent.planner import select_tools
from agent.report import generate_report
from models.schema import PCBContextV2
from rag.loader import load_rules
from rag.retriever import RetrievedRule
from tools.clock_check_tool import check_clock_layout
from tools.connectivity_tool import check_connectivity


def v2_sample() -> dict:
    base = json.loads((Path(__file__).parent / "fixtures" / "v2.json").read_text(encoding="utf-8"))
    for index, component in enumerate(base["components"]):
        component.update(x=float(index * 100), y=250.0, rotation=0.0, layer="1")
    base.update({
        "schemaVersion": 2,
        "pads": [
            {"component": base["components"][0]["reference"], "number": "1", "x": 0, "y": 250, "net": "GND"},
            {"component": base["components"][1]["reference"], "number": "2", "x": 100, "y": 250, "net": "GND"},
        ],
        "connections": [{
            "source": f"{base['components'][0]['reference']}.1",
            "target": f"{base['components'][1]['reference']}.2",
            "net": "GND", "basis": "shared_net_name",
        }],
        "drc": {"available": False, "errors": [], "reason": "EDA DRC unavailable"},
        "geometry": {"outline": [], "holes": [], "vias": []},
    })
    return base


def test_v2_schema_and_selected_tools() -> None:
    data = v2_sample()
    data["geometry"]["outline"] = [{"primitiveId": "outline-test", "kind": "polyline", "source": ["R", 0, 0, 3937, 2756, 0, 0]}]
    context = PCBContextV2.model_validate(data)
    assert context.geometry.outline[0].source == ["R", 0, 0, 3937, 2756, 0, 0]
    chosen = select_tools(context)
    assert chosen == ["pcb_info", "power_check", "clock_check", "connectivity_check", "rule_search"]
    clock = check_clock_layout(context)
    assert clock.status == "ok"
    assert "component-center distance" in clock.detail
    connectivity = check_connectivity(context)
    assert connectivity.status == "insufficient_data"
    assert "do not prove routed copper" in connectivity.detail


def test_unverified_issue_is_removed_but_recommendation_survives() -> None:
    context = PCBContextV2.model_validate(v2_sample())
    rule = next(item for item in load_rules() if item.rule_id == "MCU Layout Rule #3")
    draft = {
        "summary": "依据 MCU Layout Rule #3，需复核布局。",
        "issues": [{
            "category": "Layout", "severity": "high", "problem": "晶振过远",
            "suggestion": "缩短走线", "ruleIds": [rule.rule_id],
        }],
        "recommendations": [{"priority": "high", "action": "测量 OSC 走线", "ruleIds": [rule.rule_id]}],
    }
    report = generate_report(json.dumps(draft, ensure_ascii=False), [RetrievedRule(rule, 0.8)], context)
    assert report.issues == []
    assert "未能与 EDA DRC 原文对应" in report.summary
    assert len(report.recommendations) == 1


def test_drc_quote_is_confirmed_and_invalid_link_rejected() -> None:
    data = v2_sample()
    data["drc"] = {"available": True, "errors": ["EDA DRC: GND pad is unconnected"]}
    context = PCBContextV2.model_validate(data)
    rule = load_rules()[0]
    draft = {
        "summary": f"依据 {rule.rule_id}，应修复 DRC。",
        "issues": [{
            "category": "Signal", "severity": "high", "problem": "EDA DRC: GND pad is unconnected",
            "suggestion": "检查网络连接", "ruleIds": [rule.rule_id],
        }],
        "recommendations": [],
    }
    report = generate_report(json.dumps(draft), [RetrievedRule(rule, 0.8)], context)
    assert report.issues[0].kind == "confirmed_issue"


def test_connection_error_from_eda_drc_is_reported_with_rule() -> None:
    data = v2_sample()
    error = "Connection Error (net=OSC_IN): SMD Pad (OSC_IN): C1_1 is disconnected from other object"
    data["drc"] = {"available": True, "errors": [error]}
    context = PCBContextV2.model_validate(data)
    rule = next(item for item in load_rules() if item.rule_id == "Connectivity Rule #1")
    draft = {
        "summary": f"依据 {rule.rule_id}，检查当前连接状态。",
        "issues": [],
        "recommendations": [{"priority": "high", "action": "完成布线后重跑 DRC。", "ruleIds": [rule.rule_id]}],
    }
    report = generate_report(json.dumps(draft, ensure_ascii=False), [RetrievedRule(rule, 0.9)], context)
    assert report.issues[0].problem == error
    assert report.issues[0].severity == "high"
    assert report.issues[0].ruleIds == [rule.rule_id]
    assert report.knowledgeReferences[0].source == "https://prodocs.lceda.cn/cn/pcb/design-check-drc/"


def test_connection_risks_are_bounded_and_span_distinct_nets() -> None:
    data = v2_sample()
    errors = [
        "Connection Error (net=OSC_IN): C1_1 is disconnected",
        "Connection Error (net=OSC_IN): Y1_1 is disconnected",
        "Connection Error (net=GND): C1_2 is disconnected",
        "Connection Error (net=3V3): C3_1 is disconnected",
    ]
    data["drc"] = {"available": True, "errors": errors}
    context = PCBContextV2.model_validate(data)
    rule = next(item for item in load_rules() if item.rule_id == "Connectivity Rule #1")
    draft = {
        "summary": f"依据 {rule.rule_id}，全部电路无法工作。",
        "issues": [
            {"category": "Layout", "severity": "critical", "problem": errors[0],
             "suggestion": "未经确认的具体走线方案", "ruleIds": [rule.rule_id]},
            {"category": "Layout", "severity": "critical", "problem": errors[2],
             "suggestion": "未经确认的具体走线方案", "ruleIds": [rule.rule_id]},
        ],
        "recommendations": [],
    }
    report = generate_report(json.dumps(draft, ensure_ascii=False), [RetrievedRule(rule, 0.9)], context)
    assert len(report.issues) == 3
    assert [issue.problem for issue in report.issues] == [errors[0], errors[2], errors[3]]
    assert all(issue.severity == "high" for issue in report.issues)
    assert "全部电路无法工作" not in report.summary
    assert "4 项连接性错误" in report.summary


def test_save_context_writes_a_validated_fixed_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "OUTPUT_DIRECTORY", tmp_path)
    with TestClient(main.app) as client:
        response = client.post("/api/save_context", json=v2_sample())
    assert response.status_code == 200
    path = tmp_path / "robot_controller_context_v06.json"
    assert response.json() == {"saved": True, "path": str(path)}
    saved = PCBContextV2.model_validate_json(path.read_text(encoding="utf-8"))
    assert saved.schemaVersion == 2
    assert saved.statistics.componentCount == 20
