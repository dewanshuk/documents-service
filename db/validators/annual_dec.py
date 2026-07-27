from datetime import date, datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field, ConfigDict
from uuid import UUID
from db.models.annual_dec import DeclarationType


class AnnualDeclarationCreate(BaseModel):
    declaration_name: DeclarationType
    financial_year: str
    assigned_date: date
    due_date: date
    activity_closure_date: date
    status: Optional[str] = "Pending"

    model_config = ConfigDict(use_enum_values=True)


class AnnualDeclarationUpdate(BaseModel):
    declaration_name: Optional[DeclarationType] = None
    financial_year: Optional[str] = None
    assigned_date: Optional[date] = None
    due_date: Optional[date] = None
    activity_closure_date: Optional[date] = None
    status: Optional[str] = None

    model_config = ConfigDict(use_enum_values=True)


class AnnualDeclarationFilters(BaseModel):
    declaration_name: Optional[str] = None
    financial_year: Optional[str] = None
    assigned_date_from: Optional[date] = None
    assigned_date_to: Optional[date] = None
    due_date_from: Optional[date] = None
    due_date_to: Optional[date] = None
    activity_closure_date_from: Optional[date] = None
    activity_closure_date_to: Optional[date] = None


class QuestionResponsePayload(BaseModel):
    question_id: str
    response: Optional[str] = None
    declaration_details: Optional[list[dict]] = None


class SaveDeclarationRequest(BaseModel):
    """Same payload shape for draft (partial/null allowed) and submit (all required)."""

    status: Literal["draft", "submit"]
    responses: list[QuestionResponsePayload] = Field(default_factory=list)
