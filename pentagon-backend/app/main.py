from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
import asyncio
import logging
import time

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from app.config import cors_origin_list, settings
from app.db.session import initialize_database
from app.security.capability_auth import require_capability
from app.security.request_limits import RequestBodyLimitMiddleware
from app.services.checkpointer import prepare_checkpointer
from app.routes import (
    agent,
    chat,
    collections,
    commands,
    documents,
    files,
    keys,
    mcp,
    memories,
    models,
    skills,
    voice,
    workflows,
)
from app.services import mcp_bridge

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    _app.state.database_ready = False
    _app.state.database_retry_after = 0.0
    _app.state.database_retry_lock = asyncio.Lock()
    try:
        await asyncio.to_thread(initialize_database)
        _app.state.database_ready = True
    except Exception as exc:
        # A paused/unreachable hosted database must not prevent the local UI
        # from opening. API routes receive a sanitized 503 and initialization
        # is retried when traffic returns.
        logger.warning("Database initialization failed; starting in degraded mode error=%s", type(exc).__name__)
    # The chat checkpointer's tables are created here, not on the first chat
    # turn: its setup runs CREATE INDEX CONCURRENTLY, which waits for every
    # transaction that is already open -- and a streaming turn keeps its own
    # session open while the response is being read. A no-op on SQLite, and a
    # failure is logged rather than fatal, so a locked or unreachable database
    # does not stop the rest of the app from starting.
    if _app.state.database_ready:
        try:
            await prepare_checkpointer()
        except Exception as exc:
            logger.warning("Checkpointer initialization failed error=%s", type(exc).__name__)
    # T10: connect configured MCP servers once, before any turn can ask for
    # their tools. A broken server is recorded in the bridge's problems,
    # never a startup failure.
    await mcp_bridge.connect_all()
    # R0: index jobs left `running` by a crash go back to `queued` (they are
    # idempotent per batch), then the worker starts. Tests disable the worker
    # so jobs are driven deterministically instead of racing a poll loop.
    worker_stop: asyncio.Event | None = None
    worker_task: asyncio.Task[object] | None = None
    if settings.job_worker_enabled and _app.state.database_ready:
        from app.rag2.jobs import default_queue, start_worker

        default_queue.requeue_interrupted()
        worker_stop, worker_task = start_worker()
    _app.state.worker_stop = worker_stop
    _app.state.worker_task = worker_task
    yield
    worker_stop = getattr(_app.state, "worker_stop", worker_stop)
    worker_task = getattr(_app.state, "worker_task", worker_task)
    if worker_stop is not None and worker_task is not None:
        worker_stop.set()
        try:
            await asyncio.wait_for(worker_task, timeout=5)
        except (TimeoutError, asyncio.CancelledError):
            worker_task.cancel()
    await mcp_bridge.shutdown()


app = FastAPI(
    title="Pentagon Backend",
    description="A bring-your-own-key NVIDIA NIM chat API.",
    version="0.1.0",
    lifespan=lifespan,
)
app.state.database_ready = True
app.state.database_retry_after = 0.0
app.state.database_retry_lock = asyncio.Lock()


@app.middleware("http")
async def retry_database_initialization(request: Request, call_next):
    if request.url.path.startswith("/api/") and request.method != "OPTIONS":
        if not app.state.database_ready and time.monotonic() >= app.state.database_retry_after:
            async with app.state.database_retry_lock:
                if not app.state.database_ready and time.monotonic() >= app.state.database_retry_after:
                    try:
                        await asyncio.to_thread(initialize_database)
                        app.state.database_ready = True
                        app.state.database_retry_after = 0.0
                        try:
                            await prepare_checkpointer()
                        except Exception as exc:
                            logger.warning("Checkpointer retry failed error=%s", type(exc).__name__)
                        if settings.job_worker_enabled and getattr(app.state, "worker_task", None) is None:
                            from app.rag2.jobs import default_queue, start_worker

                            await asyncio.to_thread(default_queue.requeue_interrupted)
                            app.state.worker_stop, app.state.worker_task = start_worker()
                    except Exception as exc:
                        app.state.database_retry_after = time.monotonic() + 5.0
                        logger.warning("Database retry failed error=%s", type(exc).__name__)
        if not app.state.database_ready:
            return JSONResponse(
                status_code=503,
                content={"detail": "Database is unavailable. Pentagon is retrying; try again shortly."},
                headers={"Retry-After": "5"},
            )
    return await call_next(request)


@app.exception_handler(OperationalError)
async def database_operational_error(_request: Request, exc: OperationalError) -> JSONResponse:
    app.state.database_ready = False
    app.state.database_retry_after = time.monotonic() + 1.0
    logger.warning("Database operation failed; marking service unavailable error=%s", type(exc).__name__)
    return JSONResponse(
        status_code=503,
        content={"detail": "Database is unavailable. Pentagon is retrying; try again shortly."},
        headers={"Retry-After": "1"},
    )

# Leaves room for the configured 120 MiB video upload plus multipart framing,
# while stopping accidental or hostile unbounded body buffering.
app.add_middleware(
    RequestBodyLimitMiddleware,
    max_bytes=130 * 1024 * 1024,
)

# The iOS and Android shells run the same bundle inside a native WebView, which
# makes them a different origin from this API. Without this the phone build
# fails every request at the preflight, before a route ever sees it.
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origin_list(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    # The chat route streams, and the browser hides a cross-origin response
    # from fetch unless it is told to expose the headers it needs.
    expose_headers=["Content-Disposition", "X-Audio-Format", "X-Audio-Sample-Rate", "X-Audio-Channels"],
)


@app.exception_handler(RequestValidationError)
async def sanitized_validation_error(
    _request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    # Pydantic's default error payload includes the rejected input. Omitting it
    # prevents a submitted API key from appearing in validation responses.
    errors = [
        {
            "loc": list(error.get("loc", ())),
            "msg": error.get("msg", "Invalid request."),
            "type": error.get("type", "value_error"),
        }
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errors})


_api_auth = [Depends(require_capability)]
app.include_router(keys.router, dependencies=_api_auth)
app.include_router(models.router, dependencies=_api_auth)
app.include_router(chat.router, dependencies=_api_auth)
app.include_router(agent.router, dependencies=_api_auth)
app.include_router(documents.router, dependencies=_api_auth)
app.include_router(files.router)
app.include_router(voice.router, dependencies=_api_auth)
app.include_router(commands.router, dependencies=_api_auth)
app.include_router(memories.router, dependencies=_api_auth)
app.include_router(collections.router, dependencies=_api_auth)
app.include_router(skills.router, dependencies=_api_auth)
app.include_router(workflows.router, dependencies=_api_auth)
app.include_router(mcp.router, dependencies=_api_auth)

