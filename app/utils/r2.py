"""
r2.py — Cloudflare R2 file storage utility (S3-compatible)
Used for all file uploads in Pinpoint Direct (design request assets, proofs, etc.)
"""
import json
import os
import uuid
from pathlib import Path

import boto3
from botocore.client import Config

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "r2.json"

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)
    _client = boto3.client(
        "s3",
        endpoint_url=cfg["endpoint"],
        aws_access_key_id=cfg["access_key_id"],
        aws_secret_access_key=cfg["secret_access_key"],
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )
    return _client


def _get_bucket():
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)
    return cfg["bucket_name"]


def upload_file(file_obj, filename, folder="uploads"):
    """
    Upload a file-like object to R2.
    Returns the R2 key (path within bucket).
    folder: e.g. 'design_requests/123', 'proofs/456'
    """
    ext = Path(filename).suffix.lower()
    safe_name = f"{uuid.uuid4().hex}{ext}"
    key = f"{folder}/{safe_name}"

    client = _get_client()
    bucket = _get_bucket()

    # Determine content type
    content_types = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".gif": "image/gif", ".pdf": "application/pdf",
        ".tif": "image/tiff", ".tiff": "image/tiff",
        ".svg": "image/svg+xml", ".ai": "application/postscript",
        ".eps": "application/postscript", ".psd": "image/vnd.adobe.photoshop",
    }
    content_type = content_types.get(ext, "application/octet-stream")

    client.upload_fileobj(
        file_obj,
        bucket,
        key,
        ExtraArgs={"ContentType": content_type}
    )
    return key


def get_presigned_url(key, expires_in=3600):
    """Generate a presigned URL for downloading a file (default 1 hour)."""
    client = _get_client()
    bucket = _get_bucket()
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expires_in,
    )


def delete_file(key):
    """Delete a file from R2."""
    client = _get_client()
    bucket = _get_bucket()
    client.delete_object(Bucket=bucket, Key=key)


def upload_files_from_request(request_files_list, folder):
    """
    Upload multiple FileStorage objects from a Flask request.
    Returns comma-separated list of R2 keys.
    """
    keys = []
    allowed_exts = {".jpg", ".jpeg", ".png", ".pdf", ".ai", ".eps",
                    ".svg", ".tif", ".tiff", ".psd"}
    for f in request_files_list:
        if not f or not f.filename:
            continue
        ext = Path(f.filename).suffix.lower()
        if ext not in allowed_exts:
            continue
        key = upload_file(f.stream, f.filename, folder=folder)
        keys.append(key)
    return ",".join(keys)
