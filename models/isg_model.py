# models/isg_model.py
"""ISG (İş Sağlığı ve Güvenliği) nonconformity records and their evidence.

Every row is one nonconformity opened on a site (``territories``) and owned by
one responsible person of the ISG team.  Two independent attributes are stored:

* ``status``   — ``acik`` while the nonconformity is still open, ``kapali`` once
  it was closed; ``closed_at`` / ``closed_by_id`` remember when and by whom;
* ``severity`` — ``kritik`` / ``onemli`` / ``az_onemli``, the importance picked
  in the form ("Önem Derecesi").

Closing a record may carry evidence files (PDF report or a photo).  The bytes
live in PostgreSQL (``BYTEA``) because the API host has an ephemeral filesystem
and the photo bucket is optional; this keeps the evidence available after
restarts without extra storage configuration.  List responses expose the
metadata only, the bytes are streamed by a dedicated endpoint.

SRU and DCU are the two main sites; the stat cards of the page are computed
from ``territories.name`` (case-insensitive), so renaming a site in Ayarlar
moves its rows to the new name without touching this table.
"""

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from db.base import Base

#: Hard limit for one uploaded evidence file, mirrored by
#: ``ck_isg_attachments_size_limit`` and enforced by
#: ``repositories/isg_evidence.py``.
MAX_EVIDENCE_BYTES = 10 * 1024 * 1024

#: Stored states.  The same two codes are a check constraint on the table.
ISG_STATUS_OPEN = "acik"
ISG_STATUS_CLOSED = "kapali"
ISG_STATUSES = (ISG_STATUS_OPEN, ISG_STATUS_CLOSED)
ISG_STATUS_LABELS = {
    ISG_STATUS_OPEN: "Açık",
    ISG_STATUS_CLOSED: "Kapalı",
}

#: Importance codes of "Önem Derecesi".  The same three codes are a check
#: constraint on the table.  The label is exposed as ``severity_label`` so the
#: React table never needs to duplicate the Turkish spelling.
ISG_SEVERITY_CRITICAL = "kritik"
ISG_SEVERITY_IMPORTANT = "onemli"
ISG_SEVERITY_LOW = "az_onemli"
ISG_SEVERITIES = (
    ISG_SEVERITY_CRITICAL,
    ISG_SEVERITY_IMPORTANT,
    ISG_SEVERITY_LOW,
)
ISG_SEVERITY_DEFAULT = ISG_SEVERITY_IMPORTANT
ISG_SEVERITY_LABELS = {
    ISG_SEVERITY_CRITICAL: "Kritik",
    ISG_SEVERITY_IMPORTANT: "Önemli",
    ISG_SEVERITY_LOW: "Az Önemli",
}

#: The ISG team members offered by the "Sorumlu" dropdown.  The schema accepts
#: them case-insensitively and stores the canonical spelling below, so the
#: table always shows the same names.
ISG_RESPONSIBLES = (
    "Ramiz Khayramov",
    "Mustafa Palta",
    "Andrey Stepanov",
    "Imomjon Shadyev",
)
MAX_RESPONSIBLE_LENGTH = 100

#: Sites whose opened/closed totals are the stat cards of the page.
ISG_STAT_SITES = ("SRU", "DCU")

#: Description limits ("Açıklama") mirrored by the schema and the frontend.
MAX_DESCRIPTION_LENGTH = 2000


class IsgNonconformityModel(Base):
    __tablename__ = "isg_nonconformities"

    __table_args__ = (
        CheckConstraint(
            "status IN ('acik', 'kapali')",
            name="ck_isg_nonconformities_status",
        ),
        CheckConstraint(
            "severity IN ('kritik', 'onemli', 'az_onemli')",
            name="ck_isg_nonconformities_severity",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    record_date = Column(
        Date,
        nullable=False,
        server_default=func.current_date(),
        index=True,
    )
    description = Column(Text, nullable=False)

    status = Column(
        String(10),
        nullable=False,
        default=ISG_STATUS_OPEN,
        server_default=ISG_STATUS_OPEN,
        index=True,
    )

    # "Önem Derecesi": Kritik / Önemli / Az Önemli.  It is independent of the
    # open/closed status — a closed record keeps the importance it was opened
    # with, and an open one can be critical.
    severity = Column(
        String(12),
        nullable=False,
        default=ISG_SEVERITY_DEFAULT,
        server_default=ISG_SEVERITY_DEFAULT,
        index=True,
    )

    # "Şantiye": the site where the nonconformity was found.  Deleting a site
    # that still owns records is refused (RESTRICT), like daily faults.
    territory_id = Column(
        Integer,
        ForeignKey("territories.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    responsible_name = Column(
        String(MAX_RESPONSIBLE_LENGTH),
        nullable=False,
        index=True,
    )

    closed_at = Column(DateTime(timezone=True), nullable=True)
    closed_by_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    created_by_id = Column(
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
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    territory = relationship("TerritoryModel")
    created_by = relationship("UserModel", foreign_keys=[created_by_id])
    closed_by = relationship("UserModel", foreign_keys=[closed_by_id])
    attachments = relationship(
        "IsgAttachmentModel",
        back_populates="nonconformity",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="IsgAttachmentModel.id",
    )

    def __str__(self) -> str:
        return f"ISG uygunsuzluğu #{self.id}"


class IsgAttachmentModel(Base):
    """A PDF report or a photo proving that a nonconformity was closed."""

    __tablename__ = "isg_attachments"

    __table_args__ = (
        CheckConstraint(
            "file_size > 0",
            name="ck_isg_attachments_size_positive",
        ),
        CheckConstraint(
            f"file_size <= {MAX_EVIDENCE_BYTES}",
            name="ck_isg_attachments_size_limit",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    nonconformity_id = Column(
        Integer,
        ForeignKey("isg_nonconformities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    file_name = Column(String(255), nullable=False)
    content_type = Column(String(100), nullable=False)
    file_size = Column(Integer, nullable=False)
    file_data = Column(LargeBinary, nullable=False)

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

    nonconformity = relationship(
        "IsgNonconformityModel",
        back_populates="attachments",
    )
    uploaded_by = relationship("UserModel")

    def __str__(self) -> str:
        return self.file_name


__all__ = [
    "ISG_RESPONSIBLES",
    "ISG_SEVERITIES",
    "ISG_SEVERITY_CRITICAL",
    "ISG_SEVERITY_DEFAULT",
    "ISG_SEVERITY_IMPORTANT",
    "ISG_SEVERITY_LABELS",
    "ISG_SEVERITY_LOW",
    "ISG_STAT_SITES",
    "ISG_STATUSES",
    "ISG_STATUS_CLOSED",
    "ISG_STATUS_LABELS",
    "ISG_STATUS_OPEN",
    "MAX_DESCRIPTION_LENGTH",
    "MAX_EVIDENCE_BYTES",
    "MAX_RESPONSIBLE_LENGTH",
    "IsgAttachmentModel",
    "IsgNonconformityModel",
]
