"""One canonical draft drives escaped HTML and Markdown. No remote resources."""
import copy
import hashlib
import html
import json
import zipfile
from datetime import datetime
from notes.repository import now, uid
from notes.service import check, fail, find, source_state


def anchor(row):
    return f'src-{row["entry_id"]}-r{row["revision"]}'


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def display_time(value):
    return datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M %z")


def render(draft, flags, attachments):
    body = draft["revisions"][-1]["body"]
    esc = html.escape
    # HTML escapes all user/model text; no script, iframe, markdown-to-HTML or fetch.
    label = "文字已核对" if draft["confirmation"] else "草稿 · 待核对"
    history = "便签已有更新；本包保留此前版本，请核对后使用。" if flags["source_changed"] else ""
    rows_by_id = {r["entry_id"]: r for r in draft["snapshot"]["entries"]}
    purpose = draft["snapshot"]["purpose"]
    parts = ["<!doctype html><html lang='zh-CN'><meta charset='utf-8'><meta name='viewport' content='width=device-width'>",
             "<meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'\">",
             "<title>PCB 交接记录</title><style>body{max-width:940px;margin:32px auto;padding:0 24px;font:16px/1.7 system-ui;color:#243044}pre{white-space:pre-wrap;overflow-wrap:anywhere}article{border:1px solid #ddd;padding:18px;margin:16px 0;border-radius:12px}img{max-width:100%;max-height:700px}small{color:#617082}</style>",
             "<h1>PCB 交接记录</h1>", f"<p><small>{label} · 版本 {draft['version']} · {esc(display_time(draft['created_at']))}</small></p>"]
    if history:
        parts.append(f"<p>{history}</p>")
    if purpose:
        parts.append(f'<h2>交接事项</h2><pre>{esc(purpose)}</pre>')
    parts.append("<h2>工作记录</h2>")
    md = ["# PCB 交接记录", "", label, history]
    if purpose:
        md.extend(["", "## 交接事项", purpose])
    md.extend(["", "## 工作记录"])
    for i, block in enumerate(body["blocks"]):
        manual = block.get("human_edited", False)
        row = rows_by_id[block["source_refs"][0]["entry_id"]]
        heading = block.get("heading") or row["title"] or "、".join(o["label"] for o in row["objects"]) or f"记录 {i+1}"
        kind = "进展" if row["kind"] == "progress" else "记录"
        parts.append(f'<article><h3>{esc(heading)}</h3><small>{kind} · {esc(row["status"])}{" · 已编辑，请核对原文" if manual else ""}</small><pre>{esc(block["text"])}</pre>')
        md.extend(["", f"### {heading}" + ("（已编辑，请核对原文）" if manual else ""), block["text"]])
        for ref in block["source_refs"]:
            source = rows_by_id[ref["entry_id"]]
            source_label = source["title"] or "记录"
            source_kind = "进展" if source["kind"] == "progress" else "记录"
            parts.append(f'<a href="#{anchor(ref)}">{esc(source_label)} · {source_kind} · 第 {ref["revision"]} 版原文</a> ')
            md.append(f'原文：{source_label} · {source_kind} · 第 {ref["revision"]} 版')
        parts.append("</article>")
    if body["human_addition"]:
        parts.append(f'<h2>补充事项</h2><pre>{esc(body["human_addition"])}</pre>')
        md.extend(["", "## 补充事项", body["human_addition"]])
    if body["gaps"] and not body["ignored_gaps"]:
        parts.append("<h2>待补充</h2><ul>" + "".join(f"<li>{esc(g)}</li>" for g in body["gaps"]) + "</ul>")
        md.extend(["", "## 待补充", *body["gaps"]])
    parts.append("<h2>原始记录</h2>")
    original = ["# 本次实际来源", "仅包含此次选择的条目版本；没有完整历史。"]
    for row in draft["snapshot"]["entries"]:
        parts.extend([f'<article id="{anchor(row)}"><h3>{esc(row["title"] or row["body"].splitlines()[0][:60])}</h3>',
                      f'<small>{"进展" if row["kind"] == "progress" else "记录"} · {esc(row["status"])} · {esc(display_time(row["created_at"]))} · v{row["revision"]}</small>',
                      f'<pre>{esc(row["body"])}</pre><p>对象：{esc("、".join(o["label"] for o in row["objects"]) or "整板记录")}</p></article>'])
        original.extend(["", f'## {row["entry_id"]} / v{row["revision"]}', row["body"]])
    if draft["snapshot"]["attachments"]:
        parts.append("<h2>附图</h2>")
    for a in draft["snapshot"]["attachments"]:
        name = f'attachments/{a["id"]}.{a["extension"]}'
        parts.append(f'<article><h3>{esc(a["name"])}</h3><pre>{esc(a["caption"] or "未填写图片说明")}</pre>')
        parts.append(f'<a href="{name}"><img src="{name}" alt="附图"></a>' if name in attachments else "<p>本包为纯文字导出，未包含此图片。</p>")
        parts.append("</article>")
    parts.append("<footer><small>附件和原文随包保存。</small></footer></html>")
    # Markdown remains plain text; raw HTML is escaped to avoid active content in viewers.
    def safe_markdown(lines):
        # Block user-supplied Markdown links/images as well as raw HTML.
        return esc("\n".join(lines)).replace("[", "\\[").replace("]", "\\]").encode("utf-8")
    return "\n".join(parts).encode("utf-8"), safe_markdown(md), safe_markdown(original)


def package(repo, command):
    # Lock spans source permission checks and bounded file construction to avoid a
    # revoked-sharing race. Export never walks directories supplied by callers.
    with repo.transaction() as state:
        draft = copy.deepcopy(find(state["drafts"], command.draft_id))
        check(draft["version"], command.expected_version)
        flags = source_state(state, draft["snapshot"])
        if not draft["confirmation"] and not command.allow_unconfirmed:
            fail("请先确认草稿，或明确选择导出未确认草稿")
        if flags["source_changed"] and not command.acknowledge_history:
            fail("来源有更新，请核对并确认导出历史版本")
        if flags["sharing_changed"]:
            # A new explicit permission must restore sharing and create a new
            # snapshot. Old confirmations cannot revive revoked content.
            fail("来源分享范围已变，请重新选择允许分享的记录并生成草稿")
        if not command.share_confirmation:
            fail("请确认本次分享范围")
        files = {}
        for a in draft["snapshot"]["attachments"]:
            path = repo.file("attachments", f'{a["id"]}.{a["extension"]}')
            if command.text_only:
                continue
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != a["sha256"]:
                fail("附件缺失或已损坏，请恢复图片，或明确选择纯文字导出")
            files[f'attachments/{path.name}'] = path.read_bytes()
        rendered, markdown, originals = render(draft, flags, files)
        files.update({"阅读说明.html": rendered, "交接报告.md": markdown, "原始记录.md": originals,
                      "data/notes.json": encode(draft["snapshot"]["entries"]),
                      "data/objects.json": encode([{ "entry_id": r["entry_id"], "objects": r["objects"]} for r in draft["snapshot"]["entries"]]),
                      "data/report.json": encode({k: draft[k] for k in ("id", "kind", "origin", "version", "created_at", "confirmation", "snapshot_hash")} | {"body": draft["revisions"][-1]["body"], "generation": {k:v for k,v in (draft.get("generation_config") or {}).items() if k in ("provider", "model", "prompt_version", "structure_version")}, **flags})})
        package_id = uid()
        manifest = {"schema_version": 1, "id": package_id, "created_at": now(), "draft_id": draft["id"], "draft_version": draft["version"],
                    "snapshot_hash": draft["snapshot_hash"], "confirmation": draft["confirmation"], **flags, "text_only": command.text_only,
                    "sources": [{k: r[k] for k in ("note_id", "entry_id", "revision", "note_version")} for r in draft["snapshot"]["entries"]],
                    "files": [{"path": n, "size": len(b), "sha256": hashlib.sha256(b).hexdigest()} for n, b in files.items()]}
        # Manifest excludes itself to avoid a recursive self-hash.
        files["manifest.json"] = encode(manifest)
        path = repo.file("packages", f"PCB交接包_{package_id}.zip")
        with zipfile.ZipFile(path, "x", zipfile.ZIP_DEFLATED) as archive:
            for name, raw in files.items():
                archive.writestr(f"PCB交接包_{package_id}/{name}", raw)
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() or len(archive.namelist()) != len(files):
                fail("交接包校验失败", 500)
            for name, raw in files.items():
                if archive.read(f"PCB交接包_{package_id}/{name}") != raw:
                    fail("交接包内容校验失败", 500)
        result = {"id": package_id, "filename": path.name, "size": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "created_at": now(), "draft_id": draft["id"]}
        state["packages"][package_id] = result
        return result
