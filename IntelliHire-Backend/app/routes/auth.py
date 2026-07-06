
from fastapi import APIRouter, Depends, HTTPException
from app.models.job_description import EmployeeMaster
from sqlalchemy import select , func
from app.core.security import CurrentUser, get_current_user
from sqlalchemy.orm import Session
router = APIRouter(prefix="/auth", tags=["Auth"])
from app.db.deps import get_db
import logging
logger = logging.getLogger("__name__")

@router.get("/me")
def get_me(
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        if not current_user.email or not current_user.email.strip():
            raise HTTPException(
                status_code=400,
                detail="Email is missing for the authenticated user"
            )

        email = current_user.email.strip().lower()

        stmt = (
            select(EmployeeMaster.EmpId.label("emp_id"))
            .where(
                EmployeeMaster.EmailId.is_not(None),
                func.trim(EmployeeMaster.EmailId) != "",
                func.lower(func.trim(EmployeeMaster.EmailId)) == email
            )
        )

        row = db.execute(stmt).mappings().first()

        if not row:
            raise HTTPException(
                status_code=404,
                detail=f"No employee found for email: {current_user.email}"
            )

        return {
            "user_id": current_user.user_id,
            "email": current_user.email,
            "full_name": current_user.full_name,
            "hris_emp_id": row["emp_id"],
            "roles": current_user.roles,
        }

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(f"me api failed: {e}")

        raise HTTPException(
            status_code=500,
            detail={
                "error": f"something went wrong"
            
            })