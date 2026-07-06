from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from app.models.assessments import Assessment
from app.models.candidate import Candidate
from app.models.job_description import EmployeeMaster, JobDescription
from app.models.panel_assignments import PanelAssignment
from app.services.pipeline import ensure_default_pipeline_stages_for_jd
from sqlalchemy.orm import Session
from sqlalchemy import func,and_
from app.db.deps import get_db
from app.core.logger import get_logger
from app.models.application import Application, ApplicationStageHistory
from app.models.screening_result import ScreeningResult
from app.models.resume import Resume
from app.schemas.pipeline import AddStageRequest, AddStagesRequest, AddToPipelineRequest, BulkAddToPipelineRequest, DynamicAddStagesRequest, MovePipelineRequest
from app.services.assessment_service import ensure_assessment_stage_exists
import re
from app.core.security import CurrentUser, require_admin, require_recruiter,require_hr_manager, require_panelist,require_any_role


router = APIRouter(tags=["pipeline"])
logger = get_logger("pipeline")


RECRUITER_PIPELINE_STAGE = "RECRUITER_ASSESSMENT"
PIPELINE_STATUS_IN_PROGRESS = "IN_PROGRESS"
PIPELINE_STAGE_DELETED = "DELETED"
PIPELINE_STATUS_REMOVED = "REMOVED_FROM_PIPELINE"
CEO_STAGE = "CEO_STAGE"

def get_stage_code_from_pipeline_stage(stage: str | None) -> str | None:
    """
    Maps pipeline stage names to assessment stage codes.

    RECRUITER_ASSESSMENT -> RECRUITER
    L1_ASSESSMENT        -> L1
    L2_ASSESSMENT        -> L2
    L3_ASSESSMENT        -> L3
    L4_ASSESSMENT        -> L4
    """
    if not stage:
        return None

    stage = stage.strip().upper()

    if stage == RECRUITER_PIPELINE_STAGE:
        return "RECRUITER"
    
    if stage == CEO_STAGE:
        return "CEO"
    
    if stage == "HR":
        return "HR"

    match = re.fullmatch(r"(L[1-9][0-9]*)_ASSESSMENT", stage)
    if match:
        return match.group(1)

    return None


def is_removed_application(app: Application) -> bool:
    return (
        app.current_stage == PIPELINE_STAGE_DELETED
        or app.status == PIPELINE_STATUS_REMOVED
    )


def activate_jd_if_needed(db: Session, jd_id: int | None) -> None:
    if not jd_id:
        return

    jd = db.query(JobDescription).filter(JobDescription.jd_id == jd_id).first()
    if jd and jd.status != "Active":
        jd.status = "Active"
    
    # # Ensure "RECRUITER" stage exists in the stages list
    #     stages: list = jd.stages if jd.stages is not None else []
    #     if "RECRUITER" not in stages:
    #         stages.append("RECRUITER")
    #         jd.stages = stages   # re-assign the updated list


def ensure_recruiter_assessment_for_application(db: Session, first_stage: str,application_id: int) -> None:
    """
    Creates one stage-based assessment row for recruiter stage.
    This row contains:
    - GENERAL section with fixed SCREENING questions from question bank
    - TECH section for manual/LLM questions
    """
    ensure_assessment_stage_exists(
        db=db,
        application_id=application_id,
        # stage_code="RECRUITER",
        stage_code=first_stage

    )


def ensure_assessment_for_pipeline_stage(
    db: Session,
    application_id: int,
    pipeline_stage: str | None,
    # stage_level: int
) -> None:
    # stage_code = get_stage_code_from_pipeline_stage(pipeline_stage)


    ensure_assessment_stage_exists(
        db=db,
        application_id=application_id,
        stage_code=pipeline_stage,
        # stage_level=stage_level
    )


def add_stage_history(
    db: Session,
    application_id: int,
    from_stage: str | None,
    to_stage: str,
    changed_by: str | None = None,
    remarks: str | None = None,
) -> None:
    db.add(ApplicationStageHistory(
        application_id=application_id,
        from_stage=from_stage or "NOT_IN_PIPELINE",
        to_stage=to_stage,
        changed_by=changed_by or "system",
        remarks=remarks,
    ))


@router.post("/pipeline/add")
def add_to_pipeline(payload: AddToPipelineRequest, current_user: CurrentUser = Depends(require_any_role),db: Session = Depends(get_db)):
    try:
        screening = None

        if payload.screening_result_id:
            screening = db.query(ScreeningResult).filter(
                ScreeningResult.screening_result_id == payload.screening_result_id
            ).first()
            if not screening:
                raise HTTPException(status_code=404, detail="Screening result not found")

        jd_id = payload.jd_id or (screening.jd_id if screening else None)

        if not jd_id:
            raise HTTPException(status_code=400, detail="JD ID not resolvable")

        # activate_jd_if_needed(db, jd_id)


        
        # ✅ fetch JD
        jd = db.query(JobDescription).filter(
            JobDescription.jd_id == jd_id
        ).first()

        if not jd:
            raise HTTPException(status_code=404, detail="Job description not found")
        
        if jd and jd.status != "Active":
            jd.status = "Active"

        # ✅ if stages are empty, add RECRUITER + HR into JD
        jd_stages = ensure_default_pipeline_stages_for_jd(db, jd)

        
        logger.info("jd_stages value after ensure: %s", jd_stages)
        logger.info("jd_stages type after ensure: %s", type(jd_stages))
        if isinstance(jd_stages, list) and jd_stages:
            logger.info("jd_stages[0] type: %s", type(jd_stages[0]))



        # ✅ first stage will be RECRUITER
        first_stage = jd_stages[0]["stage_name"]



        app = db.query(Application).filter(
            Application.candidate_id == payload.candidate_id,
            Application.jd_id == jd_id,
        ).first()

        changed_by = str(getattr(payload, "changed_by", None) or "system")
        remarks = getattr(payload, "remarks", None)

        if app:
            previous_stage = app.current_stage

            # Always refresh latest resume/screening pointers if provided.
            if payload.resume_id:
                app.current_resume_id = payload.resume_id
            elif screening:
                app.current_resume_id = screening.resume_id

            if screening:
                app.latest_screening_result_id = screening.screening_result_id

            # If app was removed earlier, re-activate the same application_id.
            if is_removed_application(app):
                app.current_stage = first_stage
                app.status = PIPELINE_STATUS_IN_PROGRESS

                add_stage_history(
                    db=db,
                    application_id=app.application_id,
                    from_stage=previous_stage,
                    to_stage=first_stage,
                    changed_by=changed_by,
                    remarks=remarks or "Re-added to pipeline",
                )

                db.flush()

                ensure_recruiter_assessment_for_application(
                    db=db,
                    application_id=app.application_id,
                    first_stage=first_stage
                )

                db.commit()
                db.refresh(app)

                return {
                    "message": "Candidate re-added to pipeline",
                    "status": "reactivated",
                    "application_id": app.application_id,
                    "current_stage": app.current_stage,
                    "application_status": app.status,
                }

            # Alreadipeline. Do not reset stage back to recruitery active in p.
            ensure_assessment_for_pipeline_stage(
                db=db,
                application_id=app.application_id,
                pipeline_stage=app.current_stage,
            )

            db.commit()
            db.refresh(app)

            return {
                "message": "Candidate already exists in pipeline",
                "status": "already_exists",
                "application_id": app.application_id,
                "current_stage": app.current_stage,
                "application_status": app.status,
            }

        app = Application(
            jd_id=jd_id,
            candidate_id=payload.candidate_id,
            current_resume_id=payload.resume_id or (screening.resume_id if screening else None),
            latest_screening_result_id=payload.screening_result_id,
            current_stage=first_stage,
            status=PIPELINE_STATUS_IN_PROGRESS,
        )
        db.add(app)
        db.flush()

        add_stage_history(
            db=db,
            application_id=app.application_id,
            from_stage="NOT_IN_PIPELINE",
            to_stage=first_stage,
            changed_by=changed_by,
            remarks=remarks or "Added to pipeline",
        )

        # jd = db.query(JobDescription).filter(JobDescription.jd_id == jd_id).first()
        
        # if not jd:
        #     raise HTTPException(status_code=404, detail="Job description not found")

        # jd_stages = ensure_default_pipeline_stages_for_jd(db, jd)


        ensure_recruiter_assessment_for_application(
            db=db,
            application_id=app.application_id,
            first_stage=first_stage
        )

        db.commit()
        db.refresh(app)

        return {
            "message": "Candidate added to pipeline",
            "status": "created",
            "application_id": app.application_id,
            "current_stage": app.current_stage,
            "application_status": app.status,
            }   
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Add to pipeline failed")
        raise HTTPException(status_code=500, detail=f"Add to pipeline failed !")


@router.post("/pipeline/move")
def move_pipeline(payload: MovePipelineRequest, current_user: CurrentUser = Depends(require_any_role),db: Session = Depends(get_db)):
    try:
        app = db.query(Application).filter(
            Application.application_id == payload.application_id
        ).first()

        if not app:
            raise HTTPException(status_code=404, detail="Application not found")

        previous = app.current_stage

        app.current_stage = payload.to_stage
        app.status = payload.status
      

        add_stage_history(
            db=db,
            application_id=app.application_id,
            from_stage=previous,
            to_stage=payload.to_stage,
            changed_by=payload.changed_by,
            remarks=payload.remarks,
        )

        # If moving to RECRUITER_ASSESSMENT, L1_ASSESSMENT, L2_ASSESSMENT, etc.,
        # create the corresponding stage-based assessment row.
        ensure_assessment_for_pipeline_stage(
            db=db,
            application_id=app.application_id,
            pipeline_stage=payload.to_stage,
        )

        db.commit()
        db.refresh(app)

        return {
            "message": "Pipeline updated",
            "application_id": app.application_id,
            "current_stage": app.current_stage,
            "status": app.status,
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Pipeline move failed")
        raise HTTPException(status_code=500, detail=f"Pipeline move failed !")



@router.get("/pipeline/jd_id={jd_id}")
def get_pipeline(
    jd_id: int,
    current_user: CurrentUser = Depends(require_any_role),
    db: Session = Depends(get_db),
):
    try:
        rows = (
            db.query(Application)
            .filter(
                Application.jd_id == jd_id,
                Application.status != PIPELINE_STATUS_REMOVED,
                Application.current_stage != PIPELINE_STAGE_DELETED,
            )
            .all()
        )

        return [
            {
                "application_id": row.application_id,
                "jd_id": row.jd_id,
                "candidate_id": row.candidate_id,
                "current_resume_id": row.current_resume_id,
                "latest_screening_result_id": row.latest_screening_result_id,
                "current_stage": row.current_stage,
                "status": row.status,
            }
            for row in rows
        ]

    except SQLAlchemyError as e:
        logger.exception(
            "Database error while fetching pipeline for jd_id=%s",
            jd_id,
        )

        raise HTTPException(
            status_code=500,
            detail="Database error while fetching pipeline.",
        ) from e

    except Exception as e:
        logger.exception(
            "Unexpected error while fetching pipeline for jd_id=%s",
            jd_id,
        )

        raise HTTPException(
            status_code=500,
            detail="Unexpected error while fetching pipeline.",
        ) from e


@router.get("/pipeline/list_ids")
def list_req_ids(
    current_user: CurrentUser = Depends(require_any_role),
    db: Session = Depends(get_db),
):
    try:
        user_roles = {role.upper() for role in current_user.roles or []}

        query = (
            db.query(JobDescription.req_id)
            .join(Application, JobDescription.jd_id == Application.jd_id)
            .filter(
                Application.status != PIPELINE_STATUS_REMOVED,
                Application.current_stage != PIPELINE_STAGE_DELETED,
            )
        )

        # ADMIN can see all req_ids
        if "ADMIN" in user_roles:
            pass

        # RECRUITER can see only JDs created by them
        elif "RECRUITER" in user_roles:
            if not current_user.full_name:
                raise HTTPException(
                    status_code=400,
                    detail="Current user full_name is required for recruiter filtering.",
                )

            query = query.filter(
                JobDescription.created_by_email == current_user.email
            )

        # Optional: block other roles
        else:
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to view req_ids.",
            )

        rows = query.distinct().all()

        return {
            "req_ids": [r.req_id for r in rows]
        }

    except HTTPException:
        raise

    except Exception as e:
        logger.exception("List ids failed due to : %s", str(e))
        raise HTTPException(
            status_code=500,
            detail="Failed to fetch req_ids !",
        )


@router.get("/pipeline/reqid={req_id}")
def get_pipeline_by_req_id(
    req_id: str,
    current_user: CurrentUser = Depends(require_any_role),
    db: Session = Depends(get_db)
):
    try:
        jd = db.query(JobDescription).filter(
            JobDescription.req_id == req_id
        ).first()

        if not jd:
            raise HTTPException(status_code=404, detail="JD not found")

        jd_id = jd.jd_id

        latest_screening_subq = (
            db.query(
                ScreeningResult.candidate_id,
                func.max(ScreeningResult.screening_result_id).label("latest_id"),
            )
            .filter(ScreeningResult.jd_id == jd_id)
            .group_by(ScreeningResult.candidate_id)
            .subquery()
        )

        rows = (
            db.query(
                Application,
                Candidate,
                ScreeningResult,
                Assessment,
                PanelAssignment,
                EmployeeMaster
            )
            .join(Candidate, Candidate.candidate_id == Application.candidate_id)
            .outerjoin(
                latest_screening_subq,
                latest_screening_subq.c.candidate_id == Application.candidate_id,
            )
            .outerjoin(
                ScreeningResult,
                ScreeningResult.screening_result_id == latest_screening_subq.c.latest_id,
            )
            .outerjoin(
                Assessment,
                and_(
                    Assessment.application_id == Application.application_id,
                    Assessment.stage_code == Application.current_stage,
                ),
            )
            .outerjoin(
                PanelAssignment,
                and_(
                    PanelAssignment.application_id == Application.application_id,
                    PanelAssignment.panel_stage == Application.current_stage,
                    PanelAssignment.is_active == True,
                    PanelAssignment.is_primary == True,
                ),
            )
            .outerjoin(
                EmployeeMaster,
                EmployeeMaster.EmpId == PanelAssignment.hris_employee_id,
            )
            .filter(
                Application.jd_id == jd_id,
                Application.status != PIPELINE_STATUS_REMOVED,
                Application.current_stage != PIPELINE_STAGE_DELETED,
            )
            .all()
        )

        data = []

        for application, candidate, screening, assessment, panel, empmaster in rows:
            data.append({
                "application_id": application.application_id,
                "candidate_id": candidate.candidate_id,
                "full_name": candidate.full_name,
                "job_title": jd.title,
                "match_score": float(screening.overall_score) if screening and screening.overall_score is not None else None,
                "current_stage": application.current_stage,
                "application_status": application.status,
                "assessment_status": assessment.status if assessment else None,
                "assigned_recruiter_id": application.assigned_recruiter_id,
                "assigned_primary_panelist_name": empmaster.EmpName if empmaster else None,
                "panel_assignment_id": panel.panel_assignment_id if panel else None,
                "panel_assigned_by": panel.assigned_by if panel else None,
            })

        return {
            "req_id": req_id,
            "jd_id": jd_id,
            "job_title": jd.title,
            "total_candidates": len(data),
            "stages": jd.stages or [],
            "data": data,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Pipeline fetch failed: %s", str(e))
        raise HTTPException(status_code=500, detail=f"Failed to fetch pipeline !")

@router.post("/pipeline/add-stages", status_code=201)
def add_stages(
    payload: AddStagesRequest,
    current_user: CurrentUser = Depends(require_any_role),
    db: Session = Depends(get_db)
):
    try:
        jd = db.query(JobDescription).filter(
            JobDescription.req_id == payload.req_id
        ).first()

        if not jd:
            raise HTTPException(status_code=404, detail="Requisition not found")

        input_stages = payload.stages or []
        if not input_stages:
            raise HTTPException(status_code=400, detail="No stages provided")

        # ✅ Normalize input
        normalized_input_names = [s.stage_name.strip() for s in input_stages]

        # ✅ Check duplicates inside payload
        if len(set(n.lower() for n in normalized_input_names)) != len(normalized_input_names):
            raise HTTPException(
                status_code=400,
                detail="Duplicate stage names in request"
            )

        existing_stages = jd.stages or []

        # ✅ Check duplicates with existing DB data
        existing_names = {
            s.get("stage_name", "").lower()
            for s in existing_stages
        }

        for name in normalized_input_names:
            if name.lower() in existing_names:
                raise HTTPException(
                    status_code=409,
                    detail=f"Stage '{name}' already exists"
                )

        # ✅ Start numbering from current max
        start_number = max(
            [s.get("stage_number", 0) for s in existing_stages],
            default=0
        )

        # ✅ Create new stages in strict sequence
        new_stages = []
        for idx, stage in enumerate(input_stages, start=1):
            new_stages.append({
                "stage_number": start_number + idx,
                "stage_name": stage.stage_name.strip(),
                "stage_information": stage.stage_information
            })

        # ✅ Append to existing stages
        updated_stages = list(existing_stages) + new_stages

        jd.stages = updated_stages

        db.commit()
        db.refresh(jd)

        return {
            "message": "Stages added successfully",
            "stages": jd.stages
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to add stages: %s", str(e))
        raise HTTPException(status_code=500, detail=f"Internal server error !")
    



@router.get("/pipeline/get-stages/reqid={req_id}")
def get_stages(
    req_id : str,
    current_user: CurrentUser = Depends(require_any_role),
    db: Session = Depends(get_db)
):
    try:
        jd = db.query(JobDescription).filter(JobDescription.req_id == req_id).first()

        if not jd:
            raise HTTPException(status_code=404, detial="Requisition not found")
        
        stages = jd.stages or []

        sorted_stages = sorted(stages, key = lambda s: s.get("stage_number",0))
    
        return {
            "req_id" : req_id, 
            "total_stages" : len(sorted_stages),
            "stages" : sorted_stages
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get stage: %s", str(e))
        raise HTTPException(status_code=500, detail=f"Internal server error!")


@router.post("/pipeline/dynamic-add-stages", status_code=201)
def add_stages(
    payload: DynamicAddStagesRequest,
    current_user: CurrentUser = Depends(require_any_role),
    db: Session = Depends(get_db)
):
    try:
      

        jd = db.query(JobDescription).filter(
            JobDescription.req_id == payload.req_id
        ).first()

        if not jd:
            raise HTTPException(status_code=404, detail="Requisition not found")

        input_stages = payload.stages or []
        if not input_stages:
            raise HTTPException(status_code=400, detail="No stages provided")

        # -----------------------------------------
        # Validate duplicate stage numbers
        # -----------------------------------------
        stage_numbers = [s.stage_number for s in input_stages]
        if len(stage_numbers) != len(set(stage_numbers)):
            raise HTTPException(
                status_code=400,
                detail="Duplicate stage_number values in request"
            )

        # -----------------------------------------
        # Validate duplicate stage names
        # -----------------------------------------
        stage_names = [s.stage_name.strip().upper() for s in input_stages]
        if len(stage_names) != len(set(stage_names)):
                raise HTTPException(
                status_code=400,
                detail="Duplicate stage_name values in request"
            )

        # -----------------------------------------
        # Normalize and sort by FE-provided stage_number
        # -----------------------------------------
        updated_stages = sorted(
            [
                {
                    "stage_number": s.stage_number,
                    "stage_name": s.stage_name.strip().upper(),
                    "stage_information": s.stage_information
                }
                for s in input_stages
            ],
            key=lambda x: x["stage_number"]
        )

        # -----------------------------------------
        # Optional strict sequencing check
        # e.g. 1,2,3,4 only (no gaps)
        # -----------------------------------------
        # for idx, stage in enumerate(updated_stages, start=1):
        #     if stage["stage_number"] != idx:
        #         raise HTTPException(
        #             status_code=400,
        #             detail="stage_number must be in strict sequence starting from 1"
        #         )

        # -----------------------------------------
        # Store directly
        # -----------------------------------------
        jd.stages = updated_stages

        db.commit()
        db.refresh(jd)

        return {
            "message": "Stages updated successfully",
            "stages": jd.stages
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to add/update stages: %s", str(e))
        raise HTTPException(status_code=500, detail="Internal server error")
    



@router.post("/applications/bulk-add")
def bulk_add_to_pipeline(
    payload: BulkAddToPipelineRequest,
    current_user: CurrentUser = Depends(require_any_role),
    db: Session = Depends(get_db),
):
    try:
        logger.info(
            "Bulk add screening_ids=%s recruiter=%s",
            payload.screening_ids,
            payload.recruiter_id,
        )

        screenings = db.query(ScreeningResult).filter(
            ScreeningResult.screening_result_id.in_(payload.screening_ids)
        ).all()

        screening_map = {s.screening_result_id: s for s in screenings}

        inserted = []
        updated = []
        skipped = []

        changed_by = str(payload.recruiter_id) if payload.recruiter_id else "system"

        # -------------------------------------------------------
        # Preload job descriptions
        # -------------------------------------------------------
        jd_ids = {s.jd_id for s in screenings if s.jd_id}
        jds = db.query(JobDescription).filter(JobDescription.jd_id.in_(jd_ids)).all()
        jd_map = {jd.jd_id: jd for jd in jds}

        # -------------------------------------------------------
        # Activate JD + ensure default stages + cache first stage
        # -------------------------------------------------------
        jd_first_stage_map = {}

        for jd_id, jd in jd_map.items():
            if jd.status != "Active":
                jd.status = "Active"

            jd_stages = ensure_default_pipeline_stages_for_jd(db, jd)

            if not jd_stages or not isinstance(jd_stages[0], dict):
                raise HTTPException(
                    status_code=500,
                    detail=f"Invalid stage configuration for jd_id={jd_id}"
                )

            jd_first_stage_map[jd_id] = jd_stages[0]["stage_name"]

        # -------------------------------------------------------
        # Process each screening
        # -------------------------------------------------------
        for screening_result_id in payload.screening_ids:
            screening = screening_map.get(screening_result_id)

            if not screening:
                skipped.append({
                    "screening_result_id": screening_result_id,
                    "reason": "not found",
                })
                continue

            jd = jd_map.get(screening.jd_id)
            if not jd:
                skipped.append({
                    "screening_result_id": screening_result_id,
                    "candidate_id": screening.candidate_id,
                    "reason": f"Job description not found for jd_id={screening.jd_id}",
                })
                continue

            first_stage = jd_first_stage_map.get(screening.jd_id)
            if not first_stage:
                skipped.append({
                    "screening_result_id": screening_result_id,
                    "candidate_id": screening.candidate_id,
                    "reason": f"First stage not configured for jd_id={screening.jd_id}",
                })
                continue

            existing = db.query(Application).filter(
                Application.jd_id == screening.jd_id,
                Application.candidate_id == screening.candidate_id,
            ).first()

            if existing:
                previous_stage = existing.current_stage

                existing.current_resume_id = screening.resume_id
                existing.latest_screening_result_id = screening.screening_result_id
                existing.assigned_recruiter_id = payload.recruiter_id

                if is_removed_application(existing):
                    existing.current_stage = first_stage
                    existing.status = PIPELINE_STATUS_IN_PROGRESS

                    add_stage_history(
                        db=db,
                        application_id=existing.application_id,
                        from_stage=previous_stage,
                        to_stage=first_stage,
                        changed_by=changed_by,
                        remarks="Bulk re-added to pipeline",
                    )

                    # ✅ keep recruiter assessment creation as initial mandatory step
                    ensure_recruiter_assessment_for_application(
                        db=db,
                        first_stage=first_stage,
                        application_id=existing.application_id,
                    )

                    updated.append({
                        "candidate_id": screening.candidate_id,
                        "application_id": existing.application_id,
                        "status": "reactivated",
                    })
                    continue

                # Already active. Do not reset stage.
                ensure_assessment_for_pipeline_stage(
                    db=db,
                    application_id=existing.application_id,
                    pipeline_stage=existing.current_stage,
                )

                skipped.append({
                    "candidate_id": screening.candidate_id,
                    "application_id": existing.application_id,
                    "screening_result_id": screening_result_id,
                    "reason": "already active in pipeline",
                })
                continue

            application = Application(
                jd_id=screening.jd_id,
                candidate_id=screening.candidate_id,
                current_resume_id=screening.resume_id,
                latest_screening_result_id=screening.screening_result_id,
                assigned_recruiter_id=payload.recruiter_id,
                current_stage=first_stage,
                status=PIPELINE_STATUS_IN_PROGRESS,
            )

            db.add(application)
            db.flush()

            add_stage_history(
                db=db,
                application_id=application.application_id,
                from_stage="NOT_IN_PIPELINE",
                to_stage=first_stage,
                changed_by=changed_by,
                remarks="Bulk added to pipeline",
            )

            # ✅ keep recruiter assessment creation as initial mandatory step
            ensure_recruiter_assessment_for_application(
                db=db,
                first_stage=first_stage,
                application_id=application.application_id,
            )

            inserted.append({
                "candidate_id": screening.candidate_id,
                "application_id": application.application_id,
                "status": "created",
            })

        db.commit()

        return {
            "message": "Pipeline updated",
            "inserted_count": len(inserted),
            "updated_count": len(updated),
            "skipped_count": len(skipped),
            "inserted": inserted,
            "updated": updated,
            "skipped": skipped,
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Bulk add failed: %s", str(e))
        raise HTTPException(status_code=500, detail=f"Bulk add failed")