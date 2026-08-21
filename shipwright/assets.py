"""gs:// or local path → bytes. Local paths keep dry-runs free of GCS."""
from __future__ import annotations

import os


def read(uri: str) -> bytes:
    if uri.startswith("gs://"):
        from google.cloud import storage

        bucket, _, name = uri[5:].partition("/")
        return storage.Client().bucket(bucket).blob(name).download_as_bytes()
    with open(os.path.expanduser(uri), "rb") as f:
        return f.read()


def write(uri: str, data: bytes, content_type: str = "image/png") -> str:
    if uri.startswith("gs://"):
        from google.cloud import storage

        bucket, _, name = uri[5:].partition("/")
        storage.Client().bucket(bucket).blob(name).upload_from_string(data, content_type=content_type)
        return uri
    os.makedirs(os.path.dirname(os.path.expanduser(uri)) or ".", exist_ok=True)
    with open(os.path.expanduser(uri), "wb") as f:
        f.write(data)
    return uri
