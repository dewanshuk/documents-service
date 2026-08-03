from fastapi import APIRouter
from fastapi.responses import JSONResponse
from .route_utils import log_and_json_response
from storage.storage_ops import generate_blob_sas_url, COMPLIANCE_CONTAINER

from core.openapi_tags import TAG_COMMON

router = APIRouter(tags=[TAG_COMMON])

# Generic shared endpoints for compliance resources.


@router.get("/querys/files")
async def download_file(path: str):
    """Generate a temporary SAS URL for a compliance file download."""
    try:
        if not path.startswith("/compliance/") or ".." in path:
            return log_and_json_response(
                None,
                {"path": path},
                "/query/file",
                "GET",
                400,
                {"error": "Invalid file path"},
            )

        blob_name = path.lstrip("/")
        url = await generate_blob_sas_url(
            container=COMPLIANCE_CONTAINER, blob_name=blob_name, expiry_minutes=15
        )
        return log_and_json_response(
            None,
            {"path": path},
            "/query/file",
            "GET",
            200,
            {"url": url},
        )
    except Exception as e:
        return log_and_json_response(
            None,
            {"path": path},
            "/query/file",
            "GET",
            500,
            {"error": "Error generating file URL", "details": str(e)},
        )
