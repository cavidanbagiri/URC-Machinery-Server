# models/forum_model.py
"""Forum topics, their comments and the photos attached to a topic.

The forum is where the workshop talks about an event: a mechanic reports that a
tyre burst and a spare part is needed urgently, attaches a photo, the chief
mechanic and the others answer, and finally the author marks the topic as
resolved so it is archived.

A topic is therefore a small discussion thread:

* ``forum_topics``       one row per thread (title, body, optional machine)
* ``forum_topic_photos`` photos attached to the opening message
* ``forum_comments``     the replies, oldest first

Photo bytes live in PostgreSQL, exactly like the daily fault PDFs: the API host
(Render) has an ephemeral filesystem, so storing the file in the database keeps
the pictures available after a restart without extra storage configuration.
"""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from db.base import Base

#: Text limits; mirrored by the Pydantic schemas and the frontend counters.
MAX_TITLE_LENGTH = 160
MAX_BODY_LENGTH = 4000
MAX_COMMENT_LENGTH = 2000
MAX_RESOLUTION_LENGTH = 1000

#: Hard limit for one uploaded photo (mirrored by
#: ``ck_forum_topic_photos_size_limit`` and enforced by the repository).
MAX_PHOTO_BYTES = 5 * 1024 * 1024
#: A topic may not carry more photos than this (checked by the repository).
MAX_PHOTOS_PER_TOPIC = 6


class ForumTopicModel(Base):
    __tablename__ = "forum_topics"

    id = Column(Integer, primary_key=True, index=True)

    title = Column(String(MAX_TITLE_LENGTH), nullable=False)
    body = Column(Text, nullable=False)

    #: Optional link to the machine the topic is about ("bu arabanın lastiği
    #: patladı"). ``SET NULL`` so deleting a machine keeps the discussion.
    machine_id = Column(
        Integer,
        ForeignKey("all_machines.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    created_by_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    #: True once the author (or a user with write permission) closes the topic.
    is_resolved = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
        index=True,
    )
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    #: How the problem was solved ("Lastik değiştirildi, araç sahaya döndü").
    resolution_note = Column(Text, nullable=True)

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

    # Two foreign keys point at ``users``; the explicit ``foreign_keys`` keeps
    # the mapper from guessing which column belongs to which relationship.
    author = relationship("UserModel", foreign_keys=[created_by_id])
    resolver = relationship("UserModel", foreign_keys=[resolved_by_id])
    machine = relationship("AllMachineModel")

    photos = relationship(
        "ForumTopicPhotoModel",
        back_populates="topic",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ForumTopicPhotoModel.created_at, ForumTopicPhotoModel.id",
    )
    comments = relationship(
        "ForumCommentModel",
        back_populates="topic",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ForumCommentModel.created_at, ForumCommentModel.id",
    )

    def __str__(self) -> str:
        return self.title


class ForumTopicPhotoModel(Base):
    """A photo of the opening message (burst tyre, damaged hose, ...)."""

    __tablename__ = "forum_topic_photos"

    __table_args__ = (
        CheckConstraint(
            "file_size > 0",
            name="ck_forum_topic_photos_size_positive",
        ),
        CheckConstraint(
            f"file_size <= {MAX_PHOTO_BYTES}",
            name="ck_forum_topic_photos_size_limit",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    topic_id = Column(
        Integer,
        ForeignKey("forum_topics.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    file_name = Column(String(255), nullable=False)
    content_type = Column(String(100), nullable=False, default="image/jpeg")
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

    topic = relationship("ForumTopicModel", back_populates="photos")
    uploaded_by = relationship("UserModel")

    def __str__(self) -> str:
        return self.file_name


class ForumCommentModel(Base):
    """One reply in a topic. Plain text; newlines are kept for the UI."""

    __tablename__ = "forum_comments"

    id = Column(Integer, primary_key=True, index=True)
    topic_id = Column(
        Integer,
        ForeignKey("forum_topics.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    body = Column(Text, nullable=False)

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

    topic = relationship("ForumTopicModel", back_populates="comments")
    author = relationship("UserModel")

    def __str__(self) -> str:
        return f"Yorum #{self.id}"


__all__ = [
    "MAX_BODY_LENGTH",
    "MAX_COMMENT_LENGTH",
    "MAX_PHOTOS_PER_TOPIC",
    "MAX_PHOTO_BYTES",
    "MAX_RESOLUTION_LENGTH",
    "MAX_TITLE_LENGTH",
    "ForumCommentModel",
    "ForumTopicModel",
    "ForumTopicPhotoModel",
]
