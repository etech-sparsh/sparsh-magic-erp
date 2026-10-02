"""Storage abstraction for assistant attachments.

Two interchangeable backends selected by configuration:

  * LocalStorage — writes under settings.LOCAL_STORAGE_DIR (development).
  * S3Storage    — delegates to the existing app.services.s3_service (production).

Both expose the same async interface. A stored file is referenced by an opaque
``ref`` string (a relative path for local, an S3 key for S3); the provider is
persisted alongside it so URLs can be regenerated on demand (S3 signed URLs
expire). Blocking boto3 / disk calls are pushed to a thread executor so the
event loop never stalls — mirroring app/routes/media.py.
"""
from __future__ import annotations

import asyncio
import functools
import os
import uuid
from typing import Optional

from app.assistant.config import config
from app.config.settings import settings


def _provider_name() -> str:
    """Resolve the active provider: env override wins, else AssistantConfig."""
    return (settings.ATTACHMENT_STORAGE_PROVIDER or config.STORAGE_PROVIDER or "s3").lower()


def _make_key(filename: str) -> str:
    """UUID-prefixed object key, matching the s3_service naming convention."""
    safe = os.path.basename(filename or "file")
    return f"assistant/{uuid.uuid4()}_{safe}"


class StorageBackend:
    """Common async interface. ``ref`` is the persisted, provider-specific id."""

    provider = "base"

    async def save(self, local_path: str, filename: str, content_type: str) -> str:
        raise NotImplementedError

    async def signed_url(self, ref: str, expires_in: int = 3600) -> str:
        raise NotImplementedError

    async def download(self, ref: str, local_path: str) -> bool:
        raise NotImplementedError

    async def delete(self, ref: str) -> bool:
        raise NotImplementedError


class LocalStorage(StorageBackend):
    """Filesystem backend for development. Files live under LOCAL_STORAGE_DIR;
    they are served back through the assistant download route, not a public URL."""

    provider = "local"

    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = os.path.abspath(base_dir or settings.LOCAL_STORAGE_DIR)
        os.makedirs(self.base_dir, exist_ok=True)

    def _abs(self, ref: str) -> str:
        # Guard against path traversal: the resolved path must stay under base_dir.
        target = os.path.abspath(os.path.join(self.base_dir, ref))
        if os.path.commonpath([self.base_dir, target]) != self.base_dir:
            raise ValueError("Invalid storage reference")
        return target

    async def save(self, local_path: str, filename: str, content_type: str) -> str:
        ref = _make_key(filename)
        dest = self._abs(ref)
        os.makedirs(os.path.dirname(dest), exist_ok=True)

        def _copy():
            with open(local_path, "rb") as src, open(dest, "wb") as out:
                while chunk := src.read(1024 * 1024):
                    out.write(chunk)

        await asyncio.get_event_loop().run_in_executor(None, _copy)
        return ref

    async def signed_url(self, ref: str, expires_in: int = 3600) -> str:
        # Served (auth-checked) by GET /assistant/files/local/{ref}. The assistant
        # router is mounted under /api (see backend/main.py), so include that
        # prefix; the frontend resolves it against window.location.origin.
        return f"/api/assistant/files/local/{ref}"

    async def download(self, ref: str, local_path: str) -> bool:
        src = self._abs(ref)
        if not os.path.exists(src):
            return False

        def _copy():
            with open(src, "rb") as s, open(local_path, "wb") as d:
                while chunk := s.read(1024 * 1024):
                    d.write(chunk)

        await asyncio.get_event_loop().run_in_executor(None, _copy)
        return True

    async def delete(self, ref: str) -> bool:
        try:
            target = self._abs(ref)
        except ValueError:
            return False
        if os.path.exists(target):
            await asyncio.get_event_loop().run_in_executor(None, os.remove, target)
        return True

    def local_path(self, ref: str) -> Optional[str]:
        """Absolute on-disk path for the download route (None if missing)."""
        try:
            target = self._abs(ref)
        except ValueError:
            return None
        return target if os.path.exists(target) else None


class S3Storage(StorageBackend):
    """Production backend reusing the existing S3 service (boto3 is blocking, so
    calls run in a thread executor)."""

    provider = "s3"

    async def save(self, local_path: str, filename: str, content_type: str) -> str:
        from app.services.s3_service import get_s3_client

        ref = _make_key(filename)
        loop = asyncio.get_event_loop()

        def _upload():
            client = get_s3_client()
            with open(local_path, "rb") as f:
                client.upload_fileobj(
                    f,
                    settings.S3_BUCKET_NAME,
                    ref,
                    ExtraArgs={"ContentType": content_type or "application/octet-stream"},
                )

        await loop.run_in_executor(None, _upload)
        return ref

    async def signed_url(self, ref: str, expires_in: int = 3600) -> str:
        from app.services.s3_service import get_signed_url

        return await asyncio.get_event_loop().run_in_executor(
            None, functools.partial(get_signed_url, ref, expires_in)
        )

    async def download(self, ref: str, local_path: str) -> bool:
        from app.services.s3_service import download_file_from_s3

        return await asyncio.get_event_loop().run_in_executor(
            None, functools.partial(download_file_from_s3, ref, local_path)
        )

    async def delete(self, ref: str) -> bool:
        from app.services.s3_service import delete_file_from_s3

        return await asyncio.get_event_loop().run_in_executor(
            None, functools.partial(delete_file_from_s3, ref)
        )


def get_storage() -> StorageBackend:
    """Factory: return the configured storage backend instance."""
    if _provider_name() == "local":
        return LocalStorage()
    return S3Storage()
