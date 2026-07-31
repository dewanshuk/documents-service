import asyncio
import traceback

from fastapi import UploadFile, File, Form, APIRouter, Depends
from typing import List

from utils.deps import get_current_user
from utils.record_ids import next_query_id
from db.db_manager import db_manager
from db.models.helpdesk import ComplianceQuery, COBCEDeclarations, COIDeclarations
from db.validators.comp_help import QueryType
from storage.storage_ops import upload_files, init_json, append_json, read_json
from utils.authorize import (
    is_active_cobce_coi_gift_lead,
    is_active_complaint_lead,
    is_active_query_lead,
)
from utils.actor_display import format_actor_name, format_pending_at
from utils.helpers import (
    db_timestamp_now,
    get_type_and_model_by_id,
    validate_word_limit,
    get_model_by_id,
    now_ist,
)
from utils.email_notifications import (
    notify_record_created,
    notify_record_responded,
    notify_record_closed,
)
from .route_utils import log_and_json_response
from core.openapi_tags import TAG_QUERY

router = APIRouter(tags=[TAG_QUERY])

# Query endpoints for raising, responding, closing, viewing, and downloading query files.


@router.get("/query/{query_id}")
async def view_query(query_id: str, user: dict = Depends(get_current_user)):
    """Get the details and conversation history for a specific query."""
    try:
        try:
            model = await get_model_by_id(query_id)
        except ValueError as e:
            return log_and_json_response(
                user.get("staff_id"),
                {"query_id": query_id},
                "/query/{query_id}",
                "GET",
                400,
                {"error": str(e)},
            )
        record = await db_manager.get(model, query_id)
        if not record:
            return log_and_json_response(
                user["staff_id"],
                {"query_id": query_id},
                "/query/{query_id}",
                "GET",
                404,
                {"error": "Record Not found"},
            )

        data = (
            await read_json(record.ResponseJsonPath)
            if record.ResponseJsonPath
            else None
        )

        if hasattr(record, "QueryId"):
            record_id = record.QueryId
        elif hasattr(record, "GiftId"):
            record_id = record.GiftId
        elif hasattr(record, "ComplaintId"):
            record_id = record.ComplaintId
        elif hasattr(record, "COBCEId"):
            record_id = record.COBCEId
        elif hasattr(record, "COIId"):
            record_id = record.COIId
        else:
            record_id = None

        if getattr(record, "Status", None) == "Draft" or record.OverallStatus == "Closed":
            pending_at_display = "-"
        else:
            pending_at_display = await format_pending_at(record.PendingAt, record.CreatedBy)

        actor_name = await format_actor_name(record.CreatedBy)
        closed_by_name = await format_actor_name(getattr(record, "ClosedBy", None))

        response_body = {
            "details": {
                "id": record_id,
                "status": record.OverallStatus,
                "pendingAt": pending_at_display,
                "createdBy": record.CreatedBy,
                "actor_name": actor_name,
                "createdOn": str(record.CreatedOn) if record.CreatedOn else None,
                "closureDate": str(record.ClosureDate) if record.ClosureDate else None,
                "closedBy": getattr(record, "ClosedBy", None),
                "closed_by_name": closed_by_name,
                "workflowStatus": getattr(record, "Status", None),
            },
            "conversation": data,
        }

        return log_and_json_response(
            user["staff_id"],
            {"query_id": query_id},
            "/query/{query_id}",
            "GET",
            200,
            response_body,
        )
    except Exception as e:
        print(traceback.format_exc())
        return log_and_json_response(
            user.get("staff_id"),
            {"query_id": query_id},
            "/query/{query_id}",
            "GET",
            500,
            {"error": "Error fetching querys", "details": str(e)},
        )


@router.post("/query")
async def raise_query(
    queryType: QueryType = Form(...),
    title: str = Form(...),
    description: str = Form(...),
    files: List[UploadFile] = File(default=[]),
    user: dict = Depends(get_current_user),
):
    """Raise a new compliance query with optional attached files."""
    try:
        if len(files) > 6:
            return log_and_json_response(
                user["staff_id"],
                {"title": title, "description": description},
                "/query",
                "POST",
                400,
                {"error": "Max 6 files allowed"},
            )

        try:
            validate_word_limit(title, 50)
            validate_word_limit(description, 500)
        except ValueError as e:
            return log_and_json_response(
                user["staff_id"],
                {"title": title, "description": description},
                "/query",
                "POST",
                400,
                {"error": str(e)},
            )

        query_id = await next_query_id(user["staff_id"])
        now = now_ist()
        created_on = db_timestamp_now()

        file_paths = await upload_files(query_id, "user", files)

        json_data = {
            "id": query_id,
            "conversation": [
                {
                    "actor": "User",
                    "actorId": user["staff_id"],
                    "dateTime": now.isoformat(),
                    "data": {
                        "title": title,
                        "description": description,
                    },
                    "files": file_paths,
                }
            ],
        }

        json_path = await init_json(query_id, json_data)

        await db_manager.create(
            ComplianceQuery,
            {
                "QueryId": query_id,
                "QueryType": queryType.value,
                "Title": title,
                "Description": description,
                "CreatedOn": created_on,
                "CreatedBy": user["staff_id"],
                "OverallStatus": "Pending",
                "PendingAt": 1,
                "ResponseJsonPath": json_path,
            },
        )

        asyncio.create_task(notify_record_created(
            "query", query_id, user["staff_id"], title=title,
        ))

        return log_and_json_response(
            user["staff_id"],
            {"query_id": query_id},
            "/query",
            "POST",
            201,
            {
                "details": f"Query has been created with query_id: {query_id}",
                "status": "Pending",
                "query_id": query_id,
            },
        )
    except Exception as e:
        return log_and_json_response(
            user.get("staff_id"),
            {"title": title, "description": description},
            "/query",
            "POST",
            500,
            {"error": "Error creating query", "details": str(e)},
        )


@router.post("/query/{query_id}/respond")
async def respond(
    query_id: str,
    message: str = Form(...),
    files: List[UploadFile] = File(default=[]),
    user: dict = Depends(get_current_user),
):
    """Add a response to an existing query conversation."""
    try:
        try:
            model, record_type = await get_type_and_model_by_id(query_id)
        except ValueError as e:
            return log_and_json_response(
                user.get("staff_id"),
                {"query_id": query_id},
                "/query/{query_id}/respond",
                "POST",
                400,
                {"error": str(e)},
            )
        record = await db_manager.get(model, query_id)
        if not record:
            return log_and_json_response(
                user["staff_id"],
                {"query_id": query_id},
                "/query/{query_id}/respond",
                "POST",
                404,
                {"error": "Response Not found"},
            )

        if isinstance(record, COBCEDeclarations):
            if record.Status == "Draft":
                return log_and_json_response(
                    user["staff_id"],
                    {"query_id": query_id},
                    "/query/{query_id}/respond",
                    "POST",
                    400,
                    {"error": "Draft cannot be responded"},
                )
            if not record.ResponseJsonPath:
                return log_and_json_response(
                    user["staff_id"],
                    {"query_id": query_id},
                    "/query/{query_id}/respond",
                    "POST",
                    400,
                    {"error": "COBCE not submitted yet"},
                )

        if isinstance(record, COIDeclarations):
            if record.Status == "Draft":
                return log_and_json_response(
                    user["staff_id"],
                    {"query_id": query_id},
                    "/query/{query_id}/respond",
                    "POST",
                    400,
                    {"error": "Draft cannot be responded"},
                )
            if not record.ResponseJsonPath:
                return log_and_json_response(
                    user["staff_id"],
                    {"query_id": query_id},
                    "/query/{query_id}/respond",
                    "POST",
                    400,
                    {"error": "COI not submitted yet"},
                )

        if record.OverallStatus == "Closed":
            return log_and_json_response(
                user["staff_id"],
                {"query_id": query_id},
                "/query/{query_id}/respond",
                "POST",
                400,
                {"error": "Already closed"},
            )

        persona_check = False
        if record.PendingAt == 0:
            if (
                record_type in ["cobce", "coi", "gift"]
                and user["staff_id"] != record.CreatedBy
            ):
                persona_check = await is_active_cobce_coi_gift_lead(user["staff_id"])
            elif record_type == "complaint" and user["staff_id"] != record.CreatedBy:
                persona_check = await is_active_complaint_lead(user["staff_id"])
            elif record_type == "query":
                persona_check = await is_active_query_lead(user["staff_id"])
            else:
                persona_check = False
            if not persona_check:
                return log_and_json_response(
                    user["staff_id"],
                    {"query_id": query_id},
                    "/query/{query_id}/respond",
                    "POST",
                    403,
                    {"error": "Not Authorized to Perform this action."},
                )

        elif record.PendingAt == 1:
            if user["staff_id"] != record.CreatedBy:
                return log_and_json_response(
                    user["staff_id"],
                    {"query_id": query_id},
                    "/query/{query_id}/respond",
                    "POST",
                    401,
                    {"error": "Users can only respond to their own queries"},
                )

        if len(files) > 6:
            return log_and_json_response(
                user["staff_id"],
                {"query_id": query_id},
                "/query/{query_id}/respond",
                "POST",
                400,
                {"error": "Max 6 files allowed"},
            )

        try:
            validate_word_limit(message, 500)
        except ValueError as e:
            return log_and_json_response(
                user["staff_id"],
                {"query_id": query_id},
                "/query/{query_id}/respond",
                "POST",
                400,
                {"error": str(e)},
            )

        actor = "Compliance Team" if persona_check else "User"
        next_pending = 1 if record.PendingAt == 0 else 0
        file_paths = await upload_files(query_id, actor, files)
        entry = {
            "actor": actor,
            "actorId": user["staff_id"],
            "dateTime": now_ist().isoformat(),
            "data": {"comment": message},
            "files": file_paths,
        }
        if not record.ResponseJsonPath:
            return log_and_json_response(
                user["staff_id"],
                {"query_id": query_id},
                "/query/{query_id}/respond",
                "POST",
                400,
                {"error": "No conversation available"},
            )
        await append_json(record.ResponseJsonPath, entry)

        await db_manager.update(model, query_id, {"PendingAt": next_pending})

        title = getattr(record, "Title", getattr(record, "ComplaintDetails", getattr(record, "Person", getattr(record, "SubType", ""))))
        asyncio.create_task(notify_record_responded(
            record_type, query_id, user["staff_id"], record.CreatedBy,
            title=title,
            response_text=message,
        ))

        return log_and_json_response(
            user["staff_id"],
            {"query_id": query_id},
            "/query/{query_id}/respond",
            "POST",
            200,
            {
                "details": "Response added",
                "nextPending": "Compliance Team" if next_pending == 1 else "User",
            },
        )
    except Exception as e:
        return log_and_json_response(
            user.get("staff_id"),
            {"query_id": query_id},
            "/query/{query_id}/respond",
            "POST",
            500,
            {"error": "Error responding to query", "details": str(e)},
        )


@router.post("/query/{query_id}/close")
async def close_query(
    query_id: str,
    comment: str = Form(...),
    user: dict = Depends(get_current_user),
):
    """Close an open compliance query with a comment."""
    try:
        try:
            model, record_type = await get_type_and_model_by_id(query_id)
        except ValueError as e:
            return log_and_json_response(
                user.get("staff_id"),
                {"query_id": query_id, "comment": comment},
                "/query/{query_id}/close",
                "POST",
                400,
                {"error": str(e)},
            )
        record = await db_manager.get(model, query_id)
        if not record:
            return log_and_json_response(
                user["staff_id"],
                {"query_id": query_id, "comment": comment},
                "/query/{query_id}/close",
                "POST",
                404,
                {"error": "Record Not found"},
            )

        persona_check = False
        if record.PendingAt == 0:
            if (
                record_type in ["cobce", "coi", "gift"]
                and user["staff_id"] != record.CreatedBy
            ):
                persona_check = await is_active_cobce_coi_gift_lead(user["staff_id"])
            elif record_type == "complaint" and user["staff_id"] != record.CreatedBy:
                persona_check = await is_active_complaint_lead(user["staff_id"])
            elif record_type == "query":
                persona_check = await is_active_query_lead(user["staff_id"])
            else:
                persona_check = False

        if not persona_check:
            return log_and_json_response(
                user["staff_id"],
                {"query_id": query_id, "comment": comment},
                "/query/{query_id}/close",
                "POST",
                403,
                {"error": "Not Authorized to Perform this action."},
            )

        if record.OverallStatus == "Closed":
            return log_and_json_response(
                user["staff_id"],
                {"query_id": query_id, "comment": comment},
                "/query/{query_id}/close",
                "POST",
                400,
                {"error": "Already closed"},
            )

        try:
            validate_word_limit(comment, 500)
        except ValueError as e:
            return log_and_json_response(
                user["staff_id"],
                {"query_id": query_id, "comment": comment},
                "/query/{query_id}/close",
                "POST",
                400,
                {"error": str(e)},
            )

        entry = {
            "actor": "Compliance Team",
            "actorId": user["staff_id"],
            "dateTime": now_ist().isoformat(),
            "data": {"comment": comment},
            "files": [],
        }
        if not record.ResponseJsonPath:
            return log_and_json_response(
                user["staff_id"],
                {"query_id": query_id, "comment": comment},
                "/query/{query_id}/close",
                "POST",
                400,
                {"error": "No conversation available"},
            )
        await append_json(record.ResponseJsonPath, entry)
        await db_manager.update(
            model,
            query_id,
            {
                "OverallStatus": "Closed",
                "PendingAt": -1,
                "ClosureDate": db_timestamp_now(),
                "ClosedRemarks": comment,
            },
        )

        title = getattr(record, "Title", getattr(record, "ComplaintDetails", getattr(record, "Person", getattr(record, "SubType", ""))))
        asyncio.create_task(notify_record_closed(
            record_type, query_id, user["staff_id"], record.CreatedBy,
            title=title,
        ))

        return log_and_json_response(
            user["staff_id"],
            {"query_id": query_id, "comment": comment},
            "/query/{query_id}/close",
            "POST",
            200,
            {"status": "Closed"},
        )
    except Exception as e:
        return log_and_json_response(
            user.get("staff_id"),
            {"query_id": query_id, "comment": comment},
            "/query/{query_id}/close",
            "POST",
            400,
            {"error": "Error closing query", "details": str(e)},
        )
