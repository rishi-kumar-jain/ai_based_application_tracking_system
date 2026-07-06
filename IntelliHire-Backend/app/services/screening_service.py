from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.core.config import Settings
from app.models.screeningweightconfigs import ScreeningWeightConfig
from app.services.llm_service import _safe_dict, _safe_list_of_strings, _safe_score_0_100

# def build_screening_result(
#     settings: Settings,
#     llm_result: dict,
#     jd_mandatory_skills: list[str],
#     screening_weights: dict[str, float] | None = None,
# ) -> dict:
#     weights = screening_weights or settings.screening_weights
#     weights = validate_screening_weights(weights)

#     other_scores = llm_result.get("other_scores", {})
#     other_score = 0.0

#     for key, weight in weights.items():
#         score = float(other_scores.get(key, 0) or 0)
#         other_score += score * weight / 100

#     matched_skills = llm_result.get("matched_skills", [])
#     partial_skills = llm_result.get("partial_skills", [])
#     missing_skills = llm_result.get("missing_skills", [])

#     skills_matched = len(matched_skills)
#     skills_partial = len(partial_skills)            # optional count
#     total_skills = len(jd_mandatory_skills or [])

#     skill_score = float(llm_result.get("skill_score", 0) or 0)

#     overall_score = round((skill_score + other_score) / 2, 2)

#     thresholds = settings.status_thresholds
#     if overall_score >= thresholds["high"]:
#         status = "High Match"
#     elif overall_score >= thresholds["medium"]:
#         status = "Medium Match"
#     else:
#         status = "Low Match"

#     return {
#         "skill_score": round(skill_score, 2),
#         "other_score": round(other_score, 2),
#         "overall_score": overall_score,
#         "skills_matched": skills_matched,
#         "skills_partial": skills_partial,          # NEW: count of partial skills
#         "total_skills": total_skills,
#         "matched_skills": matched_skills,
#         "partial_skills": partial_skills,          # NEW: array of exact JD skills
#         "missing_skills": missing_skills,
#         "match_status": status,
#         "other_score_breakdown": other_scores,
#         "screening_weights_used": weights,
#         "full_name": llm_result.get("full_name"),
#         "email": llm_result.get("email"),
#         "phone": llm_result.get("phone"),
#         "extracted_skills": llm_result.get("extracted_skills", []),
#     }


def build_screening_result(
    settings: Settings,
    llm_result: dict,
    jd_mandatory_skills: list[str],
    screening_weights: dict[str, float] | None = None,
) -> dict:
    weights = screening_weights or settings.screening_weights
    weights = validate_screening_weights(weights)

    other_scores = llm_result.get("other_scores", {}) or {}
    other_score_justifications = llm_result.get("other_score_justifications", {}) or {}

    # Only keep weights greater than 0
    active_weights = {
        key: float(weight or 0)
        for key, weight in weights.items()
        if float(weight or 0) > 0
    }

    total_active_weight = sum(active_weights.values())

    other_score = 0.0
    filtered_other_score_breakdown = {}
    normalized_other_score_justifications = {}
    screening_weights_used = {}

    if total_active_weight > 0:
        for key, raw_weight in active_weights.items():
            effective_weight = raw_weight / total_active_weight * 100

            score = float(other_scores.get(key, 0) or 0)
            weighted_score = score * effective_weight / 100

            other_score += weighted_score

            filtered_other_score_breakdown[key] = round(score, 2)

            screening_weights_used[key] = round(effective_weight, 2)

            normalized_other_score_justifications[key] = {
                "score": round(score, 2),
                "configured_weight": round(raw_weight, 2),
                "effective_weight": round(effective_weight, 2),
                "weighted_score": round(weighted_score, 2),
                "justification": other_score_justifications.get(
                    key,
                    "No justification provided by LLM."
                ),
            }

    skill_evaluations = llm_result.get("skill_evaluations", []) or []

    matched_skills = [
        item.get("jd_skill")
        for item in skill_evaluations
        if item.get("match_status") == "matched"
    ]

    partial_skills = [
        item.get("jd_skill")
        for item in skill_evaluations
        if item.get("match_status") == "partial"
    ]

    missing_skills = [
        item.get("jd_skill")
        for item in skill_evaluations
        if item.get("match_status") == "missing"
    ]

    skills_matched = len(matched_skills)
    skills_partial = len(partial_skills)
    total_skills = len(jd_mandatory_skills or [])

    if skill_evaluations:
        skill_score = sum(
            float(item.get("match_score", 0) or 0)
            for item in skill_evaluations
        ) / len(skill_evaluations)
    else:
        skill_score = 0.0

    overall_score = round((skill_score + other_score) / 2, 2)

    thresholds = settings.status_thresholds

    if overall_score >= thresholds["high"]:
        status = "High Match"
    elif overall_score >= thresholds["medium"]:
        status = "Medium Match"
    else:
        status = "Low Match"

    return {
        "skill_score": round(skill_score, 2),
        "other_score": round(other_score, 2),
        "overall_score": overall_score,

        "skills_matched": skills_matched,
        "skills_partial": skills_partial,
        "total_skills": total_skills,

        "matched_skills": matched_skills,
        "partial_skills": partial_skills,
        "missing_skills": missing_skills,

        "match_status": status,

        # Only active weights are included here
        "other_score_breakdown": filtered_other_score_breakdown,
        "other_score_justifications": normalized_other_score_justifications,
        "screening_weights_used": screening_weights_used,

        "full_name": llm_result.get("full_name"),
        "email": llm_result.get("email"),
        "phone": llm_result.get("phone"),
        "extracted_skills": llm_result.get("extracted_skills", []),
        "skill_evaluations": skill_evaluations,
    }


SCREENING_WEIGHT_KEYS = {
    "experience",
    "responsibilities",
    "projects",
    "location",
    "certification",
    "education",
}


def validate_screening_weights(weights: dict) -> dict[str, float]:
    if not isinstance(weights, dict):
        raise HTTPException(
            status_code=400,
            detail="weights must be a valid object"
        )

    incoming_keys = set(weights.keys())

    missing = SCREENING_WEIGHT_KEYS - incoming_keys
    extra = incoming_keys - SCREENING_WEIGHT_KEYS

    if missing:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Missing screening weight keys",
                "missing_keys": list(missing),
            },
        )

    if extra:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Invalid screening weight keys",
                "extra_keys": list(extra),
            },
        )

    normalized = {}

    for key in SCREENING_WEIGHT_KEYS:
        try:
            value = float(weights[key])
        except Exception:
            raise HTTPException(
                status_code=400,
                detail=f"Weight for {key} must be numeric"
            )

        if value < 0 or value > 100:
            raise HTTPException(
                status_code=400,
                detail=f"Weight for {key} must be between 0 and 100"
            )

        normalized[key] = round(value, 2)

    total = round(sum(normalized.values()), 2)

    if abs(total - 100.0) > 0.01:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Screening weights must total 100",
                "current_total": total,
            },
        )

    return normalized


def get_default_screening_weights(settings: Settings) -> dict[str, float]:
    return validate_screening_weights(settings.screening_weights)

def get_effective_screening_weights(
    db: Session,
    settings: Settings,
    jd_id: int,
) -> tuple[dict[str, float], str]:
    config = db.query(ScreeningWeightConfig).filter(
        ScreeningWeightConfig.jd_id == jd_id,
        ScreeningWeightConfig.is_active == True
    ).first()

    if config:
        return validate_screening_weights(config.weights), "custom"

    return get_default_screening_weights(settings), "default"