import asyncio
from typing import List

from fastapi import APIRouter, Depends, UploadFile, File, Form, Query
from fastapi.responses import JSONResponse

from utils.deps import get_current_user
from utils.record_ids import resolve_record
from utils.authorize import is_lead_for_type
from utils.actor_display import format_actor_name, format_pending_at
from utils.email_notifications import notify_record_responded, notify_record_closed
from db.db_manager import db_manager
from storage.storage_ops import upload_files, resolve_file_urls, load_json, save_json
from .route_utils import log_and_json_response
from utils.helpers import now_ist, db_timestamp_now, validate_word_limit, format_datetime_ist
from core.openapi_tags import TAG_COMMON

router = APIRouter(tags=[TAG_COMMON])

CREATED_BY_FIELD = {
    "query": "CreatedBy",
    "gift": "CreatedBy",
    "complaint": "CreatedBy",
    "cobce": "CreatedBy",
    "coi": "CreatedBy",
}

RECORD_TYPE_DISPLAY = {
    "query": "Query",
    "gift": "Gift",
    "complaint": "Complaint",
    "cobce": "COBCE",
    "coi": "COI",
}


async def _load_conversation(json_uri: str) -> dict:
    return await load_json(json_uri)


async def _save_conversation(json_uri: str, data: dict) -> None:
    await save_json(json_uri, data)


@router.get("/conversation/{record_id}")
async def get_conversation(
    record_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: dict = Depends(get_current_user),
):
    """Retrieve the conversation thread for a compliance record.

    Supports pagination via `limit` (default 50) and `offset` (default 0).
    Offset counts from the end, so offset=0 returns the most recent `limit` messages.
    The response includes `total_messages` and `has_more` for the client to detect
    whether older messages exist.
    """
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

        is_admin = is_lead_for_type(user, record_type)

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
        else:
            record_id_val = db_id

        closed_by = getattr(record, "ClosedBy", None)
        is_draft_or_closed = (
            getattr(record, "Status", None) == "Draft"
            or getattr(record, "OverallStatus", None) == "Closed"
        )

        async def _pending_at_or_dash():
            if is_draft_or_closed:
                return "-"
            return await format_pending_at(
                getattr(record, "PendingAt", None),
                created_by,
                is_admin=is_admin,
                assigned_to=getattr(record, "AssignedTo", None),
            )

        # Resolve actor names and pending-at label in parallel (3 DB lookups → 1 round-trip).
        actor_name, closed_by_name, pending_at_display = await asyncio.gather(
            format_actor_name(created_by),
            format_actor_name(closed_by),
            _pending_at_or_dash(),
        )

        details = {
            "id": record_id_val,
            "status": getattr(record, "OverallStatus", None),
            "pendingAt": pending_at_display,
            "createdBy": created_by,
            "actor_name": actor_name,
            "recordType": RECORD_TYPE_DISPLAY.get(record_type, record_type),
            "createdOn": format_datetime_ist(getattr(record, "CreatedOn", None)),
            "closureDate": format_datetime_ist(getattr(record, "ClosureDate", None)),
            "closedBy": closed_by,
            "closed_by_name": closed_by_name,
            "workflowStatus": getattr(record, "Status", None),
        }

        json_path = getattr(record, "ResponseJsonPath", None)
        if not json_path:
            return JSONResponse(
                content={
                    "id": record_id_val, "details": details,
                    "conversation": [], "total_messages": 0, "has_more": False,
                },
                status_code=200,
            )

        conv = await _load_conversation(json_path)
        all_messages = conv.get("conversation", []) or []
        total_messages = len(all_messages)

        # Paginate from the end (most recent messages by default).
        end = total_messages - offset
        start = max(0, end - limit)
        page = all_messages[start:end]

        # Resolve file URLs for this page in parallel instead of sequentially.
        if page:
            file_url_lists = await asyncio.gather(
                *[resolve_file_urls(entry.get("files")) for entry in page]
            )
            for entry, urls in zip(page, file_url_lists):
                entry["files"] = urls
                entry["dateTime"] = format_datetime_ist(entry.get("dateTime"))

        return JSONResponse(
            content={
                "id": record_id_val,
                "details": details,
                "conversation": page,
                "total_messages": total_messages,
                "has_more": start > 0,
            },
            status_code=200,
        )
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

        is_admin = is_lead_for_type(user, record_type)

        if not is_owner and not is_admin:
            return log_and_json_response(
                staff_id, {"record_id": record_id},
                "/respond/{record_id}", "POST", 403,
                {"error": "Not authorized to respond to this record"},
            )

        if getattr(record, "OverallStatus", None) in ("Closed", "Completed"):
            return log_and_json_response(
                staff_id, {"record_id": record_id},
                "/respond/{record_id}", "POST", 400,
                {"error": "Record is already closed"},
            )

        # Turn-based enforcement: PendingAt=1 → admin's turn, PendingAt=0 → owner's
        # turn. Admins may only act as Admin on records they do not own; on their
        # own records they can only respond as User (when PendingAt=0).
        pending_at = getattr(record, "PendingAt", None)
        acting_as_admin = is_admin and not is_owner
        if acting_as_admin and pending_at != 1:
            return log_and_json_response(
                staff_id, {"record_id": record_id},
                "/respond/{record_id}", "POST", 403,
                {"error": "Waiting for the user's response before you can respond again"},
            )
        if not acting_as_admin and pending_at != 0:
            return log_and_json_response(
                staff_id, {"record_id": record_id},
                "/respond/{record_id}", "POST", 403,
                {"error": "Waiting for the admin's response before you can respond again"},
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
        actor = "Admin" if acting_as_admin else "User"
        file_paths = await upload_files(db_id, actor.lower(), files)

        conv = await _load_conversation(json_path)
        conv["conversation"].append({
            "actor": actor,
            "actorId": staff_id,
            "actor_name": await format_actor_name(staff_id),
            "dateTime": now.isoformat(),
            "message": message,
            "files": file_paths,
        })
        await _save_conversation(json_path, conv)

        new_pending = 0 if acting_as_admin else 1

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
    remarks: str = Form(...),
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
        is_admin = is_lead_for_type(user, record_type)

        if not is_admin:
            return log_and_json_response(
                staff_id, {"record_id": record_id},
                "/close/{record_id}", "POST", 403,
                {"error": "Only admins can close records"},
            )

        try:
            validate_word_limit(remarks, 500)
        except ValueError as e:
            return log_and_json_response(
                staff_id, {"record_id": record_id},
                "/close/{record_id}", "POST", 400,
                {"error": str(e)},
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
        if hasattr(record, "ClosedRemarks"):
            updates["ClosedRemarks"] = remarks
        if hasattr(record, "Status"):
            updates["Status"] = "Completed"

        await db_manager.update(model, db_id, updates)

        json_path = getattr(record, "ResponseJsonPath", None)
        if json_path:
            conv = await _load_conversation(json_path)
            conv["conversation"].append({
                "actor": "Compliance Team",
                "actorId": staff_id,
                "actor_name": await format_actor_name(staff_id),
                "dateTime": now_ist().isoformat(),
                "message": remarks,
                "files": [],
            })
            await _save_conversation(json_path, conv)

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
