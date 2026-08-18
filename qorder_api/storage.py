"""S3-compatible object storage client (MinIO in dev, AWS S3 / R2 in prod).

Provides:
- ``ensure_bucket()`` — create the bucket if it doesn't exist + set public read policy.
- ``upload_file()`` — upload bytes with content type, returns the public URL.
- ``delete_file()`` — remove an object by key.
- ``get_public_url()`` — construct the public URL for a given key.

All functions are **synchronous** (boto3 is sync). They are fast enough for the
small QR PNGs (~2–5 KB) generated at table creation time. If menu photo uploads
become a bottleneck, wrap in ``asyncio.to_thread``.
"""

from __future__ import annotations

import json
import logging

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from qorder_api.config import get_settings

logger = logging.getLogger(__name__)

# Lazy-initialized module-level client and state.
_s3_client = None
_bucket_ensured = False


def _get_client():
    """Return a cached boto3 S3 client configured from app settings."""
    global _s3_client
    if _s3_client is None:
        settings = get_settings()
        _s3_client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            config=BotoConfig(signature_version="s3v4"),
            region_name="us-east-1",  # MinIO ignores this but boto3 requires it
        )
    return _s3_client


def ensure_bucket() -> None:
    """Create the bucket if it doesn't exist and set a public-read policy.

    Safe to call multiple times — skips if already done this process lifetime.
    """
    global _bucket_ensured
    if _bucket_ensured:
        return

    settings = get_settings()
    client = _get_client()
    bucket = settings.s3_bucket

    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as e:
        error_code = int(e.response["Error"]["Code"])
        if error_code == 404:
            try:
                client.create_bucket(Bucket=bucket)
                logger.info("Created S3 bucket: %s", bucket)
            except ClientError as create_err:
                # MinIO returns BucketAlreadyOwnedByYou if the bucket was created
                # between head_bucket (404) and create_bucket — safe to ignore.
                err_code = create_err.response.get("Error", {}).get("Code", "")
                if err_code != "BucketAlreadyOwnedByYou":
                    raise
        else:
            raise

    # Set public-read policy so <img src> works without auth
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "PublicRead",
                "Effect": "Allow",
                "Principal": "*",
                "Action": ["s3:GetObject"],
                "Resource": [f"arn:aws:s3:::{bucket}/*"],
            }
        ],
    }
    client.put_bucket_policy(Bucket=bucket, Policy=json.dumps(policy))
    _bucket_ensured = True
    logger.info("Bucket '%s' ready with public-read policy.", bucket)


def upload_file(
    key: str,
    data: bytes,
    content_type: str = "image/png",
    cache_control: str | None = None,
) -> str:
    """Upload bytes to S3 and return the public URL.

    Args:
        key: Object key (path within the bucket), e.g. "qr/{table_id}.png".
        data: Raw file bytes.
        content_type: MIME type for the object.
        cache_control: Optional ``Cache-Control`` header. Use a long max-age only
            for versioned keys, otherwise browsers keep serving a stale image
            after the owner replaces it.

    Returns:
        The public URL for the uploaded object.
    """
    ensure_bucket()
    settings = get_settings()
    client = _get_client()

    extra = {"CacheControl": cache_control} if cache_control else {}
    client.put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=data,
        ContentType=content_type,
        **extra,
    )

    return get_public_url(key)


def delete_file(key: str) -> None:
    """Delete an object from S3. No-op if the object doesn't exist."""
    settings = get_settings()
    client = _get_client()

    try:
        client.delete_object(Bucket=settings.s3_bucket, Key=key)
    except ClientError:
        logger.warning("Failed to delete S3 object: %s", key, exc_info=True)


def get_public_url(key: str) -> str:
    """Construct the public URL for a given object key.

    Format: ``{s3_public_url}/{bucket}/{key}``
    """
    settings = get_settings()
    base = settings.s3_public_url.rstrip("/")
    return f"{base}/{settings.s3_bucket}/{key}"


def key_from_public_url(url: str) -> str | None:
    """Recover the object key from a public URL, or ``None`` if it isn't ours.

    Used to delete the previous image when an owner replaces a menu photo.
    """
    settings = get_settings()
    marker = f"/{settings.s3_bucket}/"
    _, _, key = url.partition(marker)
    return key or None
