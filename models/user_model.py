# models.py (fixed)
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from db.base import Base




class StatusModel(Base):
    __tablename__ = "statuses"

    id = Column(Integer, primary_key=True)

    status = Column(String, nullable=False, unique=True)

    def __str__(self) -> str:
        return f"{self.status}"

# =========================================================
# IMAGE
# =========================================================

class ImageModel(Base):
    __tablename__ = "images"

    id = Column(Integer, primary_key=True)

    url = Column(String, nullable=False)

    def __str__(self):
        return f"{self.url}"


# =========================================================
# USER
# =========================================================

class UserModel(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)

    firstname = Column(String(100), nullable=False)
    lastname = Column(String(100), nullable=False)

    email = Column(
        String(200),
        nullable=False,
        unique=True,
        index=True
    )

    password = Column(String(255), nullable=False)

    image_id = Column(
        Integer,
        ForeignKey("images.id"),
        nullable=True,
        index=True
    )

    status_id = Column(
        Integer,
        ForeignKey("statuses.id"),
        nullable=False,
        index=True
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    # Relationships
    image = relationship("ImageModel")
    status = relationship("StatusModel")

    tokens = relationship(
        "TokenModel",
        back_populates="user"
    )


# =========================================================
# TOKEN
# =========================================================

class TokenModel(Base):
    __tablename__ = "tokens"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        index=True
    )

    access_token = Column(
        String(500),
        nullable=False,
        unique=True
    )

    refresh_token = Column(
        String(500),
        nullable=False,
        unique=True
    )

    expires_at = Column(
        DateTime(timezone=True),
        nullable=False
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    # Relationships
    user = relationship(
        "UserModel",
        back_populates="tokens"
    )






