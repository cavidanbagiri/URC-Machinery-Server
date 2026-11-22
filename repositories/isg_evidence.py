# repositories/isg_evidence.py
"""Validation for ISG closure evidence (a PDF report or a photo).

The bytes are stored in PostgreSQL, so the helpers here are the only guard
between an upload and the table: the file name is reduced to its base name, the
size is limited, only PDF / JPEG / PNG / WEBP are accepted and the file
signature must match the declared type (a client can lie about both the name
and the content type).

The messages are Turkish and identical to the ones of the PDF-only helpers in
``repositories/pdf_documents.py`` where the wording overlaps, so the API never
returns two different texts for "too big" or "empty file".
"""

from pathlib import Path
from typing import Any, Optional

from repositories.pdf_documents import sanitize_file_name

#: Hard limit for one uploaded evidence file (mirrored by
#: ``MAX_EVIDENCE_BYTES`` / ``ck_isg_attachments_size_limit``).
MAX_EVIDENCE_BYTES = 10 * 1024 * 1024

#: Canonical content type -> extension.  ``image/jpg`` is an alias, mapped below.
ALLOWED_EVIDENCE_TYPES = {
    "application/pdf": ".pdf",
    "application/x-pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

_CONTENT_TYPE_ALIASES = {
    "application/x-pdf": "application/pdf",
    "image/jpg": "image/jpeg",
    "image/pjpeg": "image/jpeg",
}

_EXTENSION_TYPES = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}

#: Some browsers submit an empty type (or octet-stream) for local files; then
#: only the extension can decide.
_FALLBACK_TYPES = {"", "application/octet-stream", "binary/octet-stream"}

_PDF_SIGNATURE = b"%PDF-"
_JPEG_SIGNATURE = b"\xff\xd8\xff"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

INVALID_TYPE_MESSAGE = (
    "Sadece PDF veya fotoğraf (JPEG, PNG, WEBP) yükleyebilirsiniz"
)


def is_image_content_type(content_type: Optional[str]) -> bool:
    """True for the image types this module accepts (used by the response)."""

    return (content_type or "").split(";")[0].strip().lower().startswith("image/")


def resolve_evidence_content_type(
    file_name: Optional[str],
    content_type: Optional[str],
) -> str:
    """Canonical content type of an upload or raise ``ValueError``."""

    declared = (content_type or "").split(";")[0].strip().lower()
    declared = _CONTENT_TYPE_ALIASES.get(declared, declared)

    if declared in ALLOWED_EVIDENCE_TYPES:
        return declared

    if declared in _FALLBACK_TYPES:
        suffix = Path(file_name or "").suffix.lower()
        if suffix in _EXTENSION_TYPES:
            return _EXTENSION_TYPES[suffix]

    raise ValueError(INVALID_TYPE_MESSAGE)


def _signature_matches(content_type: str, data: bytes) -> bool:
    if content_type == "application/pdf":
        return data.startswith(_PDF_SIGNATURE)
    if content_type == "image/jpeg":
        return data.startswith(_JPEG_SIGNATURE)
    if content_type == "image/png":
        return data.startswith(_PNG_SIGNATURE)
    if content_type == "image/webp":
        # RIFF container with the "WEBP" fourcc at byte 8.
        return (
            len(data) >= 12
            and data[:4] == b"RIFF"
            and data[8:12] == b"WEBP"
        )
    return False


def validate_evidence(
    file_name: Optional[str],
    content_type: Optional[str],
    data: bytes,
    *,
    max_bytes: int = MAX_EVIDENCE_BYTES,
) -> dict[str, Any]:
    """Validate one evidence file; raises ``ValueError`` with a Turkish text."""

    if not data:
        raise ValueError("Boş dosya yüklenemez")

    if len(data) > max_bytes:
        limit_mb = max_bytes // (1024 * 1024)
        raise ValueError(f"Kanıt boyutu en fazla {limit_mb} MB olabilir")

    resolved_name = sanitize_file_name(file_name)
    resolved_type = resolve_evidence_content_type(
        file_name or resolved_name,
        content_type,
    )

    # Both the name and the type are client supplied; the signature is not.
    if not _signature_matches(resolved_type, data):
        raise ValueError("Dosya geçerli bir PDF veya fotoğraf değil")

    return {
        "file_name": resolved_name,
        "content_type": resolved_type,
        "file_size": len(data),
    }


__all__ = [
    "ALLOWED_EVIDENCE_TYPES",
    "INVALID_TYPE_MESSAGE",
    "MAX_EVIDENCE_BYTES",
    "is_image_content_type",
    "resolve_evidence_content_type",
    "validate_evidence",
]
