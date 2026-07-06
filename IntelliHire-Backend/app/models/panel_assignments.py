from typing import Optional

from sqlalchemy import (
    BigInteger,
    String,
    Boolean,
    TIMESTAMP,
    ForeignKey,
    Integer,
    Index,
    Text,
    text,
)

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base_class import Base


class PanelAssignment(Base):
    __tablename__ = "panel_assignments"
    __table_args__ = (
        # Unique active panelist per (application, stage, employee)
        Index(
            "ux_panel_member_active",
            "application_id",
            "panel_stage",
            "hris_employee_id",
            unique=True,
            postgresql_where=text("is_active = true"),
        ),

        # Only one primary panelist active per (application, stage)
        Index(
            "ux_primary_panel_active",
            "application_id",
            "panel_stage",
            unique=True,
            postgresql_where=text("is_active = true AND is_primary = true"),
        ),

        Index(
            "ix_panel_app_stage_active",
            "application_id",
            "panel_stage",
            "is_active",
        ),

        {"schema": "intellihire"},
    )

    panel_assignment_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    application_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("intellihire.applications.application_id"),
        nullable=False,
    )

    panel_stage: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    # Match EmployeeMaster.EmpId type
    hris_employee_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )

    is_primary: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    # Preserves selection order shown in UI
    sequence_no: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )

    # Audit fields
    assigned_by: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )

    created_at: Mapped[object] = mapped_column(
        TIMESTAMP,
        server_default=func.now(),
    )

    # Soft delete fields
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    removed_at: Mapped[Optional[object]] = mapped_column(
        TIMESTAMP,
        nullable=True,
    )

    removed_by: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )

    candidate_purpose: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )