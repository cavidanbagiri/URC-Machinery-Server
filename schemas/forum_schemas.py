# schemas/forum_schemas.py
"""Pydantic schemas for the forum module.

Workflow the API supports:

1. a mechanic opens a topic (title + free text + optional machine) and uploads
   the photos of the problem,
2. everybody comments on it (chief mechanic, other workshops, ...),
3. the author marks the topic as resolved and it is archived.

Photo upload is a separate multipart request, exactly like the daily fault PDFs,
because the JSON body cannot carry binary data.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.forum_model import (
    MAX_BODY_LENGTH,
    MAX_COMMENT_LENGTH,
    MAX_RESOLUTION_LENGTH,
    MAX_TITLE_LENGTH,
)

#: Top level (opening) message plus its machine link.
MAX_MACHINE_OPTIONS = 50


def _clean_text(value: str, *, field_label: str, max_length: int) -> str:
    """Collapse surrounding whitespace and reject a blank value."""

    cleaned = (value or "").replace("\r\n", "\n").strip()
    if not cleaned:
        raise ValueError(f"{field_label} zorunludur")
    if len(cleaned) > max_length:
        raise ValueError(
            f"{field_label} en fazla {max_length} karakter olabilir"
        )
    return cleaned


def _clean_optional_text(value: Optional[str], *, max_length: int) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.replace("\r\n", "\n").strip()
    if not cleaned:
        return None
    if len(cleaned) > max_length:
        raise ValueError(f"Metin en fazla {max_length} karakter olabilir")
    return cleaned


def normalize_title(value: str) -> str:
    return _clean_text(value, field_label="Başlık", max_length=MAX_TITLE_LENGTH)


def normalize_body(value: str) -> str:
    return _clean_text(value, field_label="Konu açıklaması", max_length=MAX_BODY_LENGTH)


def normalize_comment(value: str) -> str:
    return _clean_text(value, field_label="Yorum", max_length=MAX_COMMENT_LENGTH)


# =========================================================
# WRITE
# =========================================================

class ForumTopicCreateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., max_length=MAX_TITLE_LENGTH)
    body: str = Field(..., max_length=MAX_BODY_LENGTH)
    #: Optional: the topic may be about a specific machine.
    machine_id: Optional[int] = Field(None, gt=0)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return normalize_title(value)

    @field_validator("body")
    @classmethod
    def validate_body(cls, value: str) -> str:
        return normalize_body(value)


class ForumCommentCreateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(..., max_length=MAX_COMMENT_LENGTH)

    @field_validator("body")
    @classmethod
    def validate_body(cls, value: str) -> str:
        return normalize_comment(value)


class ForumResolveSchema(BaseModel):
    """Close (``is_resolved=True``) or reopen a topic."""

    model_config = ConfigDict(extra="forbid")

    is_resolved: bool = True
    resolution_note: Optional[str] = Field(
        None, max_length=MAX_RESOLUTION_LENGTH
    )

    @field_validator("resolution_note")
    @classmethod
    def normalize_note(cls, value: Optional[str]) -> Optional[str]:
        return _clean_optional_text(value, max_length=MAX_RESOLUTION_LENGTH)


# =========================================================
# READ
# =========================================================

class ForumPhotoSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    topic_id: int
    file_name: str
    content_type: str = "image/jpeg"
    file_size: int = 0

    uploaded_by_id: Optional[int] = None
    uploaded_by_name: Optional[str] = None
    created_at: Optional[datetime] = None


class ForumCommentSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    topic_id: int
    body: str

    author_id: Optional[int] = None
    author_name: Optional[str] = None
    author_position: Optional[str] = None

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ForumTopicSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    body: str

    machine_id: Optional[int] = None
    machine_label: Optional[str] = None
    identification_no: Optional[str] = None
    plate_no: Optional[str] = None

    author_id: Optional[int] = None
    author_name: Optional[str] = None
    author_position: Optional[str] = None

    is_resolved: bool = False
    resolved_at: Optional[datetime] = None
    resolved_by_id: Optional[int] = None
    resolved_by_name: Optional[str] = None
    resolution_note: Optional[str] = None

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    comments_count: int = 0
    photos: list[ForumPhotoSchema] = Field(default_factory=list)
    comments: list[ForumCommentSchema] = Field(default_factory=list)


class PaginatedForumTopicsSchema(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[ForumTopicSchema]


class ForumMachineOptionSchema(BaseModel):
    """Machine picker of the "new topic" form."""

    id: int
    identification_no: Optional[str] = None
    plate_no: Optional[str] = None
    vin_no: Optional[str] = None
    status_name: Optional[str] = None


__all__ = [
    "MAX_MACHINE_OPTIONS",
    "ForumCommentCreateSchema",
    "ForumCommentSchema",
    "ForumMachineOptionSchema",
    "ForumPhotoSchema",
    "ForumResolveSchema",
    "ForumTopicCreateSchema",
    "ForumTopicSchema",
    "PaginatedForumTopicsSchema",
    "normalize_body",
    "normalize_comment",
    "normalize_title",
]
