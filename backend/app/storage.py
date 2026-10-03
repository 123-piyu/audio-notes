import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from .config import settings

# boto3 works with any S3-compatible service: MinIO, Cloudflare R2, Supabase.
_s3 = boto3.client(
    "s3",
    endpoint_url=settings.s3_endpoint_url,
    aws_access_key_id=settings.s3_access_key,
    aws_secret_access_key=settings.s3_secret_key,
    region_name=settings.s3_region,
    config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
)


def presign_put(key: str, content_type: str, expires: int = 900) -> str:
    """URL the BROWSER uploads to directly. Pure local signing, no network call.
    The browser must send the same Content-Type header it was signed with."""
    return _s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": settings.s3_bucket, "Key": key, "ContentType": content_type},
        ExpiresIn=expires,
    )


def head_object(key: str) -> dict | None:
    """Return object metadata, or None if it doesn't exist. Blocking call:
    invoke through asyncio.to_thread from async code."""
    try:
        return _s3.head_object(Bucket=settings.s3_bucket, Key=key)
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            return None
        raise

def download_file(key: str, dest: str) -> None:
    """Download an object to a local path. Blocking: call via asyncio.to_thread."""
    _s3.download_file(settings.s3_bucket, key, dest)