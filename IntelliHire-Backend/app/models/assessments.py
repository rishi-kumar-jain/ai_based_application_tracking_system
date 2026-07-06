from app.db.base_class import Base
from sqlalchemy import BigInteger, String, Text, Integer, TIMESTAMP, ForeignKey, func, Numeric, UniqueConstraint, text, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column


class Assessment(Base):
    __tablename__ = "assessments"
    __table_args__ = (
        UniqueConstraint(
            "application_id",
            "stage_code",
            name="uq_assessment_application_stage",
        ),
        {"schema": "intellihire"},
    )

    assessment_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    application_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("intellihire.applications.application_id"),
        nullable=False,
    )

    # New stage-based design
    stage_code: Mapped[str] = mapped_column(String(30), nullable=False)
    stage_level: Mapped[int | None] = mapped_column(Integer, nullable=True)

    assessment_sections: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    transcript_s3_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    overall_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)

    summary_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_recommendation: Mapped[str | None] = mapped_column(String(30), nullable=True)

    ai_assessment_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ai_summary_generated_at: Mapped[object | None] = mapped_column(TIMESTAMP, nullable=True)

    status: Mapped[str] = mapped_column(String(30), nullable=False, default="Start")

    created_at: Mapped[object] = mapped_column(TIMESTAMP, server_default=func.now())
    updated_at: Mapped[object] = mapped_column(
        TIMESTAMP,
        server_default=func.now(),
        onupdate=func.now(),
    )

    discrepency_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    areas_of_concern: Mapped[str | None] = mapped_column(Text, nullable=True)
    areas_to_probe_in_next_round: Mapped[str | None] = mapped_column(Text, nullable=True)

    problem_statements: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    assessment_taken_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    transcript_file_name: Mapped[str | None] = mapped_column(String(50), nullable=True)

class AssessmentQuestionBank(Base):
    __tablename__ = "assessment_question_bank"
    __table_args__ = {"schema": "intellihire"}

    question_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    stage_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    
    section_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    display_order: Mapped[int | None] = mapped_column(Integer, nullable=True)

    expected_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    

    topic: Mapped[str | None] = mapped_column(String(100), nullable=True)
    difficulty: Mapped[str | None] = mapped_column(String(30), nullable=True)

    source: Mapped[str] = mapped_column(String(30), nullable=False, default="fixed")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    

    created_at: Mapped[object] = mapped_column(TIMESTAMP, server_default=func.now())
    updated_at: Mapped[object] = mapped_column(
        TIMESTAMP,
        server_default=func.now(),
        onupdate=func.now(),
    )

    

    
    req_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    assessment_sections: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )




