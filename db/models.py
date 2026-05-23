from sqlalchemy.orm import DeclarativeBase, DeclarativeMeta, mapped_column
from sqlalchemy import Column, String, Boolean

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    staff_id = mapped_column(String, primary_key=True)
    email = mapped_column(String, unique=True, nullable=False, index=True)
    status = mapped_column(String, nullable=False)
    is_master_admin = mapped_column(Boolean, nullable=False, default=False)
    is_knowledge_hub_admin = mapped_column(Boolean, nullable=False, default=False)
    is_policy_hub_admin = mapped_column(Boolean, nullable=False, default=False)
    __table_args__ = {"schema": "users"}

import uuid
import enum
from sqlalchemy import String, Date, DateTime, Text, ForeignKey, UniqueConstraint, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import mapped_column, relationship
from datetime import datetime
from zoneinfo import ZoneInfo
from db.models import Base

IST = ZoneInfo("Asia/Kolkata")

class DeclarationType(enum.Enum):
    COBCE_COI = "COBCE/COI"
    R5_18 = "R5.18"

class AnnualDeclaration(Base):
    __tablename__ = "annual_declarations"
    
    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    declaration_name = mapped_column(Enum(DeclarationType), nullable=False)
    financial_year = mapped_column(String(7), nullable=False)
    assigned_date = mapped_column(Date, nullable=False)
    due_date = mapped_column(Date, nullable=False)
    activity_closure_date = mapped_column(Date, nullable=False)
    status = mapped_column(String(50), default="Pending")
    last_updated_at = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(IST),
        onupdate=lambda: datetime.now(IST)
    )
    file_path = mapped_column(Text, nullable=True) # To store file path if needed
    last_uploaded_file_at = mapped_column(
        DateTime(timezone=True),nullable=True
    ) # To track when a file was last uploaded for this declaration
    last_uploaded_by = mapped_column(String(50), nullable=True) # To track who uploaded the file
    __table_args__ = (
        UniqueConstraint("declaration_name", "financial_year", name="uq_decl_name_fy"),
        {"schema": "annual_declarations"} # Keeping it in the same schema as discussed
    )