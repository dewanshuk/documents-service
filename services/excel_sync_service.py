import asyncio
from datetime import datetime as DateTime
from io import BytesIO

from openpyxl import Workbook, load_workbook
from sqlalchemy import select, and_, delete

from db.db_manager import get_session
from db.models import AnnualDeclaration, UserDeclarationStatus, SyncStatus, User, as_declaration_name
from db.models.helpdesk import COBCEDeclarations, COIDeclarations
from utils.helpers import IST, format_datetime_ist, now_ist, to_db_timestamp
from utils.record_ids import build_annual_user_status_id, year_from_financial_year
from services.excel_service import _header_index_map

BATCH_SIZE = 500

_STATUS_DISPLAY = {
    "not_started": "Pending",
    "Pending": "Pending",
    "draft": "In-Progress",
    "completed": "Completed",
}

_INVALID_FILENAME_CHARS = str.maketrans({c: "_" for c in r'\/?*[]:'})


def _sanitize_filename_part(value: str) -> str:
    return value.translate(_INVALID_FILENAME_CHARS).strip()


def _format_submitted_on(value) -> str:
    """Format timestamptz as '15/AUG/2026 14:30' in IST. Blank when null."""
    return format_datetime_ist(value)


class InvalidStaffIdsError(ValueError):
    def __init__(self, invalid_ids: list[str]):
        self.invalid_ids = invalid_ids
        super().__init__(f"Invalid staff_ids: {', '.join(invalid_ids)}")


def _iter_excel_rows(file_bytes: bytes):
    wb = load_workbook(BytesIO(file_bytes), read_only=True, data_only=True)
    ws = wb.active
    rows = ws.iter_rows(values_only=True)
    header = next(rows, None)
    if not header:
        wb.close()
        return {}, []

    col_map = _header_index_map(header)
    data_rows = [row for row in rows if row and any(row)]
    wb.close()
    return col_map, data_rows


def _is_pending_row(row, status_col: int | None) -> bool:
    if status_col is None:
        return True
    return str(row[status_col] or "").strip().lower() != "completed"


async def process_declaration_excel(declaration_id: str, file_bytes: bytes) -> dict:
    """Parse Excel bytes and upsert UserDeclarationStatus rows (notify yes/no)."""
    col_map, data_rows = await asyncio.to_thread(_iter_excel_rows, file_bytes)

    staff_col = col_map.get("Staff ID")
    notify_col = col_map.get("Notify")
    status_col = col_map.get("Status")
    remarks_col = col_map.get("Remarks")

    if staff_col is None:
        raise ValueError("Excel must contain a 'Staff ID' column")

    async with get_session() as session:
        declaration = await session.get(AnnualDeclaration, declaration_id)
        if not declaration:
            raise ValueError("Declaration cycle not found")
        annual_declaration_id = declaration.id

    pending_rows = [row for row in data_rows if _is_pending_row(row, status_col)]

    # Collect all staff IDs present in this Excel upload.
    excel_staff_ids: set[str] = set()
    for row in pending_rows:
        sid = row[staff_col]
        if sid:
            excel_staff_ids.add(str(sid).strip())

    if excel_staff_ids:
        async with get_session() as session:
            existing_ids = set(
                (
                    await session.execute(
                        select(User.staff_id).where(User.staff_id.in_(excel_staff_ids))
                    )
                ).scalars().all()
            )
        invalid_ids = sorted(excel_staff_ids - existing_ids)
        if invalid_ids:
            raise InvalidStaffIdsError(invalid_ids)

    processed = 0
    excluded = 0

    for batch_start in range(0, len(pending_rows), BATCH_SIZE):
        batch = pending_rows[batch_start : batch_start + BATCH_SIZE]

        async with get_session() as session:
            for row in batch:
                staff_id = row[staff_col]
                if not staff_id:
                    continue
                staff_id = str(staff_id).strip()

                status_val = str(row[status_col] or "").strip() if status_col is not None else ""
                notify_raw = str(row[notify_col] or "").strip() if notify_col is not None else ""
                remarks_val = str(row[remarks_col] or "").strip() if remarks_col is not None else ""

                notify_val = (
                    status_val.lower() == "pending"
                    and notify_raw.lower() == "yes"
                    and remarks_val.lower() == "available"
                )

                existing = (
                    await session.execute(
                        select(UserDeclarationStatus).where(
                            and_(
                                UserDeclarationStatus.declaration_id == declaration_id,
                                UserDeclarationStatus.staff_id == staff_id,
                            )
                        )
                    )
                ).scalar_one_or_none()

                if existing:
                    existing.notify = notify_val
                    existing.remarks = remarks_val or None
                else:
                    session.add(
                        UserDeclarationStatus(
                            id=build_annual_user_status_id(
                                staff_id, annual_declaration_id
                            ),
                            declaration_id=declaration_id,
                            staff_id=staff_id,
                            status="not_started",
                            notify=notify_val,
                            remarks=remarks_val or None,
                        )
                    )

                if notify_val:
                    processed += 1
                else:
                    excluded += 1

            await session.commit()

    # Delete not_started records for staff IDs no longer in the Excel.
    if excel_staff_ids:
        async with get_session() as session:
            await session.execute(
                delete(UserDeclarationStatus).where(
                    and_(
                        UserDeclarationStatus.declaration_id == declaration_id,
                        UserDeclarationStatus.status == "not_started",
                        UserDeclarationStatus.staff_id.not_in(excel_staff_ids),
                    )
                )
            )
            await session.commit()

    async with get_session() as session:
        declaration = await session.get(AnnualDeclaration, declaration_id)
        declaration.sync_status = SyncStatus.COMPLETED
        await session.commit()

    return {
        "declaration_id": annual_declaration_id,
        "sync_status": SyncStatus.COMPLETED.value,
        "processed": processed,
        "excluded_users": excluded,
    }

async def generate_declaration_status_excel(declaration_id: str) -> tuple[BytesIO, str]:
    """Build a fresh status report (from DB, not the uploaded template)."""
    async with get_session() as session:
        declaration = await session.get(AnnualDeclaration, declaration_id)
        if not declaration:
            raise ValueError("Declaration not found")

        stmt = select(UserDeclarationStatus).where(
            UserDeclarationStatus.declaration_id == declaration_id
        )
        user_statuses = (await session.execute(stmt)).scalars().all()
        if not user_statuses:
            raise ValueError("No uploaded data available for this declaration")

        staff_ids = [us.staff_id for us in user_statuses]
        user_rows = (
            await session.execute(
                select(User.staff_id, User.username, User.status).where(
                    User.staff_id.in_(staff_ids)
                )
            )
        ).all()
        user_info = {u.staff_id: u for u in user_rows}

        # Get self declarations for conflicts
        conflict_staff_ids = [us.staff_id for us in user_statuses if us.has_conflicts]
        self_declarations_map: dict[str, list[str]] = {sid: [] for sid in conflict_staff_ids}

        if conflict_staff_ids:
            fy_year = year_from_financial_year(declaration.financial_year)
            # CreatedOn on helpdesk tables is TIMESTAMP WITHOUT TIME ZONE (UTC-naive).
            start_date = to_db_timestamp(DateTime(fy_year, 4, 1, tzinfo=IST))
            end_date = to_db_timestamp(DateTime(fy_year + 1, 3, 31, 23, 59, 59, tzinfo=IST))

            cobce_stmt = select(COBCEDeclarations.CreatedBy, COBCEDeclarations.COBCEId).where(
                and_(
                    COBCEDeclarations.CreatedBy.in_(conflict_staff_ids),
                    COBCEDeclarations.CreatedOn >= start_date,
                    COBCEDeclarations.CreatedOn <= end_date
                )
            )
            cobce_rows = (await session.execute(cobce_stmt)).all()
            for created_by, record_id in cobce_rows:
                self_declarations_map[created_by].append(record_id)

            coi_stmt = select(COIDeclarations.CreatedBy, COIDeclarations.COIId).where(
                and_(
                    COIDeclarations.CreatedBy.in_(conflict_staff_ids),
                    COIDeclarations.CreatedOn >= start_date,
                    COIDeclarations.CreatedOn <= end_date
                )
            )
            coi_rows = (await session.execute(coi_stmt)).all()
            for created_by, record_id in coi_rows:
                self_declarations_map[created_by].append(record_id)

    def _build_workbook():
        wb = Workbook(write_only=True)
        ws = wb.create_sheet(title="Status")
        ws.append([
            "Staff Id", "Name", "Status", "Submitted on", "Active", "Remarks", "Self Declaration",
        ])

        for us in user_statuses:
            info = user_info.get(us.staff_id)
            name = (info.username if info and info.username else "") or ""
            is_active = bool(info and str(info.status or "").strip().lower() == "active")

            decls = self_declarations_map.get(us.staff_id, [])

            ws.append([
                us.staff_id,
                name,
                _STATUS_DISPLAY.get(us.status, us.status),
                _format_submitted_on(us.submitted_at),
                "Yes" if is_active else "No",
                us.remarks or "",
                ", ".join(decls),
            ])

        out = BytesIO()
        wb.save(out)
        out.seek(0)
        return out

    output = await asyncio.to_thread(_build_workbook)

    decl_name = _sanitize_filename_part(as_declaration_name(declaration.declaration_name))
    fy = _sanitize_filename_part(str(declaration.financial_year).replace("-", "_"))
    timestamp = now_ist().strftime("%Y%m%d%H%M")
    filename = f"{decl_name}_{fy}_{timestamp}_Status.xlsx"

    return output, filename
