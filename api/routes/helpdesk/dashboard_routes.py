from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse

from utils.deps import get_current_user
from utils.authorize import is_helpdesk_admin
from services.dashboard_service import get_dashboard, get_dashboard_export_file
from .route_utils import log_and_json_response

from core.openapi_tags import TAG_COMMON

router = APIRouter(tags=[TAG_COMMON])


@router.get("/dashboard")
async def dashboard(
    tab: str = Query("pending", pattern="^(pending|all)$"),
    search: Optional[str] = Query(None, max_length=200),
    type_filter: Optional[str] = Query(None, alias="type", max_length=500),
    sub_type: Optional[str] = Query(None, max_length=100),
    response_status: Optional[str] = Query(None, max_length=50),
    overall_status: Optional[str] = Query(None, max_length=50),
    updated_on_start: Optional[date] = Query(None),
    updated_on_end: Optional[date] = Query(None),
    response_due_start: Optional[date] = Query(None),
    response_due_end: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    """
    Unified dashboard for all compliance items.

    - tab=pending: items that need action (non-completed)
    - tab=all: all items including completed
    - type: comma-separated filter, e.g. type=query,gift,complaint
      Allowed values: annual_declarations, self_declarations, query, gift, complaint
    - Admin sees all records; regular user sees only their own.
    """
    try:
        staff_id = user["staff_id"]
        is_admin = await is_helpdesk_admin(user)

        data = await get_dashboard(
            staff_id=staff_id,
            is_admin=is_admin,
            tab=tab,
            search=search,
            type_filter=type_filter,
            sub_type=sub_type,
            response_status=response_status,
            overall_status=overall_status,
            updated_on_start=updated_on_start,
            updated_on_end=updated_on_end,
            response_due_start=response_due_start,
            response_due_end=response_due_end,
            page=page,
            page_size=page_size,
        )

        return JSONResponse(content=data, status_code=200)
    except ValueError as e:
        return JSONResponse(content={"error": str(e)}, status_code=400)
    except Exception as e:
        return log_and_json_response(
            user.get("staff_id"),
            {
                "tab": tab,
                "search": search,
                "type_filter": type_filter,
                "sub_type": sub_type,
                "response_status": response_status,
                "overall_status": overall_status,
                "updated_on_start": str(updated_on_start) if updated_on_start else None,
                "updated_on_end": str(updated_on_end) if updated_on_end else None,
                "response_due_start": str(response_due_start) if response_due_start else None,
                "response_due_end": str(response_due_end) if response_due_end else None,
            },
            "/dashboard",
            "GET",
            500,
            {"error": "Error loading dashboard", "details": str(e)},
        )


@router.get("/dashboard/export")
async def export_dashboard(
    tab: str = Query("pending", pattern="^(pending|all)$"),
    search: Optional[str] = Query(None, max_length=200),
    type_filter: Optional[str] = Query(None, alias="type", max_length=500),
    sub_type: Optional[str] = Query(None, max_length=100),
    response_status: Optional[str] = Query(None, max_length=50),
    overall_status: Optional[str] = Query(None, max_length=50),
    updated_on_start: Optional[date] = Query(None),
    updated_on_end: Optional[date] = Query(None),
    response_due_start: Optional[date] = Query(None),
    response_due_end: Optional[date] = Query(None),
    user: dict = Depends(get_current_user),
):
    """
    Export dashboard records to xlsx using the same role-scoped filters as /dashboard.
    Supports comma-separated type filter, e.g. type=query,gift
    """
    try:
        staff_id = user["staff_id"]
        is_admin = await is_helpdesk_admin(user)

        stream = await get_dashboard_export_file(
            staff_id=staff_id,
            is_admin=is_admin,
            tab=tab,
            search=search,
            type_filter=type_filter,
            sub_type=sub_type,
            response_status=response_status,
            overall_status=overall_status,
            updated_on_start=updated_on_start,
            updated_on_end=updated_on_end,
            response_due_start=response_due_start,
            response_due_end=response_due_end,
        )
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"dashboard_export_{timestamp}.xlsx"

        return StreamingResponse(
            stream,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except ValueError as e:
        return JSONResponse(content={"error": str(e)}, status_code=400)
    except Exception as e:
        return log_and_json_response(
            user.get("staff_id"),
            {
                "tab": tab,
                "search": search,
                "type_filter": type_filter,
                "sub_type": sub_type,
                "response_status": response_status,
                "overall_status": overall_status,
                "updated_on_start": str(updated_on_start) if updated_on_start else None,
                "updated_on_end": str(updated_on_end) if updated_on_end else None,
                "response_due_start": str(response_due_start) if response_due_start else None,
                "response_due_end": str(response_due_end) if response_due_end else None,
            },
            "/dashboard/export",
            "GET",
            500,
            {"error": "Error exporting dashboard", "details": str(e)},
        )
