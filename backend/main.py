"""Local FastAPI bridge between the EDA extension and a Qwen-compatible API."""

import logging
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from openai import APIConnectionError, APIStatusError, APITimeoutError

from agent.pcb_agent import PCBReviewAgent
from agent.report import InvalidModelReport
from config.settings import Settings
from models.schema import PCBContext, PCBContextV2, PCBReviewReport
from rag.retriever import KnowledgeBaseUnavailable
from review.routes import router as review_router
from notes.routes import router as notes_router, lifespan


logging.basicConfig(
    level=getattr(logging, Settings().log_level),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("ai_eda_copilot")
OUTPUT_DIRECTORY = Path(__file__).resolve().parents[1] / "output"
CONTEXT_FILENAME = "robot_controller_context_v06.json"

app = FastAPI(title="PCB 工作台配套服务", version="0.9.7", lifespan=lifespan)
app.include_router(review_router)
app.include_router(notes_router)
# Local desktop extension origin varies between EDA editions. Bind Uvicorn to
# 127.0.0.1 (see README) and allow cross-origin requests for this local bridge.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def log_request(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """Log request outcome and an opaque ID without PCB data or credentials."""
    request_id = uuid4().hex[:12]
    request.state.request_id = request_id
    started = perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
        # Avoid printing arbitrary exception text: providers may include sensitive
        # request details in their error messages.
        logger.error("request_id=%s unhandled backend error type=%s", request_id, type(exc).__name__)
        detail = "后端内部异常，请查看脱敏日志。" if request.url.path.startswith("/api/reviews") else "Internal backend error"
        response = JSONResponse(status_code=500, content={"detail": detail})
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request_id=%s method=%s path=%s status=%s duration_ms=%.1f",
        request_id, request.method, request.url.path, response.status_code,
        (perf_counter() - started) * 1000,
    )
    return response


def get_agent() -> PCBReviewAgent:
    settings = Settings()
    if not settings.configured:
        raise HTTPException(
            status_code=503,
            detail=f"模型尚未配置完整：{', '.join(settings.missing_fields)}",
        )
    if not settings.llm_base_url.rstrip("/").endswith("/v1"):
        raise HTTPException(status_code=503, detail="LLM_BASE_URL 必须以 /v1 结尾。")
    return PCBReviewAgent(settings)


@app.get("/health")
def health() -> dict[str, object]:
    settings = Settings()
    return {"status": "ok", "llmConfigured": settings.configured}


@app.post("/api/save_context")
def save_context(context: PCBContextV2) -> dict[str, str | bool]:
    """Persist a validated V2 Context to one fixed project-local path."""
    destination = OUTPUT_DIRECTORY / CONTEXT_FILENAME
    temporary = OUTPUT_DIRECTORY / f".{CONTEXT_FILENAME}.{uuid4().hex}.tmp"
    try:
        OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps(context.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(destination)
        if not destination.is_file() or destination.stat().st_size == 0:
            raise OSError("context file did not appear after write")
    except OSError as exc:
        logger.error("PCB Context write failed, error_type=%s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="PCB 上下文保存失败，请检查输出目录权限。") from exc
    finally:
        temporary.unlink(missing_ok=True)
    return {"saved": True, "path": str(destination)}


@app.post("/api/analyze_pcb", response_model=PCBReviewReport)
async def analyze_pcb(
    context: PCBContextV2 | PCBContext,
    agent: PCBReviewAgent = Depends(get_agent),
) -> PCBReviewReport:
    try:
        return await agent.analyze(context)
    except APITimeoutError as exc:
        logger.warning("LLM request timed out")
        raise HTTPException(status_code=504, detail="模型请求超时，原生检查数据仍保留。") from exc
    except APIConnectionError as exc:
        logger.warning("LLM endpoint unreachable")
        raise HTTPException(status_code=502, detail="模型服务不可达，请检查局域网服务。") from exc
    except APIStatusError as exc:
        logger.warning("LLM endpoint returned HTTP %s", exc.status_code)
        raise HTTPException(status_code=502, detail=f"模型服务返回异常（HTTP {exc.status_code}）。") from exc
    except InvalidModelReport as exc:
        logger.warning("LLM returned an invalid report: %s", exc)
        raise HTTPException(status_code=502, detail="模型报告格式或证据校验未通过，请重试。") from exc
    except KnowledgeBaseUnavailable as exc:
        logger.error("PCB knowledge retrieval unavailable")
        raise HTTPException(status_code=503, detail="知识库或嵌入模型不可用，请查看后端日志。") from exc
