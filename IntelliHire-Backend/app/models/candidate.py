from sqlalchemy import String, TIMESTAMP, Boolean, BigInteger
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.db.base_class import Base

class Candidate(Base):
    __tablename__ = "candidates"
    __table_args__ = {"schema": "intellihire"}

    candidate_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    duplicate_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[object] = mapped_column(TIMESTAMP, server_default=func.now())
