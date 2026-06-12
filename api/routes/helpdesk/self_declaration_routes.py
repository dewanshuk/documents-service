import json
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile

from services.self_declaration_service import save_self_declaration
from utils.deps import get_current_user
from .self_declaration_config import SELF_DECLARATION_FORM_CONFIG
from .route_utils import log_and_json_response

router = APIRouter()


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


@router.post("/self-declaration")
async def save_self_declaration_endpoint(
    declaration_type: str = Form(..., description="cobce or coi"),
    status: str = Form(..., description="draft or submit"),
    subType: str = Form(...),
    id: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    rows: Optional[str] = Form(
        None,
        description="COBCE only: JSON array of {nature_of_violation, person_responsible}",
    ),
    formData: Optional[str] = Form(None),
    files: List[UploadFile] = File(default=[]),
    user: dict = Depends(get_current_user),
):
    """
    Unified save for self-declarations (COBCE or COI).
    Omit id to create; pass id to update an existing draft.
    """
    staff_id = user["staff_id"]
    parsed_form = json.loads(formData) if formData else None
    parsed_rows = json.loads(rows) if rows else None

    try:
        result = await save_self_declaration(
            staff_id=staff_id,
            declaration_type=declaration_type,
            status=status,
            sub_type=subType,
            record_id=id,
            description=description,
            form_data=parsed_form,
            files=files,
            rows=parsed_rows,
        )
        http_status = 201 if not id and status == "draft" else 200
        message = (
            "Declaration submitted successfully"
            if status == "submit"
            else "Draft saved successfully"
        )
        return log_and_json_response(
            staff_id,
            {
                "declaration_type": declaration_type,
                "status": status,
                "id": id,
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
            {"declaration_type": declaration_type, "status": status, "id": id},
            "/self-declaration",
            "POST",
            400,
            {"error": str(e)},
        )
    except Exception as e:
        return log_and_json_response(
            staff_id,
            {"declaration_type": declaration_type, "status": status, "id": id},
            "/self-declaration",
            "POST",
            500,
            {"error": "Error saving self-declaration", "details": str(e)},
        )
