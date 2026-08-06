"""Shared helpers for formatting actor/user display names consistently across all APIs."""

from typing import Optional

from db.db_manager import db_manager
from db.models.helpdesk import User

COMPLIANCE_TEAM_LABEL = "Compliance Team"


async def get_username(staff_id: Optional[str]) -> Optional[str]:
    if not staff_id:
        return None
    user = await db_manager.get(User, staff_id)
    return user.username if user and user.username else staff_id


async def format_actor_name(staff_id: Optional[str]) -> Optional[str]:
    """Format a staff_id as 'username (staff_id)' for consistent display across APIs."""
    if not staff_id:
        return None
    username = await get_username(staff_id)
    return f"{username} ({staff_id})"


async def format_pending_at(
    pending_at: Optional[int],
    created_by: Optional[str],
    is_admin: bool = False,
    assigned_to: Optional[str] = None,
) -> str:
    """Common pendingAt display: creator's name when pending on the user, else Compliance Team.

    When the viewer is an admin and the record is pending on compliance (pending_at == 1),
    show the actual assigned admin's name instead of the generic label, if one is assigned.
    """
    if pending_at == 1:
        if is_admin and assigned_to:
            return await format_actor_name(assigned_to) or COMPLIANCE_TEAM_LABEL
        return COMPLIANCE_TEAM_LABEL
    if pending_at == 0:
        return await format_actor_name(created_by) or COMPLIANCE_TEAM_LABEL
    return "-"
