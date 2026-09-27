"""Bind model explanations to queried snapshot facts, not merely existing IDs."""

import json
import re
from models.schema import PCBContextV2
from review.drc import object_index
from review.schema import AgentDraft, Explanation, ReviewReport

UNIT_NUMBER = re.compile(r"(-?\d+(?:\.\d+)?)\s*(mm|mil|MHz|GHz|mA|V|Ω|%)\b")


def validate_explanations(draft: AgentDraft, report: ReviewReport, context: PCBContextV2) -> tuple[list[Explanation],list[Explanation],list[dict]]:
    evidence = {item.id:item for item in report.evidence}
    issues = {item.id:item for item in report.drc.issues}
    objects = object_index(context)
    queried = {eid for trace in report.analysis_trace for eid in trace.evidence_ids}
    for eid in list(queried):
        if eid in evidence:
            queried.update(evidence[eid].issue_ids)
    rules = {item["id"]: item for item in report.knowledge_references}
    accepted: list[Explanation] = []
    pending: list[Explanation] = []
    rejected: list[dict] = []
    for kind,entries in (("explanations",draft.explanations),("pending_checks",draft.pending_checks)):
        for entry in entries:
            reason = None
            if not entry.evidence_ids or any(eid not in evidence or eid not in queried for eid in entry.evidence_ids):
                reason = "引用的证据不存在或未通过工具取得。"
            elif any(evidence[eid].snapshot_id != report.snapshot_id for eid in entry.evidence_ids):
                reason = "证据不属于当前快照。"
            elif any(item not in issues or item not in queried for item in entry.issue_ids):
                reason = "引用的原生 DRC 标识不存在或未查询。"
            elif any(obj not in objects for obj in entry.object_ids):
                reason = "相关对象不在当前快照。"
            elif any(rule_id not in rules for rule_id in entry.rule_ids):
                reason = "知识规则未经本次检索。"
            else:
                cited_rules = {rule["id"] for eid in entry.evidence_ids if eid in evidence and evidence[eid].kind == "search_rules" and isinstance(evidence[eid].data, dict) for rule in evidence[eid].data.get("rules", []) if isinstance(rule, dict) and "id" in rule}
                if any(rule_id not in cited_rules for rule_id in entry.rule_ids):
                    reason = "引用规则没有绑定到本项实际检索证据。"
                elif kind == "explanations" and any(issues[issue_id].category not in rules[rule_id].get("applicable_drc_categories", []) for rule_id in entry.rule_ids for issue_id in entry.issue_ids if issue_id in issues):
                    reason = "知识规则不适用于所引用的原生 DRC 类型；不能作为该问题依据。"
            associated = {obj for eid in entry.evidence_ids if eid in evidence for obj in evidence[eid].object_ids}
            if entry.issue_ids:
                associated_drc = {obj.object_id for issue_id in entry.issue_ids if issue_id in issues for obj in issues[issue_id].objects}
                if any(obj not in associated_drc for obj in entry.object_ids):
                    reason = "原生 DRC 未涉及所引用对象；拒绝将其归入该错误。"
            elif any(obj not in associated for obj in entry.object_ids):
                reason = "对象与所引用工具证据不一致。"
            text = " ".join((entry.title_zh,entry.explanation_zh,*entry.steps_zh,entry.verification_zh,entry.uncertainty_zh))
            prose_objects = re.findall(r"(?<![\w])(?:U|Y|C|R|J|L|D|Q)\d+(?:\.\d+)?(?![\w])",text)
            if any(obj not in objects for obj in prose_objects):
                reason = "正文引用了不存在的元件或焊盘。"
            if any("Connection Error" == issues[item].category for item in entry.issue_ids if item in issues):
                if "短路" in entry.explanation_zh and not re.search(r"(?:不|未|不能|不等于).{0,8}短路",entry.explanation_zh):
                    reason = "连接性未连接错误不能改写为短路。"
            claimed_routing = re.search(r"(?:已经|已)布通",entry.explanation_zh) and not re.search(r"(?:不能|无法|不|不足以).{0,12}(?:已经|已)布通",entry.explanation_zh)
            if claimed_routing or re.search(r"(?:整板|整个.{0,12}网络|全部电路).{0,8}(?:失效|无法工作|烧毁)",entry.explanation_zh):
                reason = "该整体电气结论没有对应证据。"
            measurements = [evidence[eid] for eid in entry.evidence_ids if eid in evidence and evidence[eid].kind == "measure_pad_distance"]
            native_values: list[tuple[str, str]] = []
            cited_native_ids = {issue_id for eid in entry.evidence_ids if eid in evidence and evidence[eid].kind in {"get_drc_issue_details", "list_drc_issues"} for issue_id in evidence[eid].issue_ids}
            for issue_id in entry.issue_ids:
                if issue_id not in issues or issue_id not in cited_native_ids:
                    continue
                raw = issues[issue_id].raw
                explanation = raw.get("explanation", {}) if isinstance(raw, dict) else {}
                parameters = explanation.get("param", {}) if isinstance(explanation, dict) else {}
                if isinstance(parameters, dict):
                    # Only explicit native display values, bound to actually
                    # queried/cited DRC; not arbitrary errData or model numbers.
                    for key in ("diameter", "minDistance", "shouldBe"):
                        if isinstance(parameters.get(key), str):
                            native_values.extend(UNIT_NUMBER.findall(parameters[key]))
            for number,unit in UNIT_NUMBER.findall(text):
                expected = []
                for measure in measurements:
                    if unit in ("mil","mm"):
                        expected.append(measure.data[f"distance_{unit}"])
                expected.extend(float(value) for value, source_unit in native_values if source_unit == unit)
                # Measured distances and explicit native rule display values;
                # do not accept a general knowledge rule as a board threshold.
                if not expected or not any(abs(float(number)-float(value)) <= max(0.01,abs(float(value))*0.001) for value in expected):
                    reason = "数值或单位未与实际测量或所引用原生 DRC 参数一致；不接受未提供来源的阈值。"
            if measurements and re.search(r"(?:实际|测得|测量).{0,8}走线长度",entry.explanation_zh) and not re.search(r"不(?:等于|是).{0,6}走线长度",entry.explanation_zh):
                reason = "平面直线距离不能改写为实际走线长度。"
            if kind == "explanations" and not entry.issue_ids:
                reason = "没有原生 DRC 对应项，只能作为待核查建议。"
            if kind == "explanations" and re.search(r"(?:晶振|去耦|阻抗|EMC|电源完整性).{0,12}(?:违规|不合格|过远|不足|超标)",entry.title_zh+entry.explanation_zh):
                reason = "知识规则或位置观察不能单独证明此电气/布局违规；需要具体约束和原生证据。"
            if reason:
                rejected.append({"title_zh":entry.title_zh,"reason_zh":reason,"original_model_entry":entry.model_dump(mode="json")})
            else:
                (accepted if kind == "explanations" else pending).append(entry)
    return accepted,pending,rejected
