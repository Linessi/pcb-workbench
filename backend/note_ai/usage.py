"""Durable request budget shared across notebooks/processes, without prompt data."""
import json
import sqlite3
from pathlib import Path
from notes.repository import now, uid
from config.settings import Settings

PATH = Path(__file__).resolve().parents[2] / 'output/notes-provider-usage.sqlite3'


def connection():
    PATH.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(PATH,timeout=10)
    c.execute('CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, provider TEXT, model TEXT, started TEXT, result TEXT)')
    return c


def reserve(provider,model):
    with connection() as c:
        c.execute('BEGIN IMMEDIATE')
        count=c.execute("SELECT count(*) FROM requests WHERE provider='deepseek'").fetchone()[0]
        if provider=='deepseek' and count>=Settings().notes_deepseek_request_limit:
            raise ValueError('本轮 DeepSeek 请求上限已到；仍可用本机服务或按原文导出')
        key=uid()
        c.execute('INSERT INTO requests VALUES (?,?,?,?,?)',(key,provider,model,now(),json.dumps({'status':'sent'})))
        return key


def finish(key,result):
    # Caller passes a whitelist of counts/status/timing; never prompt or raw response.
    allowed={k:v for k,v in result.items() if k in ('status','usage','seconds','http_status','error_type','finish_reason','model')}
    with connection() as c:
        c.execute('UPDATE requests SET result=? WHERE id=?',(json.dumps(allowed),key))


def totals():
    with connection() as c:
        return dict(c.execute('SELECT provider,count(*) FROM requests GROUP BY provider').fetchall())
