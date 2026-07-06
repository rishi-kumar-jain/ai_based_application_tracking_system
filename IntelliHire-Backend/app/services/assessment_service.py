def _extract_questions_from_assessment_items(assessment_items) -> list[str]:
    questions: list[str] = []

    for item in assessment_items or []:
        if not isinstance(item, dict):
            continue

        question = str(item.get("question") or "").strip()
        if question:
            questions.append(question)

    return questions
# Final Interviewer Recommendation:
# {final_recommendation or ""}


import re
import uuid
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from fastapi import HTTPException

from app.services.email_service import send_email
from app.services.llm_service import _azure_client, _strip_json_fence


SECTION_LABELS = {
    "GENERAL": "General Screening",
    "TECH": "Technical Assessment",
    "PROBLEM_SOLVING": "Problem Solving Assessment",
    "BEHAVIORAL": "Behavioral Assessment",
    "AI_NATIVE_TRAITS": "Ai native questions",
    "HR": "Hr Assessment"
}

VALID_FINAL_RECOMMENDATIONS = {"HIRE", "HOLD", "REJECT"}


def normalize_stage_code(stage_code: str) -> str:
    if not stage_code:
        raise HTTPException(status_code=400, detail="stage_code is required")
    return stage_code.strip().upper()


def normalize_section_type(section_type: str) -> str:
    if not section_type:
        raise HTTPException(status_code=400, detail="section_type is required")
    return section_type.strip().upper()

import re
from fastapi import HTTPException


def get_stage_spec(stage_code: str) -> dict:
    stage_code = normalize_stage_code(stage_code)

    if stage_code == "RECRUITER":
        return {
            "stage_code": "RECRUITER",
            "stage_level": 0,
            "sections": ["GENERAL", "TECH", "AI_NATIVE_TRAITS"],
        }

    if stage_code == "HR":
        return {
            "stage_code": "HR",
            "stage_level": 1,
            "sections": ["SINGLE"],
        }

    # Matches: TECHNICAL_ROUND_2, TECHNICAL_ROUND_3, ...
    technical_match = re.fullmatch(r"TECHNICAL_ROUND_([2-9][0-9]*)", stage_code)

    if technical_match:
        round_number = int(technical_match.group(1))

        if round_number >= 2:
            return {
                "stage_code": "TECHNICAL_ROUND_2",
                "stage_level": 1,
                "sections": ["SINGLE"],
            }

        raise HTTPException(
            status_code=400,
            detail="Technical round must be Technical_Round_2 or higher.",
        )

    # Matches: LEADERSHIP_ROUND_1, LEADERSHIP_ROUND_2, ...
    leadership_match = re.fullmatch(r"LEADERSHIP_ROUND_([1-9][0-9]*)", stage_code)

    if leadership_match:
        round_number = int(leadership_match.group(1))

        if round_number >= 1:
            return {
                "stage_code": "LEADERSHIP_ROUND_1",
                "stage_level": 1,
                "sections": ["SINGLE"],
            }

    # Default fallback for other valid stage names
    return {
        "stage_code": stage_code,
        "stage_level": 1,
        "sections": ["SINGLE"],
    }


def validate_section_for_stage(stage_code: str, section_type: str) -> None:
    spec = get_stage_spec(stage_code)
    section_type = normalize_section_type(section_type)

    if section_type not in spec["sections"]:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Invalid section_type for this stage_code",
                "stage_code": spec["stage_code"],
                "allowed_sections": spec["sections"],
            },
        )


def build_empty_assessment_sections(stage_code: str) -> dict:
    spec = get_stage_spec(stage_code)


# {
#  "stage_code": stage_code,
#  "stage_level": 1, #
#  "sections": ["SINGLE"],
#     }
    sections = {}

    for section_type in spec["sections"]:
        sections[section_type] = {
            "section_type": section_type,
            "section_label": SECTION_LABELS.get(section_type, section_type),
            "items": [],
            "section_summary_feedback": None,
        }

    return sections


from app.core.config import Settings
from app.models.assessments import Assessment, AssessmentQuestionBank
from sqlalchemy import or_
from sqlalchemy.orm import Session


def get_question_bank_section_types(
    stage_code: str,
    target_section_type: str,
) -> list[str]:
    stage_code = normalize_stage_code(stage_code)
    target_section_type = normalize_section_type(target_section_type)

    # if stage_code == "RECRUITER" and target_section_type == "GENERAL":
    #     return ["SCREENING"]
    
    
    # if stage_code == "RECRUITER" and target_section_type == "GENERAL":
    #     return ["SCREENING", "AI_NATIVE_TRAITS"]


    
    if stage_code == "RECRUITER" and target_section_type == "GENERAL":
        return ["SCREENING"]  # ✅ only screening goes into GENERAL

    if stage_code == "RECRUITER" and target_section_type == "AI_NATIVE_TRAITS":
        return ["AI_NATIVE_TRAITS"]  # ✅ traits go into their own section

    if stage_code == "HR":
        return ["HR"]
    
    # if re.fullmatch(r"L[1-9][0-9]*", stage_code) and target_section_type == "BEHAVIORAL":
    #     return ["SCREENING"]

    return []   #"RECRUITER"	"AI_NATIVE_TRAITS"



def fetch_fixed_questions_for_section(
    db: Session,
    stage_code: str,
    target_section_type: str,
) -> list[AssessmentQuestionBank]:
    return (
        db.query(AssessmentQuestionBank)
        .filter(
            AssessmentQuestionBank.stage_code == normalize_stage_code(stage_code),
            AssessmentQuestionBank.section_type == normalize_section_type(target_section_type),
            AssessmentQuestionBank.is_active.is_(True),
        )
        .order_by(
            AssessmentQuestionBank.display_order.asc(),
            AssessmentQuestionBank.question_id.asc(),
        )
        .all()
    )



def build_assessment_sections_with_fixed_questions(
    db: Session,
    stage_code: str,
) -> dict:
    stage_spec = get_stage_spec(stage_code)

    effective_stage_code = stage_spec["stage_code"]

    sections = build_empty_assessment_sections(stage_code)

    for target_section_type in sections.keys():
        fixed_questions = fetch_fixed_questions_for_section(
            db=db,
            stage_code=effective_stage_code,
            target_section_type=target_section_type,
        )

        for q in fixed_questions:
            sections[target_section_type]["items"].append({
                "item_id": str(uuid.uuid4()),
                "question_bank_id": q.question_id,
                "question": q.question,
                "expected_answer": q.expected_answer,
                "source": q.source or "fixed",
                "topic": q.topic,
                "difficulty": q.difficulty,
                "score": None,
                "is_na": False,
                "comment": None,
                "is_fixed": True,
                "answer_type": q.answer_type or "rating_text",
                "max_score": 10,
                "bank_section_type": q.section_type,

                # optional debug fields
                "requested_stage_code": normalize_stage_code(stage_code),
                "question_source_stage_code": effective_stage_code,
            })

    return sections



def ensure_assessment_stage_exists(
    db: Session,
    application_id: int,
    stage_code: str,
    # stage_level: int
) -> Assessment:
    # spec = get_stage_spec(stage_code)

    existing = db.query(Assessment).filter(
        Assessment.application_id == application_id,
        # Assessment.stage_code == spec["stage_code"],
        Assessment.stage_code == stage_code
    ).first()

    if existing:
        if existing.status == "cancelled":
            existing.status = "start"
        return existing

    assessment = Assessment(
        application_id=application_id,
        # stage_code=spec["stage_code"],
        stage_code=stage_code,
        # stage_level=spec["stage_level"],
        # stage_level=stage_level,
        assessment_sections=build_assessment_sections_with_fixed_questions(
            db=db,
            # stage_code=spec["stage_code"],
            stage_code=stage_code
        ),
        summary_feedback=None,
        final_recommendation=None,
        overall_score=None,
        status="start",
    )

    db.add(assessment)
    db.flush()

    return assessment



def _extract_questions_from_items(items: list) -> list[str]:
    questions = []

    for item in items or []:
        if not isinstance(item, dict):
            continue

        q = str(item.get("question") or "").strip()
        if q:
            questions.append(q)

    return questions


def _extract_existing_questions_from_sections(
    assessment_sections: dict,
    section_type: str | None = None,
) -> list[str]:
    questions = []

    if not isinstance(assessment_sections, dict):
        return questions

    if section_type:
        section_type = normalize_section_type(section_type)
        section = assessment_sections.get(section_type) or {}
        return _extract_questions_from_items(section.get("items", []))

    for section in assessment_sections.values():
        if isinstance(section, dict):
            questions.extend(_extract_questions_from_items(section.get("items", [])))

    return questions


def _dedupe_questions(questions: list[str]) -> list[str]:
    seen = set()
    result = []

    for q in questions or []:
        clean = str(q or "").strip()
        if not clean:
            continue

        key = " ".join(clean.lower().split())

        if key not in seen:
            result.append(clean)
            seen.add(key)

    return result




# # - Final interviewer recommendation
# # - Do not override interviewer recommendation.
ASSESSMENT_AI_SUMMARY_PROMPT = """
You are an AI assessment summary engine for an enterprise hiring system.

Return ONLY valid JSON.
No markdown.
No explanation.
No extra text.

You will receive:
- JD context
- Candidate resume context
- Assessment stage code
- Assessment sections containing questions, expected answers, scores, NA flags, and interviewer comments
- Overall interviewer feedback
- Backend calculated overall score out of 10
- Optional transcript text for the full assessment stage

Important rules:
- Do not invent facts.
- Use interviewer scores and comments as the primary truth.
- Use transcript text only if provided.
- If transcript is provided, use it as supporting evidence.

- Questions marked NA must be ignored in score interpretation.
- The backend calculated overall score out of 10 is the score of record.
- If transcript evidence is insufficient, say so clearly.

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





def generate_stage_assessment_ai_summary_with_llm(
    settings: Settings,
    jd_context: dict,
    resume_context: dict,
    stage_code: str,
    assessment_sections: dict,
    summary_feedback: str | None,
    # final_recommendation: str | None,
    overall_score_out_of_10: float | None,
    transcript_text: str | None,
) -> dict:
    if settings.llm_provider == "mock":
        return {
            "overall_score_out_of_10": overall_score_out_of_10,
            "candidate_stage_summary": "Mock stage-level candidate summary.",
            "section_level_summary": [],
            "question_level_summary": [],
            "overall_strengths": [],
            "overall_risks": [],
            "interviewer_feedback_summary": summary_feedback or "",
            "transcript_summary": None,
            "recommendation_alignment": "not_enough_evidence",
            "ai_recommendation_signal": "insufficient_evidence",
            "final_ai_summary": "Mock final AI summary.",
        }

    if settings.llm_provider != "azure":
        raise HTTPException(status_code=500, detail="Unsupported LLM provider")

    client = _azure_client(settings.azure_openai_api_key,settings.azure_openai_api_version,settings.azure_openai_endpoint)

    user_prompt = f"""
Stage Code:
{stage_code}

JD Context:
{json.dumps(jd_context, ensure_ascii=False, indent=2)}

Candidate Resume Context:
{json.dumps(resume_context, ensure_ascii=False, indent=2)}

Assessment Sections:
{json.dumps(assessment_sections or {}, ensure_ascii=False, indent=2)}

Backend Calculated Overall Score Out Of 10:
{overall_score_out_of_10}

Overall Interviewer Summary Feedback:
{summary_feedback or ""}

Transcript Text:
{transcript_text or "NO_TRANSCRIPT_PROVIDED"}
""".strip()

    response = client.chat.completions.create(
        model=settings.azure_openai_deployment,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": ASSESSMENT_AI_SUMMARY_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )

    content = response.choices[0].message.content or "{}"
    parsed = json.loads(_strip_json_fence(content))

    return parsed if isinstance(parsed, dict) else {}



def build_transcript_s3_key(application_id: int, stage_code: str) -> str:
    stage_code = normalize_stage_code(stage_code)
    return f"assessment-transcripts/application-{application_id}/{stage_code}/transcript"


def save_file_at_key(settings, content: bytes, s3_key: str, filename: str) -> dict:
    if settings.file_storage_mode == "local":
        local_path = Path(settings.local_storage_root) / s3_key
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(content)

        return {
            "s3_key": None,
            "local_path": str(local_path),
        }

    import boto3

    s3 = boto3.client("s3")

    s3.put_object(
        Bucket=settings.s3_bucket,  # rename if your setting uses different name
        Key=s3_key,
        Body=content,
    )

    return {
        "s3_key": s3_key,
        "local_path": None,
    }






from copy import deepcopy
import uuid
from fastapi import HTTPException

YES_VALUES = {"yes", "y", "true", "t", "1"}
NO_VALUES = {"no", "n", "false", "f", "0"}

def _coerce_yes_no(value):
    """
    Accepts bool, int/float (0/1), and common yes/no strings.
    Returns bool or raises HTTPException.
    """
    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)

    if isinstance(value, str):
        v = value.strip().lower()
        if v in YES_VALUES:
            return True
        if v in NO_VALUES:
            return False

    raise HTTPException(
        status_code=400,
        detail="Yes/No question requires answer as boolean (true/false) or yes/no",
    )


def validate_assessment_sections(stage_code: str, assessment_sections: dict) -> dict:
    spec = get_stage_spec(stage_code)

    if not isinstance(assessment_sections, dict):
        raise HTTPException(status_code=400, detail="assessment_sections must be an object")

    cleaned = deepcopy(assessment_sections)

    # Ensure required sections exist
    for required_section in spec["sections"]:
        if required_section not in cleaned:
            cleaned[required_section] = {
                "section_type": required_section,
                "section_label": SECTION_LABELS.get(required_section, required_section),
                "items": [],
                "section_summary_feedback": None,
            }

    for section_type, section_data in cleaned.items():
        validate_section_for_stage(stage_code, section_type)

        if not isinstance(section_data, dict):
            raise HTTPException(status_code=400, detail=f"{section_type} section must be an object")

        items = section_data.get("items", [])
        if not isinstance(items, list):
            raise HTTPException(status_code=400, detail=f"{section_type}.items must be a list")

        for item in items:
            if not isinstance(item, dict):
                raise HTTPException(status_code=400, detail=f"{section_type}.items contains invalid item")

            # Existing defaults
            item.setdefault("item_id", str(uuid.uuid4()))
            item.setdefault("source", "manual")
            item.setdefault("is_na", False)
            item.setdefault("comment", None)
            item.setdefault("score", None)
            item.setdefault("is_fixed", False)

            # New defaults for your new requirements
            item.setdefault("answer_type", "rating_text")  # or "yes_no"
            item.setdefault("answer", None)                # str for rating_text, bool for yes_no
            item.setdefault("max_score", 10)

            is_na = item.get("is_na") is True
            answer_type = (item.get("answer_type") or "rating_text").strip().lower()

            # If NA: ignore score/answer
            if is_na:
                item["score"] = None
                item["answer"] = None
                continue

            # ---- YES/NO handling ----
            if answer_type in ("yes_no", "yesno", "boolean", "bool"):
                # must have answer, compute the score
                coerced = _coerce_yes_no(item.get("score"))
                item["answer"] = coerced
                item["max_score"] = 10
                # item["score"] = 10.0 if coerced else 0.0
                item["score"] = coerced
                continue

            # ---- RATING handling (0..10) ----
            # For rating_text: we validate score (if present) and clamp to 0..10
            score = item.get("score")
            if score is not None:
                try:
                    score_float = float(score)
                except Exception:
                    raise HTTPException(status_code=400, detail="Question score must be numeric")

                if score_float < 0 or score_float > 10:
                    raise HTTPException(status_code=400, detail="Question score must be between 0 and 10")

                item["score"] = score_float

            # Always use 10-scale going forward
            item["max_score"] = 10

    return cleaned





def _to_bool(value) -> bool | None:
    """Convert common yes/no/true/false representations to bool."""
    if value is None:
        return None

    # already boolean
    if isinstance(value, bool):
        return value

    # numeric
    if isinstance(value, (int, float)):
        if value == 1:
            return True
        if value == 0:
            return False
        return None

    # string cases
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"yes", "y", "true", "t", "1"}:
            return True
        if v in {"no", "n", "false", "f", "0"}:
            return False

    return None


def _is_yes_no_question(item: dict) -> bool:
    """Detect yes/no questions by common fields."""
    qtype = (
        item.get("question_type")
        or item.get("type")
        or item.get("input_type")
        or item.get("answer_type")
    )

    if isinstance(qtype, str):
        qtype_norm = qtype.strip().lower().replace("-", "_").replace(" ", "_")
        return qtype_norm in {"yes_no", "yesno", "boolean", "bool"}

    # fallback: some systems store options like ["Yes", "No"]
    options = item.get("options") or item.get("choices")
    if isinstance(options, (list, tuple)) and len(options) == 2:
        norm = {str(o).strip().lower() for o in options}
        if norm == {"yes", "no"}:
            return True

    return False




def calculate_stage_score_out_of_10(assessment_sections: dict) -> float | None:
    total_score = 0.0
    counted_questions = 0

    for section_data in (assessment_sections or {}).values():
        if not isinstance(section_data, dict):
            continue

        items = section_data.get("items", [])

        for item in items:
            if not isinstance(item, dict):
                continue

            if item.get("is_na") is True:
                continue

            score = item.get("score")

            if score is None:
                continue

            # ✅ Handle boolean
            if isinstance(score, bool):
                score = 10.0 if score else 0.0

            # ✅ Handle string
            elif isinstance(score, str):
                val = score.strip().lower()
                if val == "yes":
                    score = 10.0
                elif val == "no":
                    score = 0.0
                else:
                    try:
                        score = float(val)
                    except ValueError:
                        continue

            # ✅ Handle numeric
            else:
                try:
                    score = float(score)
                except (TypeError, ValueError):
                    continue

            score = max(0.0, min(10.0, score))

            total_score += score
            counted_questions += 1

    if counted_questions == 0:
        return None

    return round(total_score / counted_questions, 2)






def generate_recruiter_stage_assessment_ai_summary_with_llm(
    settings: Settings,
    jd_context: dict,
    resume_context: dict,
    stage_code: str,
    assessment_sections: dict,
    summary_feedback: str | None,
    transcript_text: str | None,
) -> dict:
    if settings.llm_provider == "mock":
        return {
            
            "candidate_stage_summary": "Mock stage-level candidate summary.",
            "section_level_summary": [],
            "question_level_summary": [],
            "overall_strengths": [],
            "overall_risks": [],
            "interviewer_feedback_summary": summary_feedback or "",
            "transcript_summary": None,
            "recommendation_alignment": "not_enough_evidence",
            "ai_recommendation_signal": "insufficient_evidence",
            "final_ai_summary": "Mock final AI summary.",
        }

    if settings.llm_provider != "azure":
        raise HTTPException(status_code=500, detail="Unsupported LLM provider")

    client = _azure_client(settings.azure_openai_api_key,settings.azure_openai_api_version,settings.azure_openai_endpoint)

    user_prompt = f"""
Stage Code:
{stage_code}

JD Context:
{json.dumps(jd_context, ensure_ascii=False, indent=2)}

Candidate Resume Context:
{json.dumps(resume_context, ensure_ascii=False, indent=2)}

Assessment Sections:
{json.dumps(assessment_sections or {}, ensure_ascii=False, indent=2)}

Overall Interviewer Summary Feedback:
{summary_feedback or ""}

Transcript Text:
{transcript_text or "NO_TRANSCRIPT_PROVIDED"}
""".strip()

    response = client.chat.completions.create(
        model=settings.azure_openai_deployment,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": RECRUITER_ASSESSMENT_AI_SUMMARY_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )

    content = response.choices[0].message.content or "{}"
    parsed = json.loads(_strip_json_fence(content))

    return parsed if isinstance(parsed, dict) else {}

RECRUITER_ASSESSMENT_AI_SUMMARY_PROMPT = """
You are an AI recruiter-stage assessment summary engine for an enterprise hiring system.

Return ONLY valid JSON.
No markdown.
No explanation.
No extra text.

You will receive:
- JD context
- Candidate resume context
- Assessment stage code
- Assessment sections, if available
- Overall interviewer or recruiter feedback, if available
- Mandatory transcript text for the full recruiter stage conversation

Critical scoring rule:
- overall_score_out_of_10 must be generated entirely by AI.
- There is no backend-calculated score for this recruiter stage.
- The AI-generated score must be based primarily and directly on transcript evidence.
- JD context, resume context, assessment sections, and recruiter feedback may be used only as supporting context.
- Do not copy, infer, average, or reuse any score from assessment sections.
- Existing scores in assessment sections must be ignored completely for overall_score_out_of_10, even if they are high.
- Do not assign a high score based only on resume claims, JD match, interviewer feedback, or assessment section scores.
- If the transcript does not contain enough assessment-relevant evidence, return overall_score_out_of_10 as null.
- If the transcript contains clear negative evidence of role mismatch, return a low score instead of null.

Critical role-fit override rule:
- Role alignment is the highest-priority scoring factor.
- The target role requirements from JD context should be used only to understand what role alignment means.
- The transcript must provide evidence that the candidate has experience relevant to the target role.
- If the transcript clearly shows that the candidate's core profile is from a different domain or role than the target role, overall_score_out_of_10 MUST be between 0 and 4.
- If the transcript shows that the candidate lacks the primary skills required for the target role, overall_score_out_of_10 MUST be between 0 and 4.
- Strong communication, confidence, general work experience, testing experience, automation experience, willingness to relocate, shift flexibility, or positive attitude MUST NOT raise the score above 4 when core role alignment is missing.
- Domain mismatch overrides all positive secondary signals.
- If the candidate is clearly not aligned to the target role based on transcript evidence, ai_recommendation_signal MUST be "reject".

Transcript rule:
- Transcript text is mandatory.
- The transcript is the primary source of truth.
- Analyze the candidate based on what was actually discussed in the transcript.
- If something is not demonstrated, stated, or evidenced in the transcript, do not treat it as confirmed.

Assessment section rule:
- Assessment sections are supporting data only.
- Use assessment sections only to understand what was intended to be assessed.
- Assessment section questions and expected answers may provide context for evaluation criteria.
- Existing assessment section scores, answers, boolean values, ratings, and comments MUST NOT be used as scoring evidence unless the same evidence is explicitly present in the transcript.
- Do not average, copy, infer, or reuse any score from assessment sections.
- Questions marked NA must be ignored.
- If a question is marked NA, do not generate a question-level score for it.
- If a question is not covered in the transcript, mark transcript_evidence as null and explain that evidence is insufficient.
- High scores in sections such as AI_NATIVE_TRAITS must not influence overall_score_out_of_10 unless the transcript itself demonstrates those traits.

Scoring scale:
- 9-10: Excellent transcript evidence of strong target-role alignment, relevant primary skills, clear communication, and minimal concerns.
- 7-8: Good transcript evidence of target-role alignment with only minor gaps or follow-up areas.
- 5-6: Partial target-role alignment; some relevant experience is present, but depth, ownership, or fit is unclear.
- 3-4: Weak target-role alignment; limited relevant experience, significant skill gaps, or candidate is mostly from a different profile.
- 1-2: Very poor target-role alignment; candidate's demonstrated background is largely unrelated to the role or primary skills are missing.
- 0: Transcript clearly indicates no relevant fit for the target role.
- null: Transcript is too limited or not assessment-relevant enough to determine fit.

Scoring priority:
1. Target-role alignment based on transcript evidence.
2. Demonstrated primary skills required for the role.
3. Depth and specificity of relevant examples.
4. Communication quality and secondary traits.

Important scoring constraints:
- Communication quality alone cannot justify a score above 4.
- General professional experience alone cannot justify a score above 4.
- Experience in a different domain cannot justify a score above 4 unless the transcript clearly demonstrates transferable target-role skills.
- Positive secondary signals must not compensate for missing primary role skills.

Evidence rules:
- Do not invent facts.
- Use concise transcript-backed reasoning.
- If transcript evidence is insufficient, say so clearly.
- Do not assume skills, salary fit, notice period, communication quality, motivation, availability, or role fit unless present in transcript.

Recommendation rules:
- ai_recommendation_signal must be one of:
  - recommended
  - hold
  - not recommended
  - insufficient_evidence

Use the following general guidance:
- hire: Transcript shows strong alignment with role expectations, relevant experience, clear communication, and no major concerns.
- hold: Transcript shows partial alignment or mixed evidence; needs further evaluation.
- reject: Transcript shows clear mismatch, major concerns, or insufficient role fit based on conversation.
- insufficient_evidence: Transcript is too limited or does not contain enough assessment-relevant information.

Score and recommendation consistency rule:
- If ai_recommendation_signal is "not recommended", overall_score_out_of_10 MUST be between 0 and 4.
- If ai_recommendation_signal is "hold", overall_score_out_of_10 MUST be between 4 and 6.
- If ai_recommendation_signal is "recommended", overall_score_out_of_10 MUST be between 7 and 10.
- If ai_recommendation_signal is "insufficient_evidence", overall_score_out_of_10 MUST be null.
- Never return ai_recommendation_signal = "not recommended" with overall_score_out_of_10 above 4.
- Never return ai_recommendation_signal = "hold" with overall_score_out_of_10 above 6.
- Never return recommendation_alignment = "not_enough_evidence" with a numeric high score.

recommendation_alignment must be one of:
- strongly_aligned
- aligned
- partially_aligned
- not_enough_evidence


Final self-check before returning JSON:
- Verify that overall_score_out_of_10 is supported by transcript evidence only.
- Verify that assessment section scores did not influence overall_score_out_of_10.
- Verify that role mismatch does not receive a score above 4.
- Verify that reject does not receive a score above 4.
- Verify that insufficient_evidence receives null score.
- If these rules conflict, role-fit override and score-recommendation consistency rules take priority.



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



# def send_assessment_completed_email(
#     recruiter_email: str,
#     recruiter_name: str,
#     candidate_name: str,
#     job_title: str,
#     round_name: str,
#     interviewer_name: str,
#     recommendation: str,
#     assessment_link: str,
# ):
#     subject = f"Assessment Completed - {candidate_name}"

#     body = f"""
# Hello {recruiter_name},

# The assessment for the following candidate has been completed:

# Candidate: {candidate_name}
# Requisition: {job_title}
# Interview Round: {round_name}
# Interviewer: {interviewer_name}
# Assessment Status: Completed
# Recommendation: {recommendation}

# You can review the assessment details and AI-generated summary using the link below:

# {assessment_link}

# Regards,
# IntelliHire Team
# """

#     html_body = f"""
# <html>
#   <body>
#     <p>Hello {recruiter_name},</p>

#     <p>The assessment for the following candidate has been completed:</p>

#     <p>
#       <strong>Candidate:</strong> {candidate_name}<br/>
#       <strong>Requisition:</strong> {job_title}<br/>
#       <strong>Interview Round:</strong> {round_name}<br/>
#       <strong>Interviewer:</strong> {interviewer_name}<br/>
#       <strong>Assessment Status:</strong> Completed<br/>
#       <strong>Recommendation:</strong> {recommendation}
#     </p>

#     <p>
#       You can review the assessment details and AI-generated summary using the link below:
#     </p>

#     <p>
#       <a href="{assessment_link}">View Assessment Details</a>
#     </p>

#     <p>
#       Regards,<br/>
#       IntelliHire Team
#     </p>
#   </body>
# </html>
# """

#     send_email(
#         to_email=recruiter_email,
#         subject=subject,
#         body=body,
#         html_body=html_body,
#     )




def _format_llm_generated_competencies(generated: list[dict]) -> list[dict]:
    return [
        {
            "item_id": str(uuid.uuid4()),
            "competency_name": row["competency_name"],
            "description": row["description"],
            "covered_mandatory_skills": row["covered_mandatory_skills"],
            "evaluation_focus": row["evaluation_focus"],
            "source": "llmcompetencies",
            "score": None,
            "is_na": False,
            "comment": None,
            "is_fixed": False,
        }
        for row in generated
    ]



def _get_existing_competencies_from_question_bank(
    db: Session,
    req_id: int,
    stage_code: str,
) -> list[dict]:
    row = (
        db.query(AssessmentQuestionBank)
        .filter(
            AssessmentQuestionBank.req_id == req_id,
            AssessmentQuestionBank.stage_code == stage_code,
            AssessmentQuestionBank.is_active.is_(True),
        )
        .first()
    )

    if not row or not row.assessment_sections:
        return []

    competencies = row.assessment_sections.get("competencies")

    if not isinstance(competencies, list):
        return []

    return competencies


def _store_competencies_in_question_bank(
    db: Session,
    req_id: int,
    stage_code: str,
    competencies: list[dict],
) -> None:
    assessment_sections = {
        "competencies": competencies
    }

    existing_row = (
        db.query(AssessmentQuestionBank)
        .filter(
            AssessmentQuestionBank.req_id == req_id,
            AssessmentQuestionBank.stage_code == stage_code,
        )
        .first()
    )

    if existing_row:
        existing_row.assessment_sections = assessment_sections
        existing_row.is_active = True
        existing_row.source = "llmcompetencies"
    else:
        row = AssessmentQuestionBank(
            req_id=req_id,
            stage_code=stage_code,
            assessment_sections=assessment_sections,
            source="llmcompetencies",
            is_active=True,
        )

        db.add(row)

    db.commit()