import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from io import BytesIO
from typing import Optional

from sqlalchemy import select, and_, or_, func
from openpyxl import Workbook

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
DEFAULT_PAGE_SIZE = 10


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


async def _get_matching_staff_ids(session, search: str) -> set[str]:
    pattern = _search_pattern(search)
    rows = (
        await session.execute(
            select(User.staff_id).where(User.username.ilike(pattern))
        )
    ).all()
    return {row.staff_id for row in rows}


def _needs_python_post_filters(
    response_status: Optional[str],
    overall_status: Optional[str],
    response_due_start: Optional[date],
    response_due_end: Optional[date],
    resolved_type_filter: Optional[str],
) -> bool:
    if (response_status or "").strip() or response_due_start or response_due_end:
        return True
    if (overall_status or "").strip() and resolved_type_filter in (None, "Annual Declaration"):
        return True
    return False


async def get_dashboard(
    staff_id: str,
    is_admin: bool,
    tab: str = "pending",
    search: Optional[str] = None,
    type_filter: Optional[str] = None,
    sub_type: Optional[str] = None,
    response_status: Optional[str] = None,
    overall_status: Optional[str] = None,
    updated_on_start: Optional[date] = None,
    updated_on_end: Optional[date] = None,
    response_due_start: Optional[date] = None,
    response_due_end: Optional[date] = None,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> dict:
    resolved_type_filter = (
        _parse_type_filter(type_filter) if (type_filter or "").strip() else None
    )
    has_filters = _has_user_filters(
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
    python_post_filters = _needs_python_post_filters(
        response_status=response_status,
        overall_status=overall_status,
        response_due_start=response_due_start,
        response_due_end=response_due_end,
        resolved_type_filter=resolved_type_filter,
    )

    if has_filters and python_post_filters:
        all_items = await _build_dashboard_items(
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
            for_export=False,
            page=page,
            page_size=page_size,
            fetch_all_for_filter=True,
        )
        summary = _compute_summary(all_items)
        total = len(all_items)
        start = (page - 1) * page_size
        page_items = all_items[start : start + page_size]
    else:
        summary, total = await _compute_summary_and_total(
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
            resolved_type_filter=resolved_type_filter,
            has_filters=has_filters,
        )
        page_items = await _build_dashboard_items(
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
            for_export=False,
            page=page,
            page_size=page_size,
            fetch_all_for_filter=False,
        )

    return {
        "items": page_items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "summary": summary,
    }


async def get_dashboard_export_file(
    staff_id: str,
    is_admin: bool,
    tab: str = "pending",
    search: Optional[str] = None,
    type_filter: Optional[str] = None,
    sub_type: Optional[str] = None,
    response_status: Optional[str] = None,
    overall_status: Optional[str] = None,
    updated_on_start: Optional[date] = None,
    updated_on_end: Optional[date] = None,
    response_due_start: Optional[date] = None,
    response_due_end: Optional[date] = None,
) -> BytesIO:
    items = await _build_dashboard_items(
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
        for_export=True,
    )

    wb = Workbook(write_only=True)
    ws = wb.create_sheet(title="Dashboard Export")
    ws.append([
        "Request ID",
        "Type",
        "Sub Type",
        "Response Status",
        "Overall Status",
        "Created On",
        "Updated On",
        "Response Due Date",
        "Created By",
        "Created By Name",
    ])

    for item in items:
        ws.append([
            item.get("request_id"),
            item.get("type"),
            item.get("sub_type"),
            item.get("response_status"),
            item.get("overall_status"),
            item.get("created_on"),
            item.get("updated_on"),
            item.get("response_due_date"),
            item.get("created_by"),
            item.get("created_by_name"),
        ])

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return output


async def _build_dashboard_items(
    staff_id: str,
    is_admin: bool,
    tab: str,
    search: Optional[str],
    type_filter: Optional[str],
    sub_type: Optional[str],
    response_status: Optional[str],
    overall_status: Optional[str],
    updated_on_start: Optional[date],
    updated_on_end: Optional[date],
    response_due_start: Optional[date],
    response_due_end: Optional[date],
    for_export: bool = False,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    fetch_all_for_filter: bool = False,
) -> list[dict]:
    resolved_type_filter = (
        _parse_type_filter(type_filter) if (type_filter or "").strip() else None
    )
    has_filters = _has_user_filters(
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

    collectors = _select_collectors(resolved_type_filter)
    single_collector = len(collectors) == 1

    sql_offset = None
    sql_limit = None
    per_table_limit = None

    if for_export or fetch_all_for_filter:
        pass
    elif has_filters and single_collector:
        sql_offset = (page - 1) * page_size
        sql_limit = page_size
    else:
        per_table_limit = page * page_size

    params = CollectorParams(
        per_table_limit=per_table_limit,
        sql_offset=sql_offset,
        sql_limit=sql_limit,
        search=search.strip() if search else None,
        sub_type=sub_type,
        overall_status=overall_status,
        updated_on_start=updated_on_start,
        updated_on_end=updated_on_end,
    )

    if has_filters and params.search:
        async with get_session() as session:
            params.search_staff_ids = await _get_matching_staff_ids(session, params.search)

    grouped_items = await asyncio.gather(
        *[collector(staff_id, is_admin, tab, params) for collector in collectors]
    )
    items = [item for group in grouped_items for item in group]

    async with get_session() as session:
        all_staff = {i.get("created_by") for i in items if i.get("created_by")}
        name_map = await _get_user_name_map(session, all_staff)

    for item in items:
        cb = item.get("created_by")
        item["created_by_name"] = name_map.get(cb, cb) if cb else None
        item["_search_blob"] = _build_search_blob(
            item.get("_search_blob"),
            item.get("created_by_name"),
        )

    if has_filters:
        items = _apply_filters(
            items=items,
            search=search,
            type_filter=resolved_type_filter,
            sub_type=sub_type,
            response_status=response_status,
            overall_status=overall_status,
            updated_on_start=updated_on_start,
            updated_on_end=updated_on_end,
            response_due_start=response_due_start,
            response_due_end=response_due_end,
        )

    items.sort(key=lambda x: x.get("updated_on") or x.get("created_on") or "", reverse=True)

    if not for_export and not fetch_all_for_filter and not (has_filters and single_collector):
        start = (page - 1) * page_size
        items = items[start : start + page_size]

    for item in items:
        item.pop("_search_blob", None)

    return items


def _as_date(value) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        try:
            if "T" in value:
                return datetime.fromisoformat(value).date()
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _contains_ci(haystack: str, needle: str) -> bool:
    return needle.lower() in (haystack or "").lower()


def _matches_text_filter(value: Optional[str], expected: Optional[str]) -> bool:
    if not expected:
        return True
    return (value or "").strip().lower() == expected.strip().lower()


@dataclass
class CollectorParams:
    per_table_limit: Optional[int] = None
    sql_offset: Optional[int] = None
    sql_limit: Optional[int] = None
    search: Optional[str] = None
    search_staff_ids: Optional[set[str]] = None
    sub_type: Optional[str] = None
    overall_status: Optional[str] = None
    updated_on_start: Optional[date] = None
    updated_on_end: Optional[date] = None


def _has_user_filters(
    search: Optional[str],
    type_filter: Optional[str],
    sub_type: Optional[str],
    response_status: Optional[str],
    overall_status: Optional[str],
    updated_on_start: Optional[date],
    updated_on_end: Optional[date],
    response_due_start: Optional[date],
    response_due_end: Optional[date],
) -> bool:
    return any([
        (search or "").strip(),
        (type_filter or "").strip(),
        (sub_type or "").strip(),
        (response_status or "").strip(),
        (overall_status or "").strip(),
        updated_on_start,
        updated_on_end,
        response_due_start,
        response_due_end,
    ])


def _search_pattern(search: str) -> str:
    return f"%{search.strip()}%"


def _build_search_where(column_filters, staff_id_col, staff_ids: Optional[set[str]]):
    filters = list(column_filters)
    if staff_ids:
        filters.append(staff_id_col.in_(staff_ids))
    return or_(*filters)


def _apply_date_range_filters(stmt, date_col, start: Optional[date], end: Optional[date]):
    if start:
        stmt = stmt.where(func.date(date_col) >= start)
    if end:
        stmt = stmt.where(func.date(date_col) <= end)
    return stmt


def _apply_overall_status_filter(stmt, status_col, overall_status: Optional[str]):
    if overall_status:
        stmt = stmt.where(
            func.lower(status_col) == overall_status.strip().lower()
        )
    return stmt


def _apply_tab_pending_filter_helpdesk(stmt, status_col, tab: str):
    if tab == "pending":
        stmt = stmt.where(func.lower(status_col) != "completed")
    return stmt


def _apply_pagination(stmt, order_col, params: CollectorParams):
    stmt = stmt.order_by(order_col.desc())
    if params.sql_limit is not None:
        if params.sql_offset:
            stmt = stmt.offset(params.sql_offset)
        stmt = stmt.limit(params.sql_limit)
    elif params.per_table_limit:
        stmt = stmt.limit(params.per_table_limit)
    return stmt


def _select_collectors(resolved_type_filter: Optional[str]):
    if resolved_type_filter == "Annual Declaration":
        return [_collect_annual_declarations]
    if resolved_type_filter == "Self Declaration":
        return [_collect_self_declarations]
    if resolved_type_filter == "Query":
        return [_collect_queries]
    if resolved_type_filter == "Complaint":
        return [_collect_complaints]
    if resolved_type_filter == "Gift Declaration":
        return [_collect_gifts]
    return [
        _collect_annual_declarations,
        _collect_self_declarations,
        _collect_queries,
        _collect_complaints,
        _collect_gifts,
    ]


TYPE_FILTER_MAP = {
    "annual_declarations": "Annual Declaration",
    "self_declarations": "Self Declaration",
    "query": "Query",
    "gift": "Gift Declaration",
    "complaint": "Complaint",
}


def _parse_type_filter(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    key = value.strip().lower()
    if key not in TYPE_FILTER_MAP:
        allowed = ", ".join(TYPE_FILTER_MAP)
        raise ValueError(f"Invalid type filter. Allowed values: {allowed}")
    return TYPE_FILTER_MAP[key]


def _apply_filters(
    items: list[dict],
    search: Optional[str],
    type_filter: Optional[str],
    sub_type: Optional[str],
    response_status: Optional[str],
    overall_status: Optional[str],
    updated_on_start: Optional[date],
    updated_on_end: Optional[date],
    response_due_start: Optional[date],
    response_due_end: Optional[date],
) -> list[dict]:
    filtered = []
    search_q = (search or "").strip().lower()

    for item in items:
        if search_q:
            search_blob = item.get("_search_blob") or ""
            if not _contains_ci(search_blob, search_q):
                continue

        if not _matches_text_filter(item.get("type"), type_filter):
            continue
        if sub_type:
            item_type = (item.get("type") or "").strip().lower()
            if item_type not in {"annual declaration", "self declaration"}:
                continue
            if not _matches_text_filter(item.get("sub_type"), sub_type):
                continue
        if not _matches_text_filter(item.get("response_status"), response_status):
            continue
        if not _matches_text_filter(item.get("overall_status"), overall_status):
            continue

        updated_on = _as_date(item.get("updated_on"))
        if updated_on_start and (updated_on is None or updated_on < updated_on_start):
            continue
        if updated_on_end and (updated_on is None or updated_on > updated_on_end):
            continue

        due_on = _as_date(item.get("response_due_date"))
        if response_due_start and (due_on is None or due_on < response_due_start):
            continue
        if response_due_end and (due_on is None or due_on > response_due_end):
            continue

        filtered.append(item)

    return filtered


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


def _empty_stats() -> dict:
    return {"total": 0, "due": 0, "overdue": 0}


def _merge_stats(*stats: dict) -> dict:
    return {
        "total": sum(s["total"] for s in stats),
        "due": sum(s["due"] for s in stats),
        "overdue": sum(s["overdue"] for s in stats),
    }


def _stats_to_summary(
    annual: dict,
    self_decl: dict,
    queries: dict,
    complaints: dict,
    gifts: dict,
) -> dict:
    combined = _merge_stats(annual, self_decl, queries, complaints, gifts)
    return {
        "total_due": combined["due"] + combined["overdue"],
        "total_overdue": combined["overdue"],
        "annual_declarations": annual["total"],
        "self_declarations": self_decl["total"],
        "queries": queries["total"],
        "complaints": complaints["total"],
        "gifts": gifts["total"],
    }


async def _prepare_stats_params(
    search: Optional[str],
    sub_type: Optional[str],
    overall_status: Optional[str],
    updated_on_start: Optional[date],
    updated_on_end: Optional[date],
    has_filters: bool,
) -> CollectorParams:
    params = CollectorParams(
        search=search.strip() if search else None,
        sub_type=sub_type,
        overall_status=overall_status,
        updated_on_start=updated_on_start,
        updated_on_end=updated_on_end,
    )
    if has_filters and params.search:
        async with get_session() as session:
            params.search_staff_ids = await _get_matching_staff_ids(session, params.search)
    return params


async def _compute_summary_and_total(
    staff_id: str,
    is_admin: bool,
    tab: str,
    search: Optional[str],
    type_filter: Optional[str],
    sub_type: Optional[str],
    response_status: Optional[str],
    overall_status: Optional[str],
    updated_on_start: Optional[date],
    updated_on_end: Optional[date],
    response_due_start: Optional[date],
    response_due_end: Optional[date],
    resolved_type_filter: Optional[str],
    has_filters: bool,
) -> tuple[dict, int]:
    params = await _prepare_stats_params(
        search=search,
        sub_type=sub_type,
        overall_status=overall_status,
        updated_on_start=updated_on_start,
        updated_on_end=updated_on_end,
        has_filters=has_filters,
    )

    include_annual = resolved_type_filter in (None, "Annual Declaration")
    include_self = resolved_type_filter in (None, "Self Declaration")
    include_query = resolved_type_filter in (None, "Query")
    include_complaint = resolved_type_filter in (None, "Complaint")
    include_gift = resolved_type_filter in (None, "Gift Declaration")

    tasks = []
    task_keys = []
    if include_annual:
        tasks.append(_stats_annual_declarations(staff_id, tab, params))
        task_keys.append("annual")
    if include_self:
        tasks.append(_stats_self_declarations(staff_id, is_admin, tab, params))
        task_keys.append("self")
    if include_query:
        tasks.append(_stats_queries(staff_id, is_admin, tab, params))
        task_keys.append("query")
    if include_complaint:
        tasks.append(_stats_complaints(staff_id, is_admin, tab, params))
        task_keys.append("complaint")
    if include_gift:
        tasks.append(_stats_gifts(staff_id, is_admin, tab, params))
        task_keys.append("gift")

    results = await asyncio.gather(*tasks) if tasks else []
    stats_map = dict(zip(task_keys, results))

    annual = stats_map.get("annual", _empty_stats())
    self_decl = stats_map.get("self", _empty_stats())
    queries = stats_map.get("query", _empty_stats())
    complaints = stats_map.get("complaint", _empty_stats())
    gifts = stats_map.get("gift", _empty_stats())

    summary = _stats_to_summary(annual, self_decl, queries, complaints, gifts)
    total = summary["annual_declarations"] + summary["self_declarations"] + summary["queries"] + summary["complaints"] + summary["gifts"]
    return summary, total


def _helpdesk_due_date_expr(model):
    return func.date(model.CreatedOn) + SELF_DECL_DUE_DAYS


async def _count_stmt(session, stmt) -> int:
    count_stmt = select(func.count()).select_from(stmt.subquery())
    return (await session.execute(count_stmt)).scalar_one()


async def _stats_annual_declarations(staff_id, tab, params: CollectorParams) -> dict:
    async with get_session() as session:
        today = date.today()
        updated_col = func.coalesce(
            UserDeclarationStatus.last_saved_at,
            UserDeclarationStatus.submitted_at,
            AnnualDeclaration.last_updated_at,
        )
        base = (
            select(UserDeclarationStatus, AnnualDeclaration)
            .join(
                AnnualDeclaration,
                UserDeclarationStatus.declaration_id == AnnualDeclaration.id,
            )
            .where(
                and_(
                    AnnualDeclaration.assigned_date <= today,
                    UserDeclarationStatus.notify.is_(True),
                    UserDeclarationStatus.staff_id == staff_id,
                )
            )
        )
        if tab == "pending":
            base = base.where(UserDeclarationStatus.status != "completed")
        if params.sub_type:
            base = base.where(
                AnnualDeclaration.declaration_name.ilike(params.sub_type.strip())
            )
        if params.search:
            pattern = _search_pattern(params.search)
            base = base.where(
                or_(
                    UserDeclarationStatus.id.ilike(pattern),
                    AnnualDeclaration.reference_id.ilike(pattern),
                )
            )
        base = _apply_date_range_filters(
            base, updated_col, params.updated_on_start, params.updated_on_end
        )

        total = await _count_stmt(session, base)
        open_items = base.where(UserDeclarationStatus.status != "completed")
        overdue = await _count_stmt(
            session, open_items.where(AnnualDeclaration.due_date < today)
        )
        due = await _count_stmt(
            session, open_items.where(AnnualDeclaration.due_date >= today)
        )
        return {"total": total, "due": due, "overdue": overdue}


async def _stats_helpdesk_model(
    session,
    model,
    pk_field: str,
    staff_id: str,
    is_admin: bool,
    tab: str,
    params: CollectorParams,
) -> dict:
    if hasattr(model, "LastUpdatedOn"):
        updated_col = func.coalesce(model.LastUpdatedOn, model.CreatedOn)
    else:
        updated_col = model.CreatedOn

    base = select(model)
    if not is_admin:
        base = base.where(model.CreatedBy == staff_id)
    base = _apply_tab_pending_filter_helpdesk(base, model.OverallStatus, tab)
    base = _apply_overall_status_filter(base, model.OverallStatus, params.overall_status)
    base = _apply_date_range_filters(
        base, updated_col, params.updated_on_start, params.updated_on_end
    )
    if params.search:
        pattern = _search_pattern(params.search)
        search_filters = [getattr(model, pk_field).ilike(pattern)]
        if hasattr(model, "Description"):
            search_filters.append(model.Description.ilike(pattern))
        if model is GiftDeclarations:
            search_filters.append(model.Person.ilike(pattern))
        if model is Complaints:
            search_filters.append(model.ComplaintDetails.ilike(pattern))
        if model is ComplianceQuery:
            search_filters.extend([
                model.Title.ilike(pattern),
                model.Description.ilike(pattern),
            ])
        base = base.where(
            _build_search_where(search_filters, model.CreatedBy, params.search_staff_ids)
        )

    total = await _count_stmt(session, base)
    today = date.today()
    due_date_expr = _helpdesk_due_date_expr(model)
    open_items = base.where(func.lower(model.OverallStatus) != "completed")
    overdue = await _count_stmt(session, open_items.where(due_date_expr < today))
    due = await _count_stmt(session, open_items.where(due_date_expr >= today))
    return {"total": total, "due": due, "overdue": overdue}


async def _stats_self_declarations(staff_id, is_admin, tab, params: CollectorParams) -> dict:
    models = SELF_DECLARATION_MODELS
    if params.sub_type:
        models = [
            entry
            for entry in SELF_DECLARATION_MODELS
            if entry[1].lower() == params.sub_type.strip().lower()
        ]
        if not models:
            return _empty_stats()

    async with get_session() as session:
        totals = _empty_stats()
        for model, _, pk_field in models:
            stats = await _stats_helpdesk_model(
                session, model, pk_field, staff_id, is_admin, tab, params
            )
            totals = _merge_stats(totals, stats)
        return totals


async def _stats_queries(staff_id, is_admin, tab, params: CollectorParams) -> dict:
    async with get_session() as session:
        return await _stats_helpdesk_model(
            session, ComplianceQuery, "QueryId", staff_id, is_admin, tab, params
        )


async def _stats_complaints(staff_id, is_admin, tab, params: CollectorParams) -> dict:
    async with get_session() as session:
        return await _stats_helpdesk_model(
            session, Complaints, "ComplaintId", staff_id, is_admin, tab, params
        )


async def _stats_gifts(staff_id, is_admin, tab, params: CollectorParams) -> dict:
    async with get_session() as session:
        return await _stats_helpdesk_model(
            session, GiftDeclarations, "GiftId", staff_id, is_admin, tab, params
        )


def _build_search_blob(*parts) -> str:
    return " | ".join(
        str(part).strip() for part in parts if part is not None and str(part).strip()
    )


async def _collect_annual_declarations(staff_id,is_admin, tab, params: CollectorParams) -> list[dict]:
    """
    Annual declarations are always scoped to the logged-in user (admin included).
    Shown only when Excel has been processed with notify=True.
    """
    async with get_session() as session:
        items = []
        today = date.today()
        updated_col = func.coalesce(
            UserDeclarationStatus.last_saved_at,
            UserDeclarationStatus.submitted_at,
            AnnualDeclaration.last_updated_at,
        )

        stmt = (
            select(UserDeclarationStatus, AnnualDeclaration)
            .join(
                AnnualDeclaration,
                UserDeclarationStatus.declaration_id == AnnualDeclaration.id,
            )
            .where(
                and_(
                    AnnualDeclaration.assigned_date <= today,
                    UserDeclarationStatus.notify.is_(True),
                    UserDeclarationStatus.staff_id == staff_id,
                )
            )
        )

        if tab == "pending":
            stmt = stmt.where(UserDeclarationStatus.status != "completed")

        if params.sub_type:
            stmt = stmt.where(
                AnnualDeclaration.declaration_name.ilike(params.sub_type.strip())
            )

        if params.search:
            pattern = _search_pattern(params.search)
            stmt = stmt.where(
                or_(
                    UserDeclarationStatus.id.ilike(pattern),
                    AnnualDeclaration.reference_id.ilike(pattern),
                )
            )

        stmt = _apply_date_range_filters(
            stmt, updated_col, params.updated_on_start, params.updated_on_end
        )
        stmt = _apply_pagination(stmt, updated_col, params)

        rows = (await session.execute(stmt)).all()

        for uds, decl in rows:
            item = _build_annual_item(
                decl=decl,
                status=uds.status,
                item_staff_id=uds.staff_id,
                submitted_at=uds.submitted_at,
                user_status_id=uds.id,
                updated_on=uds.last_saved_at or uds.submitted_at or decl.last_updated_at,
            )
            if _matches_tab(item, tab):
                items.append(item)

    return items


def _build_annual_item(
    decl: AnnualDeclaration,
    status: str,
    item_staff_id,
    submitted_at,
    user_status_id=None,
    updated_on=None,
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
    if not request_id and item_staff_id and decl.reference_id:
        request_id = build_annual_user_status_id(item_staff_id, decl.reference_id)
    elif not request_id:
        request_id = decl.reference_id

    updated_val = updated_on or submitted_at or decl.last_updated_at or decl.assigned_date
    return {
        "request_id": request_id,
        "reference_id": decl.reference_id,
        "staff_id": item_staff_id,
        "type": "Annual Declaration",
        "sub_type": as_declaration_name(decl.declaration_name),
        "response_status": response_status,
        "overall_status": overall,
        "created_on": _fmt_date(decl.assigned_date),
        "updated_on": _fmt_date(updated_val),
        "response_due_date": _fmt_date(due),
        "created_by": item_staff_id,
        "created_by_name": None,
        "declaration_status": status,
        "_search_blob": _build_search_blob(
            request_id,
            decl.reference_id,
        ),
    }


SELF_DECLARATION_MODELS = [
    (COBCEDeclarations, "COBCE", "COBCEId"),
    (COIDeclarations, "COI", "COIId"),
    (R518Declarations, "R5.18", "R518Id"),
]


async def _collect_self_declarations(
    staff_id, is_admin, tab, params: CollectorParams
) -> list[dict]:
    async with get_session() as session:
        items = []
        models = SELF_DECLARATION_MODELS
        if params.sub_type:
            models = [
                entry
                for entry in SELF_DECLARATION_MODELS
                if entry[1].lower() == params.sub_type.strip().lower()
            ]
            if not models:
                return []

        for model, sub_type, pk_field in models:
            if hasattr(model, "LastUpdatedOn"):
                updated_col = func.coalesce(model.LastUpdatedOn, model.CreatedOn)
            else:
                updated_col = model.CreatedOn

            stmt = select(model)
            if not is_admin:
                stmt = stmt.where(model.CreatedBy == staff_id)

            stmt = _apply_tab_pending_filter_helpdesk(stmt, model.OverallStatus, tab)
            stmt = _apply_overall_status_filter(stmt, model.OverallStatus, params.overall_status)
            stmt = _apply_date_range_filters(
                stmt, updated_col, params.updated_on_start, params.updated_on_end
            )

            if params.search:
                pattern = _search_pattern(params.search)
                search_filters = [getattr(model, pk_field).ilike(pattern)]
                if hasattr(model, "Description"):
                    search_filters.append(model.Description.ilike(pattern))
                stmt = stmt.where(
                    _build_search_where(
                        search_filters, model.CreatedBy, params.search_staff_ids
                    )
                )

            stmt = _apply_pagination(stmt, updated_col, params)

            records = (await session.execute(stmt)).scalars().all()
            for rec in records:
                request_id = getattr(rec, pk_field)
                due = _compute_due_date(rec.CreatedOn)
                overall = rec.OverallStatus or "Pending"
                rs = _response_status(due, overall)
                updated_on = getattr(rec, "LastUpdatedOn", None) or rec.CreatedOn
                description = getattr(rec, "Description", None)
                if not isinstance(description, str):
                    description = None

                item = {
                    "request_id": request_id,
                    "type": "Self Declaration",
                    "sub_type": sub_type,
                    "response_status": rs,
                    "overall_status": overall,
                    "created_on": _fmt_date(rec.CreatedOn),
                    "updated_on": _fmt_date(updated_on),
                    "response_due_date": _fmt_date(due),
                    "created_by": rec.CreatedBy,
                    "created_by_name": None,
                    "_search_blob": _build_search_blob(request_id, description),
                }
                if _matches_tab(item, tab):
                    items.append(item)

    return items


async def _collect_queries(staff_id, is_admin, tab, params: CollectorParams) -> list[dict]:
    async with get_session() as session:
        updated_col = func.coalesce(ComplianceQuery.LastUpdatedOn, ComplianceQuery.CreatedOn)
        stmt = select(ComplianceQuery)
        if not is_admin:
            stmt = stmt.where(ComplianceQuery.CreatedBy == staff_id)

        stmt = _apply_tab_pending_filter_helpdesk(stmt, ComplianceQuery.OverallStatus, tab)
        stmt = _apply_overall_status_filter(stmt, ComplianceQuery.OverallStatus, params.overall_status)
        stmt = _apply_date_range_filters(
            stmt, updated_col, params.updated_on_start, params.updated_on_end
        )

        if params.search:
            pattern = _search_pattern(params.search)
            stmt = stmt.where(
                _build_search_where(
                    [
                        ComplianceQuery.QueryId.ilike(pattern),
                        ComplianceQuery.Title.ilike(pattern),
                        ComplianceQuery.Description.ilike(pattern),
                    ],
                    ComplianceQuery.CreatedBy,
                    params.search_staff_ids,
                )
            )

        stmt = _apply_pagination(stmt, updated_col, params)

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
                "updated_on": _fmt_date(rec.LastUpdatedOn or rec.CreatedOn),
                "response_due_date": _fmt_date(due),
                "created_by": rec.CreatedBy,
                "created_by_name": None,
                "_search_blob": _build_search_blob(
                    rec.QueryId,
                    rec.Title,
                    rec.Description,
                ),
            }
            if _matches_tab(item, tab):
                items.append(item)

    return items


async def _collect_complaints(staff_id, is_admin, tab, params: CollectorParams) -> list[dict]:
    async with get_session() as session:
        updated_col = func.coalesce(Complaints.LastUpdatedOn, Complaints.CreatedOn)
        stmt = select(Complaints)
        if not is_admin:
            stmt = stmt.where(Complaints.CreatedBy == staff_id)

        stmt = _apply_tab_pending_filter_helpdesk(stmt, Complaints.OverallStatus, tab)
        stmt = _apply_overall_status_filter(stmt, Complaints.OverallStatus, params.overall_status)
        stmt = _apply_date_range_filters(
            stmt, updated_col, params.updated_on_start, params.updated_on_end
        )

        if params.search:
            pattern = _search_pattern(params.search)
            stmt = stmt.where(
                _build_search_where(
                    [
                        Complaints.ComplaintId.ilike(pattern),
                        Complaints.ComplaintDetails.ilike(pattern),
                    ],
                    Complaints.CreatedBy,
                    params.search_staff_ids,
                )
            )

        stmt = _apply_pagination(stmt, updated_col, params)

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
                "updated_on": _fmt_date(rec.LastUpdatedOn or rec.CreatedOn),
                "response_due_date": _fmt_date(due),
                "created_by": rec.CreatedBy,
                "created_by_name": None,
                "_search_blob": _build_search_blob(
                    rec.ComplaintId,
                    rec.ComplaintDetails,
                ),
            }
            if _matches_tab(item, tab):
                items.append(item)

    return items


async def _collect_gifts(staff_id, is_admin, tab, params: CollectorParams) -> list[dict]:
    async with get_session() as session:
        updated_col = func.coalesce(GiftDeclarations.ClosureDate, GiftDeclarations.CreatedOn)
        stmt = select(GiftDeclarations)
        if not is_admin:
            stmt = stmt.where(GiftDeclarations.CreatedBy == staff_id)

        stmt = _apply_tab_pending_filter_helpdesk(stmt, GiftDeclarations.OverallStatus, tab)
        stmt = _apply_overall_status_filter(stmt, GiftDeclarations.OverallStatus, params.overall_status)
        stmt = _apply_date_range_filters(
            stmt, updated_col, params.updated_on_start, params.updated_on_end
        )

        if params.search:
            pattern = _search_pattern(params.search)
            stmt = stmt.where(
                _build_search_where(
                    [
                        GiftDeclarations.GiftId.ilike(pattern),
                        GiftDeclarations.Person.ilike(pattern),
                    ],
                    GiftDeclarations.CreatedBy,
                    params.search_staff_ids,
                )
            )

        stmt = _apply_pagination(stmt, updated_col, params)

        records = (await session.execute(stmt)).scalars().all()
        items = []
        for rec in records:
            due = _compute_due_date(rec.CreatedOn)
            overall = rec.OverallStatus or "Pending"
            rs = _response_status(due, overall)
            updated_on = rec.ClosureDate or rec.CreatedOn

            item = {
                "request_id": rec.GiftId,
                "type": "Gift Declaration",
                "sub_type": "Gift",
                "response_status": rs,
                "overall_status": overall,
                "created_on": _fmt_date(rec.CreatedOn),
                "updated_on": _fmt_date(updated_on),
                "response_due_date": _fmt_date(due),
                "created_by": rec.CreatedBy,
                "created_by_name": None,
                "_search_blob": _build_search_blob(rec.GiftId, rec.Person),
            }
            if _matches_tab(item, tab):
                items.append(item)

    return items


def _matches_tab(item: dict, tab: str) -> bool:
    if tab == "all":
        return True
    overall = (item.get("overall_status") or "").lower()
    return overall != "completed"
