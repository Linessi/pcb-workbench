"""Conservative, lossless DRC leaf extraction. No LLM decides native counts."""

import hashlib
import json
import re
from collections import Counter, defaultdict
from typing import Any
from models.schema import PCBContextV2
from review.schema import DrcInventory, DrcIssue, ObjectLink


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def object_index(context: PCBContextV2) -> dict[str, ObjectLink]:
    index: dict[str, ObjectLink] = {}
    for component in context.components:
        index[component.reference] = ObjectLink(object_id=component.reference, kind="component", primitive_id=component.primitiveId, match_basis="当前快照位号精确匹配")
    pad_counts = Counter((pad.component, pad.number) for pad in context.pads)
    for pad in context.pads:
        # Real KiCad footprints have repeated/blank numbers (USB shell, QFN
        # exposed pads). Never overwrite one physical pad with another.
        pid = f"{pad.component}.{pad.number}" if pad.number and pad_counts[(pad.component, pad.number)] == 1 else f"primitive:{pad.primitiveId}"
        index[pid] = ObjectLink(object_id=pid, kind="pad", primitive_id=pad.primitiveId, match_basis="当前快照焊盘图元 ID 精确匹配")
    for net in context.nets:
        index[f"net:{net}"] = ObjectLink(object_id=f"net:{net}", kind="net", match_basis="原生 DRC 网络字段精确匹配")
    for item in context.geometry.outline:
        index[f"primitive:{item.primitiveId}"] = ObjectLink(object_id=f"primitive:{item.primitiveId}", kind="primitive", primitive_id=item.primitiveId, match_basis="当前快照图元 ID 精确匹配")
    return index


def raw_message(value: dict[str, Any]) -> str:
    def label(obj: Any) -> str:
        if not isinstance(obj, dict):
            return ""
        return " ".join(str(obj[key]) for key in ("typeName", "suffix") if obj.get(key))
    explanation = value.get("explanation", {})
    detail = explanation.get("str", "") if isinstance(explanation, dict) else str(explanation)
    detail = str(detail).replace("{obj1}", label(value.get("obj1"))).replace("{obj2}", label(value.get("obj2")))
    parameters = explanation.get("param", {}) if isinstance(explanation, dict) else {}
    if isinstance(parameters, dict):
        for key, parameter in parameters.items():
            if key not in {"obj1", "obj2"} and isinstance(parameter, (str, int, float)):
                detail = detail.replace("{" + key + "}", str(parameter))
    net = f" (net={value['net']})" if value.get("net") else ""
    return f"{value['errorType']}{net}: {detail or ' → '.join(filter(None, (label(value.get('obj1')), label(value.get('obj2')))))}"


def translate_standard(message: str, category: str, net: str | None, objects: list[ObjectLink], raw: dict | None = None) -> tuple[str, str]:
    # Exact templates/parameters observed in V4.1.60's real RP2040-board DRC.
    # Preserve native numbers/units and original JSON; do not invent thresholds.
    record = raw or {}
    explanation = record.get("explanation", {})
    explanation = explanation if isinstance(explanation, dict) else {}
    parameters = explanation.get("param", {})
    parameters = parameters if isinstance(parameters, dict) else {}
    kinds = {"Device": "器件", "SMD Pad": "贴片焊盘", "TH Pad": "通孔焊盘", "Via": "过孔", "Track": "导线", "Prohibited Region": "禁止区域", "Copper Region(Filled)": "已填充铜箔区域"}
    def native_label(key: str) -> str:
        obj = record.get(key, {})
        if not isinstance(obj, dict):
            return "对象一" if key == "obj1" else "对象二"
        return kinds.get(obj.get("typeName"), "原生对象") + str(obj.get("suffix", ""))
    template = explanation.get("str")
    if category == "Clearance Error" and template == "{obj1} and {obj2} overlap":
        return f"原生 DRC 报告间距错误：{native_label('obj1')} 与 {native_label('obj2')} 重叠。请核对当前规则及导入后的几何对象。", "template"
    if category == "Clearance Error" and template == "{obj1} to {obj2} distance is {minDistance}, should be {shouldBe}" and all(isinstance(parameters.get(key), str) for key in ("minDistance", "shouldBe")):
        return f"原生 DRC 报告间距错误：{native_label('obj1')} 至 {native_label('obj2')} 的距离为 {parameters['minDistance']}，当前规则要求 {parameters['shouldBe']}。请核对原工程约束与导入后的规则。", "template"
    if category == "Physical Error" and template == "The inner diameter of the via hole of {obj1} is {diameter}, which should be {shouldBe}" and all(isinstance(parameters.get(key), str) for key in ("diameter", "shouldBe")):
        return f"原生 DRC 报告过孔尺寸错误：{native_label('obj1')} 内径为 {parameters['diameter']}，当前规则要求 {parameters['shouldBe']}。请核对原工程及制造约束，勿直接将导入默认规则视为原板违规依据。", "template"
    labels = "、".join(item.object_id for item in objects if item.kind != "net") or "原生检查涉及的对象"
    if category == "Connection Error" and re.search(r"disconnected|unconnected|not connected", message, re.I):
        suffix = f"（网络 {net}）" if net else ""
        return f"原生 DRC 报告连接性错误：{labels}{suffix} 尚未与同一网络的其他对象完成连接。需在原生 DRC 面板核对连接位置。", "template"
    if re.search(r"short circuit|short-circuit", message, re.I):
        return f"原生 DRC 报告短路相关错误：{labels}。需查看原始证据核对涉及对象及网络。", "template"
    if re.search(r"[\u4e00-\u9fff]", message) and not re.search(r"\b[A-Za-z]+\s+[A-Za-z]+\s+[A-Za-z]+\b", message):
        return f"原生 DRC 报告：{message}", "template"
    return "原生 DRC 报告了一项检查结果；其描述尚未完整翻译。请展开原始证据核查，当前不推断根因。", "pending"


def stable_issue_fingerprint(category: str, net: str | None, objects: list[ObjectLink], raw: Any, message: str) -> str:
    """Match native facts, excluding the runtime DRC index and representative point.

    V4.1.60 live captures showed explanation.errData.globalIndex increasing on
    every check. Preserve that entire structure as evidence, never as identity.
    This also derives comparison keys for older immutable report IDs.
    """
    record = raw if isinstance(raw, dict) else {}
    explanation = record.get("explanation")
    explanation = explanation if isinstance(explanation, dict) else {}
    parameters = explanation.get("param")
    parameters = parameters if isinstance(parameters, dict) else {}
    stable_objects = sorted(link.primitive_id or link.object_id for link in objects if link.kind != "net")
    identity = {
        "type": category, "net": net, "objects": stable_objects,
        "rule": {key: record[key] for key in ("ruleId", "rule", "ruleName") if key in record},
        "template": explanation.get("str", message), "subtype": parameters.get("type"),
    }
    if isinstance(record.get("objs"), list):
        # Include every native object ID, even objects the collector cannot yet
        # select. Partial pad mapping must not merge distinct copper violations.
        identity["native_objects"] = sorted(item for item in record["objs"] if isinstance(item, str))
    if not stable_objects:
        identity["raw_objects"] = [record[key] for key in ("obj1", "obj2") if isinstance(record.get(key), dict)]
    return fingerprint(identity)


def parse_drc(context: PCBContextV2) -> DrcInventory:
    execution = context.drc.execution or {}
    status = str(execution.get("status", "completed" if context.drc.available else "unavailable"))
    if status not in {"completed", "error", "not_run", "unavailable"}:
        status = "error"
    if not context.drc.available:
        return DrcInventory(status=status, native_count=None, parsed_count=0, unknown_results=[], issues=[], groups=[], count_note_zh=context.drc.reason or "原生 DRC 未完成；不能将空列表解释为检查通过。")
    leaves: list[tuple[str, Any]] = []
    unknown: list[dict[str, Any]] = []

    def visit(value: Any, path: str) -> None:
        if isinstance(value, list):
            for i, child in enumerate(value):
                visit(child, f"{path}[{i}]")
        elif isinstance(value, dict) and isinstance(value.get("errorType"), str):
            # A recognized violation is a leaf; do not recurse into object metadata.
            leaves.append((path, value))
        elif isinstance(value, dict) and isinstance(value.get("list"), list):
            for i, child in enumerate(value["list"]):
                visit(child, f"{path}.list[{i}]")
        elif isinstance(value, str) and value.strip():
            leaves.append((path, value))
        else:
            unknown.append({"source_path": path, "raw": value, "message_zh": "存在尚未完整解析的检查结果；该结构的违规条数无法可靠确定。"})

    if context.drc.raw is not None:
        visit(context.drc.raw, "$.drc.raw")
    else:
        # Historical snapshots kept strings only; no invented native objects.
        visit(context.drc.errors, "$.drc.errors")
    index = object_index(context)
    primitive_map = {item.primitive_id: item for item in index.values() if item.primitive_id}
    suffix_map: dict[str, ObjectLink] = {}
    for pad in context.pads:
        pid = f"{pad.component}.{pad.number}"
        if pid in index and pad.number:
            suffix_map[f"{pad.component}_{pad.number}"] = index[pid]
    counts: Counter[str] = Counter()
    issues: list[DrcIssue] = []
    for path, value in leaves:
        record = value if isinstance(value, dict) else {}
        message = raw_message(record) if record else str(value)
        category = str(record.get("errorType") or message.split(" (net=", 1)[0].split(":", 1)[0])
        net_match = re.search(r"\(net=([^)]+)\)", message)
        net = str(record["net"]) if record.get("net") else (net_match.group(1) if net_match else None)
        objects: dict[str, ObjectLink] = {}
        raw_objects = [record[key] for key in ("obj1", "obj2") if isinstance(record.get(key), dict)]
        # Only IDs in this snapshot are usable, even if the raw result contains stale IDs.
        native_ids = record.get("objs")
        has_native_ids = isinstance(native_ids, list)
        if has_native_ids:
            for candidate in native_ids:
                if isinstance(candidate, str) and candidate in primitive_map and (not has_native_ids or candidate in native_ids):
                    link = primitive_map[candidate].model_copy(update={"match_basis": "原生 DRC objs 与当前快照图元 ID 精确一致"})
                    objects[link.object_id] = link
        for obj in raw_objects:
            for key in ("primitiveId", "primitive_id", "id", "pid"):
                candidate = obj.get(key)
                if isinstance(candidate, str) and candidate in primitive_map:
                    link = primitive_map[candidate].model_copy(update={"match_basis": f"原生 DRC {key} 与快照图元 ID 一致"})
                    objects[link.object_id] = link
            # Native IDs take precedence. Suffix-only matching is allowed only
            # for a unique, nonblank pad number when IDs were not supplied.
            label = str(obj.get("suffix", "")).rsplit(":", 1)[-1].strip()
            if not has_native_ids and label in suffix_map:
                link = suffix_map[label].model_copy(update={"match_basis": "原生 DRC suffix 与唯一焊盘标识精确一致"})
                objects[link.object_id] = link
        if not raw_objects:
            for suffix, link in suffix_map.items():
                if re.search(rf"(?<![\w.]){re.escape(suffix)}(?![\w.])", message):
                    objects[link.object_id] = link.model_copy(update={"match_basis": "历史 DRC 文本精确匹配；缺少原始对象结构"})
        if net and f"net:{net}" in index:
            objects[f"net:{net}"] = index[f"net:{net}"]
        links = list(objects.values())
        object_links = [link for link in links if link.kind != "net"]
        stable_objects = sorted(link.primitive_id or link.object_id for link in object_links)
        fp = stable_issue_fingerprint(category, net, links, value, message)
        counts[fp] += 1
        zh, translated = translate_standard(message, category, net, links, record)
        selected = [link for link in links if link.primitive_id]
        scope = "exact" if any(link.kind == "pad" for link in selected) else "component" if any(link.kind == "component" for link in selected) else "net" if net else "unavailable"
        position = None
        for obj in raw_objects:
            if isinstance(obj.get("x"), (int, float)) and isinstance(obj.get("y"), (int, float)):
                position = {"x": obj["x"], "y": obj["y"], "unit": "mil", "source": "原生 DRC 对象字段"}
                break
        issues.append(DrcIssue(
            id=f"drc-{fp[:24]}-{counts[fp]}", fingerprint=fp,
            match_strength="object" if stable_objects and raw_objects else "text",
            raw_message=message, raw=value, source_path=path, category=category,
            native_severity=str(record["severity"]) if record.get("severity") is not None else None,
            priority="high" if category == "Connection Error" else "medium",
            priority_reason_zh="连接性问题优先处理；这是本系统处理优先级，不代表原生严重级别或整板失效。" if category == "Connection Error" else "本系统建议先核对原生检查证据；不替代原生严重级别。",
            net=net, objects=links, position=position, message_zh=zh, translation_status=translated,
            parse_status="parsed" if record else "partial", location_scope=scope,
            limitations_zh="对象或代表点可能随重新布线变化；相同指纹的重复记录仍逐项保留。选择对象不等于缩放到错误点。" if stable_objects else "仅文本指纹，跨快照匹配较弱；请在原生 DRC 面板定位。",
        ))
    for item in issues:
        if counts[item.fingerprint] > 1:
            item.match_strength = "ambiguous"
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for item in issues:
        groups[(item.category, item.net or "")].append(item.id)
    return DrcInventory(
        status=status, native_count=None if unknown else len(leaves), parsed_count=len(issues), unknown_results=unknown, issues=issues,
        groups=[{"category": kind, "net": net, "issue_ids": ids, "count": len(ids)} for (kind, net), ids in groups.items()],
        count_note_zh="全量逐项保留；分组和 AI 摘要不改变原生错误集合。" if not unknown else "已保留全部可识别明细及未知原始结构；原生精确总数暂不可确定。",
    )
