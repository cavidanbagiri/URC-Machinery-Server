# services/storage_service.py
"""S3-compatible object storage helpers for machine photos.

PostgreSQL keeps only the object key of every photo; the browser-facing URL is
derived at response time:

* ``S3_PUBLIC_BASE_URL`` set  -> public-read bucket, the URL points straight at
  Cloud.ru object storage (fast, no signing, no backend hop).
* ``S3_PUBLIC_BASE_URL`` empty -> presigned GET URL (private bucket).

boto3 is synchronous, so every network call is executed in a worker thread to
keep the FastAPI event loop free.
"""

import asyncio
import logging
import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)

#: Canonical content type -> file extension used for the stored object.
ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

#: Browsers occasionally send ``image/jpg``; treat it as JPEG.
_CONTENT_TYPE_ALIASES = {"image/jpg": "image/jpeg", "image/pjpeg": "image/jpeg"}

_EXTENSION_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}

DEFAULT_MAX_UPLOAD_MB = 10
DEFAULT_PRESIGN_EXPIRES_SECONDS = 86_400
MAX_PRESIGN_EXPIRES_SECONDS = 604_800  # SigV4 hard limit: 7 days

#: Environment variables without which photo storage cannot be used.
#: ``S3_REGION`` has a default and ``S3_PUBLIC_BASE_URL`` is optional.
REQUIRED_SETTINGS = (
    "S3_ENDPOINT",
    "S3_BUCKET",
    "S3_ACCESS_KEY_ID",
    "S3_SECRET_ACCESS_KEY",
)


class StorageNotConfigured(RuntimeError):
    """Required ``S3_*`` environment variables are missing."""


class StorageError(RuntimeError):
    """The object storage rejected a request (network, credentials, ...)."""


# =========================================================
# CONFIGURATION
# =========================================================

def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or "").strip() or default


def endpoint_url() -> str:
    return _env("S3_ENDPOINT")


def region_name() -> str:
    return _env("S3_REGION", "ru-central-1")


def bucket_name() -> str:
    return _env("S3_BUCKET")


def public_base_url() -> str:
    """Public-read bucket URL, e.g. ``https://<bucket>.s3.cloud.ru``."""

    return _env("S3_PUBLIC_BASE_URL").rstrip("/")


def addressing_style() -> str:
    style = _env("S3_ADDRESSING_STYLE", "path").lower()
    return style if style in {"path", "virtual", "auto"} else "path"


def missing_configuration() -> list[str]:
    """Names of the required ``S3_*`` variables that are absent or blank.

    Returning names (never values) keeps the startup log and ``/api/health``
    safe to expose: they say *what* an operator forgot to set on the host.
    """

    return [name for name in REQUIRED_SETTINGS if not _env(name)]


def is_configured() -> bool:
    """True when every credential needed to talk to the bucket is present."""

    return not missing_configuration()


def max_upload_mb() -> int:
    raw = _env("S3_MAX_UPLOAD_MB", str(DEFAULT_MAX_UPLOAD_MB))
    try:
        value = int(float(raw))
    except ValueError:
        value = DEFAULT_MAX_UPLOAD_MB
    return value if value > 0 else DEFAULT_MAX_UPLOAD_MB


def max_upload_bytes() -> int:
    return max_upload_mb() * 1024 * 1024


def presign_expires_seconds() -> int:
    raw = _env("S3_PRESIGN_EXPIRES_SECONDS", str(DEFAULT_PRESIGN_EXPIRES_SECONDS))
    try:
        value = int(float(raw))
    except ValueError:
        value = DEFAULT_PRESIGN_EXPIRES_SECONDS
    return max(60, min(value, MAX_PRESIGN_EXPIRES_SECONDS))


# =========================================================
# UPLOAD VALIDATION
# =========================================================

def resolve_content_type(
    filename: str | None,
    declared_content_type: str | None,
) -> str:
    """Return a canonical image content type or raise ``ValueError``.

    ``application/octet-stream`` and empty values are common from drag & drop,
    so in that case the extension decides. Any other non-image type is
    rejected instead of trusting the file name.
    """

    declared = (declared_content_type or "").split(";")[0].strip().lower()
    declared = _CONTENT_TYPE_ALIASES.get(declared, declared)

    if declared in ALLOWED_IMAGE_TYPES:
        return declared

    if declared and declared != "application/octet-stream":
        raise ValueError(
            "Yalnızca JPEG, PNG veya WEBP formatındaki fotoğraflar yüklenebilir"
        )

    suffix = Path(filename or "").suffix.lower()
    if suffix in _EXTENSION_TYPES:
        return _EXTENSION_TYPES[suffix]

    raise ValueError(
        "Yalnızca JPEG, PNG veya WEBP formatındaki fotoğraflar yüklenebilir"
    )


def validate_size(size_bytes: int) -> None:
    if size_bytes <= 0:
        raise ValueError("Boş dosya yüklenemez")
    if size_bytes > max_upload_bytes():
        raise ValueError(f"Dosya çok büyük (en fazla {max_upload_mb()} MB)")


def build_object_key(machine_id: int, content_type: str) -> str:
    """``machines/<id>/<random>.ext`` — never derived from the user's filename."""

    extension = ALLOWED_IMAGE_TYPES.get(content_type, ".jpg")
    return f"machines/{int(machine_id)}/{uuid4().hex}{extension}"


# =========================================================
# URLs
# =========================================================

def build_photo_url(object_key: str | None) -> str:
    """Public URL for a stored object (or ``""`` when it cannot be built)."""

    if not object_key:
        return ""

    base = public_base_url()
    if base:
        return f"{base}/{quote(object_key.lstrip('/'), safe='/')}"

    if not is_configured():
        return ""

    try:
        return _client().generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket_name(), "Key": object_key},
            ExpiresIn=presign_expires_seconds(),
        )
    except (BotoCoreError, ClientError, ValueError):
        logger.exception("Could not presign object %s", object_key)
        return ""


# =========================================================
# boto3 CLIENT
# =========================================================

@lru_cache(maxsize=8)
def _build_client(
    endpoint: str,
    region: str,
    access_key: str,
    secret_key: str,
    style: str,
):
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": style},
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )


def _client():
    missing = missing_configuration()
    if missing:
        raise StorageNotConfigured(
            "Fotoğraf depolama yapılandırılmamış (eksik ortam değişkenleri: "
            + ", ".join(missing)
            + ")"
        )

    return _build_client(
        endpoint_url(),
        region_name(),
        _env("S3_ACCESS_KEY_ID"),
        _env("S3_SECRET_ACCESS_KEY"),
        addressing_style(),
    )


# =========================================================
# OPERATIONS
# =========================================================

async def upload_image(object_key: str, data: bytes, content_type: str) -> None:
    """Upload raw image bytes; raises ``StorageNotConfigured``/``StorageError``."""

    client = _client()

    def _put() -> None:
        client.put_object(
            Bucket=bucket_name(),
            Key=object_key,
            Body=data,
            ContentType=content_type,
            CacheControl="public, max-age=31536000, immutable",
        )

    try:
        await asyncio.to_thread(_put)
    except (BotoCoreError, ClientError) as exc:
        logger.error("S3 upload failed for %s: %s", object_key, exc)
        raise StorageError(f"Fotoğraf yüklenemedi: {exc}") from exc


async def delete_object(object_key: str) -> None:
    """Delete a single object; raises ``StorageNotConfigured``/``StorageError``."""

    client = _client()

    try:
        await asyncio.to_thread(
            client.delete_object,
            Bucket=bucket_name(),
            Key=object_key,
        )
    except (BotoCoreError, ClientError) as exc:
        logger.error("S3 delete failed for %s: %s", object_key, exc)
        raise StorageError(f"Fotoğraf silinemedi: {exc}") from exc


async def delete_objects(object_keys: list[str]) -> None:
    """Best-effort cleanup (used when a photo or a machine is deleted)."""

    if not object_keys:
        return

    try:
        client = _client()
    except StorageNotConfigured:
        logger.warning(
            "Skipping S3 cleanup of %s object(s): storage is not configured",
            len(object_keys),
        )
        return

    for object_key in object_keys:
        try:
            await asyncio.to_thread(
                client.delete_object,
                Bucket=bucket_name(),
                Key=object_key,
            )
        except (BotoCoreError, ClientError) as exc:
            # The database row is already gone; an orphan object is harmless.
            logger.error("S3 cleanup failed for %s: %s", object_key, exc)
