from db.db_manager import db_manager
from db.models.helpdesk import User


async def get_current_user():
    """Replace with real auth; loads admin flags from users table when present."""
    staff_id = "STAFF001"
    user = await db_manager.get(User, staff_id)
    if user:
        return {
            "staff_id": user.staff_id,
            "username": user.username,
            "is_master_admin": user.is_master_admin,
            "is_policy_hub_admin": user.is_policy_hub_admin,
            "is_query_lead": user.is_query_lead,
            "is_cheif_compliance_officer": user.is_cheif_compliance_officer,
            "is_cobce_coi_gift_lead": user.is_cobce_coi_gift_lead,
            "is_knowledge_hub_admin": user.is_knowledge_hub_admin,
        }
    return {"staff_id": staff_id, "is_master_admin": False}
