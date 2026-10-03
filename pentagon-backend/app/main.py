from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.db.session import initialize_database
from app.routes import chat, documents, keys, models, voice


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    initialize_database()
    yield


app = FastAPI(
    title="Pentagon Backend",
    description="A bring-your-own-key NVIDIA NIM chat API.",
    version="0.1.0",
    lifespan=lifespan,
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
app.include_router(documents.router)
app.include_router(voice.router)
