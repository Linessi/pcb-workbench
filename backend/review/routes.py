"""Local snapshot API; background Agent failures never erase the DRC report."""

import asyncio
import logging
from uuid import uuid4
from fastapi import APIRouter, HTTPException, Request
from config.settings import Settings
from review.agent_loop import ReviewLoop
from review.schema import AnalyzeOptions, ReviewReport, SnapshotInput
from review.store import SnapshotStore

router = APIRouter(prefix="/api/reviews")
store = SnapshotStore()
tasks: dict[str, asyncio.Task] = {}
live_reports: dict[str, ReviewReport] = {}
logger = logging.getLogger(__name__)


def read(snapshot_id: str):
    try:
        return store.read(snapshot_id)
    except (FileNotFoundError,ValueError):
        raise HTTPException(404,"未找到该快照，请重新采集当前 PCB。")


@router.post("",response_model=ReviewReport)
def create_snapshot(payload: SnapshotInput, request: Request):
    try:
        return store.create(payload,getattr(request.state,"request_id",uuid4().hex[:12]))
    except ValueError as error:
        raise HTTPException(422,str(error)) from error
    except OSError:
        raise HTTPException(500,"快照保存失败；请检查配置输出目录的访问权限。")


@router.get("/{snapshot_id}",response_model=ReviewReport)
def get_review(snapshot_id: str):
    return live_reports[snapshot_id] if snapshot_id in live_reports else read(snapshot_id)[0]


@router.post("/{snapshot_id}/analyze",response_model=ReviewReport)
async def start_analysis(snapshot_id: str, options: AnalyzeOptions):
    if snapshot_id in tasks and not tasks[snapshot_id].done():
        raise HTTPException(409,"本快照正在审查中，请等待或取消。")
    report,context = read(snapshot_id)
    store.archive_attempt(report)
    # Repeated analysis retains the exact same native issue IDs and raw data.
    report.explanations = []
    report.analysis_trace = []
    report.rejected_conclusions = []
    report.raw_model_draft = None
    report.knowledge_references = []
    report.evidence = [item for item in report.evidence if item.kind == "native_drc"]
    report.pending_checks = [item for item in report.pending_checks if not item.evidence_ids]
    report.agent_status = "running"
    report.agent_message_zh = "模型正在按需查询当前快照；完整原生 DRC 已可查看。"
    live_reports[snapshot_id] = report
    store.save(report)
    async def work():
        try:
            await ReviewLoop(Settings()).run(report,context,options.mode)
        except asyncio.CancelledError:
            pass
        finally:
            try:
                store.save(report)
                store.archive_attempt(report)
            except OSError:
                report.agent_status = "failed"
                report.agent_message_zh = "审查产物保存失败；当前内存中的原生 DRC 仍保留，请检查输出目录后重新导出。"
                logger.error("review_save_failed snapshot_id=%s", snapshot_id)
            else:
                live_reports.pop(snapshot_id,None)
    tasks[snapshot_id] = asyncio.create_task(work())
    return report


@router.post("/{snapshot_id}/cancel")
async def cancel_analysis(snapshot_id: str):
    if snapshot_id not in tasks or tasks[snapshot_id].done():
        read(snapshot_id)
        return {"cancelled":False,"message_zh":"当前没有运行中的智能体审查。"}
    tasks[snapshot_id].cancel()
    await asyncio.gather(tasks[snapshot_id],return_exceptions=True)
    # Also covers cancellation before the background coroutine first executes.
    unfinished = live_reports.pop(snapshot_id,None) or read(snapshot_id)[0]
    if unfinished and unfinished.agent_status == "running":
        unfinished.agent_status = "cancelled"
        unfinished.agent_message_zh = "审查已取消，停止后续调度；原生 DRC 结果仍保留。"
        store.save(unfinished)
    return {"cancelled":True,"message_zh":"已取消后续智能体调度；原生 DRC 引擎不支持由本插件中止。"}


@router.post("/{snapshot_id}/export")
def export_review(snapshot_id: str):
    report,_ = read(snapshot_id)
    if snapshot_id in live_reports:
        report = live_reports[snapshot_id]
    store.save(report)
    directory = store.directory(snapshot_id)
    names = ["context.json","raw_drc.json","review_report.json","agent_trace.json","report_zh.md"]
    if report.comparison:
        names.append("comparison.json")
    if not all((directory/name).is_file() and (directory/name).stat().st_size>0 for name in names):
        raise HTTPException(500,"导出文件存在性核验失败。")
    return {"saved":True,"directory":str(directory),"files":names,"parsed_count":report.drc.parsed_count,"message_zh":"完整审查产物已保存并核验。"}


@router.post("/{snapshot_id}/client_event")
def record_client_event(snapshot_id: str, payload: dict):
    # Audit only; never execute an EDA method from a page or model message.
    report,context = read(snapshot_id)
    if set(payload) != {"action","document_id","status","detail_zh","primitive_ids"} or payload.get("action") != "select_related_objects":
        raise HTTPException(422,"不支持的客户端审计动作。")
    if not isinstance(payload["primitive_ids"],list) or not all(isinstance(item,str) for item in payload["primitive_ids"]) or not isinstance(payload["detail_zh"],str):
        raise HTTPException(422,"客户端动作参数无效。")
    permitted = {obj.primitive_id for issue in report.drc.issues for obj in issue.objects if obj.primitive_id}
    # The client may select a pad's actual owner component as a labelled fallback.
    # Only owners of pads present in native evidence are eligible.
    pad_ids = {obj.object_id for issue in report.drc.issues for obj in issue.objects if obj.kind == "pad"}
    owners = {pad.component for pad in context.pads if f"{pad.component}.{pad.number}" in pad_ids}
    permitted.update(part.primitiveId for part in context.components if part.reference in owners and part.primitiveId)
    if report.source_kind != "eda_live" or not payload["primitive_ids"] or payload["document_id"] != report.provenance.get("document_id") or not set(payload["primitive_ids"]) <= permitted or payload["status"] != "verified":
        raise HTTPException(422,"客户端审计记录与快照对象不一致。")
    store._write_json(store.directory(snapshot_id),f"client_event_{uuid4().hex}.json",payload)
    return {"saved":True}
