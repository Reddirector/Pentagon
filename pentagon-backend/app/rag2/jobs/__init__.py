"""Background index jobs: queue, worker, handlers (RAG §3)."""

from app.rag2.jobs.queue import JobQueue, default_queue
from app.rag2.jobs.worker import (
    JobContext,
    handler_for,
    register_handler,
    run_once,
    start_worker,
    worker_loop,
)

__all__ = [
    "JobContext",
    "JobQueue",
    "default_queue",
    "handler_for",
    "register_handler",
    "run_once",
    "start_worker",
    "worker_loop",
]
