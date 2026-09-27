"""Lifespan-owned workers. Durable jobs survive panels; running jobs interrupt on restart."""
import asyncio
import copy
import logging
from notes.repository import now, uid
from notes.service import digest, fail, find, new_draft, snapshot, source_state
from note_ai.generation import generate
from note_ai.providers import freeze

log = logging.getLogger("pcb_notes_jobs")


class Jobs:
    def __init__(self, repo, generator=generate, concurrency=1, capacity=20):
        self.repo, self.generator = repo, generator
        self.capacity, self.concurrency = capacity, concurrency
        self.queue = asyncio.Queue(maxsize=capacity)
        self.workers = []
        self.running = {}

    async def start(self):
        with self.repo.transaction() as s:
            for j in s["jobs"].values():
                if j["status"] == "running":
                    j.update(status="interrupted", error="服务已重启，任务中断；可手工重试。", updated_at=now())
                if j["status"] == "queued":
                    if self.queue.full():
                        j.update(status="interrupted", error="恢复队列已满，请手工重试。", updated_at=now())
                    else:
                        self.queue.put_nowait(j["id"])
        self.workers = [asyncio.create_task(self.worker()) for _ in range(self.concurrency)]

    async def stop(self):
        for worker in self.workers:
            worker.cancel()
        for task in self.running.values():
            task.cancel()
        await asyncio.gather(*self.workers, *self.running.values(), return_exceptions=True)
        with self.repo.transaction() as s:
            for j in s["jobs"].values():
                if j["status"] == "running":
                    j.update(status="interrupted", error="服务已停止，请手工重试。", updated_at=now())

    def submit(self, kind, command, retry_of=None, frozen=None, frozen_config=None):
        with self.repo.transaction() as s:
            snap = frozen or snapshot(s, command)
            if frozen is None:
                if digest(snap) != command.snapshot_hash:
                    fail("来源已变化，请重新预览后提交")
            if kind == "polish" and len(snap["entries"]) != 1:
                fail("润色只能选择一条正文或进展", 422)
            config = copy.deepcopy(frozen_config) if frozen_config else freeze(command.provider if command else 'local')
            if config['provider']=='deepseek':
                consent=s.setdefault('cloud_consents',{}).get(snap['board_key'])
                if not consent and not (command and command.external_confirmed):
                    fail('请先确认：所选文字、对象标识及图片说明将发送至 DeepSeek，不发送图片或整板',403)
                s['cloud_consents'][snap['board_key']]={'at':now(),'provider':'deepseek'}
            authorization={'provider':config['provider'],'snapshot_hash':digest(snap),'entry_ids':[r['entry_id'] for r in snap['entries']],
                           'caption_ids':[a['id'] for a in snap['attachments']]}
            key = digest([kind, snap, config])
            if not retry_of:
                for j in s["jobs"].values():
                    if j["input_hash"] == key and j["status"] in ("queued", "running", "succeeded"):
                        return copy.deepcopy(j)
            if self.queue.full():
                fail("后台队列已满，请稍后重试；便签保存不受影响。", 429)
            job = {"id": uid(), "kind": kind, "snapshot": copy.deepcopy(snap), "input_hash": key, "status": "queued",
                   "config":config, "authorization":authorization,
                   "created_at": now(), "updated_at": now(), "draft_id": None, "error": None, "retry_of": retry_of, "events": [{"status": "queued", "at": now()}]}
            s["jobs"][job["id"]] = job
        # No await before response path: generation cannot start during submit.
        self.queue.put_nowait(job["id"])
        return copy.deepcopy(job)

    def cancel(self, key):
        with self.repo.transaction() as s:
            j = find(s["jobs"], key)
            if j["status"] not in ("queued", "running"):
                fail("任务已经结束")
            j.update(status="cancelled", updated_at=now(), error="已取消本地任务；不保证远端计算已经停止。")
            j["events"].append({"status": "cancelled", "at": now()})
        if key in self.running:
            self.running[key].cancel()
        return self.repo.read()["jobs"][key]

    def retry(self, key):
        old = find(self.repo.read()["jobs"], key)
        if old["status"] not in ("failed", "cancelled", "interrupted"):
            fail("只有失败、取消或中断的任务可以重试")
        if source_state(self.repo.read(), old["snapshot"])["sharing_changed"]:
            fail("来源分享范围已变，请重新选择记录")
        if not old.get('config'):
            fail('旧任务没有冻结服务配置，请重新选择来源并提交新任务')
        return self.submit(old["kind"], None, retry_of=key, frozen=old["snapshot"], frozen_config=old['config'])

    async def worker(self):
        while True:
            key = await self.queue.get()
            try:
                with self.repo.transaction() as s:
                    job = s["jobs"][key]
                    if job["status"] != "queued":
                        continue
                    if source_state(s,job['snapshot'])['sharing_changed']:
                        job.update(status='failed',error='来源已停止分享或归档，任务未发送',updated_at=now())
                        job['events'].append({'status':'permission_revoked','at':now()})
                        continue
                    if self.generator is generate and not job.get('config'):
                        job.update(status='interrupted',error='旧任务没有冻结配置，请重新提交',updated_at=now())
                        continue
                    job.update(status="running", updated_at=now())
                    job["events"].append({"status": "running", "at": now()})
                    source = copy.deepcopy(job)
                def event(data):
                    with self.repo.transaction() as state:
                        state['jobs'][key]['events'].append({**data,'at':now()})
                def permission():
                    current=self.repo.read()
                    if current['jobs'][key]['status']!='running' or source_state(current,source['snapshot'])['sharing_changed']:
                        raise ValueError('任务已取消或来源停止分享，未发送后续请求')
                task = asyncio.create_task(self.generator(source['kind'],source['snapshot'],source['config'],event,permission)
                    if self.generator is generate else self.generator(source['kind'],source['snapshot']))
                self.running[key] = task
                try:
                    result = await task
                    draft = new_draft(source["kind"], source["snapshot"], result)
                    draft['generation_config']=copy.deepcopy(source.get('config'))
                    with self.repo.transaction() as s:
                        job = s["jobs"][key]
                        if job["status"] != "running":
                            continue  # A late result never becomes active after cancel.
                        s["drafts"][draft["id"]] = draft
                        job.update(status="succeeded", draft_id=draft["id"], updated_at=now())
                        job["events"].append({"status": "succeeded", "at": now()})
                except asyncio.CancelledError:
                    if asyncio.current_task().cancelling():
                        raise
                except Exception as exc:
                    with self.repo.transaction() as s:
                        job = s["jobs"][key]
                        if job["status"] == "running":
                            job.update(status="failed", error=str(exc) if isinstance(exc, ValueError) else "模型连接失败或超时；原文已保留，请重试或使用模板包。", updated_at=now())
                            job["events"].append({"status": "failed", "at": now()})
                    log.warning("job=%s failure_type=%s", key, type(exc).__name__)
                finally:
                    self.running.pop(key, None)
            finally:
                self.queue.task_done()
