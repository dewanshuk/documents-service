from datetime import datetime, date, timedelta
from typing import Union
from zoneinfo import ZoneInfo

from fastapi.responses import JSONResponse

IST = ZoneInfo("Asia/Kolkata")
UTC = ZoneInfo("UTC")

MONTH_ABBR = ("", "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
              "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def add_working_days(start: date, working_days: int) -> date:
    """Add working days (Mon-Fri), skipping Saturdays and Sundays."""
    if working_days <= 0:
        return start

    current = start
    added = 0
    while added < working_days:
        current += timedelta(days=1)
        if current.weekday() < 5:
            added += 1
    return current


def now_ist() -> datetime:
    """Current time in IST (timezone-aware). Use for JSON / API display."""
    return datetime.now(IST)


def to_db_timestamp(dt: datetime) -> datetime:
    """
    Convert a datetime for PostgreSQL TIMESTAMP WITHOUT TIME ZONE columns.
    Aware datetimes are stored as UTC; naive values are returned unchanged.
    """
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(UTC).replace(tzinfo=None)


def db_timestamp_now() -> datetime:
    """UTC-naive now for compliance helpdesk DB columns without timezone."""
    return to_db_timestamp(now_ist())

def datetimeformatter(value: Union[datetime, date, str, int, float]) -> str:
    if isinstance(value, datetime):
        d = value.date()
    elif isinstance(value, date):
        d = value
    elif isinstance(value, (int, float)):  # Unix timestamp
        d = datetime.fromtimestamp(value).date()
    elif isinstance(value, str):
        try:
            d = datetime.fromisoformat(value).date()
        except Exception:
            patterns = [
                "%d/%m/%Y", "%m/%d/%Y",
                "%d-%m-%Y", "%m-%d-%Y",
                "%Y-%m-%d", "%Y/%m/%d",
                "%d %b %Y", "%d %B %Y",
                "%b %d, %Y", "%B %d, %Y",
            ]
            for p in patterns:
                try:
                    d = datetime.strptime(value, p).date()
                    break
                except Exception:
                    continue
            else:
                raise ValueError(f"Cannot parse date string: {value!r}")
    else:
        raise ValueError(f"Unsupported type: {type(value).__name__}")
    return f"{d.day:02d}/{MONTH_ABBR[d.month]}/{d.year:04d}"

def format_datetime_ist(value: Union[datetime, str, None]) -> str:
    """Format a datetime (or ISO string) as '15/AUG/2026 2:30 PM' in IST. Blank when null."""
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except Exception:
            return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    ist_dt = value.astimezone(IST)
    return f"{datetimeformatter(ist_dt)} {ist_dt.strftime('%I:%M %p').lstrip('0')}"

def validate_word_limit(text: str, max_words: int):
    if len(text.split()) > max_words:
        raise ValueError(f"Exceeds {max_words} words")
    
async def get_model_by_id(record_id: str):
    from utils.record_ids import resolve_record

    try:
        model, _, _ = await resolve_record(record_id)
        return model
    except ValueError:
        return ValueError("Invalid ID")


async def get_type_and_model_by_id(record_id: str):
    from utils.record_ids import resolve_record

    try:
        model, record_type, _ = await resolve_record(record_id)
        return model, record_type
    except ValueError:
        return ValueError("Invalid ID")