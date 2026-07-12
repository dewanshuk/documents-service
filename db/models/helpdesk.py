from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import Column, String, Boolean, false, func, DateTime, Integer, ForeignKey, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from datetime import datetime

class Base(DeclarativeBase):
    pass

class BaseUsers(Base):
    __abstract__ = True
    __table_args__ = {"schema": "users"}

class User(BaseUsers):
    __tablename__ = "users"
    staff_id: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True, server_default="active"
    )
    is_master_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false()
    )
    is_policy_hub_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false()
    )
    is_knowledge_hub_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false()
    )
    is_cobce_coi_gift_lead: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false()
    )
    is_complaint_lead: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false()
    )
    is_query_lead: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false()
    )
    is_cheif_compliance_officer: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false()
    )
    


class ComplianceQuery(Base):
    __tablename__ = "compliance_queries"
    __table_args__ = {"schema": "compliance"} 

    QueryId: Mapped[str] = mapped_column(String(100), primary_key=True)
    QueryType: Mapped[str] = mapped_column(String(50), nullable=False)
    Title: Mapped[str] = mapped_column(String(500), nullable=False)
    Description: Mapped[str] = mapped_column(String(5000), nullable=False)

    CreatedOn: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    CreatedBy: Mapped[str] = mapped_column(String(255), nullable=False)

    OverallStatus: Mapped[str] = mapped_column(String(50), nullable=False)
    PendingAt: Mapped[int] = mapped_column(Integer, nullable=False)
    AssignedTo: Mapped[str | None] = mapped_column(String(255), nullable=True)

    ResponseJsonPath: Mapped[str] = mapped_column(String(1000), nullable=False)

    ClosureDate: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ClosedBy: Mapped[str | None] = mapped_column(String(255), nullable=True)

    LastUpdatedOn: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )

class GiftDeclarations(Base):
    __tablename__ = "gift_declarations"
    __table_args__ = {"schema": "compliance"}

    GiftId: Mapped[str] = mapped_column(String(80), primary_key=True)
    Status: Mapped[str]
    Person: Mapped[str]
    Organization: Mapped[str]
    ApproxValueINR: Mapped[float]
    PortalApprovalTaken: Mapped[str]
    PortalNumber: Mapped[str | None]

    CreatedOn: Mapped[datetime]
    CreatedBy: Mapped[str]

    OverallStatus: Mapped[str]
    PendingAt: Mapped[int]
    AssignedTo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ResponseJsonPath: Mapped[str]

    ClosureDate: Mapped[datetime | None]
    ClosedBy: Mapped[str | None] = mapped_column(String(255), nullable=True)
    LastUpdatedOn: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

class Complaints(Base):
    __tablename__ = "complaints"
    __table_args__ = {"schema": "compliance"}

    ComplaintId: Mapped[str] = mapped_column(String(80), primary_key=True)
    ComplaintType: Mapped[str]
    ComplaintDetails: Mapped[str]

    CreatedOn: Mapped[datetime]
    CreatedBy: Mapped[str]

    OverallStatus: Mapped[str]
    PendingAt: Mapped[int]
    AssignedTo: Mapped[str | None] = mapped_column(String(255), nullable=True)

    ResponseJsonPath: Mapped[str]

    ClosureDate: Mapped[datetime | None]
    ClosedBy: Mapped[str | None] = mapped_column(String(255), nullable=True)
    LastUpdatedOn: Mapped[datetime | None]

class COBCEDeclarations(Base):
    __tablename__ = "cobce_declarations"
    __table_args__ = {"schema": "compliance"}

    COBCEId: Mapped[str] = mapped_column(String(80), primary_key=True)

    SubType: Mapped[str]
    Description: Mapped[str]
    PersonDetails: Mapped[dict] = mapped_column(JSON, nullable=False)

    Status: Mapped[str]  # Draft / In-Progress / Completed

    CreatedOn: Mapped[datetime]
    CreatedBy: Mapped[str]

    OverallStatus: Mapped[str | None]
    PendingAt: Mapped[int | None]
    AssignedTo: Mapped[str | None] = mapped_column(String(255), nullable=True)

    ClosureDate: Mapped[datetime | None]
    ClosedBy: Mapped[str | None]
    LastUpdatedOn: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    ResponseJsonPath: Mapped[str | None]

class COIDeclarations(Base):
    __tablename__ = "coi_declarations"
    __table_args__ = {"schema": "compliance"}
    COIId: Mapped[str] = mapped_column(String(80), primary_key=True)

    SubType: Mapped[str]
    FormData: Mapped[dict] = mapped_column(JSON, nullable=False)

    Status: Mapped[str]  # Draft / In-Progress / Completed

    CreatedOn: Mapped[datetime]
    CreatedBy: Mapped[str]

    OverallStatus: Mapped[str | None]
    PendingAt: Mapped[int | None]
    AssignedTo: Mapped[str | None] = mapped_column(String(255), nullable=True)

    ClosureDate: Mapped[datetime | None]
    ClosedBy: Mapped[str | None]
    LastUpdatedOn: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    ResponseJsonPath: Mapped[str | None]


class R518Declarations(Base):
    __tablename__ = "r518_declarations"
    __table_args__ = {"schema": "compliance"}

    R518Id: Mapped[str] = mapped_column(String(80), primary_key=True)

    SubType: Mapped[str]
    FormData: Mapped[dict] = mapped_column(JSON, nullable=False)

    Status: Mapped[str]  # Draft / In-Progress / Completed

    CreatedOn: Mapped[datetime]
    CreatedBy: Mapped[str]

    OverallStatus: Mapped[str | None]
    PendingAt: Mapped[int | None]
    AssignedTo: Mapped[str | None] = mapped_column(String(255), nullable=True)

    ClosureDate: Mapped[datetime | None]
    ClosedBy: Mapped[str | None]
    LastUpdatedOn: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    ResponseJsonPath: Mapped[str | None]

class RecentUserRecords(Base):
    __tablename__ = "recent_user_records"
    __table_args__ = {"schema": "compliance"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    record_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    record_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    sub_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    created_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    pending_at: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_accessed_on: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), index=True
    )