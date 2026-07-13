from io import BufferedIOBase

from minio import Minio
from minio.error import S3Error

from app.core.config import settings


def get_minio_client() -> Minio:
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_key,
        secret_key=settings.minio_secret,
        secure=settings.minio_secure,
    )


def ensure_bucket(client: Minio, bucket: str) -> None:
    try:
        exists = client.bucket_exists(bucket)
    except S3Error:
        exists = False
    if not exists:
        client.make_bucket(bucket)


def upload_object(
    *,
    object_name: str,
    data: BufferedIOBase,
    length: int,
    content_type: str,
) -> str:
    client = get_minio_client()
    ensure_bucket(client, settings.minio_bucket)
    client.put_object(
        settings.minio_bucket,
        object_name,
        data,
        length=length,
        content_type=content_type,
    )
    return f"s3://{settings.minio_bucket}/{object_name}"


def delete_object(source_uri: str | None) -> None:
    if not source_uri:
        return
    prefix = f"s3://{settings.minio_bucket}/"
    if not source_uri.startswith(prefix):
        return
    object_name = source_uri.removeprefix(prefix)
    client = get_minio_client()
    client.remove_object(settings.minio_bucket, object_name)


def download_object(source_uri: str | None) -> bytes:
    if not source_uri:
        raise ValueError("source_uri_required")
    prefix = f"s3://{settings.minio_bucket}/"
    if not source_uri.startswith(prefix):
        raise ValueError("unsupported_source_uri")

    object_name = source_uri.removeprefix(prefix)
    client = get_minio_client()
    response = client.get_object(settings.minio_bucket, object_name)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()
