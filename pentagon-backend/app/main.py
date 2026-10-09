from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
import asyncio
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import cors_origin_list, settings
from app.db.session import initialize_database
from app.services.checkpointer import prepare_checkpointer
from app.routes import (
    agent,
    chat,
    collections,
    commands,
    documents,
    keys,
    memories,
    models,
    skills,
    voice,
)
from app.services import mcp_bridge

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    initialize_database()
    # The chat checkpointer's tables are created here, not on the first chat
    # turn: its setup runs CREATE INDEX CONCURRENTLY, which waits for every
    # transaction that is already open -- and a streaming turn keeps its own
    # session open while the response is being read. A no-op on SQLite, and a
    # failure is logged rather than fatal, so a locked or unreachable database
    # does not stop the rest of the app from starting.
    try:
        await prepare_checkpointer()
    except Exception:
        logger.exception(
            "Could not create the chat checkpoint tables; a paused approval "
            "cannot be stored until this succeeds (it is retried on the next turn)"
        )
    # T10: connect configured MCP servers once, before any turn can ask for
    # their tools. A broken server is recorded in the bridge's problems,
    # never a startup failure.
    await mcp_bridge.connect_all()
    # R0: index jobs left `running` by a crash go back to `queued` (they are
    # idempotent per batch), then the worker starts. Tests disable the worker
    # so jobs are driven deterministically instead of racing a poll loop.
    worker_stop: asyncio.Event | None = None
    worker_task: asyncio.Task[object] | None = None
    if settings.job_worker_enabled:
        from app.rag2.jobs import default_queue, start_worker

        default_queue.requeue_interrupted()
        worker_stop, worker_task = start_worker()
    yield
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


app.include_router(keys.router)
app.include_router(models.router)
app.include_router(chat.router)
app.include_router(agent.router)
app.include_router(documents.router)
app.include_router(voice.router)
app.include_router(commands.router)
app.include_router(memories.router)
app.include_router(collections.router)
app.include_router(skills.router)
