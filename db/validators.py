from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel
from uuid import UUID
from db.models import DeclarationType

class AnnualDeclarationCreate(BaseModel):
    declaration_name: DeclarationType
    financial_year: str
    assigned_date: date
    due_date: date
    activity_closure_date: date
    status: Optional[str] = "Pending"

    class Config:
        use_enum_values = False

class AnnualDeclarationFilters(BaseModel):
    declaration_name: Optional[str] = None
    financial_year: Optional[str] = None
    assigned_date_from: Optional[date] = None
    assigned_date_to: Optional[date] = None
    due_date_from: Optional[date] = None
    due_date_to: Optional[date] = None
    activity_closure_date_from: Optional[date] = None
    activity_closure_date_to: Optional[date] = None

class AnnualDeclarationResponse(BaseModel):
    id: UUID
    declaration_name: str
    financial_year: str
    assigned_date: date
    due_date: date
    activity_closure_date: date
    pending_status: str # Computed field
    last_updated_at: datetime

    class Config:
        from_attributes = True