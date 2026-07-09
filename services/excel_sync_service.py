import asyncio
from io import BytesIO

from openpyxl import load_workbook
from sqlalchemy import select, and_, delete

from db.db_manager import get_session
from db.models import AnnualDeclaration, UserDeclarationStatus, SyncStatus
from utils.record_ids import build_annual_user_status_id
from services.excel_service import _header_index_map, _parse_yes_no

BATCH_SIZE = 500


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
            excel_staff_ids.add(str(sid))

    processed = 0
    excluded = 0

    for batch_start in range(0, len(pending_rows), BATCH_SIZE):
        batch = pending_rows[batch_start : batch_start + BATCH_SIZE]

        async with get_session() as session:
            for row in batch:
                staff_id = row[staff_col]
                if not staff_id:
                    continue

                notify_val = True
                if notify_col is not None:
                    notify_val = _parse_yes_no(row[notify_col])

                existing = (
                    await session.execute(
                        select(UserDeclarationStatus).where(
                            and_(
                                UserDeclarationStatus.declaration_id == declaration_id,
                                UserDeclarationStatus.staff_id == str(staff_id),
                            )
                        )
                    )
                ).scalar_one_or_none()

                if existing:
                    existing.notify = notify_val
                else:
                    session.add(
                        UserDeclarationStatus(
                            id=build_annual_user_status_id(
                                str(staff_id), annual_declaration_id
                            ),
                            declaration_id=declaration_id,
                            staff_id=str(staff_id),
                            status="not_started",
                            notify=notify_val,
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
