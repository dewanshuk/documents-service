"""Local filesystem storage (Azure Blob can be wired in later via env)."""

import asyncio
import json
import os
from io import BytesIO
from pathlib import Path
from typing import Optional

from fastapi import UploadFile

LOCAL_STORAGE_ROOT = Path(
    os.getenv("LOCAL_STORAGE_ROOT", Path(__file__).resolve().parent.parent / "local_storage")
).resolve()

COMPLIANCE_PREFIX = "/compliance"


def _blob_path(blob_name: str, container: str = "annual-declarations") -> Path:
    path = LOCAL_STORAGE_ROOT / container / blob_name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _compliance_path(record_id: str, *parts: str) -> Path:
    path = LOCAL_STORAGE_ROOT / "compliance" / record_id / Path(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _to_compliance_uri(relative_path: str) -> str:
    return f"{COMPLIANCE_PREFIX}/{relative_path}".replace("\\", "/")


async def upload_files(record_id: str, actor: str, files: list[UploadFile]) -> list[str]:
    file_paths: list[str] = []
    for upload in files:
        filename = Path(upload.filename or "file").name
        dest = _compliance_path(record_id, actor, filename)
        content = await upload.read()
        await asyncio.to_thread(dest.write_bytes, content)
        file_paths.append(_to_compliance_uri(f"{record_id}/{actor}/{filename}"))
    return file_paths


async def init_json(record_id: str, json_data: dict) -> str:
    dest = _compliance_path(record_id, "conversation.json")
    payload = json.dumps(json_data, indent=2, default=str)
    await asyncio.to_thread(dest.write_text, payload, encoding="utf-8")
    return _to_compliance_uri(f"{record_id}/conversation.json")


async def get_container_client(container: str = "annual-declarations") -> Path:
    container_dir = LOCAL_STORAGE_ROOT / "annual-declarations"
    await asyncio.to_thread(container_dir.mkdir, parents=True, exist_ok=True)
    return container_dir


async def upload_bytes(
    blob_name: str = "annual-declarations",
    data: bytes | str = None,
):
    path = _blob_path(blob_name)
    await asyncio.to_thread(path.write_bytes, data)
    return True
async def upload_stream(
    blob_name: str = "annual-declarations",
    stream: BytesIO = None,
    chunk_size: int = 4 * 1024 * 1024,
    content_type: Optional[str] = None,
    metadata: Optional[dict] = None,
):
    path = _blob_path(blob_name)
    chunks: list[bytes] = []
    while True:
        chunk = await stream.read(chunk_size)
        if not chunk:
            break
        chunks.append(chunk)
    await asyncio.to_thread(path.write_bytes, b"".join(chunks))
    return True


async def download_to_stream(
    blob_name: str = "annual-declarations",
    max_concurrency: int = 4,
):
    path = LOCAL_STORAGE_ROOT / "annual-declarations" / blob_name
    if not path.is_file():
        raise FileNotFoundError(f"Blob not found: {path}")
    data = await asyncio.to_thread(path.read_bytes)
    return BytesIO(data)


async def generate_blob_sas_url(
    blob_name: str = "annual-declarations",
    expiry_minutes: int = 15,
    permissions: str = "r",
    prefer_user_delegation: bool = True,
    container: str = "annual-declarations",
):
    path = LOCAL_STORAGE_ROOT / container / blob_name
    if not path.is_file():
        raise FileNotFoundError(f"Blob not found: {path}")
    return path.as_uri()


async def close_clients():
    pass
