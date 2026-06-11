from datetime import datetime, date
from typing import Union
from db.models.helpdesk import Complaints, ComplianceQuery, GiftDeclarations, COBCEDeclarations, COIDeclarations
from fastapi.responses import JSONResponse
MONTH_ABBR = ("", "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
              "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")

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

def validate_word_limit(text: str, max_words: int):
    if len(text.split()) > max_words:
        raise ValueError(f"Exceeds {max_words} words")
    
def get_model_by_id(record_id: str):
    if record_id.startswith("QRY-"):
        return ComplianceQuery
    elif record_id.startswith("GFT-"):
        return GiftDeclarations
    elif record_id.startswith("CMP-"):
        return Complaints
    elif record_id.startswith("COBCE-"):
        return COBCEDeclarations
    elif record_id.startswith("COI-"):
        return COIDeclarations
    else:
        return ValueError("Invalid ID")
    
def get_type_and_model_by_id(record_id: str):
    if record_id.startswith("QRY-"):
        return ComplianceQuery, "query"
    elif record_id.startswith("GFT-"):
        return GiftDeclarations, "gift"
    elif record_id.startswith("CMP-"):
        return Complaints, "complaint"
    elif record_id.startswith("COBCE-"):
        return COBCEDeclarations, "cobce"
    elif record_id.startswith("COI-"):
        return COIDeclarations, "coi"
    else:
        return ValueError("Invalid ID")