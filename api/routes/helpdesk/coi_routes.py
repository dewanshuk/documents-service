from fastapi import UploadFile, File, Form, APIRouter, Depends
from typing import List
from uuid import uuid4
from datetime import datetime
from zoneinfo import ZoneInfo
from utils.deps import get_current_user
from db.db_manager import db_manager
from db.models.helpdesk import COIDeclarations
from storage.storage_ops import upload_files, init_json
from db.validators.comp_help import validate_coi_form
from .route_utils import log_and_json_response
import json

router = APIRouter()

# COI declaration endpoints for creating, updating, and submitting COI forms.

@router.post("/coi-draft")
async def create_coi(
    subType: str = Form(...),
    formData: str = Form(...),
    status: str = Form(...),
    user: dict = Depends(get_current_user),
):
    """Create a COI declaration in draft or in-progress state."""
    try:
        sid = f"COI-{uuid4()}"
        now = datetime.now(ZoneInfo("Asia/Kolkata"))
        parsed_data = json.loads(formData)

        if status == "In-Progress":
            validate_coi_form(subType, parsed_data)

        await db_manager.create(
            COIDeclarations,
            {
                "COIId": sid,
                "SubType": subType,
                "FormData": parsed_data,
                "Status": "Draft" if status == "Draft" else "In-Progress",
                "CreatedOn": now,
                "CreatedBy": user["staff_id"],
                "PendingAt": None if status == "Draft" else 1,
                "OverallStatus": None if status == "Draft" else "Pending",
                "ResponseJsonPath": None,
            },
        )

        return log_and_json_response(
            user["staff_id"],
            {"subType": subType, "status": status},
            "/coi-draft",
            "POST",
            201,
            {"id": sid, "status": status},
        )
    except Exception as e:
        return log_and_json_response(
            user.get("staff_id"),
            {"subType": subType, "status": status},
            "/coi-draft",
            "POST",
            500,
            {"error": "Error creating COI declaration", "details": str(e)},
        )


@router.put("/coi-draft/{id}")
async def update_coi(
    id: str,
    formData: str = Form(...),
    user: dict = Depends(get_current_user),
):
    """Update a COI draft form before submission."""
    try:
        record = await db_manager.get(COIDeclarations, id)
        if not record or record.Status != "Draft":
            return log_and_json_response(
                user["staff_id"],
                {"id": id},
                "/coi-draft/{id}",
                "PUT",
                400,
                {"error": "Only draft editable"},
            )

        if record.CreatedBy != user["staff_id"]:
            return log_and_json_response(
                user["staff_id"],
                {"id": id},
                "/coi-draft/{id}",
                "PUT",
                401,
                {"error": "Unauthorized"},
            )

        parsed_data = json.loads(formData)
        validate_coi_form(record.SubType, parsed_data)

        await db_manager.update(COIDeclarations, id, {"FormData": parsed_data})

        return log_and_json_response(
            user["staff_id"],
            {"id": id},
            "/coi-draft/{id}",
            "PUT",
            200,
            {"status": "COI Form Updated"},
        )
    except Exception as he:
        return log_and_json_response(
            user.get("staff_id"),
            {"id": id},
            "/coi-draft/{id}",
            "PUT",
            500,
            {"error": "Error updating COI declaration", "details": str(he)},
        )


@router.post("/coi/{id}/submit")
async def submit_coi(
    id: str,
    files: List[UploadFile] = File(default=[]),
    user: dict = Depends(get_current_user),
):
    """Submit a COI draft form for compliance review."""
    try:
        record = await db_manager.get(COIDeclarations, id)
        if not record or record.Status != "Draft":
            return log_and_json_response(
                user["staff_id"],
                {"id": id},
                "/coi/{id}/submit",
                "POST",
                400,
                {"error": "Invalid state"},
            )

        if record.CreatedBy != user["staff_id"]:
            return log_and_json_response(
                user["staff_id"],
                {"id": id},
                "/coi/{id}/submit",
                "POST",
                401,
                {"error": "Unauthorized"},
            )

        validate_coi_form(record.SubType, record.FormData)
        now = datetime.now(ZoneInfo("Asia/Kolkata"))
        file_paths = await upload_files(id, "user", files)
        json_data = {
            "id": id,
            "conversation": [
                {
                    "actor": "User",
                    "actorId": user["staff_id"],
                    "dateTime": now.isoformat(),
                    "data": {
                        "subType": record.SubType,
                        "formData": record.FormData,
                    },
                    "files": file_paths,
                }
            ],
        }

        json_path = await init_json(id, json_data)
        await db_manager.update(
            COIDeclarations,
            id,
            {
                "Status": "In-Progress",
                "PendingAt": 1,
                "OverallStatus": "Pending",
                "ResponseJsonPath": json_path,
            },
        )

        return log_and_json_response(
            user["staff_id"],
            {"id": id},
            "/coi/{id}/submit",
            "POST",
            200,
            {"status": f"COI Self-Declaration Submitted with id: {id}"},
        )
    except Exception as e:
        return log_and_json_response(
            user.get("staff_id"),
            {"id": id},
            "/coi/{id}/submit",
            "POST",
            500,
            {"error": "Error submitting COI declaration", "details": str(e)},
        )
