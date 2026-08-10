import asyncio

from fastapi import UploadFile, File, Form, APIRouter, Depends
from typing import List

from utils.deps import get_current_user
from utils.helpers import now_ist, db_timestamp_now
from utils.record_ids import next_self_decl_id
from utils.actor_display import format_actor_name
from utils.email_notifications import notify_record_created
from db.db_manager import db_manager
from db.models.helpdesk import COBCEDeclarations
from storage.storage_ops import upload_files, init_json
from .route_utils import log_and_json_response

router = APIRouter()

# COBCE declaration endpoints for draft creation, update, and submission.


@router.post("/cobce-draft")
async def create_cobce(
    subType: str = Form(...),
    description: str = Form(...),
    user: dict = Depends(get_current_user),
):
    """Create a COBCE declaration in draft state."""
    try:
        staff_id = user["staff_id"]
        record_id = await next_self_decl_id(staff_id)
        now = now_ist()
        created_on = db_timestamp_now()
        person_details = {"name": staff_id}

        await db_manager.create(
            COBCEDeclarations,
            {
                "COBCEId": record_id,
                "SubType": subType,
                "Description": description,
                "PersonDetails": person_details,
                "Status": "Draft",
                "CreatedOn": created_on,
                "CreatedBy": staff_id,
                "OverallStatus": "Draft",
                "PendingAt": 0,
                "ResponseJsonPath": None,
            },
        )

        return log_and_json_response(
            staff_id,
            {"subType": subType, "description": description},
            "/cobce-draft",
            "POST",
            201,
            {
                "id": record_id,
                "status": "Draft",
            },
        )
    except Exception as e:
        return log_and_json_response(
            user.get("staff_id"),
            {"subType": subType, "description": description},
            "/cobce-draft",
            "POST",
            500,
            {"error": "Error creating COBCE declaration", "details": str(e)},
        )


@router.put("/cobce/{id}")
async def update_cobce(
    id: str,
    description: str = Form(...),
    subType: str = Form(...),
    user: dict = Depends(get_current_user),
):
    """Update a COBCE draft entry prior to submission."""
    try:
        record = await db_manager.get(COBCEDeclarations, id)
        if not record or record.Status != "Draft":
            return log_and_json_response(
                user["staff_id"],
                {"id": id, "description": description, "subType": subType},
                "/cobce/{id}",
                "PUT",
                400,
                {"error": "Only draft editable"},
            )

        if record.CreatedBy != user["staff_id"]:
            return log_and_json_response(
                user["staff_id"],
                {"id": id},
                "/cobce/{id}",
                "PUT",
                401,
                {"error": "Unauthorized"},
            )

        await db_manager.update(
            COBCEDeclarations,
            id,
            {
                "Description": description,
                "SubType": subType,
                "OverallStatus": "Draft",
                "PendingAt": 0,
            },
        )

        return log_and_json_response(
            user["staff_id"],
            {"id": id},
            "/cobce/{id}",
            "PUT",
            200,
            {"status": "Updated"},
        )
    except Exception as e:
        return log_and_json_response(
            user.get("staff_id"),
            {"id": id, "description": description, "subType": subType},
            "/cobce/{id}",
            "PUT",
            500,
            {"error": "Error updating COBCE declaration", "details": str(e)},
        )


@router.post("/cobce/{id}/submit")
async def submit_cobce(
    id: str,
    files: List[UploadFile] = File(default=[]),
    user: dict = Depends(get_current_user),
):
    """Submit a COBCE draft declaration for compliance review."""
    try:
        record = await db_manager.get(COBCEDeclarations, id)
        if not record or record.Status != "Draft":
            return log_and_json_response(
                user["staff_id"],
                {"id": id},
                "/cobce/{id}/submit",
                "POST",
                400,
                {"error": "Invalid state"},
            )

        if record.CreatedBy != user["staff_id"]:
            return log_and_json_response(
                user["staff_id"],
                {"id": id},
                "/cobce/{id}/submit",
                "POST",
                401,
                {"error": "Unauthorized"},
            )

        now = now_ist()
        file_paths = await upload_files(id, "user", files)
        json_data = {
            "id": id,
            "conversation": [
                {
                    "actor": "User",
                    "actorId": user["staff_id"],
                    "actor_name": await format_actor_name(user["staff_id"]),
                    "dateTime": now.isoformat(),
                    "data": {
                        "subType": record.SubType,
                        "description": record.Description,
                        "personDetails": record.PersonDetails,
                    },
                    "files": file_paths,
                }
            ],
        }

        json_path = await init_json(id, json_data)
        await db_manager.update(
            COBCEDeclarations,
            id,
            {
                "Status": "Completed",
                "PendingAt": None,
                "OverallStatus": "Completed",
                "ResponseJsonPath": json_path,
            },
        )

        asyncio.create_task(notify_record_created(
            "cobce", id, user["staff_id"], title=record.SubType,
        ))

        return log_and_json_response(
            user["staff_id"],
            {"id": id},
            "/cobce/{id}/submit",
            "POST",
            200,
            {"status": f"COBCE Declaration Submitted with id: {id}"},
        )
    except Exception as e:
        return log_and_json_response(
            user.get("staff_id"),
            {"id": id},
            "/cobce/{id}/submit",
            "POST",
            500,
            {"error": "Error submitting COBCE declaration", "details": str(e)},
        )
