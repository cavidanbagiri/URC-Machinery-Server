# repositories/pdf_documents.py
"""Guard rails shared by every module that stores PDF evidence in PostgreSQL.

Daily faults and tire changes keep the paper (work order, invoice, delivery
note) next to the record. The bytes live in PostgreSQL because the API host
(Render) has an ephemeral filesystem, so file names must be sanitized, the size
limited and the PDF signature verified before anything is written.

Both repositories import the helpers from here instead of keeping their own
copy, so the limits and the error texts stay identical.
"""

from typing import Any, Optional
from urllib.parse import quote

#: Hard limit for one uploaded PDF, mirrored by the ``file_size`` check
#: constraints of the document tables.
MAX_PDF_BYTES = 10 * 1024 * 1024

#: Browsers occasionally send "application/x-pdf"; both mean the same file.
ALLOWED_DOCUMENT_TYPES = {
    "application/pdf": ".pdf",
    "application/x-pdf": ".pdf",
}
#: Some browsers submit an empty type (or octet-stream) for local files.
_FALLBACK_DOCUMENT_TYPES = {"", "application/octet-stream"}
_PDF_SIGNATURE = b"%PDF-"
FALLBACK_DOCUMENT_NAME = "evrak.pdf"


def clamp_pagination(
    limit: int,
    offset: int,
    *,
    default_limit: int = 20,
    max_limit: int = 100,
) -> tuple[int, int]:
    """Keep client supplied paging inside the API limits."""

    limit = default_limit if limit < 1 else min(limit, max_limit)
    offset = max(offset, 0)
    return limit, offset


def sanitize_file_name(file_name: Optional[str]) -> str:
    """Take the base name only: never trust a path sent by the browser."""

    name = (file_name or "").replace("\\", "/").split("/")[-1].strip()
    name = name[:255].strip()
    return name or FALLBACK_DOCUMENT_NAME


def resolve_document_content_type(
    file_name: str, content_type: Optional[str]
) -> str:
    """Normalize the browser supplied type; only PDFs are accepted."""

    raw = (content_type or "").split(";")[0].strip().lower()
    if raw in ALLOWED_DOCUMENT_TYPES:
        return "application/pdf"
    if raw in _FALLBACK_DOCUMENT_TYPES and file_name.lower().endswith(".pdf"):
        return "application/pdf"
    raise ValueError("Sadece PDF dosyaları yüklenebilir")


def validate_document(
    file_name: Optional[str],
    content_type: Optional[str],
    data: bytes,
    *,
    max_bytes: int = MAX_PDF_BYTES,
) -> dict[str, Any]:
    """Validate an uploaded paper; raises ``ValueError`` with a Turkish text."""

    if not data:
        raise ValueError("Boş dosya yüklenemez")

    if len(data) > max_bytes:
        limit_mb = max_bytes // (1024 * 1024)
        raise ValueError(f"Evrak boyutu en fazla {limit_mb} MB olabilir")

    resolved_name = sanitize_file_name(file_name)
    resolved_type = resolve_document_content_type(
        file_name or resolved_name, content_type
    )

    # Content type and extension are client supplied; the signature is not.
    if not data.startswith(_PDF_SIGNATURE):
        raise ValueError("Dosya geçerli bir PDF değil")

    return {
        "file_name": resolved_name,
        "content_type": resolved_type,
        "file_size": len(data),
    }


def content_disposition(file_name: str, *, download: bool = False) -> str:
    """RFC 5987 header so Turkish file names survive the download."""

    disposition = "attachment" if download else "inline"
    name = sanitize_file_name(file_name)
    ascii_name = (
        name.encode("ascii", "ignore").decode("ascii") or FALLBACK_DOCUMENT_NAME
    )
    # Quotes would break the quoted-string parameter; filename* keeps the real name.
    ascii_name = ascii_name.replace('"', "_")
    return (
        f'{disposition}; filename="{ascii_name}"; '
        f"filename*=UTF-8''{quote(name, safe='')}"
    )


__all__ = [
    "ALLOWED_DOCUMENT_TYPES",
    "FALLBACK_DOCUMENT_NAME",
    "MAX_PDF_BYTES",
    "clamp_pagination",
    "content_disposition",
    "resolve_document_content_type",
    "sanitize_file_name",
    "validate_document",
]
