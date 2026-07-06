from pathlib import Path
import uuid
import boto3
from app.core.config import Settings
from urllib.parse import quote

# def _s3_client(settings: Settings):
#     kwargs = {"region_name": settings.aws_region}
#     # if settings.aws_access_key_id:
#     #     kwargs["aws_access_key_id"] = settings.aws_access_key_id
#     # if settings.aws_secret_access_key:
#     #     kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
#     return boto3.client("s3", **kwargs)



def _s3_client(settings: Settings):
    return boto3.client(
        "s3",
        region_name=settings.aws_region,
    )


def save_file(settings: Settings, content: bytes, filename: str, folder: str) -> dict:
    file_uuid = uuid.uuid4()
    ext = Path(filename).suffix
    safe_name = f"{file_uuid}{ext}"
    if settings.file_storage_mode == "s3":
        key = f"{folder}/{safe_name}"
        _s3_client(settings).put_object(Bucket=settings.s3_bucket, Key=key, Body=content)
        return {"file_uuid": file_uuid, "s3_key": key, "local_path": None, "storage_mode": "s3"}
    root = Path(settings.local_storage_root) / folder
    root.mkdir(parents=True, exist_ok=True)
    local_path = root / safe_name
    local_path.write_bytes(content)
    return {"file_uuid": file_uuid, "s3_key": None, "local_path": str(local_path), "storage_mode": "local"}

def read_file_bytes(settings: Settings, s3_key: str | None, local_path: str | None) -> bytes:
    if s3_key:
        obj = _s3_client(settings).get_object(Bucket=settings.s3_bucket, Key=s3_key)
        return obj["Body"].read()
    if local_path:
        return Path(local_path).read_bytes()
    raise ValueError("No storage reference found for file")

# def generate_download_link(settings: Settings, s3_key: str | None, local_path: str | None) -> str | None:
#     if s3_key and settings.file_storage_mode == "s3":
#         return _s3_client(settings).generate_presigned_url(
#             ClientMethod="get_object",
#             Params={"Bucket": settings.s3_bucket, "Key": s3_key},
#             ExpiresIn=3600,
#         )
#     return local_path


def overwrite_existing_file(settings: Settings, content: bytes, s3_key: str):
    _s3_client(settings).put_object(
        Bucket=settings.s3_bucket,
        Key=s3_key,
        Body=content
    )


def generate_download_link(
    settings: Settings,
    s3_key: str | None,
    local_path: str | None,
    file_name: str | None = None,
) -> str | None:
    if s3_key and settings.file_storage_mode == "s3":
        download_name = file_name or Path(s3_key).name

        return _s3_client(settings).generate_presigned_url(
            ClientMethod="get_object",
            Params={
                "Bucket": settings.s3_bucket,
                "Key": s3_key,
                "ResponseContentDisposition": (
                    f"attachment; filename*=UTF-8''{quote(download_name)}"
                ),
            },
            ExpiresIn=3600,
        )

    if local_path and settings.file_storage_mode == "local":
        return local_path

    return None
