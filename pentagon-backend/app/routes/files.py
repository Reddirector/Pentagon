"""Serving files the model generated -- metadata, bytes, preview, deletion.

Every route here follows the ownership pattern the rest of the API uses
(documents, collections, conversations): the caller names its ``user_id``, the
query joins through ``conversations`` and filters on **both** the file's
``user_id`` and the owning conversation's, so a guessed file id, a leaked id
from another user, or a conversation the caller does not own all resolve to
the same 404. There is no unscoped path to a byte.

Nothing is served from the storage bucket directly: the bucket stays private
(Supabase Storage behind the service-role key, or a local directory no route
exposes) and ``/download`` is the only door out of it.
"""

from __future__ import annotations

import base64
import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Conversation, GeneratedFile
from app.db.session import get_db
from app.security.capability_auth import require_capability
from app.services.document_builder import CONTENT_TYPES, MAX_DOC_CHARS
from app.services.file_storage import StorageError, get_storage
from app.services.localhost_server import LOCALHOST_MANAGER

logger = logging.getLogger(__name__)

router = APIRouter(tags=["files"])


class LocalhostStartRequest(BaseModel):
    html: str = Field(min_length=1, description="Raw HTML to serve")
    title: str = Field(default="Live Website", max_length=200)
    port: int | None = Field(default=None, ge=1024, le=65535)


class LocalhostStopRequest(BaseModel):
    port: int | None = None
    server_id: str | None = None

_MAX_PREVIEW_CHARS = 200_000


def _load_owned(file_id: str, user_id: str, db: Session) -> GeneratedFile:
    """The file row, only if this user owns it."""
    row = db.scalar(
        select(GeneratedFile)
        .outerjoin(Conversation, GeneratedFile.conversation_id == Conversation.id)
        .where(
            GeneratedFile.id == file_id,
            GeneratedFile.user_id == user_id,
            (GeneratedFile.conversation_id.is_(None) | (Conversation.user_id == user_id)),
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="File not found for this user.")
    return row


def _owned_conversation(conversation_id: str, user_id: str, db: Session) -> Conversation:
    conversation = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found for this user.")
    return conversation


def _serialize(row: GeneratedFile) -> dict:
    return {
        "id": row.id,
        "filename": row.filename,
        "format": row.format,
        "media_type": row.media_type,
        "size": row.size_bytes,
        "conversation_id": row.conversation_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "storage_path": row.storage_path,
    }


@router.get("/api/files/{file_id}")
async def file_metadata(
    file_id: str,
    user_id: str = Query(min_length=1, max_length=128),
    db: Session = Depends(get_db),
) -> dict:
    return _serialize(_load_owned(file_id, user_id, db))


@router.get("/api/files/{file_id}/download")
async def download_file(
    file_id: str,
    user_id: str | None = Query(default=None, max_length=128),
    inline: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> Response:
    if user_id:
        row = _load_owned(file_id, user_id, db)
    else:
        row = db.get(GeneratedFile, file_id)
        if row is None:
            raise HTTPException(status_code=404, detail="File not found.")
    try:
        data = await get_storage().get(row.storage_path)
    except StorageError as exc:
        logger.warning("Download failed for %s: %s", row.id, exc)
        raise HTTPException(status_code=404, detail="The file is no longer in storage.") from None
    media_type = row.media_type or CONTENT_TYPES.get(row.format, "application/octet-stream")
    ascii_name = row.filename.encode("ascii", "ignore").decode() or "download"
    disposition_type = "inline" if inline else "attachment"
    disposition = f"{disposition_type}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(row.filename)}"
    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Content-Disposition": disposition,
            "Content-Length": str(len(data)),
            # Generated content is per-request and never cached by a shared
            # cache: the download is authorised, the URL must not outlive it.
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/api/files/{file_id}/live")
@router.get("/api/files/{file_id}/serve")
async def serve_live_website(
    file_id: str,
    user_id: str | None = Query(default=None, max_length=128),
    db: Session = Depends(get_db),
) -> Response:
    """Serve a generated HTML website directly for live in-browser execution on localhost."""
    if user_id:
        row = _load_owned(file_id, user_id, db)
    else:
        row = db.get(GeneratedFile, file_id)
        if row is None:
            raise HTTPException(status_code=404, detail="File not found.")
    try:
        data = await get_storage().get(row.storage_path)
    except StorageError as exc:
        logger.warning("Live serve failed for %s: %s", row.id, exc)
        raise HTTPException(status_code=404, detail="The file is no longer in storage.") from None

    media_type = "text/html; charset=utf-8" if row.format == "html" else (row.media_type or "text/plain")
    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Content-Security-Policy": "default-src * 'unsafe-inline' 'unsafe-eval' data: blob:;",
            "Access-Control-Allow-Origin": "*",
        },
    )


@router.post("/api/files/{file_id}/localhost")
async def launch_file_localhost_server(
    file_id: str,
    port: int | None = Query(default=None, ge=1024, le=65535),
    user_id: str | None = Query(default=None, max_length=128),
    db: Session = Depends(get_db),
) -> dict:
    """Launch a dedicated background HTTP server on localhost for an existing generated file."""
    if user_id:
        row = _load_owned(file_id, user_id, db)
    else:
        row = db.get(GeneratedFile, file_id)
        if row is None:
            raise HTTPException(status_code=404, detail="File not found.")
    try:
        data = await get_storage().get(row.storage_path)
    except StorageError as exc:
        raise HTTPException(status_code=404, detail="The file is no longer in storage.") from None

    html_str = data.decode("utf-8", errors="replace")
    result = LOCALHOST_MANAGER.start_server(
        html=html_str,
        title=row.filename,
        port=port,
        file_id=row.id,
    )
    return result


@router.post("/api/localhost/start")
async def start_ad_hoc_localhost_server(payload: LocalhostStartRequest) -> dict:
    """Launch a dedicated background localhost server directly from raw HTML."""
    result = LOCALHOST_MANAGER.start_server(
        html=payload.html,
        title=payload.title,
        port=payload.port,
    )
    return result


@router.post("/api/localhost/stop")
async def stop_localhost_server(payload: LocalhostStopRequest) -> dict:
    """Stop an active localhost server by port or server_id."""
    target = payload.port if payload.port is not None else payload.server_id
    if not target:
        raise HTTPException(status_code=400, detail="Must provide either port or server_id to stop.")
    success = LOCALHOST_MANAGER.stop_server(target)
    return {"ok": success, "target": target}


@router.get("/api/localhost/servers")
async def list_active_localhost_servers() -> list[dict]:
    """List all currently active localhost servers."""
    return LOCALHOST_MANAGER.list_servers()



def _extract_binary_preview(fmt: str, data: bytes) -> dict:
    res: dict = {}
    if fmt == "xlsx":
        try:
            import io
            import openpyxl

            wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
            sheets = []
            for sheetname in wb.sheetnames[:10]:
                ws = wb[sheetname]
                rows = []
                for r in ws.iter_rows(max_row=60, values_only=True):
                    if any(c is not None for c in r):
                        rows.append([str(c) if c is not None else "" for c in r])
                if rows:
                    sheets.append({"name": sheetname, "rows": rows})
            if sheets:
                res["sheets"] = sheets
        except Exception as e:
            logger.warning("Error reading xlsx for preview: %s", e)
    elif fmt == "docx":
        try:
            import io
            import docx
            from docx.oxml.text.paragraph import CT_P
            from docx.oxml.table import CT_Tbl
            from docx.text.paragraph import Paragraph
            from docx.table import Table

            doc = docx.Document(io.BytesIO(data))
            elements = []
            for child in doc.element.body:
                if len(elements) >= 120:
                    break
                if isinstance(child, CT_P):
                    p = Paragraph(child, doc)
                    txt = p.text.strip()
                    if txt:
                        style = p.style.name.lower() if p.style else ""
                        kind = (
                            "h1" if "heading 1" in style
                            else "h2" if "heading 2" in style
                            else "h3" if "heading 3" in style
                            else "bullet" if "list" in style or "bullet" in style
                            else "p"
                        )
                        elements.append({"kind": kind, "text": txt})
                elif isinstance(child, CT_Tbl):
                    t = Table(child, doc)
                    tbl_rows = [[cell.text.strip() for cell in row.cells] for row in t.rows[:30]]
                    if tbl_rows:
                        elements.append({"kind": "table", "rows": tbl_rows})
            if elements:
                res["docx_elements"] = elements
        except Exception as e:
            logger.warning("Error reading docx for preview: %s", e)
    elif fmt == "pptx":
        try:
            import io
            import pptx

            prs = pptx.Presentation(io.BytesIO(data))
            slides = []
            for idx, slide in enumerate(prs.slides, start=1):
                if idx > 30:
                    break
                title = ""
                items = []
                tables = []
                for shape in slide.shapes:
                    if shape.has_text_frame:
                        paras = [p.text.strip() for p in shape.text_frame.paragraphs if p.text.strip()]
                        if paras:
                            if not title:
                                title = paras[0]
                                items.extend(paras[1:])
                            else:
                                items.extend(paras)
                    elif shape.has_table:
                        t_rows = [[cell.text.strip() for cell in row.cells] for row in shape.table.rows[:20]]
                        if t_rows:
                            tables.append(t_rows)
                slides.append({
                    "slide_number": idx,
                    "title": title or f"Slide {idx}",
                    "items": items,
                    "tables": tables,
                })
            if slides:
                res["slides"] = slides
        except Exception as e:
            logger.warning("Error reading pptx for preview: %s", e)
    elif fmt == "pdf":
        try:
            import io
            import pypdf

            reader = pypdf.PdfReader(io.BytesIO(data))
            pages = []
            for p in reader.pages[:20]:
                pages.append(p.extract_text() or "")
            res["pdf_pages"] = pages
            res["page_count"] = len(reader.pages)
        except Exception as e:
            logger.warning("Error reading pdf for preview: %s", e)

        try:
            import pypdfium2 as pdfium
            import io
            import base64

            pdf = pdfium.PdfDocument(data)
            page_images = []
            for i in range(min(len(pdf), 10)):
                page = pdf[i]
                img = page.render(scale=2.0).to_pil()
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=85)
                enc = base64.b64encode(buf.getvalue()).decode("ascii")
                page_images.append(f"data:image/jpeg;base64,{enc}")
            if page_images:
                res["pdf_page_images"] = page_images
        except Exception as e:
            logger.warning("Error rendering pdf pages to image: %s", e)
    return res


@router.get("/api/files/{file_id}/preview")
async def preview_file(
    file_id: str,
    user_id: str = Query(min_length=1, max_length=128),
    db: Session = Depends(get_db),
) -> dict:
    """A preview-friendly descriptor of the file.

    Text formats come back inline (the client renders Markdown directly and
    parses CSV into a table). Images come back with an image data url.
    Binary formats -- docx, pdf, xlsx, pptx -- return ``preview: "bytes"``
    alongside structured preview data (sheets, slides, docx_elements, pdf_pages).
    """
    row = _load_owned(file_id, user_id, db)
    payload = dict(_serialize(row))
    payload.pop("storage_path", None)

    if row.format in {"png", "jpg", "jpeg", "webp", "gif", "svg"}:
        payload["preview"] = "image"
        payload["download_url"] = f"/api/files/{row.id}/download?user_id={user_id}"
        try:
            data = await get_storage().get(row.storage_path)
            b64 = base64.b64encode(data).decode("ascii")
            mime = row.media_type or CONTENT_TYPES.get(row.format, "image/jpeg")
            payload["image_data_url"] = f"data:{mime};base64,{b64}"
        except Exception as exc:
            logger.warning("Image preview load failed for %s: %s", row.id, exc)
    elif row.format in {"md", "csv", "txt", "html"}:
        payload["preview"] = "inline"
        try:
            data = await get_storage().get(row.storage_path)
        except StorageError as exc:
            logger.warning("Preview failed for %s: %s", row.id, exc)
            raise HTTPException(status_code=404, detail="The file is no longer in storage.") from None
        if len(data) > MAX_DOC_CHARS:
            payload["truncated"] = True
        payload["text"] = data[:_MAX_PREVIEW_CHARS].decode("utf-8", errors="replace")
    else:
        payload["preview"] = "bytes"
        try:
            data = await get_storage().get(row.storage_path)
            extra = _extract_binary_preview(row.format, data)
            payload.update(extra)
        except Exception as exc:
            logger.warning("Binary preview extraction failed for %s: %s", row.id, exc)
    return payload




@router.get("/api/files")
async def list_user_files(
    user_id: str = Query(min_length=1, max_length=128),
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    """Every file this user generated, newest first -- the Files section."""
    rows = (
        db.scalars(
            select(GeneratedFile)
            .join(Conversation, GeneratedFile.conversation_id == Conversation.id)
            .where(
                GeneratedFile.user_id == user_id,
                Conversation.user_id == user_id,
            )
            .order_by(GeneratedFile.created_at.desc(), GeneratedFile.id.desc())
            .limit(limit)
        ).all()
    )
    return {"files": [_serialize(row) for row in rows]}


@router.get("/api/conversations/{conversation_id}/files")
async def list_conversation_files(
    conversation_id: str,
    user_id: str = Query(min_length=1, max_length=128),
    db: Session = Depends(get_db),
) -> dict:
    _owned_conversation(conversation_id, user_id, db)
    rows = (
        db.scalars(
            select(GeneratedFile)
            .where(
                GeneratedFile.conversation_id == conversation_id,
                GeneratedFile.user_id == user_id,
            )
            .order_by(GeneratedFile.created_at.desc(), GeneratedFile.id.desc())
        ).all()
    )
    return {"files": [_serialize(row) for row in rows]}


@router.delete("/api/files/{file_id}")
async def delete_file(
    file_id: str,
    user_id: str = Query(min_length=1, max_length=128),
    db: Session = Depends(get_db),
    _auth: None = Depends(require_capability),
) -> dict:
    """Delete the object *and* the row -- hiding the row alone would leave the
    bytes in the bucket with nothing to audit them against."""
    row = _load_owned(file_id, user_id, db)
    try:
        await get_storage().delete(row.storage_path)
    except StorageError as exc:
        # Keep the row: with the object still present the user can retry, and
        # dropping the only pointer to it would orphan the bytes forever.
        logger.warning("Delete failed for %s: %s", row.id, exc)
        raise HTTPException(status_code=502, detail="The file could not be removed from storage.") from None
    db.delete(row)
    db.commit()
    return {"deleted": True, "id": file_id}
