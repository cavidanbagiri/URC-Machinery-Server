# models/machine_photo_model.py
"""Photos of machines stored in S3-compatible object storage.

PostgreSQL keeps only the object key plus descriptive metadata; the public URL
is built at response time (see services/storage_service.py), so links never go
stale and the bucket can move without a data migration.
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from db.base import Base


class MachinePhotoModel(Base):
    __tablename__ = "machine_photos"

    # At most one "Ana fotoğraf" per machine. Mirrors
    # uq_repair_records_active_machine in models/repair_model.py.
    __table_args__ = (
        Index(
            "uq_machine_photos_primary",
            "machine_id",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(
        Integer,
        ForeignKey("all_machines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Object key inside S3_BUCKET, e.g. "machines/12/8f2c....jpg".
    object_key = Column(String(512), nullable=False, unique=True)
    original_filename = Column(String(255), nullable=True)
    content_type = Column(String(100), nullable=True)
    size_bytes = Column(Integer, nullable=True)

    is_primary = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )

    uploaded_by_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    machine = relationship("AllMachineModel", back_populates="photos")

    def __str__(self) -> str:
        return self.original_filename or self.object_key
