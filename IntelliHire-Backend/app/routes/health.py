from fastapi import APIRouter, Depends, HTTPException
import logging

from pydantic import BaseModel, Field
from app.core.config import get_settings
from app.core.security import CurrentUser, require_any_role
from app.services.storage_service import generate_download_link

logger = logging.getLogger("__health__")

router = APIRouter(tags=["health"])

@router.get("/")
def root():
    return {"message": "IntelliHire API is running with the latest updates"}

@router.get("/health")
def health(current_user: CurrentUser = Depends(require_any_role)):
    try:
        return {"status": "ok"}
    except Exception as exc:
        logger.exception("Health check failed")
        raise HTTPException(
            status_code=500,
            detail=str(exc)
        ) from exc
    


class DownloadFileRequest(BaseModel):
    s3_key: str = Field(..., min_length=1)
    file_name: str = Field(..., min_length=1)


@router.post("/files/download-url")
def get_file_download_url(
    payload: DownloadFileRequest,
    current_user: CurrentUser = Depends(require_any_role),
):
    try:
        settings = get_settings()

        s3_key = payload.s3_key.strip()
        file_name = payload.file_name.strip()

        if not s3_key:
            raise HTTPException(status_code=400, detail="s3_key is required")

        if not file_name:
            raise HTTPException(status_code=400, detail="file_name is required")

        download_url = generate_download_link(
            settings=settings,
            s3_key=s3_key,
            local_path=None,
            file_name=file_name,
        )

        if not download_url:
            raise HTTPException(
                status_code=500,
                detail="Could not generate download URL",
            )

        return {
            "file_name": file_name,
            "download_url": download_url,
            "expires_in": 3600,
        }

    except HTTPException:
        raise

    except Exception:
        logger.exception("Download URL generation failed")
        raise HTTPException(
            status_code=500,
            detail="Download URL generation failed",
        )

