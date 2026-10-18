"""Where generated files live, behind one bucket interface.

Two backends, chosen once per process from configuration:

* **Supabase Storage** -- used when ``SUPABASE_URL`` and
  ``SUPABASE_SERVICE_ROLE_KEY`` are both set. The bucket is private: it is
  addressed with the service-role key only, and the browser never sees a
  signed URL. The object key is ``<user>/<conversation>/<file><ext>``, so a
  bucket listing (if one ever happened) still cannot be mistaken for public
  content and every object is prefixed by the owner.
* **Local directory** -- the default, because Pentagon is local-first and
  Supabase is optional. Files land under ``settings.generated_file_directory``
  with the same key layout. The directory is *not* served by any route;
  bytes only leave it through ``GET /api/files/{id}/download``, which checks
  ownership first.

Neither backend is ever handed a path the model chose: keys are built from
validated ids in ``document_generation``, and :func:`_safe_key` refuses
anything that could climb out of the bucket.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# One path component: no separators, no traversal, bounded length. user ids
# are app-generated but the column accepts arbitrary strings, so anything
# outside this alphabet is folded to '_' rather than trusted.
_COMPONENT = re.compile(r"[^A-Za-z0-9._-]")
_MAX_KEY_BYTES = 512


class StorageError(Exception):
    """A storage backend refused or failed an operation."""


def build_key(user_id: str, conversation_id: str, file_id: str, extension: str) -> str:
    """Compose the object key. Every component is sanitised, never raw."""
    parts = [_COMPONENT.sub("_", part).strip(".") or "x" for part in (user_id, conversation_id, file_id)]
    ext = _COMPONENT.sub("", extension.lstrip("."))
    key = f"{parts[0]}/{parts[1]}/{parts[2]}.{ext}" if ext else "/".join(parts)
    if len(key) > _MAX_KEY_BYTES:
        raise StorageError("storage key is too long")
    return key


def _safe_key(key: str) -> str:
    """Refuse traversal before touching the filesystem or the bucket."""
    if not key or key.startswith("/") or "\\" in key:
        raise StorageError("invalid storage key")
    components = key.split("/")
    if any(component in {"", ".", ".."} for component in components):
        raise StorageError("invalid storage key")
    if len(key) > _MAX_KEY_BYTES:
        raise StorageError("storage key is too long")
    return key


class FileStorage:
    """put/get/delete over one private bucket."""

    async def put(self, key: str, data: bytes, content_type: str) -> str:
        raise NotImplementedError

    async def get(self, key: str) -> bytes:
        raise NotImplementedError

    async def delete(self, key: str) -> None:
        raise NotImplementedError


class LocalStorage(FileStorage):
    """A private directory on this machine. Never exposed as static files."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or settings.generated_file_directory)

    def _target(self, key: str) -> Path:
        safe = _safe_key(key)
        target = (self.root / safe).resolve()
        # Belt and braces: even with a sanitised key, confirm the resolved
        # path stays inside the bucket root (symlinks, odd usernames).
        root = self.root.resolve()
        if root != target and root not in target.parents:
            raise StorageError("storage key escapes the bucket")
        return target

    async def put(self, key: str, data: bytes, content_type: str) -> str:
        del content_type  # Local files carry no content type; the route sets it.
        target = self._target(key)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            # Write to a scratch name and rename: a crash mid-write must not
            # leave a truncated file that the download route would happily
            # serve as a finished document.
            scratch = target.with_name(f"{target.name}.{id(data)}.tmp")
            scratch.write_bytes(data)
            scratch.replace(target)
        except OSError as exc:
            raise StorageError(f"could not write the file ({exc.__class__.__name__})") from None
        return key

    async def get(self, key: str) -> bytes:
        target = self._target(key)
        try:
            return target.read_bytes()
        except FileNotFoundError:
            raise StorageError("file is missing from storage") from None
        except OSError as exc:
            raise StorageError(f"could not read the file ({exc.__class__.__name__})") from None

    async def delete(self, key: str) -> None:
        target = self._target(key)
        try:
            target.unlink(missing_ok=True)
        except OSError as exc:
            raise StorageError(f"could not delete the file ({exc.__class__.__name__})") from None
        # Prune now-empty per-conversation folders so a long-lived install
        # does not accumulate millions of empty directories.
        for parent in (target.parent, target.parent.parent):
            try:
                if parent != self.root.resolve() and parent.is_dir() and not any(parent.iterdir()):
                    parent.rmdir()
            except OSError:
                break


class SupabaseStorage(FileStorage):
    """The Supabase Storage REST API, with the service-role key.

    The bucket stays private: no public URL, no signed link, no anon key.
    ``httpx.AsyncClient`` is passed in so tests can drive it with a mock
    transport instead of a live project.
    """

    def __init__(
        self,
        url: str,
        service_role_key: str,
        bucket: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base = url.rstrip("/")
        self.key = service_role_key
        self.bucket = bucket
        self._client = client

    def _headers(self, content_type: str | None = None) -> dict[str, str]:
        headers = {"apikey": self.key, "Authorization": f"Bearer {self.key}"}
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _client_or_new(self) -> tuple[httpx.AsyncClient, bool]:
        if self._client is not None:
            return self._client, False
        return httpx.AsyncClient(timeout=30.0), True

    async def _ensure_bucket(self, client: httpx.AsyncClient) -> None:
        """Create the bucket on first use. Idempotent; failure is not fatal
        here -- the first put() surfaces the real error with its status."""
        try:
            await client.post(
                f"{self.base}/storage/v1/bucket",
                headers=self._headers("application/json"),
                json={"id": self.bucket, "name": self.bucket, "public": False},
            )
        except httpx.HTTPError:
            logger.warning("Could not ensure the generated-files bucket exists")

    async def put(self, key: str, data: bytes, content_type: str) -> str:
        safe = _safe_key(key)
        client, own = self._client_or_new()
        try:
            await self._ensure_bucket(client)
            response = await client.post(
                f"{self.base}/storage/v1/object/{self.bucket}/{safe}",
                headers=self._headers(content_type or "application/octet-stream"),
                content=data,
            )
            if response.status_code not in (200, 201):
                raise StorageError(f"upload failed (HTTP {response.status_code})")
        except httpx.HTTPError as exc:
            raise StorageError(f"upload failed ({exc.__class__.__name__})") from None
        finally:
            if own:
                await client.aclose()
        return key

    async def get(self, key: str) -> bytes:
        safe = _safe_key(key)
        client, own = self._client_or_new()
        try:
            response = await client.get(
                f"{self.base}/storage/v1/object/{self.bucket}/{safe}",
                headers=self._headers(),
            )
            if response.status_code == 404:
                raise StorageError("file is missing from storage")
            if response.status_code != 200:
                raise StorageError(f"download failed (HTTP {response.status_code})")
            return response.content
        except httpx.HTTPError as exc:
            raise StorageError(f"download failed ({exc.__class__.__name__})") from None
        finally:
            if own:
                await client.aclose()

    async def delete(self, key: str) -> None:
        safe = _safe_key(key)
        client, own = self._client_or_new()
        try:
            response = await client.delete(
                f"{self.base}/storage/v1/object/{self.bucket}/{safe}",
                headers=self._headers(),
            )
            # Deleting what is already gone is success: the caller's goal is
            # "no object and no row", and 404 means exactly that.
            if response.status_code not in (200, 204, 404):
                raise StorageError(f"delete failed (HTTP {response.status_code})")
        except httpx.HTTPError as exc:
            raise StorageError(f"delete failed ({exc.__class__.__name__})") from None
        finally:
            if own:
                await client.aclose()


_storage: FileStorage | None = None


def get_storage() -> FileStorage:
    """The configured backend, memoised for the life of the process."""
    global _storage
    if _storage is None:
        url = settings.supabase_url
        service_key = (
            settings.supabase_service_role_key.get_secret_value()
            if settings.supabase_service_role_key
            else None
        )
        if url and service_key:
            _storage = SupabaseStorage(url, service_key, settings.generated_file_bucket)
            logger.info("Generated files will be stored in Supabase Storage bucket '%s'", settings.generated_file_bucket)
        else:
            _storage = LocalStorage()
    return _storage


def reset_storage_for_tests() -> None:
    """Drop the memoised backend so the next call re-reads configuration."""
    global _storage
    _storage = None
