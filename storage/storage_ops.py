"""Azure Blob Storage for compliance conversations and annual declaration files."""

import json
import os
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Optional

from azure.storage.blob import BlobSasPermissions, generate_blob_sas
from azure.storage.blob.aio import BlobServiceClient
from fastapi import UploadFile

COMPLIANCE_PREFIX = "/helpdesk"
COMPLIANCE_CONTAINER = os.getenv("AZURE_COMPLIANCE_CONTAINER", "ecp")
ANNUAL_CONTAINER = os.getenv("AZURE_ANNUAL_CONTAINER", "annual-declarations")
ANNUAL_DECLARATION_BLOB_NAME = os.getenv(
    "ANNUAL_DECLARATION_BLOB_NAME", "declaration_template.xlsx"
)

_blob_client: BlobServiceClient | None = None


def _parse_connection_string(conn_str: str) -> dict[str, str]:
    return {
        part.split("=", 1)[0]: part.split("=", 1)[1]
        for part in conn_str.split(";")
        if "=" in part
    }


async def _get_client() -> BlobServiceClient:
    global _blob_client
    if _blob_client is None:
        conn = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        if not conn:
            raise RuntimeError(
                "AZURE_STORAGE_CONNECTION_STRING is required for blob storage"
            )
        _blob_client = BlobServiceClient.from_connection_string(conn)
    return _blob_client


async def get_container_client(container: str = ANNUAL_CONTAINER):
    client = await _get_client()
    return client.get_container_client(container)


def _to_compliance_uri(relative_path: str) -> str:
    return f"{COMPLIANCE_PREFIX}/{relative_path}".replace("\\", "/")


def _uri_to_blob(json_uri: str) -> tuple[str, str]:
    """Map stored URI /helpdesk/... to container ecp + blob helpdesk/..."""
    if not json_uri.startswith(f"{COMPLIANCE_PREFIX}/"):
        raise ValueError(f"Invalid compliance URI: {json_uri}")
    return COMPLIANCE_CONTAINER, json_uri.lstrip("/")


MAX_ATTACHMENT_FILES = 6
MAX_COBCE_ROWS = 5


def normalize_stored_files(entries: Optional[list]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for entry in entries or []:
        if isinstance(entry, dict):
            path = str(entry.get("path") or "")
            filename = str(entry.get("filename") or Path(path).name)
        else:
            path = str(entry or "")
            filename = Path(path).name
        if path and filename:
            normalized.append({"path": path, "filename": filename})
    return normalized


def build_upload_pool(files: list[UploadFile]) -> dict[str, UploadFile]:
    """Map upload filename -> UploadFile. Rejects duplicate upload names."""
    pool: dict[str, UploadFile] = {}
    for upload in files:
        name = Path(upload.filename or "file").name
        if name in pool:
            raise ValueError(f"Duplicate filenames in upload: {name}")
        pool[name] = upload
    return pool


async def upload_files(
    record_id: str,
    actor: str,
    files: list[UploadFile],
    *,
    prefix: str | None = None,
) -> list[dict[str, str]]:
    container = await get_container_client(COMPLIANCE_CONTAINER)
    stored: list[dict[str, str]] = []
    for upload in files:
        filename = Path(upload.filename or "file").name
        if prefix:
            relative = f"{record_id}/{prefix}/{actor}/{filename}"
        else:
            relative = f"{record_id}/{actor}/{filename}"
        blob_name = f"helpdesk/{relative}"
        content = await upload.read()
        await container.get_blob_client(blob_name).upload_blob(
            content, overwrite=True
        )
        stored.append(
            {"path": _to_compliance_uri(relative), "filename": filename}
        )
    return stored


async def resolve_desired_files(
    record_id: str,
    existing_files: Optional[list],
    desired_names: Optional[list[str]],
    upload_pool: dict[str, UploadFile],
    *,
    actor: str = "user",
    prefix: str | None = None,
) -> list[dict[str, str]]:
    """
    desired_names None → leave existing unchanged (does not consume uploads).
    desired_names [] → remove all existing.
    desired_names [names] → final set; each name from existing or upload_pool
    (matched by filename). Consumes matched uploads from the pool.
    """
    existing = normalize_stored_files(existing_files)
    if desired_names is None:
        return existing

    if len(desired_names) != len(set(desired_names)):
        raise ValueError("Duplicate filenames in files list")
    if len(desired_names) > MAX_ATTACHMENT_FILES:
        raise ValueError(f"Max {MAX_ATTACHMENT_FILES} files allowed")

    existing_by_name = {item["filename"]: item for item in existing}
    to_upload: list[UploadFile] = []
    for name in desired_names:
        if name in existing_by_name and name in upload_pool:
            raise ValueError(f"Duplicate filename(s): {name}")
        if name in existing_by_name:
            continue
        if name not in upload_pool:
            raise ValueError(f"Unknown file: {name}")
        to_upload.append(upload_pool.pop(name))

    desired_set = set(desired_names)
    to_delete = [item for item in existing if item["filename"] not in desired_set]
    if to_delete:
        await delete_compliance_files(to_delete)

    uploaded = (
        await upload_files(record_id, actor, to_upload, prefix=prefix)
        if to_upload
        else []
    )
    uploaded_by_name = {item["filename"]: item for item in uploaded}

    result: list[dict[str, str]] = []
    for name in desired_names:
        if name in existing_by_name:
            result.append(existing_by_name[name])
        else:
            result.append(uploaded_by_name[name])
    return result


async def resolve_keep_upload_files(
    record_id: str,
    existing_files: Optional[list],
    files: list[UploadFile],
    keep_files: Optional[list[str]],
    *,
    actor: str = "user",
    prefix: str | None = None,
) -> list[dict[str, str]]:
    """
    Single-target resolve: keep_files is the desired final filename list.
    None → leave existing; [] → clear; [names] → existing and/or uploads by name.
    Unmapped uploads raise.
    """
    pool = build_upload_pool(files)
    resolved = await resolve_desired_files(
        record_id,
        existing_files,
        keep_files,
        pool,
        actor=actor,
        prefix=prefix,
    )
    if pool:
        raise ValueError(
            f"Unmapped uploaded file(s): {', '.join(sorted(pool))}"
        )
    return resolved


async def copy_compliance_files(
    file_entries: Optional[list],
    new_record_id: str,
    actor: str = "user",
) -> list[dict[str, str]]:
    """Copy stored compliance blobs under a new record id; return new entries."""
    source = normalize_stored_files(file_entries)
    if not source:
        return []

    container = await get_container_client(COMPLIANCE_CONTAINER)
    copied: list[dict[str, str]] = []
    for item in source:
        src_blob = item["path"].lstrip("/")
        filename = item["filename"]
        relative = f"{new_record_id}/{actor}/{filename}"
        dest_blob = f"helpdesk/{relative}"
        src_client = container.get_blob_client(src_blob)
        if not await src_client.exists():
            continue
        downloader = await src_client.download_blob()
        content = await downloader.readall()
        await container.get_blob_client(dest_blob).upload_blob(
            content, overwrite=True
        )
        copied.append(
            {"path": _to_compliance_uri(relative), "filename": filename}
        )
    return copied


async def init_json(record_id: str, json_data: dict) -> str:
    relative = f"{record_id}/conversation.json"
    blob_name = f"helpdesk/{relative}"
    payload = json.dumps(json_data, indent=2, default=str).encode("utf-8")
    container = await get_container_client(COMPLIANCE_CONTAINER)
    await container.get_blob_client(blob_name).upload_blob(
        payload, overwrite=True, content_type="application/json"
    )
    return _to_compliance_uri(relative)


async def load_json(json_uri: str) -> dict:
    container_name, blob_name = _uri_to_blob(json_uri)
    container = await get_container_client(container_name)
    downloader = await container.get_blob_client(blob_name).download_blob()
    data = await downloader.readall()
    return json.loads(data.decode("utf-8"))


async def read_json(json_uri: str) -> dict:
    return await load_json(json_uri)


async def save_json(json_uri: str, json_data: dict) -> None:
    container_name, blob_name = _uri_to_blob(json_uri)
    payload = json.dumps(json_data, indent=2, default=str).encode("utf-8")
    container = await get_container_client(container_name)
    await container.get_blob_client(blob_name).upload_blob(
        payload, overwrite=True, content_type="application/json"
    )


async def append_json(json_uri: str, entry: dict) -> None:
    data = await load_json(json_uri)
    data.setdefault("conversation", []).append(entry)
    await save_json(json_uri, data)


async def upload_bytes(
    blob_name: str,
    data: bytes | str,
    container: str = ANNUAL_CONTAINER,
):
    if isinstance(data, str):
        data = data.encode("utf-8")
    blob_container = await get_container_client(container)
    await blob_container.get_blob_client(blob_name).upload_blob(
        data, overwrite=True
    )
    return True


async def upload_stream(
    blob_name: str,
    stream: BytesIO,
    chunk_size: int = 4 * 1024 * 1024,
    content_type: Optional[str] = None,
    metadata: Optional[dict] = None,
    container: str = ANNUAL_CONTAINER,
):
    chunks: list[bytes] = []
    while True:
        chunk = await stream.read(chunk_size)
        if not chunk:
            break
        chunks.append(chunk)
    blob_container = await get_container_client(container)
    await blob_container.get_blob_client(blob_name).upload_blob(
        b"".join(chunks),
        overwrite=True,
        content_type=content_type,
        metadata=metadata,
    )
    return True


async def download_to_stream(
    blob_name: str,
    max_concurrency: int = 4,
    container: str = ANNUAL_CONTAINER,
):
    blob_container = await get_container_client(container)
    blob_client = blob_container.get_blob_client(blob_name)
    if not await blob_client.exists():
        raise FileNotFoundError(f"Blob not found: {container}/{blob_name}")
    downloader = await blob_client.download_blob(max_concurrency=max_concurrency)
    data = await downloader.readall()
    stream = BytesIO(data)
    stream.seek(0)
    return stream


async def generate_blob_sas_url(
    blob_name: str,
    expiry_minutes: int = 15,
    permissions: str = "r",
    prefer_user_delegation: bool = True,
    container: str = ANNUAL_CONTAINER,
):
    conn = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if not conn:
        raise RuntimeError(
            "AZURE_STORAGE_CONNECTION_STRING is required to generate SAS URLs"
        )

    parts = _parse_connection_string(conn)
    account_name = parts.get("AccountName")
    account_key = parts.get("AccountKey")
    if not account_name or not account_key:
        raise RuntimeError("Invalid AZURE_STORAGE_CONNECTION_STRING")

    blob_container = await get_container_client(container)
    blob_client = blob_container.get_blob_client(blob_name)
    if not await blob_client.exists():
        raise FileNotFoundError(f"Blob not found: {container}/{blob_name}")

    perm = BlobSasPermissions(read=True)
    if "w" in permissions:
        perm.write = True

    sas_token = generate_blob_sas(
        account_name=account_name,
        container_name=container,
        blob_name=blob_name,
        account_key=account_key,
        permission=perm,
        expiry=datetime.now(timezone.utc) + timedelta(minutes=expiry_minutes),
    )
    return f"https://{account_name}.blob.core.windows.net/{container}/{blob_name}?{sas_token}"


async def delete_compliance_files(file_entries: Optional[list]) -> None:
    """Delete compliance blobs by stored path. Missing blobs are ignored."""
    if not file_entries:
        return
    container = await get_container_client(COMPLIANCE_CONTAINER)
    for entry in file_entries:
        if isinstance(entry, dict):
            path = entry.get("path") or ""
        else:
            path = str(entry or "")
        if not path:
            continue
        blob_name = path.lstrip("/")
        try:
            await container.get_blob_client(blob_name).delete_blob()
        except Exception:
            # Blob may already be gone; metadata removal still proceeds.
            pass


async def resolve_file_urls(
    file_entries: Optional[list],
) -> list[dict[str, str]]:
    """Convert stored compliance files into SAS URLs with filenames.

    Accepts legacy string paths or ``{"path", "filename"}`` objects.
    Legacy entries get ``filename: ""``.
    """
    resolved: list[dict[str, str]] = []
    for entry in file_entries or []:
        if isinstance(entry, dict):
            path = entry.get("path") or ""
            filename = entry.get("filename") or ""
        else:
            path = str(entry or "")
            filename = ""

        blob_name = path.lstrip("/")
        try:
            url = await generate_blob_sas_url(
                container=COMPLIANCE_CONTAINER,
                blob_name=blob_name,
                expiry_minutes=15,
            )
        except FileNotFoundError:
            url = path
        resolved.append({"url": url, "filename": filename})
    return resolved


async def close_clients():
    global _blob_client
    if _blob_client is not None:
        await _blob_client.close()
        _blob_client = None
