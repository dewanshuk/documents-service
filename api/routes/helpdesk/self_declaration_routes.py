import asyncio
import json
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile

from services.self_declaration_service import (
    get_self_declaration_by_id,
    save_self_declaration,
)
from utils.deps import get_current_user
from utils.authorize import is_lead_for_type
from utils.email_notifications import notify_record_created
from .self_declaration_config import SELF_DECLARATION_FORM_CONFIG
from .route_utils import log_and_json_response

from core.openapi_tags import TAG_SELF_DECLARATION

router = APIRouter(tags=[TAG_SELF_DECLARATION])


@router.get("/self-declaration/form-config")
async def get_self_declaration_form_config():
    """COBCE row schema + COI 6 questions (user picks one per submission)."""
    return log_and_json_response(
        None,
        {},
        "/self-declaration/form-config",
        "GET",
        200,
        SELF_DECLARATION_FORM_CONFIG,
    )


@router.get("/self-declaration/{record_id}")
async def get_self_declaration_endpoint(
    record_id: str,
    user: dict = Depends(get_current_user),
):
    """Get COBCE / COI self-declaration by id (draft or submitted)."""
    staff_id = user["staff_id"]
    is_admin = is_lead_for_type(user, "cobce")
    try:
        data = await get_self_declaration_by_id(record_id, staff_id, is_admin)
        return log_and_json_response(
            staff_id,
            {"record_id": record_id},
            "/self-declaration/{record_id}",
            "GET",
            200,
            data,
        )
    except ValueError as e:
        message = str(e)
        status = 403 if message == "Unauthorized" else 404
        if message == "Not a self-declaration record":
            status = 400
        return log_and_json_response(
            staff_id,
            {"record_id": record_id},
            "/self-declaration/{record_id}",
            "GET",
            status,
            {"error": message},
        )
    except Exception as e:
        return log_and_json_response(
            staff_id,
            {"record_id": record_id},
            "/self-declaration/{record_id}",
            "GET",
            500,
            {"error": "Error fetching self-declaration", "details": str(e)},
        )


@router.post("/self-declaration")
async def save_self_declaration_endpoint(
    declaration_type: str = Form(..., description="cobce or coi"),
    status: str = Form(..., description="draft or submit"),
    subType: str = Form(...),
    id: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    rows: Optional[str] = Form(
        None,
        description=(
            "COBCE only: JSON array of "
            "{nature_of_violation, person_responsible, files}. "
            "files: null | [] | [filenames]; max 5 rows, 6 files per row. "
            "Upload filenames must appear in a row's files list."
        ),
    ),
    formData: Optional[str] = Form(
        None,
        description=(
            "COI only: JSON object of form fields. "
            'Optional files: null (keep existing) | [] (clear) | '
            '["evidence.xlsx"] or GET-style [{filename, ...}]. '
            "New uploads must be attached and listed by filename."
        ),
    ),
    files: List[UploadFile] = File(default=[]),
    user: dict = Depends(get_current_user),
):
    """
    Unified save for self-declarations (COBCE or COI).
    Omit id to create; pass id to update an existing draft.
    Multipart files are matched by filename to row.files (COBCE)
    or formData.files (COI).
    """
    staff_id = user["staff_id"]
    record_id = id.strip() if id and id.strip() else None
    try:
        parsed_form = json.loads(formData) if formData else None
        parsed_rows = json.loads(rows) if rows else None
    except json.JSONDecodeError as e:
        return log_and_json_response(
            staff_id,
            {"declaration_type": declaration_type, "status": status, "id": record_id},
            "/self-declaration",
            "POST",
            400,
            {"error": f"Invalid JSON: {e}"},
        )

    upload_files_list = [f for f in files if f.filename]

    try:
        result = await save_self_declaration(
            staff_id=staff_id,
            declaration_type=declaration_type,
            status=status,
            sub_type=subType,
            record_id=record_id,
            description=description,
            form_data=parsed_form,
            files=upload_files_list,
            rows=parsed_rows,
        )
        http_status = 201 if not record_id and status == "draft" else 200
        message = (
            "Declaration submitted successfully"
            if status == "submit"
            else "Draft saved successfully"
        )

        if status == "submit" and result.get("id"):
            record_type = declaration_type.lower()
            asyncio.create_task(notify_record_created(
                record_type, result["id"], staff_id, title=subType,
            ))

        return log_and_json_response(
            staff_id,
            {
                "declaration_type": declaration_type,
                "status": status,
                "id": record_id,
                "subType": subType,
            },
            "/self-declaration",
            "POST",
            http_status,
            {"message": message, **result},
        )
    except ValueError as e:
        return log_and_json_response(
            staff_id,
            {"declaration_type": declaration_type, "status": status, "id": record_id},
            "/self-declaration",
            "POST",
            400,
            {"error": str(e)},
        )
    except Exception as e:
        return log_and_json_response(
            staff_id,
            {"declaration_type": declaration_type, "status": status, "id": record_id},
            "/self-declaration",
            "POST",
            500,
            {"error": "Error saving self-declaration", "details": str(e)},
        )
