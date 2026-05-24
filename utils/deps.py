from db.db_manager import db_manager
from db.models import User


async def get_current_user():
  """Replace with real auth; loads admin flag from users table when present."""
  staff_id = "STAFF001"
  user = await db_manager.get(User, staff_id)
  if user:
    return {
      "staff_id": user.staff_id,
      "is_master_admin": user.is_master_admin,
    }
  return {"staff_id": staff_id, "is_master_admin": False}
