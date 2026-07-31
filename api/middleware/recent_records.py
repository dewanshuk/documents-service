import json
import re

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from services.recent_records_service import log_recent_record, log_annual_declaration_recent
from db.db_manager import db_manager
from utils.actor_display import format_pending_at
from utils.helpers import get_model_by_id
from utils.deps import get_current_user

ANNUAL_VIEW_PATTERN = re.compile(
    r"^/api/declarations/declaration-responses/([^/]+)$"
)
ANNUAL_SAVE_PATTERN = re.compile(
    r"^/api/declarations/save-declaration/([^/]+)$"
)

# Routes where the record id is already part of the URL: viewing or responding
# to an existing query/complaint/gift/self-declaration.
HELPDESK_ID_IN_URL_PATTERNS = [
    ("GET", re.compile(r"^/api/compliance/query/([^/]+)$")),
    ("POST", re.compile(r"^/api/compliance/query/([^/]+)/respond$")),
    ("POST", re.compile(r"^/api/compliance/respond/([^/]+)$")),
]

# Routes that create a new record: the new id is only known after the handler
# runs, so it's read from the JSON response body instead of the URL.
HELPDESK_CREATE_PATTERNS = [
    ("POST", re.compile(r"^/api/compliance/query$"), "query_id"),
    ("POST", re.compile(r"^/api/compliance/complaint$"), "complaint_id"),
    ("POST", re.compile(r"^/api/compliance/gift$"), "gift_id"),
    ("POST", re.compile(r"^/api/compliance/self-declaration$"), "id"),
]


async def get_user_from_request(request: Request) -> str:
    user = await get_current_user()
    return user["staff_id"]


async def _pending_at_display(record) -> str:
    if getattr(record, "Status", None) == "Draft" or record.OverallStatus == "Closed":
        return "-"
    return await format_pending_at(record.PendingAt, record.CreatedBy)


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

    await log_recent_record(
        user_id=staff_id,
        record_id=record_id,
        record_type=record_type,
        title=title,
        status=record.OverallStatus or getattr(record, "Status", None),
        created_on=record.CreatedOn,
        sub_type=sub_type,
        pending_at=await _pending_at_display(record),
    )


def _match_create_route(method: str, path: str):
    for route_method, pattern, id_key in HELPDESK_CREATE_PATTERNS:
        if route_method == method and pattern.match(path):
            return id_key
    return None


def _is_id_in_url_route(method: str, path: str) -> bool:
    return any(
        route_method == method and pattern.match(path)
        for route_method, pattern in HELPDESK_ID_IN_URL_PATTERNS
    )


async def process_recent_record(staff_id: str, method: str, path: str) -> None:
    try:
        for route_method, pattern in HELPDESK_ID_IN_URL_PATTERNS:
            if route_method == method:
                match = pattern.match(path)
                if match:
                    await _log_helpdesk_record(staff_id, match.group(1))
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

        if response.status_code not in (200, 201):
            return response

        path = request.url.path
        method = request.method

        id_key = _match_create_route(method, path)
        if id_key:
            body = b"".join([chunk async for chunk in response.body_iterator])
            try:
                staff_id = await get_user_from_request(request)
                record_id = json.loads(body).get(id_key)
                if record_id:
                    await _log_helpdesk_record(staff_id, record_id)
            except Exception as e:
                print(f"Error logging recent record in middleware: {e}")
            return Response(
                content=body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

        if not _is_id_in_url_route(method, path) and not (
            (method == "GET" and ANNUAL_VIEW_PATTERN.match(path))
            or (method == "POST" and ANNUAL_SAVE_PATTERN.match(path))
        ):
            return response

        staff_id = await get_user_from_request(request)
        await process_recent_record(staff_id, method, path)
        return response
