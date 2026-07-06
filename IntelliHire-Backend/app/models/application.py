from pydantic import Field

from sqlalchemy import String, TIMESTAMP, BigInteger, ForeignKey, UniqueConstraint, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.db.base_class import Base

class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("candidate_id", "jd_id", name="uq_app_candidate_jd"),
        {"schema": "intellihire"},
    )

    application_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    jd_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("intellihire.job_descriptions.jd_id"), nullable=False)
    candidate_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("intellihire.candidates.candidate_id"), nullable=False)
    current_resume_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("intellihire.resumes.resume_id"), nullable=True)
    latest_screening_result_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("intellihire.screening_results.screening_result_id"), nullable=True)
    current_stage: Mapped[str] = mapped_column(String(50), nullable=False, default="NOT_IN_PIPELINE")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="ACTIVE")
    created_at: Mapped[object] = mapped_column(TIMESTAMP, server_default=func.now())
    updated_at: Mapped[object] = mapped_column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
    assigned_recruiter_id: Mapped[str] = mapped_column(String(30), nullable=False, default="System")
    # assessments = relationship("Assessment", backref="application", lazy="select")

class ApplicationStageHistory(Base):
    __tablename__ = "application_stage_history"
    __table_args__ = {"schema": "intellihire"}

    history_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    application_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("intellihire.applications.application_id"), nullable=False)
    from_stage: Mapped[str | None] = mapped_column(String(50), nullable=True)
    to_stage: Mapped[str] = mapped_column(String(50), nullable=False)
    changed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_at: Mapped[object] = mapped_column(TIMESTAMP, server_default=func.now())


