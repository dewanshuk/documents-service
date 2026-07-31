"""Human-readable reference IDs backed by PostgreSQL sequences (multi-pod safe)."""

from datetime import datetime

from sqlalchemy import text

from db.db_manager import get_session
from db.models.helpdesk import (
    Complaints,
    ComplianceQuery,
    GiftDeclarations,
    COBCEDeclarations,
    COIDeclarations,
)

MODEL_BY_TYPE = {
    "query": ComplianceQuery,
    "gift": GiftDeclarations,
    "complaint": Complaints,
    "cobce": COBCEDeclarations,
    "coi": COIDeclarations,
}

SELF_DECL_MODELS = [
    ("cobce", COBCEDeclarations),
    ("coi", COIDeclarations),
]

RECORD_ID_SEP = "-"
MAX_RECORD_ID_LEN = 80

# Self-decl suffix = 6-digit sequence. Annual user ids use a shorter cycle ref.
SELF_DECL_SUFFIX_LEN = 6


def current_year() -> int:
    return datetime.now().year


def year_from_financial_year(financial_year: str) -> int:
    """Extract calendar year from values like '2025-26' or '2026'."""
    return int(str(financial_year)[:4])


def parse_record_id(record_id: str) -> tuple[str, str]:
    """Split prefix-STAFF001-<suffix> correctly."""
    parts = record_id.split(RECORD_ID_SEP)
    if len(parts) >= 3 and parts[0] in ("AD", "SD"):
        return parts[1], RECORD_ID_SEP.join(parts[2:])
    elif len(parts) >= 2:
        return parts[0], RECORD_ID_SEP.join(parts[1:])
    raise ValueError(f"Invalid record id: {record_id}")


def build_annual_user_status_id(staff_id: str, annual_declaration_id: str) -> str:
    """Per-user annual declaration id, e.g. AD-STAFF001-0001."""
    if annual_declaration_id.startswith("AD-"):
        annual_declaration_id = annual_declaration_id[3:]
    return f"AD-{staff_id}{RECORD_ID_SEP}{annual_declaration_id}"


async def _next_sequence_value(schema: str, seq_key: str) -> int:
    """
    Atomically create sequence if missing and return next value.
    Safe across concurrent requests and application instances.
    """
    full_name = f"{schema}.{seq_key}"
    async with get_session() as session:
        await session.execute(
            text(
                f"CREATE SEQUENCE IF NOT EXISTS {full_name} "
                "START 1 INCREMENT 1 NO MAXVALUE"
            )
        )
        result = await session.execute(text(f"SELECT nextval('{full_name}')"))
        value = int(result.scalar_one())
        await session.commit()
        return value


async def next_query_id(staff_id: str, year: int | None = None) -> str:
    year = year or current_year()
    seq = await _next_sequence_value("compliance", f"seq_qry_{year}")
    return f"QRY{staff_id}-{seq:06d}"


async def next_complaint_id(staff_id: str, year: int | None = None) -> str:
    year = year or current_year()
    seq = await _next_sequence_value("compliance", f"seq_cmp_{year}")
    return f"CMP{staff_id}-{seq:06d}"


async def next_gift_id(staff_id: str, year: int | None = None) -> str:
    year = year or current_year()
    seq = await _next_sequence_value("compliance", f"seq_gft_{year}")
    return f"GFT{staff_id}-{seq:06d}"
async def next_self_decl_id(staff_id: str, year: int | None = None) -> str:
    year = year or current_year()
    seq = await _next_sequence_value("compliance", f"seq_sd_{year}")
    return f"SD-{staff_id}{RECORD_ID_SEP}{seq:06d}"


async def next_annual_cycle_ref() -> str:
    """Admin cycle id, zero-padded e.g. AD-0001, AD-0123 — shared by all users in that cycle."""
    seq = await _next_sequence_value("annual_declarations", "seq_ad_cycle")
    return f"AD-{seq:04d}"


def _is_annual_user_status_id(record_id: str) -> bool:
    return record_id.startswith("AD-")


def _is_self_decl_id(record_id: str) -> bool:
    return record_id.startswith("SD-")


async def resolve_record(record_id: str) -> tuple[type, str, str]:
    """Find model by human-readable DB primary key."""
    from db.db_manager import db_manager
    from db.models.annual_dec import UserDeclarationStatus

    if record_id.startswith("QRY"):
        record = await db_manager.get(ComplianceQuery, record_id)
        if record:
            return ComplianceQuery, "query", record_id

    if record_id.startswith("CMP"):
        record = await db_manager.get(Complaints, record_id)
        if record:
            return Complaints, "complaint", record_id

    if record_id.startswith("GFT"):
        record = await db_manager.get(GiftDeclarations, record_id)
        if record:
            return GiftDeclarations, "gift", record_id

    if _is_annual_user_status_id(record_id):
        record = await db_manager.get(UserDeclarationStatus, record_id)
        if record:
            return UserDeclarationStatus, "annual_declaration", record_id

    if _is_self_decl_id(record_id):
        for record_type, model in SELF_DECL_MODELS:
            record = await db_manager.get(model, record_id)
            if record:
                return model, record_type, record_id

    for record_type, model in MODEL_BY_TYPE.items():
        record = await db_manager.get(model, record_id)
        if record:
            return model, record_type, record_id

    raise ValueError(f"Record not found: {record_id}")
