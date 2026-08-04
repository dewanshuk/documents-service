from sqlalchemy import select, desc, and_
from datetime import datetime
from db.db_manager import get_session
from db.models.helpdesk import RecentUserRecords
from db.models.annual_dec import AnnualDeclaration, UserDeclarationStatus, as_declaration_name
from utils.actor_display import format_actor_name
from utils.helpers import UTC

def _format_annual_status(status: str) -> str:
    if status in ("not_started", "Pending"):
        return "Pending"
    if status == "draft":
        return "Draft"
    if status == "completed":
        return "Completed"
    return status

async def log_annual_declaration_recent(staff_id: str, declaration_id: str) -> None:
    """Log an annual declaration in the user's recent activity list."""
    async with get_session() as session:
        declaration = await session.get(AnnualDeclaration, declaration_id)
        if not declaration:
            return

        stmt = select(UserDeclarationStatus).where(
            and_(
                UserDeclarationStatus.declaration_id == declaration_id,
                UserDeclarationStatus.staff_id == staff_id,
            )
        )
        status_record = (await session.execute(stmt)).scalar_one_or_none()

    display_status = _format_annual_status(status_record.status if status_record else "not_started")
    created_on = (
        datetime.combine(declaration.assigned_date, datetime.min.time())
        if declaration.assigned_date
        else datetime.now(UTC)
    )

    pending_at = None
    if display_status != "Completed":
        pending_at = await format_actor_name(staff_id)

    await log_recent_record(
        user_id=staff_id,
        record_id=declaration_id,
        record_type="Annual Declaration",
        title=as_declaration_name(declaration.declaration_name),
        status=display_status,
        created_on=created_on,
        sub_type=declaration.financial_year,
        pending_at=pending_at,
    )

async def log_recent_record(
    user_id: str,
    record_id: str,
    record_type: str,
    title: str,
    status: str,
    created_on: datetime,
    sub_type: str | None = None,
    pending_at: str | None = None
):
    """
    Logs a record as recently accessed/used by the user.
    Keeps only the top 5 most recent records per user.
    """
    async with get_session() as session:
        # Check if it already exists
        stmt = select(RecentUserRecords).where(
            RecentUserRecords.user_id == user_id,
            RecentUserRecords.record_id == record_id
        )
        result = await session.execute(stmt)
        existing_record = result.scalar_one_or_none()

        now = datetime.now(UTC)

        if existing_record:
            # Update it
            existing_record.title = title
            existing_record.status = status
            existing_record.sub_type = sub_type
            existing_record.pending_at = pending_at
            existing_record.last_accessed_on = now
        else:
            # Insert new
            new_record = RecentUserRecords(
                user_id=user_id,
                record_id=record_id,
                record_type=record_type,
                title=title,
                sub_type=sub_type,
                status=status,
                created_on=created_on,
                pending_at=pending_at,
                last_accessed_on=now
            )
            session.add(new_record)

        await session.commit()

        # Enforce max 5 records per user
        count_stmt = select(RecentUserRecords).where(RecentUserRecords.user_id == user_id).order_by(desc(RecentUserRecords.last_accessed_on))
        result = await session.execute(count_stmt)
        user_records = result.scalars().all()

        if len(user_records) > 5:
            # Delete the older ones
            records_to_delete = user_records[5:]
            for r in records_to_delete:
                await session.delete(r)
            await session.commit()

async def get_recent_records(user_id: str):
    """
    Fetches the top 5 recent records for a user.
    """
    async with get_session() as session:
        stmt = select(RecentUserRecords).where(
            RecentUserRecords.user_id == user_id
        ).order_by(desc(RecentUserRecords.last_accessed_on)).limit(5)
        
        result = await session.execute(stmt)
        return result.scalars().all()
