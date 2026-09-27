"""Controlled provider failures: never use paid services for fault injection."""
import asyncio
import copy
import json
from types import SimpleNamespace as NS
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from test_notes import repo, setup, image, make_draft, export_request
from notes import schemas as m, service as s
from note_ai.jobs import Jobs
from note_ai import generation as g, providers as p, usage
from config.settings import Settings
from handoff.package import package


def test_subject_states_cannot_be_swapped():
    from note_ai.fidelity import check_relations
    original='C1 已经核对。C2 未核对。'
    check_relations(original,original)
    with pytest.raises(ValueError,match='对象与操作'):
        check_relations(original,'C1 未核对。C2 已经核对。')


@pytest.mark.parametrize('text',[r'C:\\Users\\name\\private.txt','/home/name/private.txt','sk-'+('x'*32),'actual-test-credential'])
def test_sensitive_cloud_text_rejected_without_echo(text):
    with pytest.raises(ValueError) as exc:
        g.check_cloud_text({'body':text},'actual-test-credential')
    assert text not in str(exc.value)


def test_cloud_text_technical_filenames_allowed():
    g.check_cloud_text({'body':'RP2040_base.kicad_pcb，C1 是 4.7uF 35V。'},'actual-test-credential')


def test_duplicate_source_structure_reported_before_partial_fidelity(repo):
    _,scope=setup(repo,'文件已打开。原理图未核对。');snap=s.snapshot(repo.read(),scope)
    with pytest.raises(ValueError,match='每个索引只出现一次'):
        g.validate('handoff',snap,{'blocks':[{'text':'文件已打开。','sources':[0]},{'text':'原理图未核对。','sources':[0]}]})
    result=g.validate('handoff',snap,{'blocks':[{'text':'文件已打开。\n\n原理图未核对。','sources':[0]}]})
    assert len(result['blocks'])==1


def test_controlled_prohibition_phrase_preserves_meaning(repo):
    _,scope=setup(repo,'不要把更正记录理解为更正设计。');snap=s.snapshot(repo.read(),scope)
    for phrase in ('不应将','不应把','不要将'):
        assert g.validate('polish',snap,{'blocks':[{'text':phrase+'更正记录理解为更正设计。','sources':[0]}]})
    with pytest.raises(ValueError):
        g.validate('polish',snap,{'blocks':[{'text':'可以将更正记录理解为更正设计。','sources':[0]}]})


def test_recording_before_after_values_is_not_an_execution_state():
    from note_ai.fidelity import action_states, check_relations
    assert action_states('再单独记修改前后的值。')==set()
    assert action_states('则单独记录修改前后的值。')==set()
    with pytest.raises(ValueError):check_relations('准备修改 C1。','已经修改 C1。')
    with pytest.raises(ValueError):check_relations('这次准备整理文件。','这次整理文件。')


def test_multisource_export_labels_and_generation_provenance(repo):
    import zipfile
    n,scope=setup(repo,'C1 未核对。')
    n=s.patch_note(repo,n['id'],m.NotePatch(expected_version=n['version'],title='规格核对'))
    b,_=setup(repo,'C2 未核对。')
    b=s.patch_note(repo,b['id'],m.NotePatch(expected_version=b['version'],title='资料待补'))
    scope.entry_ids.append(b['entries'][0]['id'])
    snap=s.snapshot(repo.read(),scope)
    body=g.validate('handoff',snap,{'blocks':[{'text':'C1 未核对。C2 未核对。','sources':[0,1],'heading':'这次交接什么'}],'gaps':[]})
    d=s.new_draft('handoff',snap,body,'generated')
    d['generation_config']={'provider':'deepseek','model':'observed-model','prompt_version':'notes-2','base_url':'SECRET_INTERNAL_LOCATION'}
    with repo.transaction() as state:state['drafts'][d['id']]=d
    result=package(repo,export_request(d))
    with zipfile.ZipFile(repo.file('packages',result['filename'])) as z:
        page=next(z.read(n).decode() for n in z.namelist() if n.endswith('阅读说明.html'))
        report=next(z.read(n).decode() for n in z.namelist() if n.endswith('data/report.json'))
    assert '这次交接什么' in page and '规格核对 · 记录' in page and '资料待补 · 记录' in page
    assert 'deepseek' in report and 'SECRET_INTERNAL_LOCATION' not in report


@pytest.fixture
def isolated(monkeypatch,tmp_path):
    settings=Settings(_env_file=None,llm_base_url='http://local.invalid/v1',llm_api_key='test-placeholder',model_name='local-test',deepseek_api_key='test-placeholder',deepseek_model='observed-model')
    monkeypatch.setattr(p,'Settings',lambda:settings)
    monkeypatch.setattr(usage,'Settings',lambda:settings)
    monkeypatch.setattr(usage,'PATH',tmp_path/'usage.sqlite3')
    return settings


def command(repo,scope,provider='local',**kw):
    snap=s.snapshot(repo.read(),scope)
    return m.JobRequest(**scope.model_dump(),snapshot_hash=s.digest(snap),provider=provider,**kw)


def test_frozen_config_distinct_provider_idempotency_and_retry(repo,isolated):
    n,scope=setup(repo)
    manager=Jobs(repo)
    a=manager.submit('polish',command(repo,scope))
    assert manager.submit('polish',command(repo,scope))['id']==a['id']
    with pytest.raises(HTTPException): manager.submit('polish',command(repo,scope,'deepseek'))
    b=manager.submit('polish',command(repo,scope,'deepseek',external_confirmed=True))
    assert b['id']!=a['id'] and 'api_key' not in json.dumps(b)
    isolated.model_name='changed-after-submit'
    manager.cancel(a['id']); retried=manager.retry(a['id'])
    assert retried['config']==a['config'] and retried['snapshot']==a['snapshot']
    assert b['authorization']['snapshot_hash']==b['input_hash'] or b['authorization']['snapshot_hash']==s.digest(b['snapshot'])
    assert b['config']['extra_body']=={'thinking':{'type':'disabled'}}
    assert a['config']['extra_body']=={'chat_template_kwargs':{'enable_thinking':False}}
    assert a['config']['prompts']['polish']==g.POLISH_POLICY
    assert a['config']['prompts']['handoff']==g.HANDOFF_POLICY


def test_queued_revocation_never_invokes_generator(repo,isolated):
    async def run():
        calls=[]; gate=asyncio.Event(); started=asyncio.Event()
        async def fake(kind,snap):
            calls.append(snap); started.set(); await gate.wait(); return g.template(snap)
        _,a=setup(repo,'先处理这条')
        n,b=setup(repo,'这条排队后撤回')
        jobs=Jobs(repo,fake); await jobs.start()
        first=jobs.submit('polish',command(repo,a)); await started.wait()
        second=jobs.submit('polish',command(repo,b,'deepseek',external_confirmed=True))
        s.patch_note(repo,n['id'],m.NotePatch(expected_version=1,share_allowed=False))
        gate.set(); await jobs.queue.join()
        assert len(calls)==1
        assert repo.read()['jobs'][second['id']]['status']=='failed'
        assert repo.read()['jobs'][first['id']]['status']=='succeeded'
        await jobs.stop()
    asyncio.run(run())


@pytest.mark.parametrize('limit',[0,1,3])
def test_durable_budget_and_local_independence(isolated,limit):
    isolated.notes_deepseek_request_limit=limit
    for i in range(limit): usage.reserve('deepseek','test')
    with pytest.raises(ValueError):usage.reserve('deepseek','test')
    usage.reserve('local','test')
    assert usage.totals().get('deepseek',0)==limit


class Failure(Exception):
    def __init__(self,code): self.status_code=code


def fake_client(monkeypatch,outputs,calls):
    class Client:
        def __init__(self,**kw):
            assert kw['max_retries']==0
            self.chat=NS(completions=self)
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def create(self,**kw):
            calls.append(kw)
            result=outputs.pop(0)
            if isinstance(result,Exception):raise result
            reason,content=result
            return NS(model=kw['model'],choices=[NS(finish_reason=reason,message=NS(content=content,reasoning_content='DO_NOT_STORE'))],usage=NS(model_dump=lambda:{'prompt_tokens':10,'completion_tokens':20,'total_tokens':30}))
    monkeypatch.setattr(g,'AsyncOpenAI',Client)


@pytest.mark.parametrize('code,attempts',[(400,1),(401,1),(402,1),(422,1),(429,2),(500,2),(503,2)])
def test_http_errors_bounded_no_fallback(repo,isolated,monkeypatch,code,attempts):
    _,scope=setup(repo); snap=s.snapshot(repo.read(),scope); calls=[]; events=[]
    fake_client(monkeypatch,[Failure(code)]*attempts,calls)
    with pytest.raises(ValueError):asyncio.run(g.generate('polish',snap,p.freeze('deepseek'),events.append))
    assert len(calls)==attempts and all(c['model']=='observed-model' for c in calls)
    assert usage.totals()['deepseek']==attempts
    assert 'DO_NOT_STORE' not in json.dumps(events)


def test_missing_credential_never_starts_request(repo,isolated,monkeypatch):
    from pydantic import SecretStr
    isolated.deepseek_api_key=SecretStr('')
    _,scope=setup(repo); calls=[]
    fake_client(monkeypatch,[],calls)
    with pytest.raises(ValueError,match='未配置完整'):
        asyncio.run(g.generate('polish',s.snapshot(repo.read(),scope),p.freeze('deepseek')))
    assert calls==[] and usage.totals()=={}


def test_timeout_is_bounded_and_does_not_echo_remote_text(repo,isolated,monkeypatch):
    _,scope=setup(repo); calls=[];events=[]
    fake_client(monkeypatch,[TimeoutError('PRIVATE_REMOTE_ERROR')],calls)
    with pytest.raises(ValueError,match='超时') as exc:
        asyncio.run(g.generate('polish',s.snapshot(repo.read(),scope),p.freeze('deepseek'),events.append))
    assert len(calls)==1 and usage.totals()['deepseek']==1
    assert 'PRIVATE_REMOTE_ERROR' not in str(exc.value)+json.dumps(events)


@pytest.mark.parametrize('bad',[('stop',''),('length','{}'),('stop','not JSON'),('stop','{"blocks":[{"text":"乱写","sources":[99]}],"gaps":[]}')])
def test_empty_truncated_bad_json_refs_fail_after_one_repair(repo,isolated,monkeypatch,bad):
    _,scope=setup(repo); snap=s.snapshot(repo.read(),scope); calls=[];events=[]
    fake_client(monkeypatch,[bad,bad],calls)
    with pytest.raises(ValueError):asyncio.run(g.generate('polish',snap,p.freeze('deepseek'),events.append))
    assert len(calls)==2
    assert len([e for e in events if e['status']=='validation_rejected'])==2


def test_repair_success_and_parameter_separation(repo,isolated,monkeypatch):
    _,scope=setup(repo,'C1 是 4.7uF 35V，未测试。');snap=s.snapshot(repo.read(),scope)
    valid=json.dumps({'blocks':[{'text':snap['entries'][0]['body'],'sources':[0]}],'gaps':[]})
    for provider in ('local','deepseek'):
        calls=[];fake_client(monkeypatch,[('stop',''),('stop',valid)],calls)
        result=asyncio.run(g.generate('polish',snap,p.freeze(provider)))
        assert result['blocks'][0]['source_refs'][0]['quote']==snap['entries'][0]['body']
        assert all(c['extra_body']==p.freeze(provider)['extra_body'] for c in calls)
        assert 'quote' not in json.loads(calls[0]['messages'][1]['content'])['entries'][0]


def test_permission_rechecked_before_repair(repo,isolated,monkeypatch):
    _,scope=setup(repo);snap=s.snapshot(repo.read(),scope);calls=[];checks=[]
    fake_client(monkeypatch,[('stop','')],calls)
    def permission():
        checks.append(1)
        if len(checks)>1:raise ValueError('revoked')
    with pytest.raises(ValueError):asyncio.run(g.generate('polish',snap,p.freeze('deepseek'),before_request=permission))
    assert len(calls)==1 and usage.totals()['deepseek']==1


def test_compact_multisource_version_binding_and_export(repo):
    n,scope=setup(repo,'文件已经打开。')
    n=s.write_entry(repo,n['id'],m.EntryWrite(expected_version=1,body='原理图尚未核对。'),True)
    scope.entry_ids=[e['id'] for e in n['entries']];snap=s.snapshot(repo.read(),scope)
    result=g.validate('handoff',snap,{'blocks':[{'text':'文件已经打开。原理图未核对。','sources':[0,1]}],'gaps':[]})
    assert len(result['blocks'])==1 and len(result['blocks'][0]['source_refs'])==2
    d=s.new_draft('handoff',snap,result)
    with repo.transaction() as state:state['drafts'][d['id']]=d
    assert package(repo,export_request(d))['size']>0
    for sources in ([0],[1,0],[0,0]):
        with pytest.raises(ValueError):g.validate('handoff',snap,{'blocks':[{'text':'文件已经打开。原理图未核对。','sources':sources}],'gaps':[]})


@pytest.mark.parametrize('original,changed',[
    ('C1 是 4.7uF 35V，C2 是 4.7uF 100V。','C1 是 4.7uF 100V，C2 是 4.7uF 35V。'),
    ('已经打开文件，未测量电压。','未打开文件，已经测量电压。'),
    ('怀疑 C1，未确认 C2。','确认 C1，怀疑 C2。'),
])
def test_relation_swaps_rejected(repo,original,changed):
    _,scope=setup(repo,original);snap=s.snapshot(repo.read(),scope)
    with pytest.raises(ValueError):g.validate('polish',snap,{'blocks':[{'text':changed,'sources':[0]}]})


def test_payload_only_selected_text_labels_and_captions(repo):
    a=image(repo);_,scope=setup(repo,attachments=[a['id']]);snap=s.snapshot(repo.read(),scope)
    snap['entries'][0]['identity']['project_name']='PRIVATE_PROJECT'
    snap['entries'][0]['objects']=[{'label':'C1','fingerprint':'PRIVATE_GEOMETRY','primitive_id':'private-id'}]
    payload=json.dumps(g.prompt_payload('handoff',snap))
    assert all(x not in payload for x in ('PRIVATE_PROJECT','PRIVATE_GEOMETRY','private-id','base64','sha256'))


@pytest.mark.parametrize('length,ok',[(12000,True),(12001,False)])
def test_body_limits(length,ok):
    if ok:assert len(m.EntryWrite(expected_version=1,body='字'*length).body)==length
    else:
        with pytest.raises(ValidationError):m.EntryWrite(expected_version=1,body='字'*length)


@pytest.mark.parametrize('count,ok',[(40,True),(41,False)])
def test_scope_limits(count,ok):
    if ok:assert len(m.Scope(board_key='x',entry_ids=[str(i) for i in range(count)]).entry_ids)==count
    else:
        with pytest.raises(ValidationError):m.Scope(board_key='x',entry_ids=[str(i) for i in range(count)])
