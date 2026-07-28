import json
import asyncio
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, UploadFile, File, Form
from fastapi.responses import JSONResponse

from utils.deps import get_current_user
from utils.record_ids import resolve_record
from utils.authorize import is_active_cobce_coi_gift_lead, is_active_complaint_lead, is_active_query_lead
from utils.email_notifications import notify_record_responded, notify_record_closed
from db.db_manager import db_manager
from storage.storage_ops import upload_files, LOCAL_STORAGE_ROOT
from .route_utils import log_and_json_response
from utils.helpers import now_ist, db_timestamp_now
from core.openapi_tags import TAG_COMMON

router = APIRouter(tags=[TAG_COMMON])

ADMIN_ROLE_CHECKERS = {
    "query": is_active_query_lead,
    "gift": is_active_cobce_coi_gift_lead,
    "complaint": is_active_complaint_lead,
    "cobce": is_active_cobce_coi_gift_lead,
    "coi": is_active_cobce_coi_gift_lead,
    "r518": is_active_cobce_coi_gift_lead,
}

CREATED_BY_FIELD = {
    "query": "CreatedBy",
    "gift": "CreatedBy",
    "complaint": "CreatedBy",
    "cobce": "CreatedBy",
    "coi": "CreatedBy",
    "r518": "CreatedBy",
}


def _json_path_on_disk(json_uri: str) -> Path:
    relative = json_uri.replace("/compliance/", "", 1)
    return LOCAL_STORAGE_ROOT / "compliance" / relative


async def _load_conversation(json_uri: str) -> dict:
    path = _json_path_on_disk(json_uri)
    data = await asyncio.to_thread(path.read_text, encoding="utf-8")
    return json.loads(data)


async def _save_conversation(json_uri: str, data: dict) -> None:
    path = _json_path_on_disk(json_uri)
    payload = json.dumps(data, indent=2, default=str)
    await asyncio.to_thread(path.write_text, payload, encoding="utf-8")


@router.get("/conversation/{record_id}")
async def get_conversation(
    record_id: str,
    user: dict = Depends(get_current_user),
):
    """Retrieve the full conversation thread for a compliance record."""
    try:
        try:
            model, record_type, db_id = await resolve_record(record_id)
        except ValueError:
            return log_and_json_response(
                user["staff_id"], {"record_id": record_id},
                "/conversation/{record_id}", "GET", 400,
                {"error": "Invalid record ID format"},
            )

        record = await db_manager.get(model, db_id)
        if not record:
            return log_and_json_response(
                user["staff_id"], {"record_id": record_id},
                "/conversation/{record_id}", "GET", 404,
                {"error": "Record not found"},
            )

        staff_id = user["staff_id"]
        created_by = getattr(record, CREATED_BY_FIELD[record_type])
        is_owner = created_by == staff_id

        checker = ADMIN_ROLE_CHECKERS.get(record_type)
        is_admin = await checker(staff_id) if checker else False

        if not is_owner and not is_admin:
            return log_and_json_response(
                staff_id, {"record_id": record_id},
                "/conversation/{record_id}", "GET", 403,
                {"error": "Not authorized to view this conversation"},
            )

        if hasattr(record, "QueryId"):
            record_id_val = record.QueryId
        elif hasattr(record, "GiftId"):
            record_id_val = record.GiftId
        elif hasattr(record, "ComplaintId"):
            record_id_val = record.ComplaintId
        elif hasattr(record, "COBCEId"):
            record_id_val = record.COBCEId
        elif hasattr(record, "COIId"):
            record_id_val = record.COIId
        elif hasattr(record, "R518Id"):
            record_id_val = record.R518Id
        else:
            record_id_val = db_id

        if getattr(record, "Status", None) == "Draft":
            pending_at_display = "-"
        elif getattr(record, "OverallStatus", None) != "Closed":
            pending_at = getattr(record, "PendingAt", None)
            if pending_at == 1:
                pending_at_display = "Compliance Team"
            elif pending_at == 0:
                pending_at_display = created_by
            else:
                pending_at_display = "-"
        else:
            pending_at_display = "-"

        details = {
            "id": record_id_val,
            "status": getattr(record, "OverallStatus", None),
            "pendingAt": pending_at_display,
            "createdBy": created_by,
            "createdOn": str(getattr(record, "CreatedOn", "")) if getattr(record, "CreatedOn", None) else None,
            "closureDate": str(getattr(record, "ClosureDate", "")) if getattr(record, "ClosureDate", None) else None,
            "closedBy": getattr(record, "ClosedBy", None),
            "workflowStatus": getattr(record, "Status", None),
        }

        json_path = getattr(record, "ResponseJsonPath", None)
        if not json_path:
            return JSONResponse(
                content={"id": record_id_val, "details": details, "conversation": []},
                status_code=200,
            )

        conv = await _load_conversation(json_path)
        conv["details"] = details
        return JSONResponse(content=conv, status_code=200)
    except Exception as e:
        return log_and_json_response(
            user.get("staff_id"), {"record_id": record_id},
            "/conversation/{record_id}", "GET", 500,
            {"error": "Error loading conversation", "details": str(e)},
        )


@router.post("/respond/{record_id}")
async def respond_to_record(
    record_id: str,
    message: str = Form(...),
    files: List[UploadFile] = File(default=[]),
    user: dict = Depends(get_current_user),
):
    """Append a chat message (with optional files) to any compliance record."""
    try:
        try:
            model, record_type, db_id = await resolve_record(record_id)
        except ValueError:
            return log_and_json_response(
                user["staff_id"], {"record_id": record_id},
                "/respond/{record_id}", "POST", 400,
                {"error": "Invalid record ID format"},
            )

        record = await db_manager.get(model, db_id)
        if not record:
            return log_and_json_response(
                user["staff_id"], {"record_id": record_id},
                "/respond/{record_id}", "POST", 404,
                {"error": "Record not found"},
            )

        staff_id = user["staff_id"]
        created_by = getattr(record, CREATED_BY_FIELD[record_type])
        is_owner = created_by == staff_id

        checker = ADMIN_ROLE_CHECKERS.get(record_type)
        is_admin = await checker(staff_id) if checker else False

        if not is_owner and not is_admin:
            return log_and_json_response(
                staff_id, {"record_id": record_id},
                "/respond/{record_id}", "POST", 403,
                {"error": "Not authorized to respond to this record"},
            )

        json_path = getattr(record, "ResponseJsonPath", None)
        if not json_path:
            return log_and_json_response(
                staff_id, {"record_id": record_id},
                "/respond/{record_id}", "POST", 400,
                {"error": "Record has no conversation (not yet submitted)"},
            )

        if len(files) > 6:
            return log_and_json_response(
                staff_id, {"record_id": record_id},
                "/respond/{record_id}", "POST", 400,
                {"error": "Max 6 files allowed"},
            )

        now = now_ist()
        actor = "Admin" if is_admin and not is_owner else "User"
        file_paths = await upload_files(db_id, actor.lower(), files)

        conv = await _load_conversation(json_path)
        conv["conversation"].append({
            "actor": actor,
            "actorId": staff_id,
            "dateTime": now.isoformat(),
            "message": message,
            "files": file_paths,
        })
        await _save_conversation(json_path, conv)

        current_pending = getattr(record, "PendingAt", None)
        new_pending = current_pending
        if is_admin and not is_owner:
            new_pending = 0
        elif is_owner:
            new_pending = 1

        await db_manager.update(model, db_id, {
            "PendingAt": new_pending,
            "LastUpdatedOn": db_timestamp_now(),
        })

        title = getattr(record, "Title", getattr(record, "ComplaintType", getattr(record, "SubType", "")))
        asyncio.create_task(notify_record_responded(
            record_type, db_id, staff_id, created_by,
            title=title,
            response_text=message,
        ))

        return log_and_json_response(
            staff_id, {"record_id": record_id},
            "/respond/{record_id}", "POST", 200,
            {"status": "Response added", "record_id": db_id},
        )
    except Exception as e:
        return log_and_json_response(
            user.get("staff_id"), {"record_id": record_id},
            "/respond/{record_id}", "POST", 500,
            {"error": "Error responding to record", "details": str(e)},
        )


@router.post("/close/{record_id}")
async def close_record(
    record_id: str,
    user: dict = Depends(get_current_user),
):
    """Admin closes a compliance record."""
    try:
        try:
            model, record_type, db_id = await resolve_record(record_id)
        except ValueError:
            return log_and_json_response(
                user["staff_id"], {"record_id": record_id},
                "/close/{record_id}", "POST", 400,
                {"error": "Invalid record ID format"},
            )

        staff_id = user["staff_id"]
        checker = ADMIN_ROLE_CHECKERS.get(record_type)
        is_admin = await checker(staff_id) if checker else False

        if not is_admin:
            return log_and_json_response(
                staff_id, {"record_id": record_id},
                "/close/{record_id}", "POST", 403,
                {"error": "Only admins can close records"},
            )

        record = await db_manager.get(model, db_id)
        if not record:
            return log_and_json_response(
                staff_id, {"record_id": record_id},
                "/close/{record_id}", "POST", 404,
                {"error": "Record not found"},
            )

        closure_date = db_timestamp_now()
        updates = {
            "OverallStatus": "Completed",
            "PendingAt": 0,
            "LastUpdatedOn": closure_date,
        }
        if hasattr(record, "ClosureDate"):
            updates["ClosureDate"] = closure_date
        if hasattr(record, "ClosedBy"):
            updates["ClosedBy"] = staff_id
        if hasattr(record, "Status"):
            updates["Status"] = "Completed"

        await db_manager.update(model, db_id, updates)

        created_by = getattr(record, "CreatedBy", "")
        title = getattr(record, "Title", getattr(record, "ComplaintType", getattr(record, "SubType", "")))
        asyncio.create_task(notify_record_closed(
            record_type, db_id, staff_id, created_by,
            title=title,
        ))

        return log_and_json_response(
            staff_id, {"record_id": record_id},
            "/close/{record_id}", "POST", 200,
            {"status": "Record closed", "record_id": db_id},
        )
    except Exception as e:
        return log_and_json_response(
            user.get("staff_id"), {"record_id": record_id},
            "/close/{record_id}", "POST", 500,
            {"error": "Error closing record", "details": str(e)},
        )
