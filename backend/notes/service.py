"""Version checks and explicit board binding. Names never establish identity."""
import base64
import copy
import hashlib
import io
import json
from fastapi import HTTPException
from PIL import Image
from notes.repository import now, uid


def fail(message, status=409):
    raise HTTPException(status_code=status, detail=message)


def find(items, key):
    if key not in items:
        fail("记录不存在", 404)
    return items[key]


def check(actual, expected):
    if actual != expected:
        fail("内容已被更新，请保留当前输入，重新读取后核对版本。")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def identity_key(identity):
    return [identity["project_id"], identity["document_id"]]


def bind(repo, command):
    identity = command.identity.model_dump()
    with repo.transaction() as state:
        boards = state["boards"]
        matching = [b for b in boards.values() if identity_key(identity) in [identity_key(i) for i in b["bindings"]]]
        if matching:
            if command.board_key and command.board_key != matching[0]["id"]:
                fail("当前工程已关联其他便签本，拒绝隐式迁移。")
            return copy.deepcopy(matching[0])
        if not command.confirm:
            return {"needs_binding": True, "candidates": list(boards.values())}
        if command.board_key:
            board = find(boards, command.board_key)
            board["bindings"].append(identity)
        else:
            board = {"id": uid(), "name": identity["project_name"], "bindings": [identity], "created_at": now()}
            boards[board["id"]] = board
        return copy.deepcopy(board)


def attachment_refs(state, ids):
    if len(set(ids)) != len(ids):
        fail("附件重复", 422)
    return [copy.deepcopy(find(state["attachments"], i)) for i in ids]


def entry(body, attachments, kind):
    if not body.strip():
        fail("正文不能为空", 422)
    return {"id": uid(), "kind": kind, "revision": 1, "created_at": now(), "revisions": [
        {"revision": 1, "body": body, "attachment_ids": attachments, "created_at": now(), "origin": "human"}]}


def create_note(repo, command):
    data = command.model_dump()
    with repo.transaction() as s:
        board = find(s["boards"], data["board_key"])
        if identity_key(data["identity"]) not in [identity_key(i) for i in board["bindings"]]:
            fail("工程尚未关联到这个便签本")
        for note in s["notes"].values():
            if note["client_id"] == data["client_id"]:
                if note["create_hash"] != digest(data):
                    fail("重复保存的内容不同，请重新读取已保存记录")
                return copy.deepcopy(note)
        attachment_refs(s, data["attachment_ids"])
        note = {"id": uid(), "board_key": data["board_key"], "identity": data["identity"], "objects": data["objects"],
                "title": data["title"], "version": 1, "status": "待确认", "archived": False, "share_allowed": True,
                "share_epoch": 1, "created_at": now(), "updated_at": now(), "entries": [entry(data["body"], data["attachment_ids"], "initial")],
                "client_id": data["client_id"], "create_hash": digest(data), "history": []}
        s["notes"][note["id"]] = note
        return copy.deepcopy(note)


def bump(note):
    note["version"] += 1
    note["updated_at"] = now()


def patch_note(repo, note_id, command):
    with repo.transaction() as s:
        note = find(s["notes"], note_id)
        check(note["version"], command.expected_version)
        note["history"].append({k: copy.deepcopy(note[k]) for k in ("version", "title", "status", "archived", "share_allowed", "updated_at")})
        for k, v in command.model_dump(exclude_none=True).items():
            if k != "expected_version":
                if k == "share_allowed" and v != note[k]:
                    note["share_epoch"] += 1
                note[k] = v
        bump(note)
        return copy.deepcopy(note)


def locate_entry(s, entry_id):
    for note in s["notes"].values():
        for item in note["entries"]:
            if item["id"] == entry_id:
                return note, item
    fail("进展记录不存在", 404)


def bind_objects(repo, note_id, command):
    with repo.transaction() as state:
        note = find(state['notes'], note_id)
        check(note['version'], command.expected_version)
        identity = command.identity.model_dump()
        if identity_key(identity) != identity_key(note['identity']):
            fail('当前工程与便签来源不同，请回到原工程关联对象。')
        objects = [o.model_dump() for o in command.objects]
        if len({o['primitive_id'] for o in objects}) != len(objects):
            fail('选中对象重复，请重新选择。', 422)
        if note['objects'] == objects:
            return copy.deepcopy(note)
        note['history'].append({'version': note['version'], 'objects': copy.deepcopy(note['objects']),
                                'identity': copy.deepcopy(note['identity']), 'updated_at': note['updated_at']})
        note['objects'] = objects
        bump(note)
        return copy.deepcopy(note)


def write_entry(repo, key, command, append=False):
    with repo.transaction() as s:
        attachment_refs(s, command.attachment_ids)
        if append:
            note = find(s["notes"], key)
            check(note["version"], command.expected_version)
            note["entries"].append(entry(command.body, command.attachment_ids, "progress"))
        else:
            note, item = locate_entry(s, key)
            check(item["revision"], command.expected_version)
            if not command.body.strip():
                fail("正文不能为空", 422)
            previous = item["revisions"][-1]
            if previous["body"] == command.body and previous["attachment_ids"] == command.attachment_ids:
                return copy.deepcopy(note)
            item["revision"] += 1
            item["revisions"].append({"revision": item["revision"], "body": command.body, "attachment_ids": command.attachment_ids,
                                       "created_at": now(), "origin": "human"})
        bump(note)
        return copy.deepcopy(note)


def upload(repo, command):
    try:
        raw = base64.b64decode(command.data, validate=True)
        if not raw or len(raw) > 6 * 1024 * 1024:
            raise ValueError()
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in ("PNG", "JPEG") or image.width * image.height > 20_000_000:
                raise ValueError()
            ext = "png" if image.format == "PNG" else "jpg"
            image.verify()
    except Exception:
        fail("仅支持有效 PNG/JPEG 图片，最大 6 MB、2000 万像素。", 422)
    # User names are display text only. Generated IDs are the only file names.
    item = {"id": uid(), "name": command.name, "extension": ext, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "revision": 1, "caption": command.caption, "captions": [{"revision": 1, "caption": command.caption}], "created_at": now()}
    path = repo.file("attachments", f'{item["id"]}.{ext}')
    path.write_bytes(raw)
    if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
        fail("附件保存校验失败", 500)
    with repo.transaction() as s:
        s["attachments"][item["id"]] = item
    return item


def caption(repo, key, command):
    with repo.transaction() as s:
        a = find(s["attachments"], key)
        check(a["revision"], command.expected_version)
        a["revision"] += 1
        a["caption"] = command.caption
        a["captions"].append({"revision": a["revision"], "caption": a["caption"]})
        return copy.deepcopy(a)


def snapshot(state, scope):
    find(state["boards"], scope.board_key)
    if len(set(scope.entry_ids)) != len(scope.entry_ids):
        fail("来源记录重复", 422)
    rows, allowed_attachments = [], set()
    for eid in scope.entry_ids:
        note, item = locate_entry(state, eid)
        if eid in scope.expected_entries:
            check(item["revision"], scope.expected_entries[eid])
        if note["id"] in scope.expected_notes:
            check(note["version"], scope.expected_notes[note["id"]])
        if note["board_key"] != scope.board_key or not note["share_allowed"] or note["archived"]:
            fail("来源不属于同一便签本，或已归档/停止分享")
        rev = item["revisions"][-1]
        allowed_attachments.update(rev["attachment_ids"])
        rows.append({"note_id": note["id"], "entry_id": eid, "revision": item["revision"], "note_version": note["version"],
                     "share_epoch": note["share_epoch"], "title": note["title"], "status": note["status"], "kind": item["kind"],
                     "created_at": item["created_at"], "body": rev["body"], "origin": rev["origin"], "objects": copy.deepcopy(note["objects"]),
                     "identity": copy.deepcopy(note["identity"]), "attachment_ids": [a for a in rev["attachment_ids"] if a in scope.attachment_ids]})
    if not set(scope.attachment_ids) <= allowed_attachments:
        fail("附件不在所选记录中", 422)
    # Keep the preview's note order; UUID ordering reads like a shuffled handoff.
    # Progress within a note remains chronological even if IDs arrive reversed.
    note_order = {key: i for i, key in enumerate(dict.fromkeys(r["note_id"] for r in rows))}
    rows.sort(key=lambda r: (note_order[r["note_id"]], r["created_at"]))
    attachments = [{k: a[k] for k in ("id", "name", "extension", "size", "sha256", "revision", "caption")}
                   for a in attachment_refs(state, scope.attachment_ids)]
    for a in attachments:
        if a["id"] in scope.expected_attachments:
            check(a["revision"], scope.expected_attachments[a["id"]])
    return {"board_key": scope.board_key, "entries": rows, "attachments": attachments, "purpose": scope.purpose}


def source_state(state, snap):
    changed, revoked = False, False
    for row in snap["entries"]:
        n, e = locate_entry(state, row["entry_id"])
        changed |= n["version"] != row["note_version"] or e["revision"] != row["revision"]
        revoked |= not n["share_allowed"] or n["share_epoch"] != row["share_epoch"] or n["archived"]
    for a in snap["attachments"]:
        changed |= find(state["attachments"], a["id"])["revision"] != a["revision"]
    return {"source_changed": changed, "sharing_changed": revoked}


def draft_view(state, key):
    d = copy.deepcopy(find(state["drafts"], key))
    d.update(source_state(state, d["snapshot"]))
    return d


def new_draft(kind, snap, generated, origin="ai"):
    body = {**generated, "human_addition": "", "ignored_gaps": False}
    return {"id": uid(), "kind": kind, "snapshot": copy.deepcopy(snap), "snapshot_hash": digest(snap), "origin": origin,
            "version": 1, "created_at": now(), "ai_original": copy.deepcopy(generated) if origin == "ai" else None,
            "revisions": [{"version": 1, "body": body, "origin": origin, "created_at": now()}], "confirmation": None, "adopted": False}


def apply_polish(repo, key, version):
    with repo.transaction() as s:
        d = find(s["drafts"], key)
        check(d["version"], version)
        if d["kind"] != "polish" or d["adopted"]:
            fail("这份草稿不能重复采用")
        row = d["snapshot"]["entries"][0]
        n, e = locate_entry(s, row["entry_id"])
        check(e["revision"], row["revision"])
        if source_state(s, d["snapshot"])["source_changed"]:
            fail("基于较早内容，请重新润色或手工复制核对。")
        e["revision"] += 1
        e["revisions"].append({"revision": e["revision"], "body": d["revisions"][-1]["body"]["blocks"][0]["text"],
                                  "attachment_ids": e["revisions"][-1]["attachment_ids"], "created_at": now(), "origin": "adopted_polish", "draft_id": key})
        bump(n)
        d["adopted"] = True
        return copy.deepcopy(n)
