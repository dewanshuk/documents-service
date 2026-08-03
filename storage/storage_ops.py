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

COMPLIANCE_PREFIX = "/compliance"
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
    """Map stored URI /compliance/... to container ecp + blob compliance/..."""
    if not json_uri.startswith(f"{COMPLIANCE_PREFIX}/"):
        raise ValueError(f"Invalid compliance URI: {json_uri}")
    return COMPLIANCE_CONTAINER, json_uri.lstrip("/")


async def upload_files(record_id: str, actor: str, files: list[UploadFile]) -> list[str]:
    container = await get_container_client(COMPLIANCE_CONTAINER)
    file_paths: list[str] = []
    for upload in files:
        filename = Path(upload.filename or "file").name
        relative = f"{record_id}/{actor}/{filename}"
        blob_name = f"compliance/{relative}"
        content = await upload.read()
        await container.get_blob_client(blob_name).upload_blob(
            content, overwrite=True
        )
        file_paths.append(_to_compliance_uri(relative))
    return file_paths


async def init_json(record_id: str, json_data: dict) -> str:
    relative = f"{record_id}/conversation.json"
    blob_name = f"compliance/{relative}"
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


async def resolve_file_urls(file_paths: Optional[list[str]]) -> list[str]:
    """Convert stored compliance file paths into temporary SAS download URLs."""
    urls: list[str] = []
    for path in file_paths or []:
        blob_name = path.lstrip("/")
        try:
            url = await generate_blob_sas_url(
                container=COMPLIANCE_CONTAINER,
                blob_name=blob_name,
                expiry_minutes=15,
            )
        except FileNotFoundError:
            url = path
        urls.append(url)
    return urls


async def close_clients():
    global _blob_client
    if _blob_client is not None:
        await _blob_client.close()
        _blob_client = None
