import uuid
import enum
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import (
    String,
    Date,
    DateTime,
    Text,
    Boolean,
    Integer,
    ForeignKey,
    UniqueConstraint,
    Enum,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, mapped_column, relationship

IST = ZoneInfo("Asia/Kolkata")


class Base(DeclarativeBase):
    pass


class DeclarationType(enum.Enum):
    COBCE_COI = "COBCE/COI"
    R5_18 = "R5.18"


class SyncStatus(enum.Enum):
    """NULL = no file uploaded | PENDING | COMPLETED | FAILED"""

    PENDING = "PENDING"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "users"}

    staff_id = mapped_column(String, primary_key=True)
    username = mapped_column(String, nullable=True)
    email = mapped_column(String, unique=True, nullable=False, index=True)
    department = mapped_column(String, nullable=True)
    status = mapped_column(String, nullable=False)
    is_master_admin = mapped_column(Boolean, nullable=False, default=False)
    is_knowledge_hub_admin = mapped_column(Boolean, nullable=False, default=False)
    is_policy_hub_admin = mapped_column(Boolean, nullable=False, default=False)


def as_declaration_name(value: DeclarationType | str) -> str:
    if isinstance(value, DeclarationType):
        return value.value
    return str(value)


class AnnualDeclaration(Base):
    __tablename__ = "annual_declarations"
    __table_args__ = (
        UniqueConstraint("declaration_name", "financial_year", name="uq_decl_name_fy"),
        {"schema": "annual_declarations"},
    )

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    declaration_name = mapped_column(String(20), nullable=False)
    financial_year = mapped_column(String(7), nullable=False)
    assigned_date = mapped_column(Date, nullable=False)
    due_date = mapped_column(Date, nullable=False)
    activity_closure_date = mapped_column(Date, nullable=False)
    status = mapped_column(String(50), nullable=False, default="Pending")
    last_updated_at = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(IST),
        onupdate=lambda: datetime.now(IST),
    )
    file_path = mapped_column(Text, nullable=True)
    last_uploaded_file_at = mapped_column(DateTime(timezone=True), nullable=True)
    last_uploaded_by = mapped_column(String(50), nullable=True)
    pending_count = mapped_column(Integer, nullable=False, default=0)
    total_count = mapped_column(Integer, nullable=False, default=0)
    excel_pending_status = mapped_column(String(20), nullable=True)
    sync_status = mapped_column(
        Enum(
            SyncStatus,
            name="sync_status_enum",
            schema="annual_declarations",
            values_callable=lambda obj: [e.value for e in obj],
            native_enum=False,
        ),
        nullable=True,
    )

    user_statuses = relationship(
        "UserDeclarationStatus",
        back_populates="declaration",
        cascade="all, delete-orphan",
    )


class UserDeclarationStatus(Base):
    """Lazy-created when user saves/submits or admin syncs notify from Excel."""

    __tablename__ = "user_declaration_status"
    __table_args__ = (
        UniqueConstraint("declaration_id", "staff_id", name="uq_declaration_user"),
        {"schema": "annual_declarations"},
    )

    id = mapped_column(String(80), primary_key=True)
    declaration_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("annual_declarations.annual_declarations.id", ondelete="CASCADE"),
        nullable=False,
    )
    staff_id = mapped_column(String(50), nullable=False)
    status = mapped_column(String(20), nullable=False, default="draft")
    has_conflicts = mapped_column(Boolean, nullable=False, default=False)
    notify = mapped_column(Boolean, nullable=False, default=True)
    submitted_at = mapped_column(DateTime(timezone=True), nullable=True)
    last_saved_at = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(IST),
        onupdate=lambda: datetime.now(IST),
    )
    created_at = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(IST)
    )

    declaration = relationship("AnnualDeclaration", back_populates="user_statuses")
    responses = relationship(
        "UserDeclarationResponse",
        back_populates="declaration_status",
        cascade="all, delete-orphan",
    )


class UserDeclarationResponse(Base):
    """One row per question; disagree details stored in JSONB."""

    __tablename__ = "user_declaration_responses"
    __table_args__ = (
        UniqueConstraint(
            "declaration_status_id", "question_id", name="uq_status_question"
        ),
        {"schema": "annual_declarations"},
    )

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    declaration_status_id = mapped_column(
        String(80),
        ForeignKey(
            "annual_declarations.user_declaration_status.id", ondelete="CASCADE"
        ),
        nullable=False,
    )
    question_id = mapped_column(String(50), nullable=False)
    response = mapped_column(String(20), nullable=True)
    declaration_details = mapped_column(JSONB, nullable=True)
    created_at = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(IST)
    )
    updated_at = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(IST),
        onupdate=lambda: datetime.now(IST),
    )

    declaration_status = relationship(
        "UserDeclarationStatus", back_populates="responses"
    )
