from app.core.config import Settings, get_settings
from app.core.security import CurrentUser, require_any_role
from app.models.application import Application
from app.models.assessments import Assessment
from app.models.auth import Role, User, UserRole
from app.models.candidate import Candidate
from app.models.job_description import EmployeeMaster, JobDescription
from app.models.panel_assignments import PanelAssignment
from app.models.screening_result import ScreeningResult
from app.schemas.panel import AssignPanelistsRequest
from sqlalchemy.orm import Session
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy import select , func, and_
from app.db.deps import get_db

from sqlalchemy.dialects.postgresql import insert

import logging

from sqlalchemy import or_, cast, String

from app.services.email_service import send_email, send_email_or_raise, send_interviewer_assessment_assigned_email
logger = logging.getLogger(__name__)

router = APIRouter(tags=["panel"])


from fastapi import HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql import func
import logging

logger = logging.getLogger(__name__)

settings = Settings()



# @router.post("/panel/assign", status_code=201)
# def assign_or_replace_panelists(
#     payload: AssignPanelistsRequest,
#     background_tasks: BackgroundTasks,
#     db: Session = Depends(get_db),
#     current_user: CurrentUser = Depends(require_any_role),
# ):
#     try:
#         if not payload.panelists:
#             raise HTTPException(
#                 status_code=400,
#                 detail="No panelists provided",
#             )   

#         # 1) Validate duplicate HRIS employee IDs in request
#         ids = [p.hris_employee_id for p in payload.panelists]

#         if len(ids) != len(set(ids)):
#             raise HTTPException(
#                 status_code=400,
#                 detail="Duplicate panelists in request",
#             )

#         # 2) Validate only one primary panelist
#         primary_count = sum(1 for p in payload.panelists if p.is_primary)

#         if primary_count > 1:
#             raise HTTPException(
#                 status_code=400,
#                 detail="Only one primary panelist allowed",
#             )

#         actor = getattr(current_user, "user_id", None)
#         actor = str(actor) if actor is not None else "system"

#         try:
#             # ----------------------------------------------------
#             # 3) Fetch application, JD and candidate for email
#             # ----------------------------------------------------
#             application = db.query(Application).filter(
#                 Application.application_id == payload.application_id
#             ).first()

#             if not application:
#                 raise HTTPException(
#                     status_code=404,
#                     detail="Application not found",
#                 )

#             job_description = db.query(JobDescription).filter(
#                 JobDescription.jd_id == application.jd_id
#             ).first()

#             if not job_description:
#                 raise HTTPException(
#                     status_code=404,
#                     detail="Job description not found",
#                 )

#             candidate = db.query(Candidate).filter(
#                 Candidate.candidate_id == application.candidate_id
#             ).first()

#             if not candidate:
#                 raise HTTPException(
#                     status_code=404,
#                     detail="Candidate not found",
#                 )

#             # ----------------------------------------------------
#             # 4) Fetch employees from public.EmployeeMaster
#             # ----------------------------------------------------
#             employees = db.execute(
#                 select(EmployeeMaster).where(
#                     EmployeeMaster.EmpId.in_(ids)
#                 )
#             ).scalars().all()

#             employee_by_id = {
#                 employee.EmpId: employee
#                 for employee in employees
#             }

#             missing_employee_ids = [
#                 emp_id for emp_id in ids
#                 if emp_id not in employee_by_id
#             ]

#             if missing_employee_ids:
#                 raise HTTPException(
#                     status_code=400,
#                     detail={
#                         "message": "Some panelists were not found in EmployeeMaster",
#                         "missing_employee_ids": missing_employee_ids,
#                     },
#                 )

#             # ----------------------------------------------------
#             # 5) Validate EmployeeMaster.EmailId exists
#             # ----------------------------------------------------
#             missing_email_ids = []

#             for emp_id in ids:
#                 employee = employee_by_id[emp_id]

#                 if not employee.EmailId or not employee.EmailId.strip():
#                     missing_email_ids.append(emp_id)

#             if missing_email_ids:
#                 raise HTTPException(
#                     status_code=400,
#                     detail={
#                         "message": "EmailId is missing in EmployeeMaster for some panelists",
#                         "employee_ids": missing_email_ids,
#                     },
#                 )

#             # ----------------------------------------------------
#             # 6) Prepare emails from EmployeeMaster
#             # ----------------------------------------------------
#             email_by_emp_id = {}

#             for emp_id in ids:
#                 employee = employee_by_id[emp_id]
#                 email_by_emp_id[emp_id] = employee.EmailId.lower().strip()

#             emails = list(email_by_emp_id.values())

#             if len(emails) != len(set(emails)):
#                 raise HTTPException(
#                     status_code=400,
#                     detail="Multiple selected panelists have the same EmailId in EmployeeMaster",
#                 )

#             # ----------------------------------------------------
#             # 7) Fetch INTERVIEWER role
#             # ----------------------------------------------------
#             interviewer_role = db.scalar(
#                 select(Role).where(
#                     Role.role_name == "INTERVIEWER"
#                 )
#             )

#             if interviewer_role is None:
#                 raise HTTPException(
#                     status_code=500,
#                     detail="INTERVIEWER role is missing in roles table",
#                 )

#             # ----------------------------------------------------
#             # 8) Fetch existing users by email
#             # ----------------------------------------------------
#             existing_users = db.execute(
#                 select(User).where(
#                     User.email.in_(emails)
#                 )
#             ).scalars().all()

#             user_by_email = {
#                 user.email.lower().strip(): user
#                 for user in existing_users
#             }

#             # ----------------------------------------------------
#             # 9) Create missing users or update existing users
#             # ----------------------------------------------------
#             for emp_id in ids:
#                 employee = employee_by_id[emp_id]
#                 email = email_by_emp_id[emp_id]
#                 full_name = employee.EmpName

#                 user = user_by_email.get(email)

#                 if user is None:
#                     user = User(
#                         email=email,
#                         full_name=full_name,
#                         is_active=True,
#                     )

#                     db.add(user)
#                     user_by_email[email] = user

#                 else:
#                     # Keep panelist user active
#                     if not user.is_active:
#                         user.is_active = True

#                     # Update name from EmployeeMaster if available
#                     if full_name and user.full_name != full_name:
#                         user.full_name = full_name

#             # Flush so newly created users get user_id
#             db.flush()

#             # ----------------------------------------------------
#             # 10) Add INTERVIEWER role to every panelist user
#             # ----------------------------------------------------
#             for email in emails:
#                 user = user_by_email[email]

#                 add_user_role_stmt = (
#                     insert(UserRole)
#                     .values(
#                         user_id=user.user_id,
#                         role_id=interviewer_role.role_id,
#                     )
#                     .on_conflict_do_nothing(
#                         index_elements=["user_id", "role_id"]
#                     )
#                 )

#                 db.execute(add_user_role_stmt)

#             # ----------------------------------------------------
#             # 11) Deactivate previous active panelists
#             #     for same application + stage
#             # ----------------------------------------------------
#             db.query(PanelAssignment).filter(
#                 PanelAssignment.application_id == payload.application_id,
#                 PanelAssignment.panel_stage == payload.panel_stage,
#                 PanelAssignment.is_active == True,
#             ).update(
#                 {
#                     PanelAssignment.is_active: False,
#                     PanelAssignment.removed_at: func.now(),
#                     PanelAssignment.removed_by: actor,
#                 },
#                 synchronize_session=False,
#             )

#             # ----------------------------------------------------
#             # 12) Insert new active panelists
#             # ----------------------------------------------------
#             rows = []

#             for idx, p in enumerate(payload.panelists, start=1):
#                 rows.append(
#                     PanelAssignment(
#                         application_id=payload.application_id,
#                         panel_stage=payload.panel_stage,
#                         hris_employee_id=p.hris_employee_id,
#                         is_primary=bool(p.is_primary),
#                         sequence_no=idx,
#                         assigned_by=actor,
#                         is_active=True,
#                         candidate_purpose=payload.candidate_purpose,
#                     )
#                 )

#             db.add_all(rows)

#             # ----------------------------------------------------
#             # 13) Commit everything together
#             # ----------------------------------------------------
#             db.commit()

#             # ----------------------------------------------------
#             # 14) Send assignment emails after successful commit
#             # ----------------------------------------------------
#             candidate_name = (
#                 candidate.full_name.strip()
#                 if candidate.full_name and candidate.full_name.strip()
#                 else f"Candidate {candidate.candidate_id}"
#             )

                        
#             req_id = job_description.req_id or "-"
#             jd_title = job_description.title or "-"

#             interview_round = payload.panel_stage.strip().upper()

#             assessment_link = (
#                 f"{settings.intellihire_base_url}"
#             )

#             for emp_id in ids:
#                 employee = employee_by_id[emp_id]

#                 interviewer_email = employee.EmailId.lower().strip()

#                 interviewer_name = (
#                     employee.EmpName.strip()
#                     if employee.EmpName and employee.EmpName.strip()
#                     else "Interviewer"
#                 )

#                 background_tasks.add_task(
#                     send_interviewer_assessment_assigned_email,
#                     interviewer_email=interviewer_email,
#                     interviewer_name=interviewer_name,
#                     candidate_name=candidate_name,
#                     req_id=req_id,
#                     jd_title=jd_title,
#                     interview_round=interview_round,
#                     assessment_link=assessment_link,
#                 )

#         except HTTPException:
#             db.rollback()
#             raise

#         except IntegrityError as e:
#             db.rollback()
#             raise HTTPException(
#                 status_code=409,
#                 detail=f"Panel update conflict. Please retry........{str(e)}",
#             )

#         except Exception:
#             db.rollback()
#             raise

#         return {
#             "message": "Panelists updated successfully",
#             "application_id": payload.application_id,
#             "panel_stage": payload.panel_stage,
#             "total_assigned": len(payload.panelists),
#         }

#     except HTTPException:
#         raise

#     except Exception as e:
#         logger.exception("Failed to update panelists: %s", str(e))
#         raise HTTPException(
#             status_code=500,
#             detail="Internal server error!",
#         )


@router.post("/panel/assign", status_code=201)
def assign_or_replace_panelists(
    payload: AssignPanelistsRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role),
):
    try:
        settings = get_settings()

        if not payload.panelists:
            raise HTTPException(
                status_code=400,
                detail="No panelists provided",
            )

        # 1. Validate duplicate HRIS employee IDs in request
        ids = [p.hris_employee_id for p in payload.panelists]

        if len(ids) != len(set(ids)):
            raise HTTPException(
                status_code=400,
                detail="Duplicate panelists in request",
            )

        # 2. Validate only one primary panelist
        primary_count = sum(1 for p in payload.panelists if p.is_primary)

        if primary_count > 1:
            raise HTTPException(
                status_code=400,
                detail="Only one primary panelist allowed",
            )

        actor = getattr(current_user, "user_id", None)
        actor = str(actor) if actor is not None else "system"

        try:
            # 3. Fetch application, JD and candidate
            application = db.query(Application).filter(
                Application.application_id == payload.application_id
            ).first()

            if not application:
                raise HTTPException(
                    status_code=404,
                    detail="Application not found",
                )

            job_description = db.query(JobDescription).filter(
                JobDescription.jd_id == application.jd_id
            ).first()

            if not job_description:
                raise HTTPException(
                    status_code=404,
                    detail="Job description not found",
                )

            candidate = db.query(Candidate).filter(
                Candidate.candidate_id == application.candidate_id
            ).first()

            if not candidate:
                raise HTTPException(
                    status_code=404,
                    detail="Candidate not found",
                )

            # 4. Fetch employees from EmployeeMaster
            employees = db.execute(
                select(EmployeeMaster).where(
                    EmployeeMaster.EmpId.in_(ids)
                )
            ).scalars().all()

            employee_by_id = {
                employee.EmpId: employee
                for employee in employees
            }

            missing_employee_ids = [
                emp_id for emp_id in ids
                if emp_id not in employee_by_id
            ]

            if missing_employee_ids:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "message": "Some panelists were not found in EmployeeMaster",
                        "missing_employee_ids": missing_employee_ids,
                    },
                )

            # 5. Validate EmployeeMaster.EmailId exists
            missing_email_ids = []

            for emp_id in ids:
                employee = employee_by_id[emp_id]

                if not employee.EmailId or not employee.EmailId.strip():
                    missing_email_ids.append(emp_id)

            if missing_email_ids:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "message": "EmailId is missing in EmployeeMaster for some panelists",
                        "employee_ids": missing_email_ids,
                    },
                )

            # 6. Prepare emails from EmployeeMaster
            email_by_emp_id = {}

            for emp_id in ids:
                employee = employee_by_id[emp_id]
                email_by_emp_id[emp_id] = employee.EmailId.lower().strip()

            emails = list(email_by_emp_id.values())

            if len(emails) != len(set(emails)):
                raise HTTPException(
                    status_code=400,
                    detail="Multiple selected panelists have the same EmailId in EmployeeMaster",
                )

            # 7. Fetch INTERVIEWER role
            interviewer_role = db.scalar(
                select(Role).where(
                    Role.role_name == "INTERVIEWER"
                )
            )

            if interviewer_role is None:
                raise HTTPException(
                    status_code=500,
                    detail="INTERVIEWER role is missing in roles table",
                )

            # 8. Fetch existing users by email
            existing_users = db.execute(
                select(User).where(
                    User.email.in_(emails)
                )
            ).scalars().all()

            user_by_email = {
                user.email.lower().strip(): user
                for user in existing_users
            }

            # 9. Create missing users or update existing users
            for emp_id in ids:
                employee = employee_by_id[emp_id]
                email = email_by_emp_id[emp_id]
                full_name = employee.EmpName

                user = user_by_email.get(email)

                if user is None:
                    user = User(
                        email=email,
                        full_name=full_name,
                        is_active=True,
                    )

                    db.add(user)
                    user_by_email[email] = user

                else:
                    if not user.is_active:
                        user.is_active = True

                    if full_name and user.full_name != full_name:
                        user.full_name = full_name

            # Flush so newly created users get user_id
            db.flush()

            # 10. Add INTERVIEWER role to every panelist user
            for email in emails:
                user = user_by_email[email]

                add_user_role_stmt = (
                    insert(UserRole)
                    .values(
                        user_id=user.user_id,
                        role_id=interviewer_role.role_id,
                    )
                    .on_conflict_do_nothing(
                        index_elements=["user_id", "role_id"]
                    )
                )

                db.execute(add_user_role_stmt)

            # 11. Deactivate previous active panelists
            db.query(PanelAssignment).filter(
                PanelAssignment.application_id == payload.application_id,
                PanelAssignment.panel_stage == payload.panel_stage,
                PanelAssignment.is_active == True,
            ).update(
                {
                    PanelAssignment.is_active: False,
                    PanelAssignment.removed_at: func.now(),
                    PanelAssignment.removed_by: actor,
                },
                synchronize_session=False,
            )

            # 12. Insert new active panelists
            rows = []

            for idx, p in enumerate(payload.panelists, start=1):
                rows.append(
                    PanelAssignment(
                        application_id=payload.application_id,
                        panel_stage=payload.panel_stage,
                        hris_employee_id=p.hris_employee_id,
                        is_primary=bool(p.is_primary),
                        sequence_no=idx,
                        assigned_by=actor,
                        is_active=True,
                        candidate_purpose=payload.candidate_purpose,
                    )
                )

            db.add_all(rows)

            # Flush DB changes but do not commit yet
            db.flush()

            # 13. Send assignment emails synchronously before commit
            candidate_name = (
                candidate.full_name.strip()
                if candidate.full_name and candidate.full_name.strip()
                else f"Candidate {candidate.candidate_id}"
            )

            req_id = job_description.req_id or "-"
            jd_title = job_description.title or "-"
            interview_round = payload.panel_stage.strip().upper()
            assessment_link = settings.intellihire_base_url

            for emp_id in ids:
                employee = employee_by_id[emp_id]

                interviewer_email = employee.EmailId.lower().strip()

                interviewer_name = (
                    employee.EmpName.strip()
                    if employee.EmpName and employee.EmpName.strip()
                    else "Interviewer"
                )

                send_email_or_raise(
                    send_interviewer_assessment_assigned_email,
                    interviewer_email=interviewer_email,
                    interviewer_name=interviewer_name,
                    candidate_name=candidate_name,
                    req_id=req_id,
                    jd_title=jd_title,
                    interview_round=interview_round,
                    assessment_link=assessment_link,
                )

            # 14. Commit only after all emails are sent successfully
            db.commit()

            return {
                "message": "Panelists updated successfully",
                "application_id": payload.application_id,
                "panel_stage": payload.panel_stage,
                "total_assigned": len(payload.panelists),
            }

        except HTTPException:
            db.rollback()
            raise

        except IntegrityError:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail="Panel update conflict. Please retry.",
            )

        except Exception as e:
            db.rollback()
            logger.exception("Failed inside panel assignment transaction: %s", str(e))
            raise

    except HTTPException:
        raise

    except Exception as e:
        logger.exception("Failed to update panelists: %s", str(e))
        raise HTTPException(
            status_code=500,
            detail="Internal server error!",
        )


@router.get("/panel/assigned", status_code=200)
def get_active_panelists(
    application_id: int,
    panel_stage: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role)
):
    try:
        assignments = (
            db.query(PanelAssignment)
            .filter(
                PanelAssignment.application_id == application_id,
                PanelAssignment.panel_stage == panel_stage,
                PanelAssignment.is_active == True
            )
            .order_by(PanelAssignment.sequence_no.asc())
            .all()
        )

        emp_ids = [a.hris_employee_id for a in assignments]
        employees = (
            db.query(EmployeeMaster)
            .filter(EmployeeMaster.EmpId.in_(emp_ids))
            .all()
        )
        emp_map = {e.EmpId: e for e in employees}

        panelists = []
        for a in assignments:
            e = emp_map.get(a.hris_employee_id)
            panelists.append({
                "sequence_no": a.sequence_no,
                "hris_employee_id": a.hris_employee_id,
                "is_primary": a.is_primary,
                "assigned_by": a.assigned_by,
                "created_at": a.created_at,
                "employee": {
                    "emp_code": e.EmpCode if e else None,
                    "emp_name": e.EmpName if e else None,
                    "email": e.EmailId if e else None,
                } if e else None
            })

        return {
            "application_id": application_id,
            "panel_stage": panel_stage,
            "count": len(panelists),
            "panelists": panelists
        }

    except Exception as e:
        logger.exception("Failed to get panelists: %s", str(e))
        raise HTTPException(status_code=500, detail="Internal server error")
    





@router.get("/employees/search", status_code=200)
def search_employees(
    q: str = Query(..., min_length=1, description="Search by EmpCode or EmpName"),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role)
):
    try:
        term = q.strip()

        employees = (
            db.query(EmployeeMaster)
            .filter(
                or_(
                    EmployeeMaster.EmpName.ilike(f"%{term}%"),
                    cast(EmployeeMaster.EmpCode, String).ilike(f"%{term}%"),
                )
            )
            .order_by(EmployeeMaster.EmpName.asc())
            .limit(limit)
            .all()
        )

        return {
            "count": len(employees),
            "results": [
                {
                    "emp_id": e.EmpId,          # ✅ REQUIRED
                    "emp_code": e.EmpCode,
                    "emp_name": e.EmpName,
                    "email": e.EmailId,
                    "horizontal_id": e.HorizontalId,
                }
                for e in employees
            ],
        }

    except Exception as e:
        logger.exception("Employee search failed: %s", str(e))
        raise HTTPException(status_code=500, detail="Internal server error")









@router.get("/panel/history", status_code=200)
def get_panel_history(
    application_id: int,
    panel_stage: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role) if settings.authenticate else None
):
    try:
        rows = (
            db.query(PanelAssignment)
            .filter(
                PanelAssignment.application_id == application_id,
                PanelAssignment.panel_stage == panel_stage,
            )
            .order_by(PanelAssignment.created_at.desc())
            .all()
        )

        return {
            "application_id": application_id,
            "panel_stage": panel_stage,
            "count": len(rows),
            "history": [
                {
                    "hris_employee_id": r.hris_employee_id,
                    "sequence_no": r.sequence_no,
                    "is_primary": r.is_primary,
                    "is_active": r.is_active,
                    "assigned_by": r.assigned_by,
                    "created_at": r.created_at,
                    "removed_by": r.removed_by,
                    "removed_at": r.removed_at,
                }
                for r in rows
            ]
        }

    except Exception as e:
        logger.exception("Failed to get panel history: %s", str(e))
        raise HTTPException(status_code=500, detail="Internal server error")






@router.get("/panelists/get-panelist-list/hrisempid={hris_emp_id}")
def get_primary_panelist_jobs(
    hris_emp_id: int,
    current_user: CurrentUser = Depends(require_any_role),
    db: Session = Depends(get_db),
):
    try:
        stmt = (
            select(
                PanelAssignment.panel_assignment_id,
                PanelAssignment.application_id,
                PanelAssignment.panel_stage,
                PanelAssignment.sequence_no,

                Application.jd_id,
                Application.current_stage,

                Assessment.assessment_id,
                Assessment.status.label("assessment_status"),
                Assessment.overall_score,
                Assessment.final_recommendation,

                JobDescription.req_id,
                JobDescription.title,
                JobDescription.location,
                JobDescription.status.label("jd_status"),
                JobDescription.grade,
                JobDescription.lob,
                JobDescription.vertical,

                Candidate.candidate_id,
                Candidate.full_name.label("candidate_name"),
                Candidate.email.label("candidate_email"),

                ScreeningResult.candidate_experience.label("candidate_experience"),
            )
            .join(
                Application,
                Application.application_id == PanelAssignment.application_id,
            )
            .join(
                JobDescription,
                JobDescription.jd_id == Application.jd_id,
            )
            .join(
                Candidate,
                Candidate.candidate_id == Application.candidate_id,
            )
            .outerjoin(
                Assessment,
                and_(
                    Assessment.application_id == Application.application_id,
                    Assessment.stage_code == PanelAssignment.panel_stage,
                ),
            )
            .outerjoin(
                ScreeningResult,
                and_(
                    ScreeningResult.jd_id == Application.jd_id,
                    ScreeningResult.candidate_id == Application.candidate_id,
                ),
            )
            .where(
                PanelAssignment.hris_employee_id == hris_emp_id,
                PanelAssignment.is_primary.is_(True),
                PanelAssignment.is_active.is_(True),
            )
            .order_by(
                PanelAssignment.created_at.desc(),
            )
        )

        rows = db.execute(stmt).mappings().all()

        return {
            "count": len(rows),
            "items": [
                {
                    "panel_assignment_id": row["panel_assignment_id"],
                    "application_id": row["application_id"],

                    "candidate_id": row["candidate_id"],
                    "candidate_name": row["candidate_name"],
                    "candidate_email": row["candidate_email"],
                    "candidate_experience": row["candidate_experience"],

                    "jd_id": row["jd_id"],
                    "req_id": row["req_id"],
                    "job_title": row["title"],
                    "location": row["location"],

                    "interview_stage": row["panel_stage"],
                    "application_current_stage": row["current_stage"],

                    # status is assessment status, not application status
                    "status": row["assessment_status"] or "not_started",

                    "assessment_id": row["assessment_id"],
                    "assessment_score": (
                        float(row["overall_score"])
                        if row["overall_score"] is not None
                        else None
                    ),
                    "final_recommendation": row["final_recommendation"],

                    "jd_status": row["jd_status"],
                    "grade": row["grade"],
                    "lob": row["lob"],
                    "vertical": row["vertical"],
                    "sequence_no": row["sequence_no"],
                }
                for row in rows
            ],
        }

    except SQLAlchemyError as e:
        logger.exception(
            "Database error while fetching primary panelist jobs for hris_emp_id=%s",
            hris_emp_id,
        )

        raise HTTPException(
            status_code=500,
            detail="Database error while fetching panelist job list.",
        ) from e

    except Exception as e:
        logger.exception(
            "Unexpected error while fetching primary panelist jobs for hris_emp_id=%s",
            hris_emp_id,
        )

        raise HTTPException(
            status_code=500,
            detail="Unexpected error while fetching panelist job list.",
        ) from e



# def send_interviewer_assessment_assigned_email(
#     interviewer_email: str,
#     interviewer_name: str,
#     candidate_name: str,
#     job_title: str,
#     interview_round: str,
#     assessment_link: str,
# ):
#     subject = f"Assessment Assigned - {candidate_name}"

#     body = f"""
# Hello {interviewer_name},

# You have been assigned to assess the candidate below:

# Candidate: {candidate_name}
# Requisition: {job_title}
# Interview Round: {interview_round}

# Please review the candidate profile and complete your assessment using the link below:

# {assessment_link}

# Your timely feedback will help us move the hiring process forward efficiently.

# Thank you.

# Regards,
# IntelliHire Team
# """

#     html_body = f"""
# <html>
#   <body>
#     <p>Hello {interviewer_name},</p>

#     <p>You have been assigned to assess the candidate below:</p>

#     <p>
#       <strong>Candidate:</strong> {candidate_name}<br/>
#       <strong>Requisition:</strong> {job_title}<br/>
#       <strong>Interview Round:</strong> {interview_round}
#     </p>

#     <p>
#       Please review the candidate profile and complete your assessment using the link below:
#     </p>

#     <p>
#       <a href="{assessment_link}">Open Assessment</a>
#     </p>

#     <p>
#       Your timely feedback will help us move the hiring process forward efficiently.
#     </p>

#     <p>Thank you.</p>

#     <p>
#       Regards,<br/>
#       IntelliHire Team
#     </p>
#   </body>
# </html>
# """

#     send_email(
#         to_email=interviewer_email,
#         subject=subject,
#         body=body,
#         html_body=html_body,
#     )