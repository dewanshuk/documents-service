from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from utils.deps import get_current_user
from utils.authorize import (
    is_active_cobce_coi_gift_lead,
    is_active_complaint_lead,
    is_active_query_lead,
)
from services.dashboard_service import get_dashboard
from .route_utils import log_and_json_response

router = APIRouter()


async def _is_any_admin(staff_id: str) -> bool:
    results = await _gather_admin_checks(staff_id)
    return any(results)


async def _gather_admin_checks(staff_id: str):
    import asyncio
    return await asyncio.gather(
        is_active_query_lead(staff_id),
        is_active_cobce_coi_gift_lead(staff_id),
        is_active_complaint_lead(staff_id),
    )


@router.get("/dashboard")
async def dashboard(
    tab: str = Query("pending", regex="^(pending|all)$"),
    search: Optional[str] = Query(None, max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    """
    Unified dashboard for all compliance items.

    - tab=pending: items that need action (non-completed)
    - tab=all: all items including completed
    - Admin sees all records; regular user sees only their own.
    """
    try:
        staff_id = user["staff_id"]
        is_admin = user.get("is_master_admin", False) or await _is_any_admin(staff_id)

        data = await get_dashboard(
            staff_id=staff_id,
            is_admin=is_admin,
            tab=tab,
            search=search,
            page=page,
            page_size=page_size,
        )

        return JSONResponse(content=data, status_code=200)
    except Exception as e:
        return log_and_json_response(
            user.get("staff_id"),
            {"tab": tab, "search": search},
            "/dashboard",
            "GET",
            500,
            {"error": "Error loading dashboard", "details": str(e)},
        )
