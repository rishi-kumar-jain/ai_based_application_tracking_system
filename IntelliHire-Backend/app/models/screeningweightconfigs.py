from sqlalchemy import BigInteger, String, Boolean, TIMESTAMP, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import String, TIMESTAMP, BigInteger, ForeignKey, Numeric, Integer,Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.db.base_class import Base

class ScreeningWeightConfig(Base):
    __tablename__ = "screening_weight_configs"
    __table_args__ = {"schema": "intellihire"}

    config_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True
    )

    jd_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("intellihire.job_descriptions.jd_id"),
        nullable=False,
        unique=True
    )

    weights: Mapped[dict] = mapped_column(JSONB, nullable=False)

    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[object] = mapped_column(TIMESTAMP, server_default=func.now())
    updated_at: Mapped[object] = mapped_column(
        TIMESTAMP,
        server_default=func.now(),
        onupdate=func.now()
    )