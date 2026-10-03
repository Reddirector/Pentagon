from __future__ import annotations

import asyncio
import io
import logging
from pathlib import PurePath
from uuid import uuid4

from docx import Document as WordDocument
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Conversation, Document, User
from app.db.session import get_db
from app.schemas import DocumentResponse
from app.security.keys import NoKeyAvailableError, resolve_api_key
from app.services.document_store import delete_document_chunks, store_chunks


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/documents", tags=["documents"])
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024
_SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt"}


@router.post("/upload", response_model=DocumentResponse, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    user_id: str = Form(min_length=1, max_length=128),
    conversation_id: str = Form(min_length=1, max_length=36),
    db: Session = Depends(get_db),
) -> dict:
    conversation = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found for this user.")

    filename = _safe_filename(file.filename or "")
    extension = PurePath(filename).suffix.lower()
    if extension not in _SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Upload a PDF, DOCX, or plain text file.")

    raw_file = await file.read(_MAX_UPLOAD_BYTES + 1)
    if len(raw_file) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="The maximum document size is 20 MB.")
    try:
        text = await asyncio.to_thread(_extract_text, raw_file, extension)
    except Exception as exc:
        logger.info("Document extraction failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=422, detail="Could not extract text from this document.") from None
    if not text.strip():
        raise HTTPException(status_code=422, detail="This document contains no extractable text.")

    chunks = await asyncio.to_thread(_chunk_text, text)
    if not chunks:
        raise HTTPException(status_code=422, detail="This document contains no extractable text.")

    try:
        api_key = resolve_api_key(db, user_id)
    except NoKeyAvailableError:
        if db.get(User, user_id) is None:
            raise HTTPException(status_code=404, detail="User not found. Store an API key first.") from None
        api_key = None
    except EncryptionConfigurationError:
        raise HTTPException(status_code=503, detail="Key decryption is not configured on the server.") from None
    except EncryptedKeyError:
        raise HTTPException(status_code=500, detail="The stored API key could not be decrypted.") from None

    document_id = str(uuid4())
    try:
        collection_name, chunks_stored = await store_chunks(
            conversation_id=conversation_id,
            document_id=document_id,
            filename=filename,
            chunks=chunks,
            user_id=user_id,
            api_key=api_key,
        )
    except Exception as exc:
        logger.warning("Document vector storage failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Could not embed or store this document.") from None

    document = Document(
        id=document_id,
        user_id=user_id,
        conversation_id=conversation_id,
        collection_name=collection_name,
        filename=filename,
        chunk_count=chunks_stored,
    )
    db.add(document)
    try:
        db.commit()
    except Exception:
        db.rollback()
        try:
            await delete_document_chunks(collection_name, document_id)
        except Exception:
            logger.warning("Orphan document chunks could not be removed after database failure")
        raise HTTPException(status_code=500, detail="Could not save document metadata.") from None

    return {
        "document_id": document.id,
        "filename": document.filename,
        "chunks_stored": document.chunk_count,
        "created_at": document.created_at,
    }


@router.delete("/{document_id}")
async def remove_document(
    document_id: str,
    user_id: str = Query(min_length=1, max_length=128),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    document = db.scalar(
        select(Document).where(Document.id == document_id, Document.user_id == user_id)
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found for this user.")

    try:
        await delete_document_chunks(document.collection_name, document.id)
    except Exception as exc:
        logger.warning("Document vector deletion failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Could not remove document chunks.") from None
    db.delete(document)
    db.commit()
    return {"deleted": True, "document_id": document_id}


@router.get("")
def list_documents(
    user_id: str = Query(min_length=1, max_length=128),
    conversation_id: str = Query(min_length=1, max_length=36),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    conversation = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found for this user.")
    rows = db.scalars(
        select(Document)
        .where(Document.user_id == user_id, Document.conversation_id == conversation_id)
        .order_by(Document.created_at)
    )
    return [
        {
            "document_id": item.id,
            "filename": item.filename,
            "chunks_stored": item.chunk_count,
            "created_at": item.created_at,
        }
        for item in rows
    ]


def _safe_filename(filename: str) -> str:
    normalized = filename.replace("\\", "/").split("/")[-1].strip()
    return normalized[:255]


def _extract_text(raw_file: bytes, extension: str) -> str:
    if extension == ".pdf":
        reader = PdfReader(io.BytesIO(raw_file), strict=False)
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    if extension == ".docx":
        document = WordDocument(io.BytesIO(raw_file))
        paragraphs = [paragraph.text for paragraph in document.paragraphs if paragraph.text]
        for table in document.tables:
            paragraphs.extend(
                " | ".join(cell.text for cell in row.cells)
                for row in table.rows
            )
        return "\n".join(paragraphs)
    return raw_file.decode("utf-8-sig")


def _chunk_text(text: str) -> list[str]:
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=2000,
        chunk_overlap=200,
        length_function=len,
    )
    return [chunk.strip() for chunk in splitter.split_text(text) if chunk.strip()]
