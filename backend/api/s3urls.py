"""Presigned S3 URL generation.

Uses the regional endpoint + SigV4 + virtual addressing so the URL targets the region
host directly and avoids the HTTP 307 redirect that new buckets outside us-east-1
return for global-endpoint presigned requests (see RATIONALE ADR-012).
"""

from __future__ import annotations

import os
import uuid

import boto3
from botocore.config import Config as BotoConfig

_REGION = os.environ.get("AWS_REGION", "ap-southeast-2")
_PHOTOS_BUCKET = os.environ.get("PHOTOS_BUCKET")
_UPLOAD_TTL = int(os.environ.get("UPLOAD_URL_TTL", "300"))
_DOWNLOAD_TTL = int(os.environ.get("DOWNLOAD_URL_TTL", "300"))

_client = None


def _s3():
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            region_name=_REGION,
            endpoint_url=f"https://s3.{_REGION}.amazonaws.com",
            config=BotoConfig(
                signature_version="s3v4", s3={"addressing_style": "virtual"}
            ),
        )
    return _client


def new_photo_key(organisation_id: str, item_id: str, content_type: str) -> str:
    ext = {
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
        "application/pdf": "pdf",
    }.get(content_type, "bin")
    return f"{organisation_id}/{item_id}/{uuid.uuid4().hex}.{ext}"


def presign_put(key: str, content_type: str) -> str:
    return _s3().generate_presigned_url(
        "put_object",
        Params={"Bucket": _PHOTOS_BUCKET, "Key": key, "ContentType": content_type},
        ExpiresIn=_UPLOAD_TTL,
    )


def presign_post(
    key: str,
    content_type: str,
    filename: str,
    max_bytes: int,
) -> dict:
    """Create a browser POST target with an enforced content-length ceiling.

    S3 presigned PUT URLs cannot carry a content-length-range policy. Evidence uses a
    POST policy so oversized files are rejected by S3 before Lambda is involved.
    """
    return _s3().generate_presigned_post(
        Bucket=_PHOTOS_BUCKET,
        Key=key,
        Fields={
            "Content-Type": content_type,
            "x-amz-meta-original-filename": filename,
        },
        Conditions=[
            {"Content-Type": content_type},
            {"x-amz-meta-original-filename": filename},
            ["content-length-range", 1, max_bytes],
        ],
        ExpiresIn=_UPLOAD_TTL,
    )


def presign_get(key: str) -> str:
    return _s3().generate_presigned_url(
        "get_object",
        Params={"Bucket": _PHOTOS_BUCKET, "Key": key},
        ExpiresIn=_DOWNLOAD_TTL,
    )


def head(key: str) -> dict:
    return _s3().head_object(Bucket=_PHOTOS_BUCKET, Key=key)
