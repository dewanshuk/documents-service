import asyncio
from datetime import datetime
from io import BytesIO

from openpyxl import load_workbook
from sqlalchemy import select, and_, delete

from db.db_manager import get_session
from db.models import AnnualDeclaration, UserDeclarationStatus, SyncStatus, User
from db.models.helpdesk import COBCEDeclarations, COIDeclarations
from db.models.annual_dec import IST
from utils.record_ids import build_annual_user_status_id, year_from_financial_year
from services.excel_service import _header_index_map, _parse_yes_no
from storage.storage_ops import download_to_stream

BATCH_SIZE = 500


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

                notify_val = True
                if notify_col is not None:
                    notify_val = _parse_yes_no(row[notify_col])

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
    async with get_session() as session:
        declaration = await session.get(AnnualDeclaration, declaration_id)
        if not declaration or not declaration.file_path:
            raise ValueError("Declaration template not available")

        # Get all user statuses
        stmt = select(UserDeclarationStatus).where(
            UserDeclarationStatus.declaration_id == declaration_id
        )
        user_statuses = (await session.execute(stmt)).scalars().all()
        
        status_map = {us.staff_id: us for us in user_statuses}
        staff_ids = list(status_map.keys())
        name_map: dict[str, str] = {}
        if staff_ids:
            user_rows = (
                await session.execute(
                    select(User.staff_id, User.username).where(User.staff_id.in_(staff_ids))
                )
            ).all()
            name_map = {staff_id: (username or "") for staff_id, username in user_rows}
        
        # Get self declarations for conflicts
        conflict_staff_ids = [us.staff_id for us in user_statuses if us.has_conflicts]
        self_declarations_map = {sid: [] for sid in conflict_staff_ids}
        
        if conflict_staff_ids:
            fy_year = year_from_financial_year(declaration.financial_year)
            start_date = datetime(fy_year, 4, 1, tzinfo=IST)
            end_date = datetime(fy_year + 1, 3, 31, 23, 59, 59, tzinfo=IST)
            
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

    stream = await download_to_stream(declaration.file_path)
    file_bytes = stream.read()
    
    def _update_excel():
        wb = load_workbook(BytesIO(file_bytes))
        ws = wb.active
        
        headers = []
        for col in range(1, ws.max_column + 1):
            val = ws.cell(row=1, column=col).value
            if val:
                headers.append((col, str(val).strip()))
                
        staff_col = None
        name_col = None
        status_col = None
        for col_idx, header in headers:
            if header.lower() == "staff id":
                staff_col = col_idx
            elif header.lower() == "name":
                name_col = col_idx
            elif header.lower() == "status":
                status_col = col_idx
                
        if not staff_col:
            raise ValueError("No Staff ID column found in template")
            
        if not status_col:
            status_col = ws.max_column + 1
            ws.cell(row=1, column=status_col, value="Status")

        if not name_col:
            name_col = ws.max_column + 1
            ws.cell(row=1, column=name_col, value="Name")
            
        completed_date_col = ws.max_column + 1
        ws.cell(row=1, column=completed_date_col, value="Completed Date")
        
        self_decl_col = ws.max_column + 1
        ws.cell(row=1, column=self_decl_col, value="Self Declarations")
        
        for row in range(2, ws.max_row + 1):
            staff_id_val = ws.cell(row=row, column=staff_col).value
            if not staff_id_val:
                continue
                
            staff_id = str(staff_id_val).strip()
            us = status_map.get(staff_id)
            if not us:
                continue

            if name_col:
                ws.cell(row=row, column=name_col, value=name_map.get(staff_id, ""))
                
            if status_col:
                ws.cell(row=row, column=status_col, value=us.status.capitalize())
            
            if us.status == "completed" and us.submitted_at:
                ws.cell(row=row, column=completed_date_col, value=us.submitted_at.strftime("%Y-%m-%d %H:%M:%S"))
                
            if us.has_conflicts:
                decls = self_declarations_map.get(staff_id, [])
                if decls:
                    ws.cell(row=row, column=self_decl_col, value=", ".join(decls))
                    
        out = BytesIO()
        wb.save(out)
        out.seek(0)
        
        from pathlib import Path
        filename = f"status_{Path(declaration.file_path).name}"
        return out, filename

    return await asyncio.to_thread(_update_excel)
