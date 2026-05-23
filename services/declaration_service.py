from datetime import date
from db.validators import AnnualDeclarationResponse
from enum import Enum
from datetime import datetime, date
from uuid import UUID

def _row_to_dict(row):
    if hasattr(row, "__dict__"):
        data = {k: v for k, v in row.__dict__.items() if k != "_sa_instance_state"}
    elif isinstance(row, dict):
        data = row.copy()
    else:
        data = dict(row)
    return data



def _serialize_dates(declaration: dict) -> dict:
    """Convert non-JSON-serializable objects to safe values."""
    serialized = {}

    for key, value in declaration.items():
        if isinstance(value, Enum):
            serialized[key] = value.value              
        elif isinstance(value, UUID):
            serialized[key] = str(value)               
        elif isinstance(value, (date, datetime)):
            serialized[key] = value.isoformat()         
        else:
            serialized[key] = value

    return serialized



def _compute_pending_status(declaration: dict) -> str:
    status = declaration.get("status", "Pending")
    due_date = declaration.get("due_date")

    if isinstance(due_date, str):
        return status

    if status and status.lower() != "pending":
        return status

    if isinstance(due_date, date):
        if due_date < date.today():
            return "Overdue"
        return "Pending"

    return status


def enrich_declaration_data(items: list) -> list:
    enriched = []
    for item in items:
        declaration = _row_to_dict(item)
        declaration["pending_status"] = _compute_pending_status(declaration)
        declaration = _serialize_dates(declaration)
        enriched.append(declaration)
    return enriched
