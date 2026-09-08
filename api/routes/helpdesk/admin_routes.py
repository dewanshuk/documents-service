import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, Query, Body
from fastapi.responses import JSONResponse
from sqlalchemy import select, func, or_

from utils.deps import get_current_user
from utils.record_ids import resolve_record
from utils.authorize import (
    is_active_cobce_coi_gift_lead,
    is_active_query_lead,
    is_lead_for_type,
)
from utils.email_notifications import notify_record_assigned
from core.constants import RECORD_TYPE_LEAD_MAP
from db.db_manager import get_session, db_manager
from db.models.helpdesk import User
from .route_utils import log_and_json_response

from core.openapi_tags import TAG_ADMINS

router = APIRouter(tags=[TAG_ADMINS])

ADMIN_ROLE_CHECKERS = {
    "query": is_active_query_lead,
    "cobce": is_active_cobce_coi_gift_lead,
    "coi": is_active_cobce_coi_gift_lead,
}


@router.get("/admins")
async def get_admins(
    record_type: str = Query(..., alias="type", max_length=100),
    search: Optional[str] = Query(None, max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    """
    Get admins (leads) for a given record type with fuzzy search on username.

    Accepts type param: Query, Annual Declaration, Self Declaration
    """
    try:
        lead_col_name = RECORD_TYPE_LEAD_MAP.get(record_type.strip().lower())
        if not lead_col_name:
            allowed = ", ".join(RECORD_TYPE_LEAD_MAP.keys())
            return JSONResponse(
                content={"error": f"Invalid type '{record_type}'. Allowed: {allowed}"},
                status_code=400,
            )

        lead_col = getattr(User, lead_col_name, None)
        if lead_col is None:
            return JSONResponse(
                content={"error": f"Lead column '{lead_col_name}' not found"},
                status_code=500,
            )

        async with get_session() as session:
            base_filters = [
                User.status == "active",
                lead_col.is_(True),
            ]

            if search and search.strip():
                pattern = f"%{search.strip()}%"
                base_filters.append(or_(
                    User.username.ilike(pattern),
                    User.staff_id.ilike(pattern),
                ))

            count_stmt = (
                select(func.count())
                .select_from(User)
                .where(*base_filters)
            )
            total = await session.scalar(count_stmt)

            offset = (page - 1) * page_size
            stmt = (
                select(User.staff_id, User.username)
                .where(*base_filters)
                .order_by(User.username)
                .limit(page_size)
                .offset(offset)
            )
            rows = (await session.execute(stmt)).all()

            items = [
                {"staff_id": r.staff_id, "username": r.username or r.staff_id}
                for r in rows
            ]

        return JSONResponse(content={
            "items": items,
            "total": total or 0,
            "page": page,
            "page_size": page_size,
        }, status_code=200)

    except Exception as e:
        return log_and_json_response(
            user.get("staff_id"),
            {"type": record_type, "search": search},
            "/admins",
            "GET",
            500,
            {"error": "Error fetching admins", "details": str(e)},
        )


@router.put("/assign/{record_id}")
async def assign_admin(
    record_id: str,
    staff_id: str = Body(..., embed=True),
    user: dict = Depends(get_current_user),
):
    """
    Assign an admin to a record. Only the matching type lead can assign
    (not master admin / CCO unless they also have that lead flag).
    May assign to yourself when you are not the creator; may assign your
    own record to another lead. Cannot assign to the creator. Reassignment
    is allowed. Does not apply to Annual Declarations.
    """
    try:
        try:
            model, record_type, db_id = await resolve_record(record_id)
        except ValueError:
            return log_and_json_response(
                user["staff_id"], {"record_id": record_id},
                "/assign/{record_id}", "PUT", 400,
                {"error": "Invalid record ID format"},
            )

        if record_type == "annual_declaration":
            return log_and_json_response(
                user["staff_id"], {"record_id": record_id},
                "/assign/{record_id}", "PUT", 400,
                {"error": "Cannot assign admin to Annual Declarations"},
            )

        caller_id = user["staff_id"]
        if not is_lead_for_type(user, record_type):
            return log_and_json_response(
                caller_id, {"record_id": record_id},
                "/assign/{record_id}", "PUT", 403,
                {"error": "Only type leads can assign records"},
            )

        record = await db_manager.get(model, db_id)
        if not record:
            return log_and_json_response(
                caller_id, {"record_id": record_id},
                "/assign/{record_id}", "PUT", 404,
                {"error": "Record not found"},
            )

        created_by = getattr(record, "CreatedBy", None)
        if staff_id == created_by:
            return log_and_json_response(
                caller_id, {"record_id": record_id, "staff_id": staff_id},
                "/assign/{record_id}", "PUT", 400,
                {"error": "Cannot assign a record to its creator"},
            )

        target_checker = ADMIN_ROLE_CHECKERS.get(record_type)
        if target_checker:
            is_target_admin = await target_checker(staff_id)
            if not is_target_admin:
                return log_and_json_response(
                    caller_id, {"record_id": record_id, "staff_id": staff_id},
                    "/assign/{record_id}", "PUT", 400,
                    {"error": f"Staff {staff_id} is not a valid lead for this record type"},
                )

        await db_manager.update(model, db_id, {"AssignedTo": staff_id})

        title = getattr(record, "Title", getattr(record, "SubType", ""))
        asyncio.create_task(notify_record_assigned(
            record_type, db_id, staff_id, caller_id, created_by,
            title=title,
        ))

        return log_and_json_response(
            caller_id, {"record_id": record_id, "staff_id": staff_id},
            "/assign/{record_id}", "PUT", 200,
            {"status": "Admin assigned", "record_id": db_id, "assigned_to": staff_id},
        )

    except Exception as e:
        return log_and_json_response(
            user.get("staff_id"), {"record_id": record_id, "staff_id": staff_id},
            "/assign/{record_id}", "PUT", 500,
            {"error": "Error assigning admin", "details": str(e)},
        )
