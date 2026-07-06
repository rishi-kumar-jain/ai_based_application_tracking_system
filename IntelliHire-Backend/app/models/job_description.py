import uuid
from sqlalchemy import String, Text, Boolean, TIMESTAMP, BigInteger, Integer,Column
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.db.base_class import Base

from typing import Any, Optional
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableList

StageObj = dict[str, Any]

class JobDescription(Base):
    __tablename__ = "job_descriptions"
    __table_args__ = {"schema": "intellihire"}

    jd_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    req_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    grade: Mapped[str] = mapped_column(String(50), nullable=True)

    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
    experience: Mapped[str | None] = mapped_column(Text, nullable=True)
    role_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    responsibilities: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    mandatory_skills: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    good_to_have_skills: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    problem_statements: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    qualifications: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")

    jd_s3_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    jd_file_uuid: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    jd_uploaded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    jd_parsed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    jd_source_type: Mapped[str | None] = mapped_column(String(20), nullable=True)  # upload/manual
    jd_raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    jd_parse_status: Mapped[str | None] = mapped_column(String(30), nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    created_at: Mapped[object] = mapped_column(TIMESTAMP, server_default=func.now())
    updated_at: Mapped[object] = mapped_column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    jd_stage: Mapped[str] = mapped_column(String(10), nullable=True, default="1.1")
    file_name: Mapped[str | None] = mapped_column(Text, nullable=True)

    jd_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    jd_score_justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    jd_suggestions: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
 
    
    
    lob_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    lob: Mapped[str | None] = mapped_column(String(100), nullable=True)

    vertical: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # stages: Mapped[list] = mapped_column(JSONB, nullable=True, server_default="[]")

    
    stages: Mapped[list[StageObj]] = mapped_column(
        MutableList.as_mutable(JSONB),
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )

    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_by_email: Mapped[str | None] = mapped_column(String(100), nullable=True)

class HorizontalMaster(Base):
    __tablename__ = "HorizontalMaster"
    __table_args__ = {"schema": "public"}  
    HorizontalId = Column(Integer, primary_key=True, index=True)
    Horizontal = Column(String)

class EmployeeMaster(Base):
    __tablename__ = "EmployeeMaster"
    __table_args__ = {"schema": "public"}

    
    EmpId: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)

    EmpCode: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    EmpName: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    EmailId: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    HorizontalId: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class ProjectMaster(Base):
    __tablename__ = "ProjectMaster"
    __table_args__ = {"schema": "public"}
    ProjId = Column(Integer, primary_key=True, index=True)
    ProjHorizontalId = Column(Integer)

class HRISTranscation(Base):
    __tablename__ = "HRISTransaction"
    __table_args__ = {"schema": "public"}

    RecId: Mapped[int] = mapped_column(
        "RecId",
        BigInteger,
        primary_key=True,
        index=True
    )

    Division: Mapped[str | None] = mapped_column(
        "Division",
        String(100),   # VARCHAR(100)
        nullable=True
    )

    Vertical: Mapped[str | None] = mapped_column(
        "Vertical",
        String(100),   # VARCHAR(100)
        nullable=True
    )

    
    SnapshotActiveFlag: Mapped[int] = mapped_column(
            "SnapshotActiveFlag",
            Integer,
            nullable=False
        )

