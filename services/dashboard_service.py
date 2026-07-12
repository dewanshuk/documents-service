import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from io import BytesIO
from typing import Optional

from sqlalchemy import select, and_, or_, func, case
from openpyxl import Workbook

from core.constants import (
    RESPONSE_DUE_DAYS,
    DEFAULT_PAGE_SIZE,
    TYPE_FILTER_MAP,
    EXPORT_COLUMNS,
)
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
    as_declaration_name,
)
from utils.record_ids import build_annual_user_status_id
from utils.helpers import datetimeformatter, UTC, add_working_days


def _format_staff_display(staff_id: Optional[str], name_map: dict[str, str]) -> Optional[str]:
    if not staff_id:
        return None
    name = name_map.get(staff_id, staff_id)
    return f"{name} ({staff_id})"




@dataclass(frozen=True)
class TableConfig:
    model: type
    type_label: str
    pk_field: str
    search_fields: tuple[str, ...]
    sub_type_field: str = ""
    sub_type_value: str = ""
    updated_field: str = ""


HELPDESK_CONFIGS = [
    TableConfig(
        model=ComplianceQuery,
        type_label="Query",
        pk_field="QueryId",
        search_fields=("QueryId", "Title", "Description"),
        sub_type_field="QueryType",
        updated_field="LastUpdatedOn",
    ),
    TableConfig(
        model=Complaints,
        type_label="Complaint",
        pk_field="ComplaintId",
        search_fields=("ComplaintId", "ComplaintDetails"),
        sub_type_field="ComplaintType",
        updated_field="LastUpdatedOn",
    ),
    TableConfig(
        model=GiftDeclarations,
        type_label="Gift Declaration",
        pk_field="GiftId",
        search_fields=("GiftId", "Person"),
        sub_type_value="Gift",
        updated_field="LastUpdatedOn",
    ),
    TableConfig(
        model=COBCEDeclarations,
        type_label="Self Declaration",
        pk_field="COBCEId",
        search_fields=("COBCEId", "Description"),
        sub_type_value="COBCE",
        updated_field="LastUpdatedOn",
    ),
    TableConfig(
        model=COIDeclarations,
        type_label="Self Declaration",
        pk_field="COIId",
        search_fields=("COIId",),
        sub_type_value="COI",
        updated_field="LastUpdatedOn",
    ),
    TableConfig(
        model=R518Declarations,
        type_label="Self Declaration",
        pk_field="R518Id",
        search_fields=("R518Id",),
        sub_type_value="R5.18",
        updated_field="LastUpdatedOn",
    ),
]


@dataclass
class FilterParams:
    search: Optional[str] = None
    search_staff_ids: Optional[set[str]] = None
    sub_type: Optional[str] = None
    overall_status: Optional[str] = None
    response_status: Optional[str] = None
    updated_on_start: Optional[date] = None
    updated_on_end: Optional[date] = None
    response_due_start: Optional[date] = None
    response_due_end: Optional[date] = None
    per_table_limit: Optional[int] = None




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
    active_types = _parse_type_filters(type_filter)

    params = FilterParams(
        search=search.strip() if search else None,
        sub_type=sub_type,
        overall_status=overall_status,
        response_status=response_status,
        updated_on_start=updated_on_start,
        updated_on_end=updated_on_end,
        response_due_start=response_due_start,
        response_due_end=response_due_end,
        per_table_limit=page * page_size,
    )

    if params.search:
        async with get_session() as session:
            params.search_staff_ids = await _get_matching_staff_ids(
                session, params.search
            )

    active_configs = [c for c in HELPDESK_CONFIGS if c.type_label in active_types]
    include_annual = "Annual Declaration" in active_types

    data_tasks = [
        _collect_helpdesk(c, staff_id, is_admin, tab, params) for c in active_configs
    ]
    count_tasks = [
        _count_helpdesk(c, staff_id, is_admin, tab, params) for c in active_configs
    ]
    if include_annual:
        data_tasks.append(_collect_annual(staff_id, tab, params))
        count_tasks.append(_count_annual(staff_id, tab, params))

    all_results = await asyncio.gather(*data_tasks, *count_tasks)

    n_data = len(data_tasks)
    data_results = all_results[:n_data]
    count_results = list(all_results[n_data:])

    all_items = [item for group in data_results for item in group]
    all_items.sort(key=lambda x: _sort_key(x.get("_updated_on")), reverse=True)

    start = (page - 1) * page_size
    page_items = all_items[start : start + page_size]

    staff_ids = set()
    for item in page_items:
        for key in ("_staff_id", "_assigned_to", "_closed_by"):
            if item.get(key):
                staff_ids.add(item[key])

    async with get_session() as session:
        name_map = await _get_user_name_map(session, staff_ids)

    summary = _build_summary(active_configs, include_annual, count_results)
    total = sum(c["total"] for c in count_results)

    return {
        "items": [_finalize_item(item, name_map, is_admin) for item in page_items],
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
    active_types = _parse_type_filters(type_filter)

    params = FilterParams(
        search=search.strip() if search else None,
        sub_type=sub_type,
        overall_status=overall_status,
        response_status=response_status,
        updated_on_start=updated_on_start,
        updated_on_end=updated_on_end,
        response_due_start=response_due_start,
        response_due_end=response_due_end,
    )

    if params.search:
        async with get_session() as session:
            params.search_staff_ids = await _get_matching_staff_ids(
                session, params.search
            )

    active_configs = [c for c in HELPDESK_CONFIGS if c.type_label in active_types]
    include_annual = "Annual Declaration" in active_types

    tasks = [
        _collect_helpdesk(c, staff_id, is_admin, tab, params) for c in active_configs
    ]
    if include_annual:
        tasks.append(_collect_annual(staff_id, tab, params))

    results = await asyncio.gather(*tasks)
    all_items = [item for group in results for item in group]
    all_items.sort(key=lambda x: _sort_key(x.get("_updated_on")), reverse=True)

    staff_ids = set()
    for item in all_items:
        for key in ("_staff_id", "_assigned_to", "_closed_by"):
            if item.get(key):
                staff_ids.add(item[key])

    async with get_session() as session:
        name_map = await _get_user_name_map(session, staff_ids)

    formatted = [_finalize_item(item, name_map, is_admin) for item in all_items]

    wb = Workbook(write_only=True)
    ws = wb.create_sheet(title="Dashboard Export")
    ws.append(EXPORT_COLUMNS)
    for item in formatted:
        ws.append([
            item.get("request_id"),
            item.get("type"),
            item.get("sub_type"),
            item.get("response_status"),
            item.get("overall_status"),
            item.get("updated_on"),
            item.get("response_due_date"),
            item.get("updated_by"),
            item.get("pending_at"),
            item.get("closed_at"),
            item.get("closed_by"),
        ])

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return output



def _parse_type_filters(type_filter: Optional[str]) -> list[str]:
    """Parse comma-separated type_filter into resolved type labels.

    Returns all types when *type_filter* is empty/None.
    """
    if not type_filter or not type_filter.strip():
        return list(TYPE_FILTER_MAP.values())

    keys = [k.strip().lower() for k in type_filter.split(",") if k.strip()]
    labels: list[str] = []
    for key in keys:
        if key not in TYPE_FILTER_MAP:
            allowed = ", ".join(TYPE_FILTER_MAP)
            raise ValueError(f"Invalid type filter '{key}'. Allowed: {allowed}")
        label = TYPE_FILTER_MAP[key]
        if label not in labels:
            labels.append(label)
    return labels if labels else list(TYPE_FILTER_MAP.values())


def _response_status(due_date, overall_status: str) -> str:
    if overall_status and overall_status.lower() == "completed":
        return "Completed"
    if due_date is None:
        return "Due"
    today = date.today()
    if isinstance(due_date, datetime):
        due_date = due_date.date()
    return "Overdue" if due_date < today else "Due"


def _working_days_due_expr(updated_col, working_days: int):
    """SQL expression for due date after N working days (excludes Sat/Sun)."""
    base_date = func.date(updated_col)
    whens = []
    # PostgreSQL DOW: Sunday=0 ... Saturday=6
    sample_week = date(2024, 1, 7)
    for pg_dow in range(7):
        sample = sample_week + timedelta(days=pg_dow)
        due = add_working_days(sample, working_days)
        whens.append(
            (func.extract("dow", base_date) == pg_dow, base_date + (due - sample).days)
        )
    return case(*whens, else_=base_date + working_days)


def _compute_due_date(last_updated) -> Optional[date]:
    if last_updated is None:
        return None
    if isinstance(last_updated, datetime):
        return add_working_days(last_updated.date(), RESPONSE_DUE_DAYS)
    return add_working_days(last_updated, RESPONSE_DUE_DAYS)


def _normalize_datetime(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return None


def _sort_key(value) -> float:
    dt = _normalize_datetime(value)
    return dt.timestamp() if dt else 0.0


def _format_date(val) -> Optional[str]:
    if val is None:
        return None
    try:
        return datetimeformatter(val)
    except (ValueError, TypeError):
        return None


def _finalize_item(item: dict, name_map: dict[str, str], is_admin: bool) -> dict:
    staff_id = item.pop("_staff_id", None)
    updated_raw = item.pop("_updated_on", None)
    due_raw = item.pop("_response_due_raw", None)
    pending_at_raw = item.pop("_pending_at", None)
    assigned_to_raw = item.pop("_assigned_to", None)
    closed_at_raw = item.pop("_closed_at", None)
    closed_by_raw = item.pop("_closed_by", None)

    item["updated_on"] = _format_date(updated_raw)
    item["response_due_date"] = _format_date(due_raw)
    item["updated_by"] = _format_staff_display(staff_id, name_map)

    if pending_at_raw == 0:
        item["pending_at"] = _format_staff_display(staff_id, name_map)
    elif pending_at_raw == 1:
        if is_admin and assigned_to_raw:
            item["pending_at"] = _format_staff_display(assigned_to_raw, name_map)
        else:
            item["pending_at"] = "Compliance Team"
    else:
        item["pending_at"] = None

    if is_admin and assigned_to_raw:
        item["assigned_to"] = _format_staff_display(assigned_to_raw, name_map)
    elif assigned_to_raw or item["type"] != "Annual Declaration":
        item["assigned_to"] = None
    else:
        item["assigned_to"] = None

    item["closed_at"] = _format_date(closed_at_raw)

    item["closed_by"] = _format_staff_display(closed_by_raw, name_map)

    return item


async def _get_user_name_map(session, staff_ids: set[str]) -> dict[str, str]:
    if not staff_ids:
        return {}
    stmt = select(User.staff_id, User.username).where(User.staff_id.in_(staff_ids))
    rows = (await session.execute(stmt)).all()
    return {r.staff_id: (r.username or r.staff_id) for r in rows}


async def _get_matching_staff_ids(session, search: str) -> set[str]:
    pattern = f"%{search.strip()}%"
    rows = (await session.execute(
        select(User.staff_id).where(User.username.ilike(pattern))
    )).all()
    return {row.staff_id for row in rows}




def _get_updated_col(config: TableConfig):
    model = config.model
    if config.updated_field:
        return func.coalesce(getattr(model, config.updated_field), model.CreatedOn)
    return model.CreatedOn


def _helpdesk_where_clauses(
    config: TableConfig, staff_id: str, is_admin: bool, tab: str, params: FilterParams,
):
    """Build WHERE clauses for a helpdesk model. Returns None to skip this config."""
    model = config.model
    updated_col = _get_updated_col(config)
    due_expr = _working_days_due_expr(updated_col, RESPONSE_DUE_DAYS)
    today = date.today()
    clauses = []

    if not is_admin:
        clauses.append(model.CreatedBy == staff_id)

    if tab == "pending":
        clauses.append(func.lower(model.OverallStatus) != "completed")
        if is_admin:
            clauses.append(model.PendingAt == 1)
        else:
            clauses.append(model.PendingAt == 0)
    elif tab == "all":
        if is_admin:
            clauses.append(or_(
                model.PendingAt == 0,
                func.lower(model.OverallStatus) == "completed",
                model.PendingAt.is_(None),
            ))
        else:
            clauses.append(or_(
                model.PendingAt == 1,
                func.lower(model.OverallStatus) == "completed",
                model.PendingAt.is_(None),
            ))

    if params.overall_status:
        clauses.append(
            func.lower(model.OverallStatus) == params.overall_status.strip().lower()
        )

    if params.sub_type:
        if config.sub_type_field:
            clauses.append(
                func.lower(getattr(model, config.sub_type_field))
                == params.sub_type.strip().lower()
            )
        elif config.sub_type_value:
            if config.sub_type_value.lower() != params.sub_type.strip().lower():
                return None

    if params.updated_on_start:
        clauses.append(func.date(updated_col) >= params.updated_on_start)
    if params.updated_on_end:
        clauses.append(func.date(updated_col) <= params.updated_on_end)

    if params.response_due_start:
        clauses.append(due_expr >= params.response_due_start)
    if params.response_due_end:
        clauses.append(due_expr <= params.response_due_end)

    if params.response_status:
        rs = params.response_status.strip().lower()
        if rs == "completed":
            clauses.append(func.lower(model.OverallStatus) == "completed")
        elif rs == "overdue":
            clauses.append(func.lower(model.OverallStatus) != "completed")
            clauses.append(due_expr < today)
        elif rs == "due":
            clauses.append(func.lower(model.OverallStatus) != "completed")
            clauses.append(due_expr >= today)

    if params.search:
        pattern = f"%{params.search}%"
        conditions = [getattr(model, f).ilike(pattern) for f in config.search_fields]
        if params.search_staff_ids:
            conditions.append(model.CreatedBy.in_(params.search_staff_ids))
        if conditions:
            clauses.append(or_(*conditions))

    return clauses, updated_col, due_expr, today


def _format_helpdesk_record(config: TableConfig, rec) -> dict:
    pk_val = getattr(rec, config.pk_field)
    overall = rec.OverallStatus or "Pending"

    updated_on = rec.CreatedOn
    if config.updated_field:
        updated_on = getattr(rec, config.updated_field, None) or rec.CreatedOn

    due = _compute_due_date(updated_on)
    rs = _response_status(due, overall)

    sub_type = config.sub_type_value or (
        getattr(rec, config.sub_type_field, None) if config.sub_type_field else None
    )

    return {
        "request_id": pk_val,
        "type": config.type_label,
        "sub_type": sub_type,
        "response_status": rs,
        "overall_status": overall,
        "_staff_id": rec.CreatedBy,
        "_updated_on": updated_on,
        "_response_due_raw": due,
        "_pending_at": getattr(rec, "PendingAt", None),
        "_assigned_to": getattr(rec, "AssignedTo", None),
        "_closed_at": getattr(rec, "ClosureDate", None),
        "_closed_by": getattr(rec, "ClosedBy", None),
    }


async def _collect_helpdesk(
    config: TableConfig, staff_id: str, is_admin: bool, tab: str, params: FilterParams,
) -> list[dict]:
    result = _helpdesk_where_clauses(config, staff_id, is_admin, tab, params)
    if result is None:
        return []
    clauses, updated_col, _, _ = result

    stmt = select(config.model)
    if clauses:
        stmt = stmt.where(*clauses)
    stmt = stmt.order_by(updated_col.desc())
    if params.per_table_limit:
        stmt = stmt.limit(params.per_table_limit)

    async with get_session() as session:
        records = (await session.execute(stmt)).scalars().all()

    return [_format_helpdesk_record(config, rec) for rec in records]


async def _count_helpdesk(
    config: TableConfig, staff_id: str, is_admin: bool, tab: str, params: FilterParams,
) -> dict:
    result = _helpdesk_where_clauses(config, staff_id, is_admin, tab, params)
    if result is None:
        return {"total": 0, "due": 0, "overdue": 0}
    clauses, _, due_expr, today = result

    model = config.model
    stmt = select(
        func.count().label("total"),
        func.sum(case(
            (and_(func.lower(model.OverallStatus) != "completed", due_expr >= today), 1),
            else_=0,
        )).label("due"),
        func.sum(case(
            (and_(func.lower(model.OverallStatus) != "completed", due_expr < today), 1),
            else_=0,
        )).label("overdue"),
    ).select_from(model)
    if clauses:
        stmt = stmt.where(*clauses)

    async with get_session() as session:
        row = (await session.execute(stmt)).one()
        return {
            "total": row.total or 0,
            "due": int(row.due or 0),
            "overdue": int(row.overdue or 0),
        }




def _annual_where_clauses(staff_id: str, tab: str, params: FilterParams):
    today = date.today()
    updated_col = func.coalesce(
        UserDeclarationStatus.last_saved_at,
        UserDeclarationStatus.submitted_at,
        AnnualDeclaration.last_updated_at,
    )

    clauses = [
        AnnualDeclaration.assigned_date <= today,
        UserDeclarationStatus.notify.is_(True),
        UserDeclarationStatus.staff_id == staff_id,
    ]

    if tab == "pending":
        clauses.append(UserDeclarationStatus.status != "completed")

    if params.sub_type:
        clauses.append(
            AnnualDeclaration.declaration_name.ilike(params.sub_type.strip())
        )

    if params.overall_status:
        os_val = params.overall_status.strip().lower()
        if os_val == "completed":
            clauses.append(UserDeclarationStatus.status == "completed")
        else:
            clauses.append(UserDeclarationStatus.status != "completed")

    if params.search:
        pattern = f"%{params.search}%"
        clauses.append(or_(
            UserDeclarationStatus.id.ilike(pattern),
            AnnualDeclaration.id.ilike(pattern),
        ))

    if params.updated_on_start:
        clauses.append(func.date(updated_col) >= params.updated_on_start)
    if params.updated_on_end:
        clauses.append(func.date(updated_col) <= params.updated_on_end)

    if params.response_due_start:
        clauses.append(AnnualDeclaration.due_date >= params.response_due_start)
    if params.response_due_end:
        clauses.append(AnnualDeclaration.due_date <= params.response_due_end)

    if params.response_status:
        rs = params.response_status.strip().lower()
        if rs == "completed":
            clauses.append(UserDeclarationStatus.status == "completed")
        elif rs == "overdue":
            clauses.append(UserDeclarationStatus.status != "completed")
            clauses.append(AnnualDeclaration.due_date < today)
        elif rs == "due":
            clauses.append(UserDeclarationStatus.status != "completed")
            clauses.append(AnnualDeclaration.due_date >= today)

    return clauses, updated_col, today


def _format_annual_record(uds, decl) -> dict:
    status = uds.status
    if status in ("not_started", "Pending"):
        display_status = "Pending"
    elif status == "draft":
        display_status = "In-Progress"
    elif status == "completed":
        display_status = "Completed"
    else:
        display_status = status

    overall = "Completed" if display_status == "Completed" else "In-Progress"
    rs = _response_status(decl.due_date, overall)
    updated_on = uds.last_saved_at or uds.submitted_at or decl.last_updated_at
    request_id = uds.id or build_annual_user_status_id(uds.staff_id, decl.id)

    return {
        "request_id": request_id,
        "reference_id": decl.id,
        "type": "Annual Declaration",
        "sub_type": as_declaration_name(decl.declaration_name),
        "response_status": rs,
        "overall_status": overall,
        "_staff_id": uds.staff_id,
        "_updated_on": updated_on,
        "_response_due_raw": decl.due_date,
        "_pending_at": None,
        "_assigned_to": None,
        "_closed_at": None,
        "_closed_by": None,
        "declaration_status": status,
    }


async def _collect_annual(
    staff_id: str, tab: str, params: FilterParams,
) -> list[dict]:
    clauses, updated_col, _ = _annual_where_clauses(staff_id, tab, params)

    stmt = (
        select(UserDeclarationStatus, AnnualDeclaration)
        .join(AnnualDeclaration, UserDeclarationStatus.declaration_id == AnnualDeclaration.id)
        .where(*clauses)
        .order_by(updated_col.desc())
    )
    if params.per_table_limit:
        stmt = stmt.limit(params.per_table_limit)

    async with get_session() as session:
        rows = (await session.execute(stmt)).all()

    return [_format_annual_record(uds, decl) for uds, decl in rows]


async def _count_annual(
    staff_id: str, tab: str, params: FilterParams,
) -> dict:
    clauses, _, today = _annual_where_clauses(staff_id, tab, params)

    stmt = (
        select(
            func.count().label("total"),
            func.sum(case(
                (and_(
                    UserDeclarationStatus.status != "completed",
                    AnnualDeclaration.due_date >= today,
                ), 1),
                else_=0,
            )).label("due"),
            func.sum(case(
                (and_(
                    UserDeclarationStatus.status != "completed",
                    AnnualDeclaration.due_date < today,
                ), 1),
                else_=0,
            )).label("overdue"),
        )
        .select_from(UserDeclarationStatus)
        .join(AnnualDeclaration, UserDeclarationStatus.declaration_id == AnnualDeclaration.id)
        .where(*clauses)
    )

    async with get_session() as session:
        row = (await session.execute(stmt)).one()
        return {
            "total": row.total or 0,
            "due": int(row.due or 0),
            "overdue": int(row.overdue or 0),
        }




def _build_summary(active_configs: list[TableConfig], include_annual: bool, count_results: list[dict]) -> dict:
    type_totals: dict[str, int] = {}
    total_due = 0
    total_overdue = 0

    for i, config in enumerate(active_configs):
        label = config.type_label
        stats = count_results[i]
        type_totals[label] = type_totals.get(label, 0) + stats["total"]
        total_due += stats["due"]
        total_overdue += stats["overdue"]

    if include_annual:
        stats = count_results[len(active_configs)]
        type_totals["Annual Declaration"] = stats["total"]
        total_due += stats["due"]
        total_overdue += stats["overdue"]

    return {
        "total_due": total_due,
        "total_overdue": total_overdue,
        "annual_declarations": type_totals.get("Annual Declaration", 0),
        "self_declarations": type_totals.get("Self Declaration", 0),
        "queries": type_totals.get("Query", 0),
        "complaints": type_totals.get("Complaint", 0),
        "gifts": type_totals.get("Gift Declaration", 0),
    }



