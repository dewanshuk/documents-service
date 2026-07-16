from datetime import datetime
from io import BytesIO

from openpyxl import Workbook
from sqlalchemy import select, func, cast, Float, case, and_

from db.db_manager import get_session
from services.excel_service import _sanitize_sheet_title
from db.models import AnnualDeclaration, DeclarationType, User, UserDeclarationStatus, as_declaration_name

ALLOWED_DESIGNATIONS = {"dvm", "ddvm", "sr dvm", "sr eo", "eo"}

HEAD_EXPORT_HEADERS = [
    "Staff ID",
    "Employee Name",
    "Department",
    "Annual Declaration Status",
    "Submitted On",
]


class HeadSummaryAccessError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _department_grouping_expr(designation: str):
    if designation in {"dvm", "ddvm"}:
        return func.regexp_replace(User.department, "^.*/", ""), "department"

    inner_replace = func.regexp_replace(User.department, "/[^/]+$", "")
    second_replace = func.regexp_replace(inner_replace, "^.*/", "")
    fallback = func.regexp_replace(User.department, "^.*/", "")
    grouping_expr = func.coalesce(func.nullif(second_replace, ""), fallback)

    if designation == "sr dvm":
        return grouping_expr, "division"

    return grouping_expr, "division_cluster"


def _resolve_head_scope(user: User) -> tuple[str, str]:
    if not user.designation:
        raise HeadSummaryAccessError("User designation not found")

    designation = user.designation.lower().strip()
    if designation not in ALLOWED_DESIGNATIONS:
        raise HeadSummaryAccessError(
            "User not authorized for this operation", status_code=403
        )

    if designation in {"dvm", "ddvm"}:
        filter_value = user.division
        filter_description = "division"
    elif designation == "sr dvm":
        filter_value = user.division_cluster
        filter_description = "division_cluster"
    else:
        filter_value = user.organization_vertical
        filter_description = "organization_vertical"

    if not filter_value:
        raise HeadSummaryAccessError(f"User {filter_description} not set")

    return filter_value, designation


def _export_status(status: str | None) -> str:
    if status == "completed":
        return "Submitted"
    return "In Progress"


def _format_submitted_on(submitted_at: datetime | None) -> str:
    if not submitted_at:
        return ""
    return submitted_at.isoformat()


async def _get_requesting_user(session, staff_id: str) -> User:
    user = (
        await session.execute(select(User).where(User.staff_id == staff_id))
    ).scalar_one_or_none()
    if not user:
        raise HeadSummaryAccessError("User not found", status_code=401)
    return user


async def _get_latest_declaration(session, declaration_name: str) -> AnnualDeclaration:
    declaration = (
        await session.execute(
            select(AnnualDeclaration)
            .where(AnnualDeclaration.declaration_name == declaration_name)
            .order_by(AnnualDeclaration.assigned_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if not declaration:
        raise HeadSummaryAccessError(
            f"No declaration cycle found for {declaration_name}"
        )
    return declaration


async def get_head_summary(staff_id: str) -> list[dict]:
    async with get_session() as session:
        user = await _get_requesting_user(session, staff_id)
        filter_value, designation = _resolve_head_scope(user)
        grouping_expr, grouping_label = _department_grouping_expr(designation)

        cobce_completed = func.sum(
            case(
                (
                    and_(
                        AnnualDeclaration.declaration_name == "COBCE/COI",
                        UserDeclarationStatus.status == "completed",
                    ),
                    1,
                ),
                else_=0,
            )
        )
        cobce_total = func.sum(
            case((AnnualDeclaration.declaration_name == "COBCE/COI", 1), else_=0)
        )
        cobce_percentage = func.coalesce(
            cast(cobce_completed, Float) / func.nullif(cobce_total, 0) * 100, 0
        )

        r518_completed = func.sum(
            case(
                (
                    and_(
                        AnnualDeclaration.declaration_name == "R5.18",
                        UserDeclarationStatus.status == "completed",
                    ),
                    1,
                ),
                else_=0,
            )
        )
        r518_total = func.sum(
            case((AnnualDeclaration.declaration_name == "R5.18", 1), else_=0)
        )
        r518_percentage = func.coalesce(
            cast(r518_completed, Float) / func.nullif(r518_total, 0) * 100, 0
        )

        stmt = (
            select(
                grouping_expr.label("group_name"),
                cobce_percentage.label("cobce_coi_percentage"),
                r518_percentage.label("r518_percentage"),
            )
            .select_from(User)
            .join(
                UserDeclarationStatus,
                User.staff_id == UserDeclarationStatus.staff_id,
            )
            .join(
                AnnualDeclaration,
                UserDeclarationStatus.declaration_id == AnnualDeclaration.id,
            )
            .where(User.department.ilike(f"%{filter_value}%"))
            .group_by(grouping_expr)
        )

        rows = (await session.execute(stmt)).all()
        return [
            {
                grouping_label: row.group_name,
                "cobce_coi_completion_percentage": round(
                    float(row.cobce_coi_percentage or 0), 2
                ),
                "r518_completion_percentage": round(
                    float(row.r518_percentage or 0), 2
                ),
            }
            for row in rows
        ]


async def generate_head_summary_export(
    staff_id: str, declaration_type: DeclarationType
) -> tuple[BytesIO, str]:
    declaration_name = as_declaration_name(declaration_type)

    async with get_session() as session:
        user = await _get_requesting_user(session, staff_id)
        filter_value, _designation = _resolve_head_scope(user)
        declaration = await _get_latest_declaration(session, declaration_name)

        stmt = (
            select(
                User.staff_id,
                User.username,
                User.department,
                UserDeclarationStatus.status,
                UserDeclarationStatus.submitted_at,
            )
            .join(
                UserDeclarationStatus,
                User.staff_id == UserDeclarationStatus.staff_id,
            )
            .where(
                User.department.ilike(f"%{filter_value}%"),
                UserDeclarationStatus.declaration_id == declaration.id,
            )
            .order_by(User.staff_id)
        )

        rows = (await session.execute(stmt)).all()

    wb = Workbook(write_only=True)
    ws = wb.create_sheet(title=_sanitize_sheet_title(declaration_name))
    ws.append(HEAD_EXPORT_HEADERS)

    for row in rows:
        ws.append(
            [
                row.staff_id,
                row.username or "",
                row.department or "",
                _export_status(row.status),
                _format_submitted_on(row.submitted_at),
            ]
        )

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    safe_name = declaration_name.replace("/", "_")
    filename = f"head_summary_{safe_name}_{declaration.financial_year}.xlsx"
    return output, filename
