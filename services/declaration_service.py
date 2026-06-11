from datetime import date, datetime
from enum import Enum
from uuid import UUID

from sqlalchemy import select, and_, cast, String, func
from sqlalchemy.orm import selectinload

from db.db_manager import get_session
from db.models import (
    AnnualDeclaration,
    User,
    UserDeclarationStatus,
    UserDeclarationResponse,
    IST,
)
from db.validators import AnnualDeclarationFilters
from api.routes.annual_dec.question_config import (
    CONFLICT_RESPONSES,
    validate_submission_responses,
)


def _row_to_dict(row):
    if hasattr(row, "__dict__"):
        return {k: v for k, v in row.__dict__.items() if k != "_sa_instance_state"}
    if isinstance(row, dict):
        return row.copy()
    return dict(row)


def _serialize(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def is_declaration_visible(assigned_date: date) -> bool:
    return assigned_date <= date.today()


def _ensure_declaration_accessible(declaration: AnnualDeclaration) -> None:
    if not is_declaration_visible(declaration.assigned_date):
        raise ValueError(
            f"Declaration is not available yet. It becomes visible on "
            f"{declaration.assigned_date.isoformat()}."
        )


async def save_user_declaration(
    declaration_id: UUID,
    staff_id: str,
    responses: list[dict],
    status: str,
) -> dict:
    is_submit = status == "submit"

    async with get_session() as session:
        declaration = await session.get(AnnualDeclaration, declaration_id)
        if not declaration:
            raise ValueError("Declaration not found")
        _ensure_declaration_accessible(declaration)

        decl_name = declaration.declaration_name.value

        if is_submit:
            errors = validate_submission_responses(responses, decl_name)
            if errors:
                raise ValueError("; ".join(errors))

        stmt = select(UserDeclarationStatus).where(
            and_(
                UserDeclarationStatus.declaration_id == declaration_id,
                UserDeclarationStatus.staff_id == staff_id,
            )
        )
        status_record = (await session.execute(stmt)).scalar_one_or_none()

        if not status_record:
            status_record = UserDeclarationStatus(
                declaration_id=declaration_id,
                staff_id=staff_id,
                status="draft",
            )
            session.add(status_record)
            await session.flush()
        elif status_record.status == "not_started":
            status_record.status = "draft"

        for resp in responses:
            existing_stmt = select(UserDeclarationResponse).where(
                and_(
                    UserDeclarationResponse.declaration_status_id == status_record.id,
                    UserDeclarationResponse.question_id == resp["question_id"],
                )
            )
            existing = (await session.execute(existing_stmt)).scalar_one_or_none()

            if existing:
                existing.response = resp["response"]
                existing.declaration_details = resp.get("declaration_details")
                existing.updated_at = datetime.now(IST)
            else:
                session.add(
                    UserDeclarationResponse(
                        declaration_status_id=status_record.id,
                        question_id=resp["question_id"],
                        response=resp["response"],
                        declaration_details=resp.get("declaration_details"),
                    )
                )

        await session.flush()

        all_resp_stmt = select(UserDeclarationResponse.response).where(
            UserDeclarationResponse.declaration_status_id == status_record.id
        )
        all_resp_rows = (await session.execute(all_resp_stmt)).all()
        has_conflicts = any(r[0] in CONFLICT_RESPONSES for r in all_resp_rows)

        status_record.has_conflicts = has_conflicts
        status_record.last_saved_at = datetime.now(IST)

        if is_submit:
            status_record.status = "completed"
            status_record.submitted_at = datetime.now(IST)
        elif status_record.status != "completed":
            status_record.status = "draft"

        await session.commit()

        return {
            "id": str(status_record.id),
            "status": status_record.status,
            "has_conflicts": status_record.has_conflicts,
        }


def _apply_declaration_filters(stmt, filters: AnnualDeclarationFilters):
    if filters.declaration_name:
        stmt = stmt.where(
            cast(AnnualDeclaration.declaration_name, String).ilike(
                f"%{filters.declaration_name}%"
            )
        )
    if filters.financial_year:
        stmt = stmt.where(AnnualDeclaration.financial_year == filters.financial_year)
    if filters.assigned_date_from:
        stmt = stmt.where(AnnualDeclaration.assigned_date >= filters.assigned_date_from)
    if filters.assigned_date_to:
        stmt = stmt.where(AnnualDeclaration.assigned_date <= filters.assigned_date_to)
    if filters.due_date_from:
        stmt = stmt.where(AnnualDeclaration.due_date >= filters.due_date_from)
    if filters.due_date_to:
        stmt = stmt.where(AnnualDeclaration.due_date <= filters.due_date_to)
    if filters.activity_closure_date_from:
        stmt = stmt.where(
            AnnualDeclaration.activity_closure_date
            >= filters.activity_closure_date_from
        )
    if filters.activity_closure_date_to:
        stmt = stmt.where(
            AnnualDeclaration.activity_closure_date <= filters.activity_closure_date_to
        )
    return stmt


async def list_declarations(
    filters: AnnualDeclarationFilters,
    page: int = 1,
    page_size: int = 25,
) -> dict:
    """Admin-only: list declarations with optional filters and pagination."""
    async with get_session() as session:
        decl_stmt = select(AnnualDeclaration)
        decl_stmt = _apply_declaration_filters(decl_stmt, filters)

        total = await session.scalar(
            select(func.count()).select_from(decl_stmt.subquery())
        )

        offset = (page - 1) * page_size
        decl_stmt = (
            decl_stmt.order_by(AnnualDeclaration.last_updated_at.desc())
            .limit(page_size)
            .offset(offset)
        )
        declarations = (await session.execute(decl_stmt)).scalars().all()

        items = [
            {
                "declaration_id": str(decl.id),
                "declaration_name": decl.declaration_name.value,
                "financial_year": decl.financial_year,
                "assigned_date": decl.assigned_date.isoformat(),
                "due_date": decl.due_date.isoformat(),
                "activity_closure_date": decl.activity_closure_date.isoformat(),
                "status": decl.status,
                "pending_count": decl.pending_count,
                "total_count": decl.total_count,
            }
            for decl in declarations
        ]

        return {
            "items": items,
            "total": total or 0,
            "page": page,
            "page_size": page_size,
        }


async def get_declaration_user_responses(
    declaration_id: UUID,
    staff_id: str,
) -> dict:
    async with get_session() as session:
        declaration = await session.get(AnnualDeclaration, declaration_id)
        if not declaration:
            raise ValueError("Declaration not found")

        stmt = (
            select(UserDeclarationStatus)
            .options(selectinload(UserDeclarationStatus.responses))
            .where(
                and_(
                    UserDeclarationStatus.declaration_id == declaration_id,
                    UserDeclarationStatus.staff_id == staff_id,
                )
            )
        )
        status_record = (await session.execute(stmt)).scalar_one_or_none()

        user = await session.get(User, staff_id)

        if not status_record:
            return {
                "declaration_id": str(declaration_id),
                "declaration_name": declaration.declaration_name.value,
                "financial_year": declaration.financial_year,
                "staff_id": staff_id,
                "name": user.username if user else None,
                "email": user.email if user else None,
                "department": user.department if user else None,
                "declaration_status": "not_started",
                "has_conflicts": False,
                "submitted_at": None,
                "responses": [],
            }

        return {
            "declaration_id": str(declaration_id),
            "declaration_name": declaration.declaration_name.value,
            "financial_year": declaration.financial_year,
            "staff_id": staff_id,
            "name": user.username if user else None,
            "email": user.email if user else None,
            "department": user.department if user else None,
            "declaration_status": status_record.status,
            "has_conflicts": status_record.has_conflicts,
            "submitted_at": (
                status_record.submitted_at.isoformat()
                if status_record.submitted_at
                else None
            ),
            "responses": [
                {
                    "question_id": r.question_id,
                    "response": r.response,
                    "declaration_details": r.declaration_details,
                }
                for r in status_record.responses
            ],
        }
