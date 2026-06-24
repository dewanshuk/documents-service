from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import select, and_

from db.db_manager import get_session
from db.models.helpdesk import (
    ComplianceQuery,
    GiftDeclarations,
    Complaints,
    COBCEDeclarations,
    COIDeclarations,
    R518Declarations,
)
from db.models.annual_dec import (
    AnnualDeclaration,
    User,
    UserDeclarationStatus,
)
from utils.record_ids import build_annual_user_status_id
from db.models.annual_dec import as_declaration_name

SELF_DECL_DUE_DAYS = 7


def _response_status(due_date, overall_status: str) -> str:
    if overall_status and overall_status.lower() == "completed":
        return "Completed"
    if due_date is None:
        return "Due"
    today = date.today()
    if isinstance(due_date, datetime):
        due_date = due_date.date()
    return "Overdue" if due_date < today else "Due"


def _compute_due_date(created_on) -> Optional[date]:
    if created_on is None:
        return None
    if isinstance(created_on, datetime):
        return (created_on + timedelta(days=SELF_DECL_DUE_DAYS)).date()
    return created_on + timedelta(days=SELF_DECL_DUE_DAYS)


def _fmt_date(val) -> Optional[str]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.isoformat()
    if isinstance(val, date):
        return val.isoformat()
    return str(val)


async def _get_user_name_map(session, staff_ids: set[str]) -> dict[str, str]:
    if not staff_ids:
        return {}
    stmt = select(User.staff_id, User.username).where(User.staff_id.in_(staff_ids))
    rows = (await session.execute(stmt)).all()
    return {r.staff_id: (r.username or r.staff_id) for r in rows}


async def get_dashboard(
    staff_id: str,
    is_admin: bool,
    tab: str = "pending",
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 25,
) -> dict:
    async with get_session() as session:
        items = []

        items += await _collect_annual_declarations(session, staff_id, is_admin, tab)
        items += await _collect_self_declarations(session, staff_id, is_admin, tab)
        items += await _collect_queries(session, staff_id, is_admin, tab)
        items += await _collect_complaints(session, staff_id, is_admin, tab)
        items += await _collect_gifts(session, staff_id, is_admin, tab)

        if search:
            q = search.lower()
            items = [
                i for i in items
                if q in (i.get("request_id") or "").lower()
                or q in (i.get("type") or "").lower()
                or q in (i.get("sub_type") or "").lower()
                or q in (i.get("created_by_name") or "").lower()
            ]

        all_staff = {i.get("created_by") for i in items if i.get("created_by")}
        name_map = await _get_user_name_map(session, all_staff)
        for item in items:
            cb = item.get("created_by")
            item["created_by_name"] = name_map.get(cb, cb) if cb else None

        summary = _compute_summary(items)

        items.sort(key=lambda x: x.get("created_on") or "", reverse=True)

        total = len(items)
        start = (page - 1) * page_size
        page_items = items[start : start + page_size]

        return {
            "items": page_items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "summary": summary,
        }


def _compute_summary(items: list[dict]) -> dict:
    total_due = 0
    total_overdue = 0
    annual_declarations = 0
    self_declarations = 0
    queries = 0
    complaints = 0
    gifts = 0

    for item in items:
        rs = (item.get("response_status") or "").lower()
        if rs == "overdue":
            total_overdue += 1
        if rs in ("due", "overdue"):
            total_due += 1

        t = item.get("type", "")
        if t == "Annual Declaration":
            annual_declarations += 1
        elif t == "Self Declaration":
            self_declarations += 1
        elif t == "Query":
            queries += 1
        elif t == "Complaint":
            complaints += 1
        elif t == "Gift Declaration":
            gifts += 1

    return {
        "total_due": total_due,
        "total_overdue": total_overdue,
        "annual_declarations": annual_declarations,
        "self_declarations": self_declarations,
        "queries": queries,
        "complaints": complaints,
        "gifts": gifts,
    }


async def _collect_annual_declarations(session, staff_id, is_admin, tab) -> list[dict]:
    """
    Annual declarations are always scoped to the logged-in user (admin included).
    Shown only when Excel has been processed with notify=True.
    Pending tab excludes completed; all tab includes them.
    Admin visibility into other users' submissions is via self-declarations.
    """
    items = []

    today = date.today()
    decl_stmt = select(AnnualDeclaration).where(
        AnnualDeclaration.assigned_date <= today
    )
    declarations = (await session.execute(decl_stmt)).scalars().all()

    for decl in declarations:
        status_stmt = select(UserDeclarationStatus).where(
            and_(
                UserDeclarationStatus.declaration_id == decl.id,
                UserDeclarationStatus.staff_id == staff_id,
            )
        )
        uds = (await session.execute(status_stmt)).scalar_one_or_none()

        if uds is None or not uds.notify:
            continue

        item = _build_annual_item(
            decl, uds.status, staff_id, uds.submitted_at, uds.id
        )
        if _matches_tab(item, tab):
            items.append(item)

    return items


def _build_annual_item(
    decl: AnnualDeclaration,
    status: str,
    staff_id,
    submitted_at,
    user_status_id=None,
) -> dict:
    display_status = status
    if status in ("not_started", "Pending"):
        display_status = "Pending"
    elif status == "draft":
        display_status = "In-Progress"
    elif status == "completed":
        display_status = "Completed"

    overall = "In-Progress"
    if display_status == "Completed":
        overall = "Completed"

    due = decl.due_date
    response_status = _response_status(due, overall)

    request_id = user_status_id
    if not request_id and staff_id and decl.reference_id:
        request_id = build_annual_user_status_id(staff_id, decl.reference_id)
    elif not request_id:
        request_id = decl.reference_id

    return {
        "request_id": request_id,
        "reference_id": decl.reference_id,
        "staff_id": staff_id,
        "type": "Annual Declaration",
        "sub_type": as_declaration_name(decl.declaration_name),
        "response_status": response_status,
        "overall_status": overall,
        "created_on": _fmt_date(decl.assigned_date),
        "response_due_date": _fmt_date(due),
        "created_by": staff_id,
        "created_by_name": None,
        "declaration_status": status,
    }


async def _collect_self_declarations(session, staff_id, is_admin, tab) -> list[dict]:
    items = []

    for model, sub_type, pk_field in [
        (COBCEDeclarations, "COBCE", "COBCEId"),
        (COIDeclarations, "COI", "COIId"),
        (R518Declarations, "R5.18", "R518Id"),
    ]:
        stmt = select(model)
        if not is_admin:
            stmt = stmt.where(getattr(model, "CreatedBy") == staff_id)

        records = (await session.execute(stmt)).scalars().all()
        for rec in records:
            request_id = getattr(rec, pk_field)
            due = _compute_due_date(rec.CreatedOn)
            overall = rec.OverallStatus or "Pending"
            rs = _response_status(due, overall)

            item = {
                "request_id": request_id,
                "type": "Self Declaration",
                "sub_type": sub_type,
                "response_status": rs,
                "overall_status": overall,
                "created_on": _fmt_date(rec.CreatedOn),
                "response_due_date": _fmt_date(due),
                "created_by": rec.CreatedBy,
                "created_by_name": None,
            }
            if _matches_tab(item, tab):
                items.append(item)

    return items


async def _collect_queries(session, staff_id, is_admin, tab) -> list[dict]:
    stmt = select(ComplianceQuery)
    if not is_admin:
        stmt = stmt.where(ComplianceQuery.CreatedBy == staff_id)

    records = (await session.execute(stmt)).scalars().all()
    items = []
    for rec in records:
        due = _compute_due_date(rec.CreatedOn)
        overall = rec.OverallStatus or "Pending"
        rs = _response_status(due, overall)

        item = {
            "request_id": rec.QueryId,
            "type": "Query",
            "sub_type": rec.QueryType,
            "response_status": rs,
            "overall_status": overall,
            "created_on": _fmt_date(rec.CreatedOn),
            "response_due_date": _fmt_date(due),
            "created_by": rec.CreatedBy,
            "created_by_name": None,
        }
        if _matches_tab(item, tab):
            items.append(item)

    return items


async def _collect_complaints(session, staff_id, is_admin, tab) -> list[dict]:
    stmt = select(Complaints)
    if not is_admin:
        stmt = stmt.where(Complaints.CreatedBy == staff_id)

    records = (await session.execute(stmt)).scalars().all()
    items = []
    for rec in records:
        due = _compute_due_date(rec.CreatedOn)
        overall = rec.OverallStatus or "Pending"
        rs = _response_status(due, overall)

        item = {
            "request_id": rec.ComplaintId,
            "type": "Complaint",
            "sub_type": rec.ComplaintType,
            "response_status": rs,
            "overall_status": overall,
            "created_on": _fmt_date(rec.CreatedOn),
            "response_due_date": _fmt_date(due),
            "created_by": rec.CreatedBy,
            "created_by_name": None,
        }
        if _matches_tab(item, tab):
            items.append(item)

    return items


async def _collect_gifts(session, staff_id, is_admin, tab) -> list[dict]:
    stmt = select(GiftDeclarations)
    if not is_admin:
        stmt = stmt.where(GiftDeclarations.CreatedBy == staff_id)

    records = (await session.execute(stmt)).scalars().all()
    items = []
    for rec in records:
        due = _compute_due_date(rec.CreatedOn)
        overall = rec.OverallStatus or "Pending"
        rs = _response_status(due, overall)

        item = {
            "request_id": rec.GiftId,
            "type": "Gift Declaration",
            "sub_type": "Gift",
            "response_status": rs,
            "overall_status": overall,
            "created_on": _fmt_date(rec.CreatedOn),
            "response_due_date": _fmt_date(due),
            "created_by": rec.CreatedBy,
            "created_by_name": None,
        }
        if _matches_tab(item, tab):
            items.append(item)

    return items


def _matches_tab(item: dict, tab: str) -> bool:
    if tab == "all":
        return True
    overall = (item.get("overall_status") or "").lower()
    return overall != "completed"
