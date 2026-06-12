"""Composite record IDs: {staff_id}-{suffix} stored as the DB primary key."""

from typing import Union
from uuid import uuid4

from sqlalchemy import text

from db.db_manager import get_session
from db.models.helpdesk import (
    Complaints,
    ComplianceQuery,
    GiftDeclarations,
    COBCEDeclarations,
    COIDeclarations,
    R518Declarations,
)

DbId = Union[str, int]

MODEL_BY_TYPE = {
    "query": ComplianceQuery,
    "gift": GiftDeclarations,
    "complaint": Complaints,
    "cobce": COBCEDeclarations,
    "coi": COIDeclarations,
    "r518": R518Declarations,
}

RECORD_ID_SEP = "-"
MAX_RECORD_ID_LEN = 80


def new_suffix() -> str:
    return str(uuid4())


def build_record_id(staff_id: str, suffix: Union[str, int]) -> str:
    """Build composite id stored in DB, e.g. STAFF001-0001 or STAFF001-<uuid>."""
    if isinstance(suffix, int):
        return f"{staff_id}{RECORD_ID_SEP}{suffix:04d}"
    return f"{staff_id}{RECORD_ID_SEP}{suffix}"


def parse_record_id(record_id: str) -> tuple[str, str]:
    """Split STAFF001-<suffix> into (staff_id, suffix). Suffix may contain hyphens (uuid)."""
    staff_id, _, suffix = record_id.partition(RECORD_ID_SEP)
    if not staff_id or not suffix:
        raise ValueError(f"Invalid record id: {record_id}")
    return staff_id, suffix


async def next_complaint_suffix() -> int:
    async with get_session() as session:
        result = await session.execute(
            text("SELECT nextval('compliance.complaint_id_seq')")
        )
        return int(result.scalar_one())


async def resolve_record(record_id: str) -> tuple[type, str, str]:
    """Find model by composite DB primary key."""
    from db.db_manager import db_manager

    for record_type, model in MODEL_BY_TYPE.items():
        record = await db_manager.get(model, record_id)
        if record:
            return model, record_type, record_id
    raise ValueError(f"Record not found: {record_id}")
