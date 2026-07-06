import uuid
from sqlalchemy import String, Text, TIMESTAMP, Boolean, BigInteger, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.db.base_class import Base

class Resume(Base):
    __tablename__ = "resumes"
    __table_args__ = {"schema": "intellihire"}

    resume_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    candidate_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("intellihire.candidates.candidate_id"), nullable=False)
    file_uuid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True, default=uuid.uuid4)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    s3_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed_resume_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_latest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    uploaded_at: Mapped[object] = mapped_column(TIMESTAMP, server_default=func.now())
