
import time
from datetime import datetime, timezone
import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, BackgroundTasks, Request
from sqlalchemy.exc import SQLAlchemyError
from app.models.application import Application, ApplicationStageHistory
from app.models.assessments import Assessment
from app.models.candidate import Candidate
from app.models.panel_assignments import PanelAssignment
from app.models.screeningweightconfigs import ScreeningWeightConfig
from app.schemas.screening import ScreeningResultManageAction, ScreeningResultsDeleteRequest, ScreeningResultsManageRequest, ScreeningWeightsResetRequest, ScreeningWeightsSaveRequest
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db.deps import get_db
from app.core.config import get_settings
from app.core.logger import get_logger
from app.models.job_description import JobDescription
from app.models.resume import Resume
from app.models.screening_result import ScreeningResult
from app.services.storage_service import save_file
from app.services.parser_service import extract_text_from_bytes
from app.services.llm_service import evaluate_resume_with_llm
from app.services.screening_service import build_screening_result, get_default_screening_weights, get_effective_screening_weights, validate_screening_weights
from app.services.candidate_service import get_or_create_candidate
from app.core.security import CurrentUser, require_admin, require_recruiter,require_hr_manager, require_panelist,require_any_role

import asyncio
import math
from concurrent.futures import ThreadPoolExecutor

from pathlib import Path



router = APIRouter(tags=["screening"])
logger = get_logger(__name__)


def now_iso() -> str:
    """
    UTC timestamp in ISO format.
    Example: 2026-05-25T10:07:12.123456+00:00
    """
    return datetime.now(timezone.utc).isoformat()


def elapsed_ms(start: float) -> float:
    """
    Returns elapsed time in milliseconds.
    """
    return round((time.perf_counter() - start) * 1000, 2)

@router.post("/screening/upload-resumes")
async def upload_resumes(
    request: Request,
    background_tasks: BackgroundTasks,
    jd_id: int = Form(...),
    current_user: CurrentUser = Depends(require_any_role),
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    try:

        MAX_FILES = 50
        MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB

        if len(files) > MAX_FILES:
            raise HTTPException(
                status_code=400,
                detail=f"Maximum {MAX_FILES} files allowed per request"
            )

        for file in files:
            content = await file.read()
            if len(content) > MAX_FILE_SIZE_BYTES:
                raise HTTPException(
                    status_code=400,
                    detail=f"{file.filename} exceeds the 10MB size limit"
                )
            await file.seek(0)  # reset after reading for size check



        ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}
        ALLOWED_CONTENT_TYPES = {
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "text/plain",
        }

        for file in files:
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


        request_start = time.perf_counter()
        request_started_at = now_iso()
        logger.info(
            "[UPLOAD_RESUMES] Request started at=%s jd_id=%s total_files=%s user=%s",
            request_started_at,
            jd_id,
            len(files),
            getattr(current_user, "email", None) or getattr(current_user, "user_id", None),
        )

        settings = get_settings()
        session_maker = request.app.state.session_maker

        # ─────────────────────────────────────────────
        # STAGE: JD lookup
        # ─────────────────────────────────────────────
        stage_start = time.perf_counter()
        logger.info("[UPLOAD_RESUMES] JD lookup started at=%s jd_id=%s", now_iso(), jd_id)

        jd = db.query(JobDescription).filter(JobDescription.jd_id == jd_id).first()

        logger.info(
            "[UPLOAD_RESUMES] JD lookup finished at=%s jd_id=%s duration_ms=%s found=%s",
            now_iso(),
            jd_id,
            elapsed_ms(stage_start),
            bool(jd),
        )

        if not jd:
            logger.warning(
                "[UPLOAD_RESUMES] JD not found jd_id=%s total_duration_ms=%s",
                jd_id,
                elapsed_ms(request_start),
            )
            raise HTTPException(status_code=404, detail="JD not found")

        # ─────────────────────────────────────────────
        # STAGE: Screening weights
        # ─────────────────────────────────────────────
        stage_start = time.perf_counter()
        logger.info(
            "[UPLOAD_RESUMES] Screening weights loading started at=%s jd_id=%s",
            now_iso(),
            jd.jd_id,
        )

        screening_weights, screening_weights_source = get_effective_screening_weights(
            db=db,
            settings=settings,
            jd_id=jd.jd_id,
        )

        logger.info(
            "[UPLOAD_RESUMES] Screening weights loading finished at=%s jd_id=%s source=%s duration_ms=%s",
            now_iso(),
            jd.jd_id,
            screening_weights_source,
            elapsed_ms(stage_start),
        )

        jd_dict = {
            "mandatory_skills": jd.mandatory_skills or [],
            "good_to_have_skills": jd.good_to_have_skills or [],
            "responsibilities": jd.responsibilities or [],
            "location": jd.location,
            "experience": jd.experience,
            "title": jd.title,
            "role_summary": jd.role_summary,
        }

        # ─────────────────────────────────────────────
        # PHASE 1: Read all file bytes
        # ─────────────────────────────────────────────
        phase_start = time.perf_counter()
        logger.info(
            "[UPLOAD_RESUMES] PHASE_1 file read started at=%s total_files=%s",
            now_iso(),
            len(files),
        )

        file_payloads = []

        for file_index, file in enumerate(files, start=1):
            file_start = time.perf_counter()
            filename = file.filename or "resume.bin"

            logger.info(
                "[UPLOAD_RESUMES] File read started at=%s file_index=%s filename=%s",
                now_iso(),
                file_index,
                filename,
            )

            content = await file.read()
            file_payloads.append((content, filename))

            logger.info(
                "[UPLOAD_RESUMES] File read finished at=%s file_index=%s filename=%s size_bytes=%s duration_ms=%s",
                now_iso(),
                file_index,
                filename,
                len(content),
                elapsed_ms(file_start),
            )

        logger.info(
            "[UPLOAD_RESUMES] PHASE_1 file read finished at=%s total_files=%s duration_ms=%s",
            now_iso(),
            len(file_payloads),
            elapsed_ms(phase_start),
        )

        # ─────────────────────────────────────────────
        # PHASE 2: Parallel Extract + LLM
        # ─────────────────────────────────────────────
        phase_start = time.perf_counter()

        total_files = len(file_payloads)
        # MAX_WORKERS = min(math.ceil(total_files / 10) * 10, 50) if total_files else 1
        MAX_WORKERS = min(total_files, 10)  # 1 worker per file, max 10
        loop = asyncio.get_running_loop()

        logger.info(
            "[UPLOAD_RESUMES] PHASE_2 extract_llm started at=%s total_files=%s max_workers=%s",
            now_iso(),
            total_files,
            MAX_WORKERS,
        )

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            tasks = [
                loop.run_in_executor(
                    executor,
                    _process_single_resume_io,
                    settings,
                    jd_dict,
                    screening_weights,
                    content,
                    filename,
                    index + 1,
                )
                for index, (content, filename) in enumerate(file_payloads)
            ]

            processed_resumes = await asyncio.gather(*tasks)

        logger.info(
            "[UPLOAD_RESUMES] PHASE_2 extract_llm finished at=%s total_files=%s duration_ms=%s",
            now_iso(),
            total_files,
            elapsed_ms(phase_start),
        )

        # ─────────────────────────────────────────────
        # PHASE 3: Sequential DB writes
        # ─────────────────────────────────────────────
        phase_start = time.perf_counter()
        logger.info(
            "[UPLOAD_RESUMES] PHASE_3 db_write started at=%s total_files=%s",
            now_iso(),
            len(processed_resumes),
        )

        results = []

        for index, proc in enumerate(processed_resumes):
            db_write_start = time.perf_counter()

            llm_result = proc["llm_result"]
            resume_text = proc["resume_text"]
            filename = proc["filename"]
            file_content = file_payloads[index][0]
            file_index = index + 1

            logger.info(
                "[UPLOAD_RESUMES] DB write started at=%s file_index=%s filename=%s jd_id=%s",
                now_iso(),
                file_index,
                filename,
                jd_id,
            )

            candidate_start = time.perf_counter()

            candidate = get_or_create_candidate(
                db=db,
                full_name=llm_result.get("full_name"),
                email=llm_result.get("email"),
                phone=llm_result.get("phone"),
            )

            logger.info(
                "[UPLOAD_RESUMES] Candidate get_or_create finished at=%s file_index=%s filename=%s candidate_id=%s duration_ms=%s",
                now_iso(),
                file_index,
                filename,
                candidate.candidate_id,
                elapsed_ms(candidate_start),
            )

            resume_update_start = time.perf_counter()

            db.query(Resume).filter(
                Resume.candidate_id == candidate.candidate_id
            ).update({"is_latest": False})

            resume = Resume(
                candidate_id=candidate.candidate_id,
                file_name=filename,
                s3_key=None,
                extracted_text=resume_text,
                parsed_resume_json=llm_result,
                is_latest=True,
            )

            db.add(resume)
            db.flush()

            logger.info(
                "[UPLOAD_RESUMES] Resume DB insert finished at=%s file_index=%s filename=%s resume_id=%s duration_ms=%s",
                now_iso(),
                file_index,
                filename,
                resume.resume_id,
                elapsed_ms(resume_update_start),
            )

            background_tasks.add_task(
                _background_s3_upload,
                settings,
                file_content,
                filename,
                resume.resume_id,
                session_maker,
            )

            screening_start = time.perf_counter()

            screening = build_screening_result(
                settings=settings,
                llm_result=llm_result,
                jd_mandatory_skills=jd.mandatory_skills or [],
                screening_weights=screening_weights,
            )

            logger.info(
                "[UPLOAD_RESUMES] Screening calculation finished at=%s file_index=%s filename=%s duration_ms=%s overall_score=%s",
                now_iso(),
                file_index,
                filename,
                elapsed_ms(screening_start),
                screening.get("overall_score"),
            )

            screening_insert_start = time.perf_counter()

            result = ScreeningResult(
                jd_id=jd.jd_id,
                candidate_id=candidate.candidate_id,
                resume_id=resume.resume_id,
                skill_score=screening["skill_score"],
                other_score=screening["other_score"],
                overall_score=screening["overall_score"],
                skills_matched=screening["skills_matched"],
                total_skills=screening["total_skills"],
                matched_skills=screening["matched_skills"],
                partial_skills=screening["partial_skills"],
                missing_skills=screening["missing_skills"],
                other_score_breakdown=screening["other_score_breakdown"],
                match_status=screening["match_status"],
                candidate_summary=llm_result.get("candidate_summary"),
                candidate_experience=llm_result.get("total_years_of_experience"),
                other_score_justifications=screening["other_score_justifications"],
            )

            db.add(result)
            db.flush()

            logger.info(
                "[UPLOAD_RESUMES] ScreeningResult DB insert finished at=%s file_index=%s filename=%s screening_result_id=%s duration_ms=%s",
                now_iso(),
                file_index,
                filename,
                result.screening_result_id,
                elapsed_ms(screening_insert_start),
            )

            results.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "resume_id": resume.resume_id,
                    "screening_result_id": result.screening_result_id,
                    "full_name": candidate.full_name,
                    "email": candidate.email,
                    "overall_score": float(result.overall_score) if result.overall_score is not None else None,
                    "skill_score": float(result.skill_score) if result.skill_score is not None else None,
                    "other_score": float(result.other_score) if result.other_score is not None else None,
                    "skills_match_text": f"{result.skills_matched}/{result.total_skills}",
                    "matched_skills": result.matched_skills,
                    "missing_skills": result.missing_skills,
                    "partial_skills": result.partial_skills,
                    "status": result.match_status,
                    "candidate_summary": llm_result.get("candidate_summary"),
                    "screening_weights_source": screening_weights_source,
                    "screening_weights_used": screening_weights,
                }
            )

            logger.info(
                "[UPLOAD_RESUMES] DB write finished at=%s file_index=%s filename=%s candidate_id=%s resume_id=%s duration_ms=%s",
                now_iso(),
                file_index,
                filename,
                candidate.candidate_id,
                resume.resume_id,
                elapsed_ms(db_write_start),
            )

        commit_start = time.perf_counter()
        logger.info("[UPLOAD_RESUMES] DB commit started at=%s jd_id=%s", now_iso(), jd.jd_id)

        db.commit()

        logger.info(
            "[UPLOAD_RESUMES] DB commit finished at=%s jd_id=%s duration_ms=%s",
            now_iso(),
            jd.jd_id,
            elapsed_ms(commit_start),
        )

        logger.info(
            "[UPLOAD_RESUMES] PHASE_3 db_write finished at=%s total_files=%s duration_ms=%s",
            now_iso(),
            len(processed_resumes),
            elapsed_ms(phase_start),
        )

        total_duration = elapsed_ms(request_start)

        logger.info(
            "[UPLOAD_RESUMES] Request finished at=%s jd_id=%s total_files=%s total_duration_ms=%s",
            now_iso(),
            jd.jd_id,
            len(file_payloads),
            total_duration,
        )

        return {
            "message": "Resumes processed successfully via latest method",
            "jd_id": jd.jd_id,
            "total_duration_ms": total_duration,
            "results": results,
        }

    except HTTPException:
        db.rollback()
        raise

    except SQLAlchemyError:
        db.rollback()

        logger.exception(
            "[UPLOAD_RESUMES] Database error jd_id=%s total_duration_ms=%s",
            jd_id,
            elapsed_ms(request_start),
        )

        raise HTTPException(
            status_code=500,
            detail="Database error while uploading resumes.",
        )

    except Exception:
        db.rollback()

        logger.exception(
            "[UPLOAD_RESUMES] Unexpected error jd_id=%s total_duration_ms=%s",
            jd_id,
            elapsed_ms(request_start),
        )

        raise HTTPException(
            status_code=500,
            detail="Unexpected error while uploading resumes.",
        )




def _process_single_resume_io(
    settings,
    jd_dict: dict,
    screening_weights: dict,
    file_content: bytes,
    filename: str,
    file_index: int | None = None,
) -> dict:
    total_start = time.perf_counter()

    logger.info(
        "[RESUME_PROCESS] Started at=%s file_index=%s filename=%s size_bytes=%s",
        now_iso(),
        file_index,
        filename,
        len(file_content),
    )

    extract_start = time.perf_counter()

    logger.info(
        "[RESUME_PROCESS] Text extraction started at=%s file_index=%s filename=%s",
        now_iso(),
        file_index,
        filename,
    )

    resume_text, extraction_meta = extract_text_from_bytes(
        file_content,
        filename,
        document_type="resume",
        return_meta=True,
    )

    logger.info(
        "[RESUME_PROCESS] Text extraction finished at=%s file_index=%s filename=%s extracted_chars=%s duration_ms=%s extraction_mode=%s source=%s total_pages=%s pages_ocrd=%s suspicious_pages=%s fallback_used=%s",
        now_iso(),
        file_index,
        filename,
        len(resume_text or ""),
        elapsed_ms(extract_start),
        extraction_meta.get("mode"),
        extraction_meta.get("source"),
        extraction_meta.get("total_pages"),
        extraction_meta.get("pages_ocrd"),
        extraction_meta.get("suspicious_pages"),
        extraction_meta.get("fallback_used"),
    )

    if not resume_text or len(resume_text.strip()) < 30:
        logger.warning(
            "[RESUME_PROCESS] Extracted text too low at=%s file_index=%s filename=%s extraction_mode=%s source=%s extracted_chars=%s",
            now_iso(),
            file_index,
            filename,
            extraction_meta.get("mode"),
            extraction_meta.get("source"),
            len(resume_text or ""),
        )

    llm_start = time.perf_counter()

    logger.info(
        "[RESUME_PROCESS] LLM evaluation started at=%s file_index=%s filename=%s",
        now_iso(),
        file_index,
        filename,
    )

    llm_result = evaluate_resume_with_llm(
    settings=settings,
    jd_dict=jd_dict,
    resume_text=resume_text,
    screening_weights=screening_weights,
)

    logger.info(
        "[RESUME_PROCESS] LLM evaluation finished at=%s file_index=%s filename=%s duration_ms=%s parsed_name=%s parsed_email=%s",
        now_iso(),
        file_index,
        filename,
        elapsed_ms(llm_start),
        llm_result.get("full_name"),
        llm_result.get("email"),
    )

    logger.info(
        "[RESUME_PROCESS] Finished at=%s file_index=%s filename=%s total_duration_ms=%s",
        now_iso(),
        file_index,
        filename,
        elapsed_ms(total_start),
    )

    return {
        "resume_text": resume_text,
        "llm_result": llm_result,
        "filename": filename,
        "extraction_meta": extraction_meta,
    }


def _background_s3_upload(
    settings,
    file_content: bytes,
    filename: str,
    resume_id: int,
    db_session_factory,
):
    total_start = time.perf_counter()

    logger.info(
        "[BACKGROUND_S3] Started at=%s resume_id=%s filename=%s size_bytes=%s",
        now_iso(),
        resume_id,
        filename,
        len(file_content),
    )

    try:
        upload_start = time.perf_counter()

        logger.info(
            "[BACKGROUND_S3] Upload started at=%s resume_id=%s filename=%s",
            now_iso(),
            resume_id,
            filename,
        )

        storage = save_file(settings, file_content, filename, "resumes")

        logger.info(
            "[BACKGROUND_S3] Upload finished at=%s resume_id=%s filename=%s duration_ms=%s s3_key=%s local_path=%s",
            now_iso(),
            resume_id,
            filename,
            elapsed_ms(upload_start),
            storage.get("s3_key"),
            storage.get("local_path"),
        )

        db_start = time.perf_counter()

        logger.info(
            "[BACKGROUND_S3] DB update started at=%s resume_id=%s filename=%s",
            now_iso(),
            resume_id,
            filename,
        )

        db = db_session_factory()

        try:
            db.query(Resume).filter(
                Resume.resume_id == resume_id
            ).update({
                "s3_key": storage["s3_key"] or storage["local_path"],
                "file_uuid": storage["file_uuid"],
            })

            db.commit()

            logger.info(
                "[BACKGROUND_S3] DB update finished at=%s resume_id=%s filename=%s duration_ms=%s",
                now_iso(),
                resume_id,
                filename,
                elapsed_ms(db_start),
            )

        except Exception:
            db.rollback()
            logger.exception(
                "[BACKGROUND_S3] DB update failed resume_id=%s filename=%s duration_ms=%s",
                resume_id,
                filename,
                elapsed_ms(db_start),
            )
            raise

        finally:
            db.close()

        logger.info(
            "[BACKGROUND_S3] Finished at=%s resume_id=%s filename=%s total_duration_ms=%s",
            now_iso(),
            resume_id,
            filename,
            elapsed_ms(total_start),
        )

    except Exception as e:
        logger.error(
            "[BACKGROUND_S3] Failed at=%s resume_id=%s filename=%s total_duration_ms=%s error=%s",
            now_iso(),
            resume_id,
            filename,
            elapsed_ms(total_start),
            e,
        )

@router.get("/screening-results/jd_id={jd_id}")
def get_screening_results(
    jd_id: int,
    current_user: CurrentUser = Depends(require_any_role),
    db: Session = Depends(get_db),
):
    try:
        # -------------------------------
        # Latest screening per candidate
        # -------------------------------
        latest_subquery = (
            db.query(
                ScreeningResult.candidate_id,
                func.max(ScreeningResult.screening_result_id).label("latest_id"),
            )
            .filter(ScreeningResult.jd_id == jd_id)
            .group_by(ScreeningResult.candidate_id)
            .subquery()
        )

        rows = (
            db.query(ScreeningResult, Candidate, Application, Resume)
            .join(
                latest_subquery,
                ScreeningResult.screening_result_id == latest_subquery.c.latest_id,
            )
            .join(
                Candidate,
                Candidate.candidate_id == ScreeningResult.candidate_id,
            )
            .outerjoin(
                Application,
                (Application.candidate_id == ScreeningResult.candidate_id)
                & (Application.jd_id == ScreeningResult.jd_id),
            )
            .outerjoin(
                Resume,
                Resume.resume_id == ScreeningResult.resume_id,
            )
            .all()
        )

        # -------------------------------
        # Count resumes
        # -------------------------------
        counts = (
            db.query(
                ScreeningResult.candidate_id,
                func.count(ScreeningResult.screening_result_id).label("cnt"),
            )
            .filter(ScreeningResult.jd_id == jd_id)
            .group_by(ScreeningResult.candidate_id)
            .all()
        )

        count_map = {c.candidate_id: c.cnt for c in counts}

        result = []

        for screening, candidate, application, resume in rows:
            # -------------------------------
            # Other JD applications
            # -------------------------------
            
            other_apps = (
                db.query(Application, JobDescription)
                .join(
                    JobDescription,
                    JobDescription.jd_id == Application.jd_id,
                )
                .filter(
                    Application.candidate_id == screening.candidate_id,
                    Application.jd_id != jd_id,
                )
                .all()
            )


            other_applications = [
                {
                    "jd_id": app.jd_id,
                    "stage": app.current_stage,
                    "status": app.status,
                    "req_id": jd.req_id,
                }
                for app, jd in other_apps
            ]

            result.append(
                {
                    "screening_result_id": screening.screening_result_id,
                    "jd_id": screening.jd_id,
                    "candidate_id": screening.candidate_id,
                    "full_name": candidate.full_name,
                    "email": candidate.email,
                    "resume_id": screening.resume_id,

                    "overall_score": (
                        float(screening.overall_score)
                        if screening.overall_score is not None
                        else None
                    ),

                    "skill_score": (
                        float(screening.skill_score)
                        if screening.skill_score is not None
                        else None
                    ),
                    "other_score": (
                        float(screening.other_score)
                        if screening.other_score is not None
                        else None
                    ),
                    
                    "other_score_breakdown": screening.other_score_breakdown,
                    "other_score_justifications": screening.other_score_justifications,


                    "skills_match_text": (
                        f"{screening.skills_matched}/{screening.total_skills}"
                    ),
                    "matched_skills": screening.matched_skills,
                    "missing_skills": screening.missing_skills,
                    "partial_skills": screening.partial_skills,

                    "screening_status": screening.match_status,
                    "candidate_summary": screening.candidate_summary,

                    # -------------------------------
                    # CURRENT JD PIPELINE
                    # -------------------------------
                    "application_id": (
                        application.application_id if application else None
                    ),
                    "current_stage": (
                        application.current_stage
                        if application
                        else "NOT_IN_PIPELINE"
                    ),
                    "application_status": (
                        application.status if application else None
                    ),

                    # -------------------------------
                    # OTHER JD PIPELINES
                    # -------------------------------
                    "other_applications": other_applications,

                    # -------------------------------
                    # MULTI RESUME FLAG
                    # -------------------------------
                    "has_multiple_resumes_for_same_jd": (
                        count_map.get(screening.candidate_id, 1) > 1
                    ),

                    "parsed_resume_json": (
                        resume.parsed_resume_json if resume else None
                    ),
                }
            )

        return result

    except HTTPException:
        raise

    except SQLAlchemyError:
        logger.exception(
            "Database error while fetching screening results for jd_id=%s",
            jd_id,
        )

        raise HTTPException(
            status_code=500,
            detail="Database error while fetching screening results.",
        )

    except Exception:
        logger.exception(
            "Unexpected error while fetching screening results for jd_id=%s",
            jd_id,
        )

        raise HTTPException(
            status_code=500,
            detail="Unexpected error while fetching screening results.",
        )


from fastapi import HTTPException, Depends
from sqlalchemy.orm import Session


@router.post("/screening-results/delete")
def delete_screening_results(
    payload: ScreeningResultsDeleteRequest,current_user: CurrentUser = Depends(require_any_role),
    db: Session = Depends(get_db),
):
    try:
        # -------------------------------------------------
        # 1. Normalize incoming IDs
        # -------------------------------------------------
        screening_result_ids = list(set(payload.screening_result_ids))

        if not screening_result_ids:
            raise HTTPException(
                status_code=400,
                detail="screening_result_ids cannot be empty",
            )

        # -------------------------------------------------
        # 2. Fetch screening results
        # -------------------------------------------------
        results = db.query(ScreeningResult).filter(
            ScreeningResult.screening_result_id.in_(screening_result_ids)
        ).all()

        found_ids = {r.screening_result_id for r in results}
        missing_ids = [x for x in screening_result_ids if x not in found_ids]

        if missing_ids:
            raise HTTPException(
                status_code=404,
                detail={
                    "message": "Some screening results were not found",
                    "missing_screening_result_ids": missing_ids,
                },
            )

        if not results:
            raise HTTPException(
                status_code=404,
                detail="No screening results found",
            )

        # -------------------------------------------------
        # 3. Check pipeline/application dependency
        # -------------------------------------------------
        application_map = {}

        for result in results:
            applications = db.query(Application).filter(
                Application.jd_id == result.jd_id,
                Application.candidate_id == result.candidate_id,
            ).all()

            if applications:
                application_map[result.screening_result_id] = applications

        # If application exists and frontend did not allow pipeline deletion,
        # block the delete.
        if application_map and not payload.delete_pipeline_records:
            blocked = []

            for screening_result_id, applications in application_map.items():
                for app in applications:
                    blocked.append({
                        "screening_result_id": screening_result_id,
                        "application_id": app.application_id,
                        "jd_id": app.jd_id,
                        "candidate_id": app.candidate_id,
                        "current_stage": app.current_stage,
                        "application_status": app.status,
                    })

            raise HTTPException(
                status_code=409,
                detail={
                    "message": (
                        "One or more candidates are already added to pipeline. "
                        "Set delete_pipeline_records=true to remove them from pipeline also."
                    ),
                    "blocked_records": blocked,
                },
            )

        deleted_application_ids = []
        deleted_screening_result_ids = []
        deleted_resume_ids = []
        skipped_resume_ids = []
        affected_candidate_ids = set()

        # -------------------------------------------------
        # 4. Delete pipeline records if allowed
        # -------------------------------------------------
        if payload.delete_pipeline_records:
            application_ids = []

            for applications in application_map.values():
                for app in applications:
                    application_ids.append(app.application_id)

            application_ids = list(set(application_ids))

            if application_ids:
                # Delete assessment records linked to applications
                # Keep this block only if you already have Assessment model.
                db.query(Assessment).filter(
                    Assessment.application_id.in_(application_ids)
                ).delete(synchronize_session=False)

                # Delete panel assignment records linked to applications
                # Keep this block only if you already have PanelAssignment model.
                db.query(PanelAssignment).filter(
                    PanelAssignment.application_id.in_(application_ids)
                ).delete(synchronize_session=False)

                                
                db.query(ApplicationStageHistory).filter(
                    ApplicationStageHistory.application_id.in_(application_ids)
                ).delete(synchronize_session=False)


                # Delete application rows
                applications_to_delete = db.query(Application).filter(
                    Application.application_id.in_(application_ids)
                ).all()

                for app in applications_to_delete:
                    deleted_application_ids.append(app.application_id)
                    db.delete(app)

                db.flush()

        # -------------------------------------------------
        # 5. Collect resume IDs before deleting screening results
        # -------------------------------------------------
        resume_ids_to_check = []
        for result in results:
            affected_candidate_ids.add(result.candidate_id)

            if result.resume_id:
                resume_ids_to_check.append(result.resume_id)

        resume_ids_to_check = list(set(resume_ids_to_check))

        # -------------------------------------------------
        # 6. Delete screening results
        # -------------------------------------------------
        for result in results:
            deleted_screening_result_ids.append(result.screening_result_id)
            db.delete(result)

        db.flush()

        # -------------------------------------------------
        # 7. Delete resumes only if safe
        # -------------------------------------------------
        if payload.delete_resume_records and resume_ids_to_check:
            for resume_id in resume_ids_to_check:
                still_used = db.query(ScreeningResult).filter(
                    ScreeningResult.resume_id == resume_id
                ).first()

                if still_used:
                    skipped_resume_ids.append(resume_id)
                    continue

                resume = db.query(Resume).filter(
                    Resume.resume_id == resume_id
                ).first()

                if resume:
                    deleted_resume_ids.append(resume.resume_id)

                    # Optional:
                    # If you have storage delete function, call it here.
                    # delete_file_from_storage(settings, resume.s3_key)

                    db.delete(resume)

            db.flush()

        # -------------------------------------------------
        # 8. Recalculate latest resume flag for affected candidates
        # -------------------------------------------------
        for candidate_id in affected_candidate_ids:
            db.query(Resume).filter(
                Resume.candidate_id == candidate_id
            ).update({"is_latest": False})

            latest_resume = db.query(Resume).filter(
                Resume.candidate_id == candidate_id
            ).order_by(Resume.resume_id.desc()).first()

            if latest_resume:
                latest_resume.is_latest = True

        db.commit()

        return {
            "message": "Screening results deleted successfully",
            "deleted_screening_result_ids": deleted_screening_result_ids,
            "deleted_application_ids": deleted_application_ids,
            "deleted_resume_ids": deleted_resume_ids,
            "skipped_resume_ids": skipped_resume_ids,
            "delete_pipeline_records": payload.delete_pipeline_records,
            "delete_resume_records": payload.delete_resume_records,
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        logger.exception("Failed to delete screening results")
        raise HTTPException(
            status_code=500,
            detail="Failed to delete screening results",
        )
    

@router.get("/screening/weights/jd_id={jd_id}")
def get_screening_weights(
    jd_id: int,
    current_user: CurrentUser = Depends(require_any_role),
    db: Session = Depends(get_db),
):
    try:
        settings = get_settings()

        jd = (
            db.query(JobDescription)
            .filter(JobDescription.jd_id == jd_id)
            .first()
        )

        if not jd:
            raise HTTPException(
                status_code=404,
                detail="JD not found",
            )

        weights, source = get_effective_screening_weights(
            db=db,
            settings=settings,
            jd_id=jd_id,
        )

        return {
            "jd_id": jd_id,
            "req_id": jd.req_id,
            "source": source,
            "weights": weights,
        }

    except HTTPException:
        # Re-raise known API errors like 404 JD not found
        raise

    except SQLAlchemyError:
        logger.exception(
            "Database error while fetching screening weights for jd_id=%s",
            jd_id,
        )

        raise HTTPException(
            status_code=500,
            detail="Database error while fetching screening weights.",
        )

    except Exception:
        logger.exception(
            "Unexpected error while fetching screening weights for jd_id=%s",
            jd_id,
        )

        raise HTTPException(
            status_code=500,
            detail="Unexpected error while fetching screening weights.",
        )

@router.post("/screening/weights/save")
def save_screening_weights(
    payload: ScreeningWeightsSaveRequest,
    current_user: CurrentUser = Depends(require_any_role),
    db: Session = Depends(get_db),
):
    try:
        jd = db.query(JobDescription).filter(
            JobDescription.jd_id == payload.jd_id
        ).first()

        if not jd:
            raise HTTPException(status_code=404, detail="JD not found")

        normalized_weights = validate_screening_weights(payload.to_weights_dict())

        config = db.query(ScreeningWeightConfig).filter(
            ScreeningWeightConfig.jd_id == payload.jd_id
        ).first()

        if config:
            config.weights = normalized_weights
            config.updated_by = payload.changed_by
            config.is_active = True
        else:
            config = ScreeningWeightConfig(
                jd_id=payload.jd_id,
                weights=normalized_weights,
                created_by=payload.changed_by,
                updated_by=payload.changed_by,
                is_active=True,
            )
            db.add(config)

        db.commit()
        db.refresh(config)

        return {
            "message": "Screening weights saved successfully",
            "jd_id": payload.jd_id,
            "req_id": jd.req_id,
            "source": "custom",
            "weights": normalized_weights,
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        logger.exception("Failed to save screening weights")
        raise HTTPException(
            status_code=500,
            detail="Failed to save screening weights"
        )


@router.post("/screening/weights/reset")
def reset_screening_weights(
    payload: ScreeningWeightsResetRequest,
    current_user: CurrentUser = Depends(require_any_role),
    db: Session = Depends(get_db),
):
    try:
        settings = get_settings()

        jd = db.query(JobDescription).filter(
            JobDescription.jd_id == payload.jd_id
        ).first()

        if not jd:
            raise HTTPException(status_code=404, detail="JD not found")

        config = db.query(ScreeningWeightConfig).filter(
            ScreeningWeightConfig.jd_id == payload.jd_id
        ).first()

        if config:
            config.is_active = False
            config.updated_by = payload.changed_by

        db.commit()

        default_weights = get_default_screening_weights(settings)

        return {
            "message": "Screening weights reset to default successfully",
            "jd_id": payload.jd_id,
            "req_id": jd.req_id,
            "source": "default",
            "weights": default_weights,
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        logger.exception("Failed to reset screening weights")
        raise HTTPException(
            status_code=500,
            detail="Failed to reset screening weights"
        )

APPLICATION_STAGE_DELETED = "DELETED"
APPLICATION_STATUS_REMOVED = "REMOVED_FROM_PIPELINE"
ASSESSMENT_STATUS_CANCELLED = "cancelled"


def soft_remove_applications_from_pipeline(
    db: Session,
    application_ids: list[int],
    changed_by: str | None = None,
    remarks: str | None = None,
    clear_screening_result_ids: list[int] | None = None,
    clear_resume_ids: list[int] | None = None,
) -> dict:
    application_ids = list(set(application_ids or []))
    clear_screening_result_ids = set(clear_screening_result_ids or [])
    clear_resume_ids = set(clear_resume_ids or [])

    removed_application_ids = []
    created_stage_history_ids = []
    cancelled_assessment_ids = []
    updated_panel_assignment_ids = []
    deleted_panel_assignment_ids = []

    if not application_ids:
        return {
            "removed_application_ids": removed_application_ids,
            "created_stage_history_ids": created_stage_history_ids,
            "cancelled_assessment_ids": cancelled_assessment_ids,
            "updated_panel_assignment_ids": updated_panel_assignment_ids,
            "deleted_panel_assignment_ids": deleted_panel_assignment_ids,
        }

    applications = db.query(Application).filter(
        Application.application_id.in_(application_ids)
    ).all()

    for app in applications:
        old_stage = app.current_stage

        already_removed = (
            app.current_stage == APPLICATION_STAGE_DELETED
            or app.status == APPLICATION_STATUS_REMOVED
        )

        if not already_removed:
            history = ApplicationStageHistory(
                application_id=app.application_id,
                from_stage=old_stage or "UNKNOWN",
                to_stage=APPLICATION_STAGE_DELETED,
                changed_by=changed_by or "system",
                remarks=remarks or "Removed from pipeline",
            )

            # If your model has status column, this will set it safely.
            if hasattr(history, "status"):
                history.status = APPLICATION_STATUS_REMOVED

            db.add(history)
            db.flush()

            if hasattr(history, "history_id"):
                created_stage_history_ids.append(history.history_id)

        app.current_stage = APPLICATION_STAGE_DELETED
        app.status = APPLICATION_STATUS_REMOVED

        # If screening result is being deleted, clear application reference.
        if (
            hasattr(app, "latest_screening_result_id")
            and app.latest_screening_result_id in clear_screening_result_ids
        ):
            app.latest_screening_result_id = None

        # If resume is being deleted, clear application reference.
        if (
            hasattr(app, "current_resume_id")
            and app.current_resume_id in clear_resume_ids
        ):
            app.current_resume_id = None

        removed_application_ids.append(app.application_id)

    # Do not delete assessments anymore.
    # Cancel draft/in-progress assessments but preserve submitted history.
    assessments = db.query(Assessment).filter(
        Assessment.application_id.in_(application_ids)
    ).all()

    for assessment in assessments:
        if assessment.status != "submitted":
            assessment.status = ASSESSMENT_STATUS_CANCELLED

        cancelled_assessment_ids.append(assessment.assessment_id)

    # Panel assignment handling:
    # If table has status column, soft-remove. Else delete old active assignment rows.
    panel_assignments = db.query(PanelAssignment).filter(
        PanelAssignment.application_id.in_(application_ids)
    ).all()

    for panel in panel_assignments:
        panel_id = getattr(panel, "panel_assignment_id", None)

        if hasattr(panel, "status"):
            panel.status = "REMOVED"
            if panel_id is not None:
                updated_panel_assignment_ids.append(panel_id)
        else:
            if panel_id is not None:
                deleted_panel_assignment_ids.append(panel_id)
            db.delete(panel)

    db.flush()

    return {
        "removed_application_ids": removed_application_ids,
        "created_stage_history_ids": created_stage_history_ids,
        "cancelled_assessment_ids": cancelled_assessment_ids,
        "updated_panel_assignment_ids": updated_panel_assignment_ids,
        "deleted_panel_assignment_ids": deleted_panel_assignment_ids,
    }


@router.post("/screening-results/manage")
def manage_screening_results(
    payload: ScreeningResultsManageRequest,
    current_user: CurrentUser = Depends(require_any_role),
    db: Session = Depends(get_db),
):
    try:
        screening_result_ids = list(set(payload.screening_result_ids))

        results = db.query(ScreeningResult).filter(
            ScreeningResult.screening_result_id.in_(screening_result_ids)
        ).all()

        found_ids = {r.screening_result_id for r in results}
        missing_ids = [x for x in screening_result_ids if x not in found_ids]

        if missing_ids:
            raise HTTPException(
                status_code=404,
                detail={
                    "message": "Some screening results were not found",
                    "missing_screening_result_ids": missing_ids,
                },
            )

        affected_candidate_ids = set()
        application_ids = []
        resume_ids_to_check = []

        for result in results:
            affected_candidate_ids.add(result.candidate_id)

            if result.resume_id:
                resume_ids_to_check.append(result.resume_id)

            applications = db.query(Application).filter(
                Application.jd_id == result.jd_id,
                Application.candidate_id == result.candidate_id,
            ).all()

            for app in applications:
                application_ids.append(app.application_id)

        application_ids = list(set(application_ids))
        resume_ids_to_check = list(set(resume_ids_to_check))

        # -------------------------------------------------
        # CASE 1: REMOVE FROM PIPELINE ONLY
        # -------------------------------------------------
        if payload.action == ScreeningResultManageAction.REMOVE_FROM_PIPELINE:
            pipeline_result = soft_remove_applications_from_pipeline(
                db=db,
                application_ids=application_ids,
                changed_by=payload.changed_by,
                remarks="Removed from pipeline",
                clear_screening_result_ids=[],
                clear_resume_ids=[],
            )

            db.commit()

            return {
                "message": "Candidates removed from pipeline successfully",
                "action": payload.action,
                **pipeline_result,

                # Nothing deleted from score list
                "deleted_screening_result_ids": [],
                "deleted_resume_ids": [],
                "skipped_resume_ids": [],

                # Kept for old frontend compatibility
                "deleted_application_ids": [],
                "deleted_assessment_ids": [],
            }

        # -------------------------------------------------
        # CASE 2: DELETE SCREENING RESULT FROM SCORE LIST
        # -------------------------------------------------

        # If application exists, do not delete it.
        # Soft-remove pipeline journey and preserve stage history.
        pipeline_result = soft_remove_applications_from_pipeline(
            db=db,
            application_ids=application_ids,
            changed_by=payload.changed_by,
            remarks="Screening result deleted; pipeline marked as removed",
            clear_screening_result_ids=screening_result_ids,
            clear_resume_ids=resume_ids_to_check if payload.delete_resume_records else [],
        )

        # -------------------------------------------------
        # Delete screening result rows
        # -------------------------------------------------
        deleted_screening_result_ids = []

        for result in results:
            deleted_screening_result_ids.append(result.screening_result_id)
            db.delete(result)

        db.flush()

        # -------------------------------------------------
        # Delete resumes only if safe
        # -------------------------------------------------
        deleted_resume_ids = []
        skipped_resume_ids = []

        if payload.delete_resume_records:
            for resume_id in resume_ids_to_check:
                still_used_by_screening = db.query(ScreeningResult).filter(
                    ScreeningResult.resume_id == resume_id
                ).first()

                if still_used_by_screening:
                    skipped_resume_ids.append(resume_id)
                    continue

                still_used_by_application = None

                if hasattr(Application, "current_resume_id"):
                    still_used_by_application = db.query(Application).filter(
                        Application.current_resume_id == resume_id
                    ).first()

                if still_used_by_application:
                    skipped_resume_ids.append(resume_id)
                    continue

                resume = db.query(Resume).filter(
                    Resume.resume_id == resume_id
                ).first()

                if resume:
                    deleted_resume_ids.append(resume.resume_id)

                    # Optional storage cleanup:
                    # delete_file_from_storage(settings, resume.s3_key)

                    db.delete(resume)

            db.flush()

        # -------------------------------------------------
        # Recalculate latest resume flag
        # -------------------------------------------------
        for candidate_id in affected_candidate_ids:
            db.query(Resume).filter(
                Resume.candidate_id == candidate_id
            ).update(
                {"is_latest": False},
                synchronize_session=False,
            )

            latest_resume = db.query(Resume).filter(
                Resume.candidate_id == candidate_id
            ).order_by(
                Resume.resume_id.desc()
            ).first()

            if latest_resume:
                latest_resume.is_latest = True

        db.commit()

        return {
            "message": "Screening results deleted successfully",
            "action": payload.action,
            **pipeline_result,
            "deleted_screening_result_ids": deleted_screening_result_ids,
            "deleted_resume_ids": deleted_resume_ids,
            "skipped_resume_ids": skipped_resume_ids,

            # Kept for old frontend compatibility
            "deleted_application_ids": [],
            "deleted_assessment_ids": [],
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception:
        db.rollback()
        logger.exception("Failed to manage screening results")
        raise HTTPException(
            status_code=500,
            detail="Failed to manage screening results",
        )
