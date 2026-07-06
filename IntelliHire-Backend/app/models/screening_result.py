from sqlalchemy import Column, String, TIMESTAMP, BigInteger, ForeignKey, Numeric, Integer,Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.db.base_class import Base

class ScreeningResult(Base):
    __tablename__ = "screening_results"
    __table_args__ = {"schema": "intellihire"}

    screening_result_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    jd_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("intellihire.job_descriptions.jd_id"), nullable=False)
    candidate_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("intellihire.candidates.candidate_id"), nullable=False)
    resume_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("intellihire.resumes.resume_id"), nullable=False)

    skill_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    other_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    overall_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)

    skills_matched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_skills: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matched_skills: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    partial_skills: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    missing_skills: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")

    other_score_breakdown: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    match_status: Mapped[str] = mapped_column(String(20), nullable=False)
    screened_at: Mapped[object] = mapped_column(TIMESTAMP, server_default=func.now())
    candidate_summary: Mapped[str] = mapped_column(Text, nullable=True)
    candidate_experience: Mapped[str] = mapped_column(Text, nullable=True)
    other_score_justifications = Column(JSONB, nullable=True)