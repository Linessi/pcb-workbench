"""Immutable snapshots and verified local exports, confined to one output root."""

import html
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4

from models.schema import PCBContextV2
from review.drc import canonical, fingerprint, object_index, parse_drc, stable_issue_fingerprint
from review.schema import Explanation, ReviewEvidence, ReviewReport, SnapshotInput

DEFAULT_OUTPUT = Path(__file__).resolve().parents[2] / "output" / "reviews"
ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")


def compare_reports(old: ReviewReport, new: ReviewReport, old_context: PCBContextV2, new_context: PCBContextV2) -> dict:
    same_document = old.provenance.get("document_id") == new.provenance.get("document_id") and old.provenance.get("project_id") == new.provenance.get("project_id")
    old_exec, new_exec = old_context.drc.execution or {}, new_context.drc.execution or {}
    reasons: list[str] = []
    if not same_document:
        reasons.append("PCB 文档或工程不一致")
    if old.source_kind != "eda_live" or new.source_kind != "eda_live":
        reasons.append("不是两次当前 EDA 实时检查")
    if old.drc.status != "completed" or new.drc.status != "completed":
        reasons.append("原生 DRC 未重新完成")
    if old.drc.unknown_results or new.drc.unknown_results:
        reasons.append("存在未完整解析的原生结果")
    if old_exec.get("scope") != new_exec.get("scope") or not new_exec.get("scope"):
        reasons.append("检查范围不可比")
    if not old_exec.get("rule_config_hash") or old_exec.get("rule_config_hash") != new_exec.get("rule_config_hash"):
        reasons.append("规则配置不可取得或已变化，不能宣称已修复")
    old_by = {item.id: item for item in old.drc.issues}
    new_by = {item.id: item for item in new.drc.issues}
    # Recompute stable matching keys without rewriting historical report/evidence
    # IDs. Earlier fingerprints included runtime errData and changed every check.
    old_keys, new_keys = defaultdict(list), defaultdict(list)
    for issue in old.drc.issues:
        old_keys[stable_issue_fingerprint(issue.category, issue.net, issue.objects, issue.raw, issue.raw_message)].append(issue)
    for issue in new.drc.issues:
        new_keys[stable_issue_fingerprint(issue.category, issue.net, issue.objects, issue.raw, issue.raw_message)].append(issue)
    matches: list[dict[str, str]] = []
    if same_document:
        for key in sorted(old_keys.keys() & new_keys.keys()):
            previous = sorted(old_keys[key], key=lambda item: item.id)
            current = sorted(new_keys[key], key=lambda item: item.id)
            for before, after in zip(previous, current):
                matches.append({"previous_issue_id": before.id, "current_issue_id": after.id, "matching_key": key})
    matched_old = {item["previous_issue_id"] for item in matches}
    matched_new = {item["current_issue_id"] for item in matches}
    remained = sorted(matched_new)
    missing = sorted(old_by.keys() - matched_old)
    added = sorted(new_by.keys() - matched_new)
    current_objects = object_index(new_context)
    eliminated: list[str] = []
    uncertain: list[str] = []
    for issue_id in missing:
        issue = old_by[issue_id]
        reliable = issue.match_strength == "object" and any(item.kind != "net" for item in issue.objects)
        if any(item.object_id not in current_objects or current_objects[item.object_id].primitive_id != item.primitive_id for item in issue.objects):
            reliable = False
        if any(new_by[item].category == issue.category and new_by[item].net == issue.net for item in added):
            # A new representative object in the same error group can replace an
            # old native record after routing. Absence alone is not a repair.
            reliable = False
        (eliminated if reliable and not reasons else uncertain).append(issue_id)
    return {
        "previous_snapshot_id": old.snapshot_id, "current_snapshot_id": new.snapshot_id,
        "same_document": same_document, "comparable": not reasons, "limitations_zh": reasons,
        "newly_reported": added, "still_reported": remained, "not_reported_again": missing,
        "matched_issues": matches, "matching_version": 2,
        "eliminated_on_recheck": eliminated, "unreliably_matched": uncertain,
        "summary_zh": f"本次新增 {len(added)} 项，仍报告 {len(remained)} 项，旧项未再次报告 {len(missing)} 项；满足可靠复查条件的消除项 {len(eliminated)} 项，不能可靠判定 {len(uncertain)} 项。",
        "matching_note_zh": "按对象、规则和描述模板匹配，不使用临时 DRC 编号或代表点。旧快照 ID 保留，并记录前后 ID 映射；重复记录仅能比较数量，代表对象变化或弱文本匹配不能直接判为修复。",
    }


def deterministic_report(context: PCBContextV2, snapshot_id: str, request_id: str, source_kind: str) -> ReviewReport:
    drc = parse_drc(context)
    provenance = dict(context.provenance or {})
    provenance.setdefault("collected_at", datetime.now(timezone.utc).isoformat())
    if drc.status == "completed":
        total = str(drc.native_count) if drc.native_count is not None else "尚不能确定"
        summary = f"本次原生 DRC 总数为 {total}，已保留 {drc.parsed_count} 条明细、{len(drc.groups)} 个分组。AI 解释另行显示，不替代完整清单。"
    else:
        summary = "原生 DRC 未成功完成；当前不能宣称零问题或检查通过。"
    evidence = [ReviewEvidence(id=item.id, snapshot_id=snapshot_id, kind="native_drc", object_ids=[link.object_id for link in item.objects], issue_ids=[item.id], data={"raw_message": item.raw_message, "raw": item.raw, "source_path": item.source_path}, limitations_zh=item.limitations_zh) for item in drc.issues]
    coverage = context.coverage or {}
    absent = [name for name in ("traces", "copper", "stackup", "design_current", "impedance", "schematic") if not isinstance(coverage.get(name), dict) or coverage[name].get("status") != "available"]
    labels = {"traces": "完整走线", "copper": "铜箔与参考平面", "stackup": "物理叠层及铜厚", "design_current": "设计电流", "impedance": "阻抗约束", "schematic": "原理图及器件引脚约束"}
    pending = [Explanation(title_zh="补充审查覆盖数据", evidence_ids=[], explanation_zh="当前缺少：" + "、".join(labels[name] for name in absent) + "。坐标及焊盘已取得时仍不能代替上述电气约束。", steps_zh=["结合原理图、器件手册与实际布线补充缺失证据，再核查规则适用性。"], verification_zh="补充数据后重新采集并执行原生 DRC；电源、信号完整性和 EMC 需要相应设计验证。", uncertainty_zh="未采集数据不表示该板不存在相关对象，也不证明违规。") ] if absent else []
    return ReviewReport(snapshot_id=snapshot_id, request_id=request_id, source_kind=source_kind, provenance=provenance, context_hash=fingerprint(context.model_dump(mode="json")), hash_scope_zh="SHA-256 覆盖服务端验证后的整个 Context JSON（键排序、紧凑编码）；包括本次 DRC、元数据及已采集字段，不涵盖未采集的工程数据。", summary_zh=summary, drc=drc, evidence=evidence, pending_checks=pending, chinese_status="pending" if any(item.translation_status == "pending" for item in drc.issues) else "passed")


def markdown_report(report: ReviewReport) -> str:
    def safe(value: object) -> str:
        # Escape markup, preserving raw identifiers and evidence as literal text.
        return html.escape(str(value)).replace("`", "\\`").replace("[", "\\[").replace("]", "\\]")
    lines = ["# AI EDA Copilot 中文设计审查报告", "", f"快照：{report.snapshot_id}", f"数据来源：{ {'eda_live':'当前 EDA 实时采集','historical_replay':'历史 EDA 快照回放','synthetic':'合成测试数据'}[report.source_kind] }", f"采集时间：{safe(report.provenance.get('collected_at'))}", f"内容哈希：{report.context_hash}", report.hash_scope_zh, "", "## 检查摘要", "", report.summary_zh, report.agent_message_zh, "", "## 原生 DRC 全量明细", "", report.drc.count_note_zh]
    for item in report.drc.issues:
        lines += ["", f"### {item.id}", "", safe(item.message_zh), f"处理优先级：{ {'high':'高','medium':'中','low':'低'}[item.priority] }。{item.priority_reason_zh}", f"原生严重级别原值：{safe(item.native_severity or '未提供')}", f"原始路径：{safe(item.source_path)}", f"相关对象：{safe('、'.join(link.object_id for link in item.objects) or '未映射')}", "", "原始证据（原文未改写）：", "", "    " + item.raw_message.replace("\n", "\n    "), "", item.limitations_zh]
    if report.drc.unknown_results:
        lines += ["", "存在尚未完整解析的检查结果，原始结构见 raw_drc.json。"]
    for title, entries in (("AI 解释与处理建议", report.explanations), ("待核查项", report.pending_checks)):
        lines += ["", f"## {title}", ""]
        for entry in entries:
            lines += [f"### {safe(entry.title_zh)}", "", safe(entry.explanation_zh), "", *[f"- {safe(step)}" for step in entry.steps_zh], "", f"修改后验证：{safe(entry.verification_zh)}", f"限制：{safe(entry.uncertainty_zh)}", f"证据：{safe('、'.join(entry.evidence_ids))}", f"规则：{safe('、'.join(entry.rule_ids))}", ""]
    lines += ["## 智能体执行记录", "", f"执行模式：{ {'not_run':'未运行','native_tool_calls':'原生工具调用','json_actions':'JSON 动作协议','explanation_only':'普通解释'}[report.agent_mode] }"]
    for trace in report.analysis_trace:
        lines += [f"- {trace.display_name_zh}：{trace.summary_zh}（{trace.duration_ms:.1f} 毫秒）；证据 {safe('、'.join(trace.evidence_ids))}"]
    lines += ["", "## 知识来源", ""]
    for rule in report.knowledge_references:
        lines += [f"- {safe(rule['id'])}：{safe(rule['title_zh'])}；{safe(rule['source'])}。中文摘要为本项目整理，不是厂商原文逐字翻译。"]
    if report.comparison:
        lines += ["", "## 前后检查比较", "", str(report.comparison["summary_zh"]), "、".join(report.comparison.get("limitations_zh", []))]
    return "\n".join(lines) + "\n"


class SnapshotStore:
    def __init__(self, root: Path = DEFAULT_OUTPUT):
        self.root = root.resolve()
        self.lock = RLock()

    def directory(self, snapshot_id: str) -> Path:
        if not ID_PATTERN.fullmatch(snapshot_id):
            raise ValueError("快照标识无效。")
        path = (self.root / snapshot_id).resolve()
        if path.parent != self.root:
            raise ValueError("输出目录不合法。")
        return path

    def _write_json(self, directory: Path, name: str, data: object) -> None:
        temporary = directory / f".{name}.{uuid4().hex}.tmp"
        try:
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
            json.loads(temporary.read_text(encoding="utf-8"))
            temporary.replace(directory / name)
            if (directory / name).stat().st_size == 0:
                raise OSError("输出文件为空。")
        finally:
            temporary.unlink(missing_ok=True)

    def create(self, payload: SnapshotInput, request_id: str) -> ReviewReport:
        with self.lock:
            context = payload.context
            if context.coverage is None:
                # V2 required these collections in the verified v0.6 collector.
                # Preserve explicit unavailable/error states in newer snapshots.
                context.coverage = {key:{"status":"available"} for key in ("components","pads","nets","outline","vias")}
                context.coverage["native_drc"] = {"status":"available" if context.drc.available else "error"}
                for key in ("traces","copper","stackup","design_current","impedance","schematic","operating_frequency"):
                    context.coverage[key] = {"status":"not_collected","reason_zh":"V2 历史采集器未采集此项。"}
            if payload.source_kind == "eda_live" and not (context.provenance or {}).get("document_id"):
                raise ValueError("实时采集必须提供当前 PCB 文档标识。")
            snapshot_id = uuid4().hex
            context.provenance = dict(context.provenance or {})
            context.provenance["snapshot_id"] = snapshot_id
            context.provenance["request_id"] = request_id
            if context.drc.execution and context.drc.execution.get("rule_config_status") == "available" and context.drc.execution.get("rule_configuration") is not None:
                context.drc.execution["rule_config_hash"] = fingerprint(context.drc.execution["rule_configuration"])
            report = deterministic_report(context, snapshot_id, request_id, payload.source_kind)
            if payload.previous_snapshot_id:
                old, old_context = self.read(payload.previous_snapshot_id)
                report.comparison = compare_reports(old, report, old_context, context)
            path = self.directory(snapshot_id)
            path.mkdir(parents=True, exist_ok=False)
            self._write_json(path, "context.json", context.model_dump(mode="json"))
            self._write_json(path, "raw_drc.json", context.drc.raw if context.drc.raw is not None else {"historical_strings_only": context.drc.errors})
            self.save(report)
            return report

    def read(self, snapshot_id: str) -> tuple[ReviewReport, PCBContextV2]:
        path = self.directory(snapshot_id)
        return (ReviewReport.model_validate_json((path / "review_report.json").read_text(encoding="utf-8")), PCBContextV2.model_validate_json((path / "context.json").read_text(encoding="utf-8")))

    def save(self, report: ReviewReport) -> None:
        with self.lock:
            path = self.directory(report.snapshot_id)
            payload = report.model_dump(mode="json")
            self._write_json(path, "review_report.json", payload)
            if report.raw_model_draft is not None:
                self._write_json(path,"llm_response_raw.json",report.raw_model_draft)
            self._write_json(path, "agent_trace.json", {"mode": report.agent_mode, "status": report.agent_status, "trace": payload["analysis_trace"], "evidence": payload["evidence"]})
            if report.comparison:
                self._write_json(path, "comparison.json", report.comparison)
            md = path / "report_zh.md"
            md.write_text(markdown_report(report), encoding="utf-8")
            if not md.is_file() or md.stat().st_size == 0:
                raise OSError("中文报告保存失败。")
            saved = ReviewReport.model_validate_json((path / "review_report.json").read_text(encoding="utf-8"))
            if saved.drc.parsed_count != len(saved.drc.issues):
                raise ValueError("导出数量核验失败。")

    def archive_attempt(self, report: ReviewReport) -> None:
        self._write_json(self.directory(report.snapshot_id), f"review_attempt_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid4().hex[:8]}.json", report.model_dump(mode="json"))
