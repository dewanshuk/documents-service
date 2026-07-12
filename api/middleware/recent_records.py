import re
from datetime import datetime

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from services.recent_records_service import log_recent_record, log_annual_declaration_recent
from db.db_manager import db_manager
from utils.helpers import get_model_by_id
from utils.deps import get_current_user

ANNUAL_VIEW_PATTERN = re.compile(
    r"^/api/declarations/declaration-responses/([^/]+)$"
)
ANNUAL_SAVE_PATTERN = re.compile(
    r"^/api/declarations/save-declaration/([^/]+)$"
)
QUERY_VIEW_PATTERN = re.compile(r"^/api/compliance/query/([^/]+)$")


async def get_user_from_request(request: Request) -> str:
    user = await get_current_user()
    return user["staff_id"]


def _pending_at_display(record) -> str:
    if getattr(record, "Status", None) == "Draft":
        return "-"
    if record.OverallStatus != "Closed":
        if record.PendingAt == 1:
            return "Compliance Team"
        if record.PendingAt == 0:
            return "me"
        return "-"
    return "-"


async def _log_helpdesk_record(staff_id: str, record_id: str) -> None:
    model = await get_model_by_id(record_id)
    if isinstance(model, Exception):
        return

    record = await db_manager.get(model, record_id)
    if not record:
        return

    record_type = "Query"
    title = getattr(record, "Title", "Query")
    sub_type = None

    if hasattr(record, "QueryId"):
        record_type = "Query"
        title = getattr(record, "Title", "Query")
        sub_type = getattr(record, "QueryType", None)
    elif hasattr(record, "ComplaintId"):
        record_type = "Complaint"
        details = getattr(record, "ComplaintDetails", "")
        title = (details[:50] + "...") if details else "Complaint"
        sub_type = getattr(record, "ComplaintType", None)
    elif hasattr(record, "GiftId"):
        record_type = "Gift Declaration"
        title = f"Gift - {getattr(record, 'Person', '')}"
        sub_type = "Gift"
    elif hasattr(record, "COBCEId"):
        record_type = "Self Declaration"
        description = getattr(record, "Description", "")
        title = (description[:50] + "...") if description else "COBCE Declaration"
        sub_type = getattr(record, "SubType", "COBCE")
    elif hasattr(record, "COIId"):
        record_type = "Self Declaration"
        title = "COI Declaration"
        sub_type = getattr(record, "SubType", "COI")
    elif hasattr(record, "R518Id"):
        record_type = "Self Declaration"
        title = "R518 Declaration"
        sub_type = getattr(record, "SubType", "R518")

    await log_recent_record(
        user_id=staff_id,
        record_id=record_id,
        record_type=record_type,
        title=title,
        status=record.OverallStatus,
        created_on=record.CreatedOn,
        sub_type=sub_type,
        pending_at=_pending_at_display(record),
    )


async def process_recent_record(staff_id: str, method: str, path: str) -> None:
    try:
        query_match = QUERY_VIEW_PATTERN.match(path)
        if query_match and method == "GET":
            await _log_helpdesk_record(staff_id, query_match.group(1))
            return

        annual_view_match = ANNUAL_VIEW_PATTERN.match(path)
        if annual_view_match and method == "GET":
            await log_annual_declaration_recent(staff_id, annual_view_match.group(1))
            return

        annual_save_match = ANNUAL_SAVE_PATTERN.match(path)
        if annual_save_match and method == "POST":
            await log_annual_declaration_recent(staff_id, annual_save_match.group(1))
            return
    except Exception as e:
        print(f"Error logging recent record in middleware: {e}")


class RecentRecordsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        if response.status_code != 200:
            return response

        path = request.url.path
        tracked = (
            (request.method == "GET" and QUERY_VIEW_PATTERN.match(path))
            or (request.method == "GET" and ANNUAL_VIEW_PATTERN.match(path))
            or (request.method == "POST" and ANNUAL_SAVE_PATTERN.match(path))
        )
        if not tracked:
            return response

        staff_id = await get_user_from_request(request)
        await process_recent_record(staff_id, request.method, path)
        return response
