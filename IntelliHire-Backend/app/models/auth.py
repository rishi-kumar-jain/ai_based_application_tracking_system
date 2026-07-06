from sqlalchemy import String, Text, Boolean, TIMESTAMP, BigInteger, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column , relationship
from sqlalchemy.sql import func
from app.db.base_class import Base



# from app.db.base import Base
class Role(Base):
    __tablename__ = "roles"
    __table_args__ = {"schema": "intellihire"}

    role_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    role_name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[object] = mapped_column(TIMESTAMP, server_default=func.now())

    users = relationship(
        "User",
        secondary="intellihire.user_roles",
        back_populates="roles",
    )

class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = {"schema": "intellihire"}

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("intellihire.users.user_id", ondelete="CASCADE"),
        primary_key=True,
    )

    role_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("intellihire.roles.role_id", ondelete="CASCADE"),
        primary_key=True,
    )


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "intellihire"}

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    azure_oid: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        unique=True,
        index=True,
    )

    roles = relationship(
        "Role",
        secondary="intellihire.user_roles",
        back_populates="users",
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[object] = mapped_column(TIMESTAMP, server_default=func.now())
    updated_at: Mapped[object] = mapped_column(
        TIMESTAMP,
        server_default=func.now(),
        onupdate=func.now(),
    )

# from __future__ import annotations

# from sqlalchemy import (
#     BigInteger,
#     String,
#     Text,
#     TIMESTAMP,
#     Boolean,
#     ForeignKey,
# )
# from sqlalchemy.orm import Mapped, mapped_column, relationship
# from sqlalchemy.sql import func

# from app.db.base import Base


# class UserRole(Base):
#     __tablename__ = "user_roles"
#     __table_args__ = {"schema": "intellihire"}

#     user_id: Mapped[int] = mapped_column(
#         BigInteger,
#         ForeignKey("intellihire.users.user_id", ondelete="CASCADE"),
#         primary_key=True,
#     )

#     role_id: Mapped[int] = mapped_column(
#         BigInteger,
#         ForeignKey("intellihire.roles.role_id", ondelete="CASCADE"),
#         primary_key=True,
#     )


# class Role(Base):
#     __tablename__ = "roles"
#     __table_args__ = {"schema": "intellihire"}

#     role_id: Mapped[int] = mapped_column(
#         BigInteger,
#         primary_key=True,
#         autoincrement=True,
#     )

#     role_name: Mapped[str] = mapped_column(
#         String(50),
#         nullable=False,
#         unique=True,
#     )

#     description: Mapped[str | None] = mapped_column(
#         Text,
#         nullable=True,
#     )

#     created_at: Mapped[object] = mapped_column(
#         TIMESTAMP,
#         server_default=func.now(),
#     )

#     users: Mapped[list["User"]] = relationship(
#         "User",
#         secondary=lambda: UserRole.__table__,
#         back_populates="roles",
#     )


# class User(Base):
#     __tablename__ = "users"
#     __table_args__ = {"schema": "intellihire"}

#     user_id: Mapped[int] = mapped_column(
#         BigInteger,
#         primary_key=True,
#         autoincrement=True,
#     )

#     email: Mapped[str] = mapped_column(
#         String(255),
#         nullable=False,
#         unique=True,
#         index=True,
#     )

#     full_name: Mapped[str | None] = mapped_column(
#         String(255),
#         nullable=True,
#     )

#     azure_oid: Mapped[str | None] = mapped_column(
#         String(100),
#         nullable=True,
#         unique=True,
#         index=True,
#     )

#     roles: Mapped[list["Role"]] = relationship(
#         "Role",
#         secondary=lambda: UserRole.__table__,
#         back_populates="users",
#     )

#     is_active: Mapped[bool] = mapped_column(
#         Boolean,
#         nullable=False,
#         default=True,
#     )

#     created_at: Mapped[object] = mapped_column(
#         TIMESTAMP,
#         server_default=func.now(),
#     )

#     updated_at: Mapped[object] = mapped_column(
#         TIMESTAMP,
#         server_default=func.now(),
#         onupdate=func.now(),
#     )