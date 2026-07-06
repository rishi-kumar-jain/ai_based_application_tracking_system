
from datetime import date, datetime
from decimal import Decimal
import json

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.application import Application
from app.models.assessments import Assessment
from app.models.job_description import JobDescription
from app.services.llm_service import _azure_client, _strip_json_fence


CEO_ASSESSMENT_AI_SUMMARY_PROMPT = """
You are an AI assessment summary engine for an enterprise hiring system.

This summary is for the CEO / final leadership round.

Return ONLY valid JSON.
No markdown.
No explanation.
No extra text.

You will receive:
- JD context
- Candidate resume context
- CEO assessment stage code
- Previous assessment rounds context

Important rules:
- The CEO round has no questions, no transcript, and no interviewer comments.
- You must judge the candidate only from previous assessment rounds.
- Do not invent facts.
- Use previous interviewer scores, comments, recommendations, concerns, and AI summaries as the source of truth.
- Questions marked NA in previous rounds must be ignored.
- If previous assessment evidence is insufficient, say so clearly.
- If previous rounds show conflicting signals, mention the conflict clearly.
- You must generate the CEO round overall score out of 10.
- The score must be based only on supplied previous assessment evidence.
- If evidence is insufficient to score confidently, return null for overall_score_out_of_10.

CEO round judgment criteria:
- Role fit based on JD requirements
- Consistency of performance across previous rounds
- Strength of technical / functional evidence
- Communication and ownership signals
- Risk areas raised by interviewers
- Whether concerns have been resolved or remain open
- Overall hiring confidence

Scoring guidance:
- 9-10: Strong hire signal with consistent evidence across previous rounds and no major unresolved concerns.
- 7-8: Positive hire signal with manageable concerns.
- 5-6: Mixed signal with meaningful unresolved concerns.
- 3-4: Weak hire signal with significant concerns.
- 0-2: Strong no-hire signal.
- null: Not enough evidence to judge.

For this CEO round:
- question_level_summary should usually be an empty list because there are no CEO questions.
- transcript_summary must be null because there is no CEO transcript.
- interviewer_feedback_summary should summarize the previous interviewers' feedback collectively.
- section_level_summary may summarize previous rounds by assessment stage or competency area.

STRICT REQUIREMENT FOR section_level_summary:

- section_type MUST be EXACTLY the "stage_code" from previous_assessments_context.
- DO NOT rename, infer, group, or normalize stage names.
- DO NOT use labels like "Technical Assessment", "HR Round", etc.
- Use stage_code exactly as provided in input.
- Each section must directly map to one stage_code from previous_assessments_context.

Return JSON in this exact format:

{
  "overall_score_out_of_10": number | null,
  "candidate_stage_summary": "string",
  "section_level_summary": [
    {
      "section_type": "string",
      "summary": "string",
      "strengths": ["string"],
      "risks": ["string"]
    }
  ],
  "question_level_summary": [
    {
      "section_type": "string",
      "item_id": "string | null",
      "question": "string",
      "score_out_of_10": number | null,
      "is_na": boolean,
      "interviewer_comment": "string | null",
      "performance_summary": "string",
      "transcript_evidence": "string | null"
    }
  ],
  "overall_strengths": ["string"],
  "overall_risks": ["string"],
  "interviewer_feedback_summary": "string",
  "transcript_summary": "string | null",
  "recommendation_alignment": "strongly_aligned | aligned | partially_aligned | not_enough_evidence",
  "ai_recommendation_signal": "recommended | hold | not recommended | insufficient_evidence",
  "final_ai_summary": "string"
}
""".strip()



def json_safe(value):
    """
    Makes SQLAlchemy/DB values JSON serializable.
    Handles Decimal, datetime, date, dict, and list recursively.
    """
    if isinstance(value, Decimal):
        return float(value)

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, dict):
        return {key: json_safe(val) for key, val in value.items()}

    if isinstance(value, list):
        return [json_safe(item) for item in value]

    return value


def normalize_ceo_ai_summary_response(parsed: dict,  previous_asssessment_stage_codes: list[str]) -> dict:
    """
    Ensures CEO AI summary always follows the required response structure.
    """


    section_level_summary = parsed.get("section_level_summary") or []

    # Build a normalized lookup (lower -> actual)
    stage_lookup = {
        stage.strip().lower(): stage for stage in previous_asssessment_stage_codes
    }

    fixed_sections = []

    for section in section_level_summary:
        raw_type = (section.get("section_type") or "").strip().lower()

        # Replace with correct stage_code if we can match loosely
        mapped_stage = stage_lookup.get(raw_type)

        if not mapped_stage:
            # fallback: assign sequentially (preserves order)
            mapped_stage = previous_asssessment_stage_codes[
                len(fixed_sections) % len(previous_asssessment_stage_codes)
            ]

        fixed_sections.append({
            "section_type": mapped_stage,
            "summary": section.get("summary", ""),
            "strengths": section.get("strengths") or [],
            "risks": section.get("risks") or [],
        })


    return {
        "overall_score_out_of_10": parsed.get("overall_score_out_of_10"),
        "candidate_stage_summary": parsed.get("candidate_stage_summary") or "",
        "section_level_summary": parsed.get("section_level_summary") or [],
        "question_level_summary": parsed.get("question_level_summary") or [],
        "overall_strengths": parsed.get("overall_strengths") or [],
        "overall_risks": parsed.get("overall_risks") or [],
        "interviewer_feedback_summary": parsed.get("interviewer_feedback_summary") or "",
        "transcript_summary": parsed.get("transcript_summary"),
        "recommendation_alignment": parsed.get(
            "recommendation_alignment",
            "not_enough_evidence",
        ),
        "ai_recommendation_signal": parsed.get(
            "ai_recommendation_signal",
            "insufficient_evidence",
        ),
        "final_ai_summary": parsed.get("final_ai_summary") or "",
    }


def build_jd_context(jd: JobDescription) -> dict:
    """
    Build JD context for LLM.
    Adjust fields according to your actual JobDescription model.
    """
    return json_safe(
        {
            "jd_id": getattr(jd, "jd_id", None),
            "job_title": getattr(jd, "job_title", None),
            "title": getattr(jd, "title", None),
            "description": getattr(jd, "description", None),
            "responsibilities": getattr(jd, "responsibilities", None),
            "requirements": getattr(jd, "requirements", None),
            "skills": getattr(jd, "skills", None),
            "experience": getattr(jd, "experience", None),
            "stages": getattr(jd, "stages", None),
        }
    )


def build_resume_context(application: Application) -> dict:
    """
    Build resume/candidate context for LLM.
    Adjust this according to your actual Application/Candidate/Resume schema.
    """
    return json_safe(
        {
            "application_id": getattr(application, "application_id", None),
            "candidate_id": getattr(application, "candidate_id", None),
            "candidate_name": getattr(application, "candidate_name", None),
            "resume_context": getattr(application, "resume_context", None),
            "resume_text": getattr(application, "resume_text", None),
            "parsed_resume": getattr(application, "parsed_resume", None),
        }
    )


def build_previous_assessments_context(
    db: Session,
    application_id: int,
    ceo_stage_code: str,
) -> list :

    """
    Fetches all previous assessment rounds for the application,
    excluding the CEO stage itself.
    """
    ceo_stage_code_normalized = ceo_stage_code.strip().lower()

    stmt = (
        select(
            Assessment.assessment_id,
            Assessment.stage_code,
            Assessment.stage_level,
            Assessment.assessment_sections,
            Assessment.transcript_text,
            Assessment.overall_score,
            Assessment.summary_feedback,
            Assessment.final_recommendation,
            Assessment.ai_assessment_summary,
            Assessment.status,
            Assessment.discrepency_reason,
            Assessment.areas_of_concern,
            Assessment.areas_to_probe_in_next_round,
            Assessment.problem_statements,
            Assessment.assessment_taken_by,
            Assessment.created_at,
            Assessment.updated_at,
        )
        .where(
            Assessment.application_id == application_id,
            Assessment.stage_code.isnot(None),
            func.lower(func.trim(Assessment.stage_code)) != ceo_stage_code_normalized,
        )
        .order_by(
            Assessment.stage_level.asc().nullslast(),
            Assessment.created_at.asc(),
        )
    )

    rows = db.execute(stmt).mappings().all()

    previous_assessments = []

    for row in rows:
        previous_assessments.append(
            json_safe(
                {
                    "assessment_id": row["assessment_id"],
                    "stage_code": row["stage_code"],
                    "stage_level": row["stage_level"],
                    "overall_score": row["overall_score"],
                    "summary_feedback": row["summary_feedback"],
                    "final_recommendation": row["final_recommendation"],
                    "areas_of_concern": row["areas_of_concern"],
                    "areas_to_probe_in_next_round": row[
                        "areas_to_probe_in_next_round"
                    ],
                    "discrepency_reason": row["discrepency_reason"],
                    "status": row["status"],
                    "assessment_taken_by": row["assessment_taken_by"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "problem_statements": row["problem_statements"] or {},
                    "assessment_sections": row["assessment_sections"] or {},
                    "ai_assessment_summary": row["ai_assessment_summary"] or {},
                    "transcript_text": row["transcript_text"],
                }
            )
        )

    return previous_assessments

def generate_ceo_assessment_ai_summary_with_llm(
    settings: Settings,
    jd_context: dict,
    resume_context: dict,
    ceo_stage_code: str,
    previous_assessments_context: list[dict],
) -> dict:
    """
    Generates CEO round AI summary based only on previous assessment rounds.
    CEO round itself has no questions, no transcript, and no interviewer feedback.
    """

    if settings.llm_provider == "mock":
        return {
            "overall_score_out_of_10": None,
            "candidate_stage_summary": "Mock CEO round summary based on previous assessments.",
            "section_level_summary": [],
            "question_level_summary": [],
            "overall_strengths": [],
            "overall_risks": [],
            "interviewer_feedback_summary": "",
            "transcript_summary": None,
            "recommendation_alignment": "not_enough_evidence",
            "ai_recommendation_signal": "insufficient_evidence",
            "final_ai_summary": "Mock final CEO AI summary.",
        }

    if settings.llm_provider != "azure":
        raise HTTPException(
            status_code=500,
            detail="Unsupported LLM provider",
        )

    client = _azure_client(settings.azure_openai_api_key,settings.azure_openai_api_version,settings.azure_openai_endpoint)

    user_prompt = f"""
CEO Stage Code:
{ceo_stage_code}

JD Context:
{json.dumps(json_safe(jd_context or {}), ensure_ascii=False, indent=2)}

Candidate Resume Context:
{json.dumps(json_safe(resume_context or {}), ensure_ascii=False, indent=2)}

Previous Assessment Rounds Context:
{json.dumps(json_safe(previous_assessments_context or []), ensure_ascii=False, indent=2)}

CEO Round Note:
This CEO round has no direct questions, no transcript, and no CEO interviewer feedback.
Generate the CEO round AI summary only from the previous assessment rounds.
""".strip()

    response = client.chat.completions.create(
        model=settings.azure_openai_deployment,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": CEO_ASSESSMENT_AI_SUMMARY_PROMPT,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
    )

    content = response.choices[0].message.content or "{}"

    try:
        parsed = json.loads(_strip_json_fence(content))
    except Exception:
        parsed = {}

    if not isinstance(parsed, dict):
        parsed = {}

    
    stage_codes = [
        item["stage_code"]
        for item in previous_assessments_context
        if item.get("stage_code")
    ]

    return normalize_ceo_ai_summary_response(parsed , stage_codes)