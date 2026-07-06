
from app.core.logger import get_logger
logger = get_logger("pipeline_service")
from app.models.job_description import JobDescription
import re
from sqlalchemy.orm import Session

# def ensure_default_jd_stages(db: Session, jd: JobDescription) -> list[dict]:
#     normalized = build_canonical_stages(jd.stages)

#     if jd.stages != normalized:
#         jd.stages = normalized
#         db.flush()

#     return normalized




# def normalize_stage_name(name: str | None) -> str:
#     return re.sub(r"\s+", " ", (name or "").strip()).upper()





# def build_canonical_stages(raw_stages: list | None) -> list[dict]:
#     """
#     Ensures:
#     - RECRUITER always exists and is first
#     - HR always exists and is last
#     - custom stages remain in between
#     - stage numbers are strictly re-numbered
#     - supports old format (list of strings) and new format (list of dicts)
#     """
#     recruiter_info = None
#     hr_info = None
#     middle = []
#     seen = set()

#     raw_stages = raw_stages or []

#     for item in raw_stages:
#         if isinstance(item, str):
#             stage_name = normalize_stage_name(item)
#             stage_information = None
#         elif isinstance(item, dict):
#             stage_name = normalize_stage_name(item.get("stage_name"))
#             stage_information = item.get("stage_information")
#         else:
#             continue

#         if not stage_name:
#             continue

#         if stage_name in seen:
#             continue
#         seen.add(stage_name)

#         if stage_name == "RECRUITER":
#             recruiter_info = stage_information
#             continue

#         if stage_name == "HR":
#             hr_info = stage_information
#             continue

#         middle.append({
#             "stage_name": stage_name,
#             "stage_information": stage_information
#         })

#     final_stages = [
#         {
#             "stage_number": 1,
#             "stage_name": "RECRUITER",
#             "stage_information": recruiter_info
#         }
#     ]

#     for item in middle:
#         final_stages.append(
#             {
#                 "stage_number": len(final_stages) + 1,
#                 "stage_name": item["stage_name"],
#                 "stage_information": item["stage_information"]
#             }
#         )

#     final_stages.append(
#         {
#             "stage_number": len(final_stages) + 1,
#             "stage_name": "HR",
#             "stage_information": hr_info
#         }
#     )

#     return final_stages


def ensure_default_pipeline_stages_for_jd(db: Session, jd: JobDescription) -> list[dict]:
    """
    If JD has no stages, initialize with:
    1. RECRUITER
    2. HR
    """
    logger.info("jd_stages value after ensure: %s", jd.stages)
    if not jd.stages:
        jd.stages = [
            {
                "stage_number": 1,
                "stage_name": "RECRUITER",
                "stage_information": None,
            },
            {
                "stage_number": 2,
                "stage_name": "HR",
                "stage_information": None,
            },
        ]
        db.flush()   # persist before further usage

    return jd.stages