"""Local-only note APIs. Fixed custom header prevents cross-site simple writes."""
import copy
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from notes.repository import Repository, now
from notes import schemas as m, service as s
from note_ai.jobs import Jobs
from note_ai.generation import template
from handoff.package import package


async def local_request(request: Request):
    if request.headers.get("X-PCB-Notes") != "1":
        raise HTTPException(403, "便签请求缺少本机客户端标识")
    origin = request.headers.get("origin")
    if origin and origin not in {"http://127.0.0.1:8000", "http://localhost:8000"}:
        raise HTTPException(403, "便签写入不接受外部网页来源；请使用扩展的本机请求桥接")
    if request.headers.get("host", "").split(":")[0] not in {"127.0.0.1", "localhost", "testserver"}:
        raise HTTPException(403, "仅支持本机便签连接")


router = APIRouter(prefix="/api", dependencies=[Depends(local_request)])


@router.get('/notes-provider')
def provider_state(request: Request, board_key: str | None = None):
    from note_ai.providers import freeze, credential
    from config.settings import Settings
    state=repo(request).read()
    selected=state.get('provider_selection', Settings().notes_default_provider)
    options=[]
    for name in ('local','deepseek'):
        config=freeze(name)
        try: credential(config); configured=True
        except ValueError: configured=False
        options.append({'provider':name,'model':config['model'],'configured':configured})
    return {'selected':selected,'options':options,'cloud_confirmed':bool(state.get('cloud_consents',{}).get(board_key))}


@router.patch('/notes-provider')
def select_provider(command: m.ProviderSelection, request: Request):
    with repo(request).transaction() as state:
        state['provider_selection']=command.provider
    return provider_state(request)


@router.post('/notes-provider/check')
async def check_provider(command: m.ProviderSelection):
    from note_ai.providers import connection
    return await connection(command.provider)


def repo(request):
    return request.app.state.notes_repo


@asynccontextmanager
async def lifespan(app):
    import os
    from config.settings import Settings
    if int(os.environ.get("WEB_CONCURRENCY", "1")) != 1:
        raise RuntimeError("便签服务必须使用单个 worker")
    settings = Settings()
    repository = Repository(settings.notes_data_directory or Path(__file__).resolve().parents[2] / "output" / "notes")
    repository.open()
    jobs = Jobs(repository, concurrency=settings.notes_concurrency, capacity=settings.notes_queue_capacity)
    app.state.notes_repo, app.state.notes_jobs = repository, jobs
    try:
        await jobs.start()
        yield
    finally:
        await jobs.stop()
        repository.close()


@router.post("/note-boards/bind")
def bind(command: m.Binding, request: Request):
    return s.bind(repo(request), command)


@router.get("/notes")
def notes(request: Request, board_key: str | None = None):
    return [n for n in repo(request).read()["notes"].values() if board_key is None or n["board_key"] == board_key]


@router.post("/notes")
def create(command: m.CreateNote, request: Request):
    return s.create_note(repo(request), command)


@router.patch("/notes/{key}")
def update(key: str, command: m.NotePatch, request: Request):
    return s.patch_note(repo(request), key, command)


@router.post("/notes/{key}/entries")
def append(key: str, command: m.EntryWrite, request: Request):
    return s.write_entry(repo(request), key, command, True)


@router.post('/notes/{key}/objects')
def bind_objects(key: str, command: m.ObjectBinding, request: Request):
    return s.bind_objects(repo(request), key, command)


@router.patch("/entries/{key}")
def edit_entry(key: str, command: m.EntryWrite, request: Request):
    return s.write_entry(repo(request), key, command)


@router.post("/attachments")
def upload(command: m.AttachmentUpload, request: Request):
    return s.upload(repo(request), command)


@router.patch("/attachments/{key}")
def caption(key: str, command: m.CaptionPatch, request: Request):
    return s.caption(repo(request), key, command)


@router.get("/attachments/{key}")
def attachment(key: str, request: Request):
    import base64
    r = repo(request)
    a = copy.deepcopy(s.find(r.read()["attachments"], key))
    p = r.file("attachments", f'{key}.{a["extension"]}')
    if not p.exists():
        s.fail("图片附件缺失", 404)
    a["data"] = base64.b64encode(p.read_bytes()).decode()
    return a


@router.post("/note-snapshots")
def preview(command: m.Scope, request: Request):
    snap = s.snapshot(repo(request).read(), command)
    return {"snapshot": snap, "snapshot_hash": s.digest(snap)}


@router.post("/ai-jobs/{kind}", status_code=202)
async def submit_job(kind: str, command: m.JobRequest, request: Request):
    if kind not in ("polish", "handoff"):
        s.fail("未知任务类型", 422)
    if command.provider is None:
        from config.settings import Settings
        command=command.model_copy(update={'provider':repo(request).read().get('provider_selection',Settings().notes_default_provider)})
    return request.app.state.notes_jobs.submit(kind, command)


@router.get("/ai-jobs")
def jobs(request: Request, board_key: str | None = None):
    return [j for j in repo(request).read()["jobs"].values() if board_key is None or j["snapshot"]["board_key"] == board_key]


@router.get("/ai-jobs/{key}")
def job(key: str, request: Request):
    return s.find(repo(request).read()["jobs"], key)


@router.post("/ai-jobs/{key}/cancel")
async def cancel(key: str, request: Request):
    return request.app.state.notes_jobs.cancel(key)


@router.post("/ai-jobs/{key}/retry", status_code=202)
async def retry(key: str, request: Request):
    return request.app.state.notes_jobs.retry(key)


@router.post("/handoff-drafts/template")
def template_draft(command: m.JobRequest, request: Request):
    r = repo(request)
    with r.transaction() as state:
        snap = s.snapshot(state, command)
        if s.digest(snap) != command.snapshot_hash:
            s.fail("来源已变化，请重新预览")
        d = s.new_draft("handoff", snap, template(snap), "template")
        state["drafts"][d["id"]] = d
        return d


@router.get("/handoff-drafts/{key}")
def draft(key: str, request: Request):
    return s.draft_view(repo(request).read(), key)


@router.patch("/handoff-drafts/{key}")
def edit_draft(key: str, command: m.DraftEdit, request: Request):
    r = repo(request)
    with r.transaction() as state:
        d = s.find(state["drafts"], key)
        s.check(d["version"], command.expected_version)
        if d["kind"] != "handoff":
            s.fail("润色草稿请采用到原条目后再编辑")
        body = copy.deepcopy(d["revisions"][-1]["body"])
        if len(command.texts) != len(body["blocks"]) or any(not t.strip() or len(t) > 15000 for t in command.texts):
            s.fail("正文段落数量或长度不符", 422)
        for block, text in zip(body["blocks"], command.texts):
            if block["text"] != text:
                block["human_edited"] = True
            block["text"] = text
        body.update(human_addition=command.human_addition, ignored_gaps=command.ignored_gaps)
        d["version"] += 1
        d["confirmation"] = None
        d["revisions"].append({"version": d["version"], "body": body, "origin": "human", "created_at": now()})
        return s.draft_view(state, key)


@router.post("/handoff-drafts/{key}/confirm")
def confirm(key: str, command: m.Version, request: Request):
    with repo(request).transaction() as state:
        d = s.find(state["drafts"], key)
        s.check(d["version"], command.expected_version)
        if s.source_state(state, d["snapshot"])["sharing_changed"]:
            s.fail("分享范围已变，请重新生成")
        d["confirmation"] = {"version": d["version"], "snapshot_hash": d["snapshot_hash"], "at": now(), "meaning": "仅确认文字表达"}
        return s.draft_view(state, key)


@router.post("/polish-drafts/{key}/apply")
def adopt(key: str, command: m.Version, request: Request):
    return s.apply_polish(repo(request), key, command.expected_version)


@router.post("/handoff-packages")
def export(command: m.ExportRequest, request: Request):
    return package(repo(request), command)


@router.get("/handoff-packages/{key}")
def download(key: str, request: Request):
    r = repo(request)
    info = s.find(r.read()["packages"], key)
    state = r.read()
    draft = s.find(state["drafts"], info["draft_id"])
    if s.source_state(state, draft["snapshot"])["sharing_changed"]:
        s.fail("来源分享范围已变，不能再次下载旧包；请重新生成")
    return FileResponse(r.file("packages", info["filename"]), filename=info["filename"], media_type="application/zip")
