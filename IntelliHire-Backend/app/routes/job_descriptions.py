import json
from locale import normalize
import logging
from pathlib import Path
from typing import Annotated, Optional
import zipfile
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from app.core.security import CurrentUser, require_admin, require_recruiter,require_hr_manager, require_panelist,require_any_role
# from app.core.security import CurrentUser
from app.services.helper import normalizenone, payload_to_string

from app.services.jd_service import build_jd_pdf
from sqlalchemy.orm import Session
from sqlalchemy import func, asc,desc

from app.db.deps import get_db
from app.core.logger import get_logger
from app.core.config import get_settings
from app.models.job_description import EmployeeMaster, HRISTranscation, HorizontalMaster, JobDescription, ProjectMaster
from app.schemas.job_description import (
    JobDescriptionSaveRequest,
    ParseUploadedJdRequest,
    ProblemStatementsSaveRequest,
)
from app.services.storage_service import overwrite_existing_file, save_file, read_file_bytes, generate_download_link
from app.services.parser_service import extract_text_from_bytes
from app.services.llm_service import analyze_jd_with_llm, enhance_jd_with_llm, parse_and_enhance_jd, parse_jd_with_llm

router = APIRouter(tags=["job_descriptions"])
# logger = get_logger("job_descriptions")



logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("job_descriptions")




def validate_problem_statements(items: list[dict]) -> None:
    mandatory = [x for x in items if x.get("is_mandatory")]
    if len(mandatory) < 3:
        raise HTTPException(status_code=400, detail="Minimum 3 mandatory problem statements required")

    for item in mandatory:
        if not (item.get("question") or "").strip():
            raise HTTPException(
                status_code=400,
                detail="Problem statement question cannot be empty",
            )
        if not item.get("key_kpis"):
            raise HTTPException(
                status_code=400,
                detail="Each mandatory problem statement must have at least one KPI",
            )

@router.post("/job-descriptions/upload-jd")
async def upload_jd(
    current_user: CurrentUser = Depends(require_any_role),
    req_id: str = Form(...),
    grade: str = Form(...),
    jd_stage: str = Form(...),
    file: Optional[UploadFile] = File(None),  # ✅ FILE PICKER WORKS
    jd_id: int | None = Form(None),
    lob_id: int | None = Form(None),
    lob: str | None = Form(None),
    vertical: str | None = Form(None),
    db: Session = Depends(get_db),
):
    try:
        ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}
        ALLOWED_CONTENT_TYPES = {
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "text/plain",
        }

        if file:
            ext = Path(file.filename).suffix.lower()
            if ext not in ALLOWED_EXTENSIONS:
                raise HTTPException(
                    status_code=400,
                    detail=f"{file.filename}: only PDF, DOCX, and TXT files are allowed"
                )
            if file.content_type not in ALLOWED_CONTENT_TYPES:
                raise HTTPException(
                    status_code=400,
                    detail=f"{file.filename}: invalid content type '{file.content_type}'"
                )
            
        settings = get_settings()

        # =====================================================
        #  CREATE NEW JD
        # =====================================================
        if not jd_id:

            if not file:
                raise HTTPException(400, "File is required for new JD")

            #  req_id must be unique
            existing = db.query(JobDescription).filter(
                JobDescription.req_id == req_id
            ).first()

            if existing:
                raise HTTPException(409, "req_id already exists")

            content = await file.read()

            #  first time → UUID-based storage
            storage = save_file(settings, content, file.filename, "jd")
          
            jd = JobDescription(
                req_id=req_id,
                grade=grade,
                jd_s3_key=storage["s3_key"] or storage["local_path"],
                jd_file_uuid=storage["file_uuid"],
                jd_uploaded=True,
                jd_parsed=False,
                jd_source_type="upload",
                jd_parse_status="not_started",
                status="draft",
                jd_stage=jd_stage,
                file_name= file.filename,
                lob_id=lob_id,
                lob=lob,
                vertical=vertical,

            )

            db.add(jd)

        # =====================================================
        #  UPDATE EXISTING JD
        # =====================================================
        else:
            jd = db.query(JobDescription).filter(
                JobDescription.jd_id == jd_id
            ).first()

            if not jd:
                raise HTTPException(404, "JD not found")

            #  ensure req_id uniqueness
            existing = db.query(JobDescription).filter(
                JobDescription.req_id == req_id,
                JobDescription.jd_id != jd_id
            ).first()

            if existing:
                raise HTTPException(409, "req_id already exists")

            # =================================================
            #  FILE UPDATE (ONLY IF PROVIDED)
            # =================================================
            if file:
                content = await file.read()

                if not jd.jd_s3_key:
                    raise HTTPException(400, "Existing JD file not found")

                overwrite_existing_file(settings, content, jd.jd_s3_key)

                jd.jd_uploaded = True
                jd.jd_parsed = False
                jd.jd_parse_status = "not_started"

            # =================================================
            #  METADATA UPDATE (ALWAYS)
            # =================================================
            jd.req_id = req_id
            jd.grade = grade
            jd.jd_stage = jd_stage
            jd.lob_id=lob_id
            jd.lob=lob
            jd.vertical= vertical
            if not jd.created_by:
                jd.created_by = current_user.full_name
            if not jd.created_by_email:
                jd.created_by_email = current_user.email

        # =====================================================
        # SAVE
        # =====================================================
        db.commit()
        db.refresh(jd)

        return {
            "message": "JD saved successfully",
            "jd_id": jd.jd_id,
            "req_id": jd.req_id,
            "grade": jd.grade,
            "jd_stage": jd.jd_stage,
            "jd_uploaded": jd.jd_uploaded,
            "jd_parsed": jd.jd_parsed,
        }

    except HTTPException:
        raise
    except Exception:
        logger.exception("JD upload/update failed")
        raise HTTPException(500, "JD upload failed")

# ---------------------------------------------------------
# Save problem statements
# ---------------------------------------------------------
@router.post("/job-descriptions/problem-statements/save")
def save_problem_statements(
    payload: ProblemStatementsSaveRequest, db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_any_role)
):
    try:
        jd = db.query(JobDescription).filter(
            JobDescription.jd_id == payload.jd_id
        ).first()
        if not jd:
            raise HTTPException(status_code=404, detail="JD not found")

        items = [item.model_dump() for item in payload.problem_statements]
        # validate_problem_statements(items)

        jd.problem_statements = items
        jd.status = payload.status
        jd.jd_stage = payload.jd_stage

        db.commit()
        db.refresh(jd)

        return {
            "message": "Problem statements saved successfully",
            "jd_id": jd.jd_id,
            "problem_statements_count": len(jd.problem_statements),
            "jd_stage" : jd.jd_stage
        }

    except HTTPException:
        raise
    except Exception:
        logger.exception("Saving problem statements failed")
        raise HTTPException(
            status_code=500,
            detail="Failed to save problem statements",
        )


# ---------------------------------------------------------
# Get JD by ID
# ---------------------------------------------------------
@router.get("/job-descriptions")
def get_jd(jd_id: int, current_user: CurrentUser = Depends(require_any_role),db: Session = Depends(get_db)):
    try:
        settings = get_settings()

        jd = db.query(JobDescription).filter(
            JobDescription.jd_id == jd_id
        ).first()
        if not jd:
            raise HTTPException(status_code=404, detail="JD not found")

        download_link = (
            generate_download_link(
                settings,
                jd.jd_s3_key if settings.file_storage_mode == "s3" else None,
                jd.jd_s3_key if settings.file_storage_mode != "s3" else None,
                jd.file_name or "JD"
            )
            if jd.jd_uploaded
            else None
        )

        return {
            "jd_id": jd.jd_id,
            "req_id": jd.req_id,
            "grade": jd.grade,
            "title": jd.title,
            "location": jd.location,
            "experience": jd.experience,
            "role_summary": jd.role_summary,
            "responsibilities": jd.responsibilities,
            "mandatory_skills": jd.mandatory_skills,
            "good_to_have_skills": jd.good_to_have_skills,
            "problem_statements": jd.problem_statements,
            "jd_uploaded": jd.jd_uploaded,
            "jd_parsed": jd.jd_parsed,
            "jd_source_type": jd.jd_source_type,
            "jd_download_url": download_link,
            "status": jd.status,
            "qualifications" : jd.qualifications,
            "file_name" : jd.file_name,
            "jd_score": jd.jd_score,
            "jd_score_justification": jd.jd_score_justification,
            "jd_suggestions": jd.jd_suggestions,
            "lob_id": jd.lob_id,
            "lob":jd.lob,
            "vertical": jd.vertical,

        }

    except HTTPException:
        raise
    except Exception:
        logger.exception("Saving problem statements failed")
        raise HTTPException(
            status_code=500,
            detail="Failed to save problem statements",
        )

    
@router.get("/job-descriptions-list")
def list_job_descriptions(
    status: str | None = Query(default=None),
    req_id: str | None = Query(default=None),
    grade: str | None = Query(default=None),
    jd_source_type: str | None = Query(default=None),
    current_user: CurrentUser = Depends(require_any_role),
    db: Session = Depends(get_db),
):
    try:
        user_roles = {role.upper() for role in current_user.roles or []}

        query = db.query(JobDescription)

        # ---------------- Role-based filtering ----------------

        # ADMIN → no restriction
        if "ADMIN" in user_roles:
            pass

        # RECRUITER → only own JDs
        elif "RECRUITER" in user_roles:
            if not current_user.full_name:
                raise HTTPException(
                    status_code=400,
                    detail="Current user full_name is required for recruiter filtering.",
                )

            query = query.filter(
                JobDescription.created_by_email == current_user.email
            )

        # Block other roles
        else:
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to view job descriptions.",
            )

        # ---------------- Query filters ----------------

        if status:
            query = query.filter(JobDescription.status == status)

        if req_id:
            query = query.filter(JobDescription.req_id == req_id)

        if grade:
            query = query.filter(JobDescription.grade == grade)

        if jd_source_type:
            query = query.filter(JobDescription.jd_source_type == jd_source_type)

        # ---------------- Fetch data ----------------

        rows = query.order_by(
            desc(JobDescription.updated_at),
            desc(JobDescription.created_at),
        ).all()

        return {
            "message": "Job descriptions fetched successfully",
            "count": len(rows),
            "items": [
                {
                    "jd_id": row.jd_id,
                    "req_id": row.req_id,
                    "grade": row.grade,
                    "title": row.title,
                    "location": row.location,
                    "experience": row.experience,
                    "status": row.status,
                    "jd_uploaded": row.jd_uploaded,
                    "jd_parsed": row.jd_parsed,
                    "jd_source_type": row.jd_source_type,
                    "created_at": row.created_at,
                    "updated_at": row.updated_at,
                    "jd_stage": row.jd_stage,
                    "lob_id": row.lob_id,
                    "lob": row.lob,
                    "vertical": row.vertical,
                }
                for row in rows
            ],
        }

    except HTTPException:
        raise
    except Exception:
        logger.exception("job-descriptions-list failed")
        raise HTTPException(
            status_code=500,
            detail="job-descriptions-list fetch failed",
        )


@router.post("/job-descriptions/parse-uploaded-jd")
async def parse_uploaded_jd(
    jd_id: int | None = Form(default=None),
    req_id: str | None = Form(default=None),
    grade: str | None = Form(default=None),
    jd_stage: str | None = Form(default=None),
    file: Optional[UploadFile] = File(None),
    lob_id: int | None = Form(default=None),
    lob: str | None = Form(default=None),
    vertical: str | None = Form(default=None),
    current_user: CurrentUser = Depends(require_any_role),
    db: Session = Depends(get_db),
):
    try:
        settings = get_settings()

        # -------------------------
        # Normalize inputs
        # -------------------------
        req_id = normalizenone(req_id)
        grade = normalizenone(grade)
        jd_stage = normalizenone(jd_stage)
        lob = normalizenone(lob)
        vertical = normalizenone(vertical)

        if file and file.filename == "":
            file = None

        jd = None
        file_bytes = None
        source_name = None

        # =====================================================
        # 🔵 CASE 1: EXISTING JD
        # =====================================================
        if jd_id:

            jd = db.query(JobDescription).filter(
                JobDescription.jd_id == jd_id
            ).first()

            if not jd:
                raise HTTPException(404, "JD not found")

            # ✅ req_id update
            if req_id is not None:
                existing = db.query(JobDescription).filter(
                    JobDescription.req_id == req_id,
                    JobDescription.jd_id != jd_id
                ).first()

                if existing:
                    raise HTTPException(409, "req_id already exists")

                jd.req_id = req_id

            # ✅ Optional updates
            if grade is not None:
                jd.grade = grade

            if jd_stage is not None:
                jd.jd_stage = jd_stage

            if lob_id is not None:
                jd.lob_id = lob_id

            if lob is not None:
                jd.lob = lob

            if vertical is not None:
                jd.vertical = vertical

            # -------------------------
            # FILE HANDLING
            # -------------------------
            if file:
                file_bytes = await file.read()
                source_name = file.filename or "jd.bin"

                if jd.jd_s3_key:
                    overwrite_existing_file(settings, file_bytes, jd.jd_s3_key)
                else:
                    storage = save_file(settings, file_bytes, source_name, "jd")

                    jd.jd_s3_key = storage["s3_key"] or storage["local_path"]
                    jd.jd_file_uuid = storage["file_uuid"]

                jd.jd_uploaded = True
                jd.jd_source_type = "upload"
                jd.jd_parsed = False
                jd.jd_parse_status = "not_started"

            elif jd.jd_s3_key:
                file_bytes = read_file_bytes(
                    settings,
                    jd.jd_s3_key if settings.file_storage_mode == "s3" else None,
                    jd.jd_s3_key if settings.file_storage_mode != "s3" else None,
                )
                source_name = jd.jd_s3_key

            else:
                raise HTTPException(
                    400,
                    "No JD file available. Please upload a file first."
                )

        # =====================================================
        # 🟢 CASE 2: NEW JD
        # =====================================================
        else:

            if not req_id:
                raise HTTPException(400, "req_id is required")

            if not file:
                raise HTTPException(400, "File is required for new JD")

            existing = db.query(JobDescription).filter(
                JobDescription.req_id == req_id
            ).first()

            if existing:
                raise HTTPException(409, "req_id already exists")

            file_bytes = await file.read()
            source_name = file.filename or "jd.bin"

            storage = save_file(settings, file_bytes, source_name, "jd")

            jd = JobDescription(
                req_id=req_id,
                grade=grade,
                jd_s3_key=storage["s3_key"] or storage["local_path"],
                jd_file_uuid=storage["file_uuid"],
                jd_uploaded=True,
                jd_parsed=False,
                jd_source_type="upload",
                jd_parse_status="not_started",
                status="draft",
                jd_stage=jd_stage or "2",
                file_name=file.filename,

                # ✅ NEW FIELDS
                lob_id=lob_id,
                lob=lob,
                vertical=vertical,
            )

            db.add(jd)
            db.flush()

        # =====================================================
        # 🧠 PARSING
        # =====================================================
        # text = extract_text_from_bytes(
        #     file_bytes,
        #     source_name or "jd.bin",
        #     document_type="jd"
        # )
        try:
            text = extract_text_from_bytes(file_bytes, source_name or "jd.bin", "jd")
        except zipfile.BadZipFile:
            raise HTTPException(400, "The uploaded file is not a valid DOCX or zip file.")

        parsed = parse_and_enhance_jd(settings, text)

        logger.info(parsed)

        # ✅ SAFE FIELD UPDATES
        if parsed.get("title") is not None:
            jd.title = parsed.get("title")


        if parsed.get("location") is not None:
            jd.location = parsed.get("location")

        if parsed.get("experience") is not None:
            jd.experience = parsed.get("experience")

        if parsed.get("role_summary") is not None:
            jd.role_summary = parsed.get("role_summary")

        if parsed.get("responsibilities") is not None:
            jd.responsibilities = parsed.get("responsibilities") or []

        if parsed.get("mandatory_skills") is not None:
            jd.mandatory_skills = parsed.get("mandatory_skills") or []

        if parsed.get("good_to_have_skills") is not None:
            jd.good_to_have_skills = parsed.get("good_to_have_skills") or []

        if parsed.get("qualifications") is not None:
            jd.qualifications = parsed.get("qualifications") or []

        if parsed.get("jd_score") is not None:
            jd.jd_score = parsed.get("jd_score")

        if parsed.get("jd_score_justification") is not None:
            jd.jd_score_justification = parsed.get("jd_score_justification")

        if parsed.get("suggestions") is not None:
            jd.jd_suggestions = parsed.get("suggestions") or []

        # ✅ Always update parsing metadata
        jd.jd_raw_text = text
        jd.jd_parsed = True
        jd.jd_parse_status = "completed"
        if not jd.created_by:
            jd.created_by = current_user.full_name
        if not jd.created_by_email:
            jd.created_by_email = current_user.email

        if jd_stage is not None:
            jd.jd_stage = jd_stage

        db.commit()
        db.refresh(jd)

        return {
            "message": "JD parsed successfully",
            "jd_id": jd.jd_id,
            "req_id": jd.req_id,
            "lob_id": jd.lob_id,
            "lob": jd.lob,
            "vertical": jd.vertical,
            "parsed_data": {
                "title": jd.title,
                "location": jd.location,
                "experience": jd.experience,
                "role_summary": jd.role_summary,
                "responsibilities": jd.responsibilities,
                "mandatory_skills": jd.mandatory_skills,
                "good_to_have_skills": jd.good_to_have_skills,
                "qualifications": jd.qualifications,
                "jd_stage": jd.jd_stage,
            },
        }

    except HTTPException:
        raise

    except Exception as e:
        db.rollback()
        logger.exception(f"JD parsing failed: {e}")

        raise HTTPException(
            status_code=500,
            detail={
                "error": "Failed to parse JD",
              
            },
        )


@router.get("/job-descriptions/analyze-improve/jd_id={jd_id}")
def analyze_improve_jd(jd_id: int, current_user: CurrentUser = Depends(require_any_role),db: Session = Depends(get_db)):
    try:
        settings = get_settings()

        jd = db.query(JobDescription).filter(
            JobDescription.jd_id == jd_id
        ).first()

        if not jd:
            raise HTTPException(status_code=404, detail="JD not found")

        jd_payload = {
            "title": jd.title,
            "location": jd.location,
            "experience": jd.experience,
            "role_summary": jd.role_summary,
            "responsibilities": jd.responsibilities or [],
            "mandatory_skills": jd.mandatory_skills or [],
            "good_to_have_skills": jd.good_to_have_skills or [],
            "qualifications": getattr(jd, "qualifications", []) or [],
        }

        analysis = analyze_jd_with_llm(settings, jd_payload)

        return {
            "message": "JD analysis generated successfully",
            "jd_id": jd.jd_id,
            "req_id": jd.req_id,
            "analysis": analysis,
        }

    except HTTPException:
        raise
    except Exception:
        logger.exception("JD analyze & improve failed")
        raise HTTPException(status_code=500, detail="Failed to analyze JD")


@router.post("/job-descriptions/save")
def save_jd(
    payload: JobDescriptionSaveRequest,
    current_user: CurrentUser = Depends(require_any_role),
    db: Session = Depends(get_db),
):
    try:
        logger.info(
            "Saving JD req_id=%s jd_id=%s status=%s validate=%s",
            payload.req_id,
            payload.jd_id,
            payload.status,
            
        )

        # ----------------------------------------------------
        # FETCH OR CREATE JD
        # ----------------------------------------------------
        if payload.jd_id:
            jd = db.query(JobDescription).filter(
                JobDescription.jd_id == payload.jd_id
            ).first()
            if not jd:
                raise HTTPException(status_code=404, detail="JD not found")
        else:
            existing = db.query(JobDescription).filter(
                JobDescription.req_id == payload.req_id
            ).first()
            if existing:
                raise HTTPException(status_code=409, detail="req_id already exists")

            jd = JobDescription(
                req_id=payload.req_id,
                grade=payload.grade,
                jd_source_type="manual",
                jd_uploaded=False,
                jd_parsed=False,
                jd_parse_status="manual",
                status=payload.status,
                jd_stage=payload.jd_stage,
                lob_id=payload.lob_id,
                lob=payload.lob,
                vertical=payload.vertical,

            )
            db.add(jd)
            db.flush()

        # ----------------------------------------------------
        # APPLY MANUAL PAYLOAD VALUES
        # ----------------------------------------------------
        jd.req_id = payload.req_id
        jd.grade = payload.grade
        jd.title = payload.title
        jd.location = payload.location
        jd.experience = payload.experience
        jd.role_summary = payload.role_summary
        jd.responsibilities = payload.responsibilities or []
        jd.mandatory_skills = payload.mandatory_skills or []
        jd.good_to_have_skills = payload.good_to_have_skills or []
        jd.qualifications = payload.qualifications or []
        jd.status = payload.status
        jd.jd_stage = payload.jd_stage

        if not jd.created_by:
            jd.created_by = current_user.full_name
        if not jd.created_by_email:
            jd.created_by_email = current_user.email

        if payload.lob_id is not None:
            jd.lob_id = payload.lob_id

        if payload.lob is not None:
            jd.lob = payload.lob

        if payload.vertical is not None:
            jd.vertical = payload.vertical

        # ----------------------------------------------------
        # VALIDATION FLOW (JSON → STRING → LLM)
        # ----------------------------------------------------
        if payload.jd_stage == "2":
            logger.info("JD validation enabled. Sending payload to LLM.")

            jd_text = payload_to_string(payload)
            settings = get_settings()
            parsed = parse_and_enhance_jd(settings, jd_text)

            logger.info("LLM enhanced JD result received")

            # -------- SAFE FIELD UPDATES (NO BAD OVERRIDES) --------
            if parsed.get("title") is not None:
                jd.title = parsed["title"]


            if parsed.get("location") is not None:
                jd.location = parsed["location"]

            if parsed.get("experience") is not None:
                jd.experience = parsed["experience"]

            if parsed.get("role_summary") is not None:
                jd.role_summary = parsed["role_summary"]

            if parsed.get("responsibilities") is not None:
                jd.responsibilities = parsed["responsibilities"] or []

            if parsed.get("mandatory_skills") is not None:
                jd.mandatory_skills = parsed["mandatory_skills"] or []

            if parsed.get("good_to_have_skills") is not None:
                jd.good_to_have_skills = parsed["good_to_have_skills"] or []

            if parsed.get("qualifications") is not None:
                jd.qualifications = parsed["qualifications"] or []


            if parsed.get("jd_score") is not None:
                jd.jd_score = parsed.get("jd_score")

            if parsed.get("jd_score_justification") is not None:
                jd.jd_score_justification = parsed.get("jd_score_justification")

            if parsed.get("suggestions") is not None:
                jd.jd_suggestions = parsed.get("suggestions") or []    

            jd.jd_parsed = True
            jd.jd_parse_status = "validated"

        # ----------------------------------------------------
        # COMMIT
        # ----------------------------------------------------
        db.commit()
        db.refresh(jd)

        return {
            "message": "JD saved successfully",
            "jd_id": jd.jd_id,
            "status": jd.status,
            "jd_stage": jd.jd_stage,
            "lob_id": jd.lob_id,
            "lob": jd.lob,
            "vertical": jd.vertical,
           
        }

    
    except HTTPException:
        raise

    except Exception as e:
        db.rollback()
        logger.exception(f"Save JD failed: {e}")

        raise HTTPException(
            status_code=500,
            detail={
                "error": "Failed to save JD",
                
            },
        )





@router.get("/get-lob-vertical-dropdowns")
def get_dropdowns(
    current_user: CurrentUser = Depends(require_any_role)
):
    try:
    

        # ✅ Division (LOB - cleaned & normalized)
        division_list = sorted([
            "AI & Data",
            "Administration",
            "Banking",
            "Business Process Management",
            "CEO Office",
            "ChairMan Office",
            "CIIS",
            "Corporate IT",
            "Cybersecurity",
            "Delivery Excellence",
            "Design Experience",
            "Digital Engineering",
            "Global Finance",
            "Global Leadership Hiring",
            "Hi-Tech",
            "Human Resources",
            "Insight Institute",
            "Internal Systems",
            "Legal",
            "Life Sciences",
            "Marketing",
            "Ops Transformation",
            "Partnerships & Alliances",
            "Platforms",
            "Presales & Strategy",
            "RMG",
            "Solutions",
            "Talent Acquisition",
            "Telecom",
            "Travel",
            "Wealth Management"
        ], key=lambda x: x.lower())

        return {
            "LOB": [
                {"id": idx + 1, "name": name}
                for idx, name in enumerate(division_list)
            ],
           
            "Vertical":[
                "Banking",
                "Corporate/Others",
                "Hi-Tech",
                "Life Sciences",
                "Telecom",
                "Wealth Management"]
        }

    except Exception as e:
        logger.exception(f"Failed to get dropdown items: {e}")

        raise HTTPException(
            status_code=500,
            detail={
                "error": "Failed to get the dropdown items"
                
            },
        )



@router.get("/job-descritptions/downlaod-jd/jdid={jd_id}")
def get_job_description_pdf(
    jd_id: int,
    current_user: CurrentUser = Depends(require_any_role),
    db: Session = Depends(get_db),
):
    jd = (
        db.query(JobDescription)
        .filter(JobDescription.jd_id == jd_id)
        .first()
    )

    if not jd:
        raise HTTPException(
            status_code=404,
            detail="Job description not found",
        )

    pdf_buffer = build_jd_pdf(jd)

    file_name = f"job_description_{jd.req_id or jd.jd_id}.pdf"

    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{file_name}"',
            "Access-Control-Expose-Headers": "Content-Disposition"
        },
    )