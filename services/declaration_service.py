from datetime import date, datetime
from enum import Enum
from uuid import UUID

from sqlalchemy import select, and_, cast, String, func, delete
from sqlalchemy.orm import selectinload

from db.db_manager import get_session
from db.models import (
    AnnualDeclaration,
    User,
    UserDeclarationStatus,
    UserDeclarationResponse,
    IST,
    as_declaration_name,
)
from db.models.helpdesk import COBCEDeclarations, COIDeclarations
from utils.helpers import db_timestamp_now, now_ist
from utils.record_ids import (
    build_annual_user_status_id,
    next_self_decl_id,
)
from storage.storage_ops import init_json
from db.validators import AnnualDeclarationFilters
from api.routes.annual_dec.question_config import (
    CONFLICT_RESPONSES,
    get_question_config,
    validate_submission_responses,
)

# Single user_declaration_responses row holds the full form JSON.
FORM_RESPONSES_QUESTION_ID = "FORM_RESPONSES"


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


def _default_responses(decl_name: str) -> list[dict]:
    return [
        {
            "question_id": qid,
            "response": None,
            "declaration_details": None,
        }
        for qid in get_question_config(decl_name)
    ]


def _merge_responses_by_question_id(
    stored: list[dict],
    incoming: list[dict],
    decl_name: str,
) -> list[dict]:
    by_qid = {r["question_id"]: r for r in stored}
    for resp in incoming:
        qid = resp["question_id"]
        by_qid[qid] = {
            "question_id": qid,
            "response": resp.get("response"),
            "declaration_details": resp.get("declaration_details"),
        }
    return [
        by_qid.get(
            qid,
            {"question_id": qid, "response": None, "declaration_details": None},
        )
        for qid in get_question_config(decl_name)
    ]


async def _load_all_responses(session, status_record_id: str) -> list[dict]:
    stmt = select(UserDeclarationResponse).where(
        UserDeclarationResponse.declaration_status_id == status_record_id
    )
    rows = (await session.execute(stmt)).scalars().all()

    form_row = next(
        (r for r in rows if r.question_id == FORM_RESPONSES_QUESTION_ID),
        None,
    )
    if form_row and form_row.declaration_details:
        stored = form_row.declaration_details.get("responses")
        if isinstance(stored, list):
            return stored

    if rows:
        return [
            {
                "question_id": r.question_id,
                "response": r.response,
                "declaration_details": r.declaration_details,
            }
            for r in rows
            if r.question_id != FORM_RESPONSES_QUESTION_ID
        ]

    return []


async def _persist_form_responses(
    session, status_record_id: str, responses: list[dict]
) -> None:
    await session.execute(
        delete(UserDeclarationResponse).where(
            UserDeclarationResponse.declaration_status_id == status_record_id
        )
    )
    session.add(
        UserDeclarationResponse(
            declaration_status_id=status_record_id,
            question_id=FORM_RESPONSES_QUESTION_ID,
            response=None,
            declaration_details={"responses": responses},
        )
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
        if not declaration.file_path:
            raise ValueError(
                "Declaration template has not been uploaded yet"
            )
        if not declaration.reference_id:
            raise ValueError("Declaration cycle is not ready (missing reference id)")

        decl_name = as_declaration_name(declaration.declaration_name)
        question_config = get_question_config(decl_name)

        stmt = select(UserDeclarationStatus).where(
            and_(
                UserDeclarationStatus.declaration_id == declaration_id,
                UserDeclarationStatus.staff_id == staff_id,
            )
        )
        status_record = (await session.execute(stmt)).scalar_one_or_none()
        is_new = status_record is None

        if status_record and status_record.notify is False and status_record.status == "not_started":
            raise ValueError("You are not required to complete this declaration")

        if is_new:
            status_record = UserDeclarationStatus(
                id=build_annual_user_status_id(staff_id, declaration.reference_id),
                declaration_id=declaration_id,
                staff_id=staff_id,
                status="draft",
            )
            session.add(status_record)
            await session.flush()
        elif status_record.status == "completed":
            raise ValueError("Declaration already submitted and cannot be edited")
        elif status_record.status == "not_started":
            status_record.status = "draft"

        stored = await _load_all_responses(session, status_record.id)
        if not stored:
            stored = _default_responses(decl_name)
        merged = _merge_responses_by_question_id(stored, responses, decl_name)
        await _persist_form_responses(session, status_record.id, merged)
        await session.flush()

        all_responses = merged

        if is_submit:
            errors = validate_submission_responses(all_responses, decl_name)
            if errors:
                raise ValueError("; ".join(errors))

        has_conflicts = any(
            r.get("response") in CONFLICT_RESPONSES for r in all_responses
        )
        status_record.has_conflicts = has_conflicts
        status_record.last_saved_at = datetime.now(IST)

        created_self_declarations: list[dict] = []
        if is_submit:
            status_record.status = "completed"
            status_record.submitted_at = datetime.now(IST)
            if has_conflicts:
                created_self_declarations = await _auto_create_self_declarations(
                    session, staff_id, all_responses, decl_name
                )
        elif status_record.status != "completed":
            status_record.status = "draft"

        await session.commit()

        return {
            "id": str(status_record.id),
            "reference_id": declaration.reference_id,
            "status": status_record.status,
            "has_conflicts": status_record.has_conflicts,
            "created_self_declarations": created_self_declarations,
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
                "reference_id": decl.reference_id,
                "declaration_name": as_declaration_name(decl.declaration_name),
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

        decl_name = as_declaration_name(declaration.declaration_name)
        question_config = get_question_config(decl_name)

        if not status_record:
            raise ValueError("No declaration found for your ID")

        if status_record.notify is False and status_record.status == "not_started":
            raise ValueError("You are not required to complete this declaration")

        prefilled = await _get_prefill_data(session, staff_id, decl_name)

        return {
            "declaration_id": str(declaration_id),
            "reference_id": declaration.reference_id,
            "user_status_id": status_record.id,
            "declaration_name": decl_name,
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
            "responses": await _load_all_responses(session, status_record.id),
            "prefilled_declarations": prefilled,
        }


def _coi_subtype_to_question(decl_name: str) -> dict[str, str]:
    return {
        q["sub_type"]: qid
        for qid, q in get_question_config(decl_name).items()
        if q.get("sub_type")
    }


def _linked_self_declaration_id(detail: dict) -> str | None:
    return detail.get("self_declaration_id") or detail.get("linked_declaration_id")


def _map_annual_coi_detail(qid: str, detail: dict, decl_name: str) -> dict:
    mapping = get_question_config(decl_name).get(qid, {}).get("form_field_map", {})
    form_data = {}
    for key, value in detail.items():
        if key in ("self_declaration_id", "linked_declaration_id"):
            continue
        form_data[mapping.get(key, key)] = value
    return form_data


async def _init_self_declaration_conversation(
    record_id: str, staff_id: str, data: dict
) -> str:
    now = now_ist()
    json_data = {
        "id": record_id,
        "conversation": [
            {
                "actor": "User",
                "actorId": staff_id,
                "dateTime": now.isoformat(),
                "data": data,
                "files": [],
            }
        ],
    }
    return await init_json(record_id, json_data)


async def _auto_create_self_declarations(
    session, staff_id: str, responses: list[dict], decl_name: str
) -> list[dict]:
    """
    When user submits an annual declaration with disagree/option_b responses,
    create self-declaration rows in COBCE / COI tables (one per detail item).
    Each record gets a conversation thread so user/admin can respond with files.
    """
    created: list[dict] = []
    created_on = db_timestamp_now()

    for resp in responses:
        if resp.get("response") not in CONFLICT_RESPONSES:
            continue

        details_list = resp.get("declaration_details") or []
        if not details_list:
            continue

        qid = resp["question_id"]

        if qid.startswith("COBCE"):
            for detail in details_list:
                linked_id = _linked_self_declaration_id(detail)
                if linked_id:
                    created.append({
                        "record_id": linked_id,
                        "type": "Self Declaration",
                        "sub_type": "COBCE",
                        "linked": True,
                    })
                    continue

                record_id = await next_self_decl_id(staff_id)
                nature = detail.get("nature_of_violation") or detail.get(
                    "description", ""
                )
                person_details = {
                    "name": detail.get("person_responsible", staff_id),
                }
                conv_data = {
                    "subType": "COBCE_VIOLATION",
                    "natureOfViolation": nature,
                    "description": nature,
                    "personDetails": person_details,
                    "source": "annual_declaration",
                    "question_id": qid,
                }
                json_path = await _init_self_declaration_conversation(
                    record_id, staff_id, conv_data
                )
                session.add(
                    COBCEDeclarations(
                        COBCEId=record_id,
                        SubType="COBCE_VIOLATION",
                        Description=nature,
                        PersonDetails=person_details,
                        Status="In_Progress",
                        CreatedOn=created_on,
                        CreatedBy=staff_id,
                        OverallStatus="Pending",
                        PendingAt=1,
                        ResponseJsonPath=json_path,
                    )
                )
                created.append({
                    "record_id": record_id,
                    "type": "Self Declaration",
                    "sub_type": "COBCE",
                    "linked": False,
                })

        elif qid.startswith("COI"):
            q_config = get_question_config(decl_name).get(qid, {})
            sub_type = q_config.get("sub_type", "OTHERS")
            for detail in details_list:
                linked_id = _linked_self_declaration_id(detail)
                if linked_id:
                    created.append({
                        "record_id": linked_id,
                        "type": "Self Declaration",
                        "sub_type": "COI",
                        "linked": True,
                    })
                    continue

                record_id = await next_self_decl_id(staff_id)
                form_data = _map_annual_coi_detail(qid, detail, decl_name)
                conv_data = {
                    "subType": sub_type,
                    "formData": form_data,
                    "source": "annual_declaration",
                    "question_id": qid,
                }
                json_path = await _init_self_declaration_conversation(
                    record_id, staff_id, conv_data
                )
                session.add(
                    COIDeclarations(
                        COIId=record_id,
                        SubType=sub_type,
                        FormData=form_data,
                        Status="In-Progress",
                        CreatedOn=created_on,
                        CreatedBy=staff_id,
                        OverallStatus="Pending",
                        PendingAt=1,
                        ResponseJsonPath=json_path,
                    )
                )
                created.append({
                    "record_id": record_id,
                    "type": "Self Declaration",
                    "sub_type": "COI",
                    "linked": False,
                })

    return created


async def _get_prefill_data(session, staff_id: str, decl_name: str) -> list[dict]:
    """
    Fetch existing self declarations for the user to pre-fill
    the annual declaration form.
    """
    prefilled = []

    if decl_name == "COBCE/COI":
        cobce_stmt = select(COBCEDeclarations).where(
            COBCEDeclarations.CreatedBy == staff_id
        )
        cobce_records = (await session.execute(cobce_stmt)).scalars().all()
        for rec in cobce_records:
            prefilled.append({
                "source": "cobce",
                "record_id": rec.COBCEId,
                "sub_type": rec.SubType,
                "question_id": "COBCE_Q1",
                "details": {
                    "nature_of_violation": rec.Description,
                    "person_responsible": (rec.PersonDetails or {}).get("name", ""),
                    "self_declaration_id": rec.COBCEId,
                },
                "status": rec.OverallStatus,
            })

        coi_stmt = select(COIDeclarations).where(
            COIDeclarations.CreatedBy == staff_id
        )
        coi_records = (await session.execute(coi_stmt)).scalars().all()

        subtype_to_question = _coi_subtype_to_question(decl_name)
        for rec in coi_records:
            question_id = subtype_to_question.get(rec.SubType, "COI_Q6")
            coi_details = dict(rec.FormData or {})
            coi_details["self_declaration_id"] = rec.COIId
            prefilled.append({
                "source": "coi",
                "record_id": rec.COIId,
                "sub_type": rec.SubType,
                "question_id": question_id,
                "details": coi_details,
                "status": rec.OverallStatus,
            })

    return prefilled
