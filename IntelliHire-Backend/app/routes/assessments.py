from datetime import datetime, timezone
from decimal import Decimal
import json
import uuid
from typing import Any, Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, logger
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError
from app.models.candidate import Candidate
from app.models.panel_assignments import PanelAssignment
from app.models.screening_result import ScreeningResult
from app.schemas.assessment import AssessmentFinalRecommendationRequest, AssessmentSaveRequest, AssessmentSubmitRequest, CEORoundAssessmentSaveSubmitRequest, CEORoundAssessmentSaveSubmitResponse, GenerateCompetenciesRequest, GenerateQuestionsRequest, TranscriptRemoveRequest
from app.services.assessment_service import _dedupe_questions, _extract_existing_questions_from_sections, _extract_questions_from_assessment_items, _format_llm_generated_competencies, _get_existing_competencies_from_question_bank, _store_competencies_in_question_bank, build_transcript_s3_key, calculate_stage_score_out_of_10, generate_recruiter_stage_assessment_ai_summary_with_llm, generate_stage_assessment_ai_summary_with_llm, normalize_section_type, normalize_stage_code, save_file_at_key, validate_assessment_sections, validate_section_for_stage
from app.services.ceo_service import build_jd_context, build_previous_assessments_context, build_resume_context, generate_ceo_assessment_ai_summary_with_llm
from app.services.email_service import send_assessment_completed_email, send_assessment_submission_confirmation_email, send_email_or_raise
from app.services.parser_service import extract_text_from_bytes
from app.services.storage_service import generate_download_link, save_file
from sqlalchemy.orm import Session
from sqlalchemy import select , func
from app.core.config import Settings, get_settings
from app.core.security import CurrentUser, require_admin, require_recruiter,require_hr_manager, require_panelist,require_any_role


import logging
logger = logging.getLogger("assessment_routes")

from app.db.deps import get_db
from app.models.application import Application, ApplicationStageHistory
from app.models.assessments import Assessment, AssessmentQuestionBank
from app.models.job_description import EmployeeMaster, JobDescription
from app.models.resume import Resume
from app.services.llm_service import _azure_client, _llm_generate_competencies, _strip_json_fence

router = APIRouter(tags=["Assessments"])


# =========================================================
# CONSTANTS
# =========================================================

VALID_ASSESSMENT_TYPES = {
    "RECRUITER_GENERAL",
    "RECRUITER_TECH",
    "L1_TECH",
    "L1_PROBLEM_SOLVING",
    "L1_BEHAVIORAL",
    "L2_TECH",
    "L2_PROBLEM_SOLVING",
    "L2_BEHAVIORAL",
    "L3_TECH",
    "L3_PROBLEM_SOLVING",
    "L3_BEHAVIORAL",
    "HR"
}

VALID_ASSESSMENT_STATUS = {"start", "draft", "completed"}
VALID_FINAL_RECOMMENDATIONS = {"RECOMMENDED", "HOLD", "NOT RECOMMENDED"} #RECOMMENDED, HOLD, or NOT RECOMMENDED


RECRUITER_GENERAL_QUESTIONS = [
    {
        "question": "Can you briefly introduce yourself and walk me through your recent experience?",
        "expected_answer": "Look for a clear, structured self-introduction covering recent roles, key responsibilities, achievements, and confidence in communication.",
        "source": "predefined",
        "topic": "Communication & Behavioral",
    },
    {
        "question": "If selected, what would be your earliest possible joining date? What is your current notice period?",
        "expected_answer": "Assess availability, notice period constraints, and alignment with the hiring and onboarding timeline.",
        "source": "predefined",
        "topic": "Availability & Logistics",
    },
    {
        "question": "Where are you currently based, and are you open to relocation or working in a hybrid setup?",
        "expected_answer": "Evaluate location constraints, openness to relocation, and flexibility toward hybrid or office-based work.",
        "source": "predefined",
        "topic": "Alignment & Intent",
    },
    {
        "question": "How has your career progressed over the years? Have you taken on increased responsibilities or leadership roles?",
        "expected_answer": "Look for growth in scope, ownership, leadership exposure, and increasing responsibility over time.",
        "source": "predefined",
        "topic": "Career Progression",
    },
    {
        "question": "What kind of industries or domains have you worked in, and which ones are you most comfortable with?",
        "expected_answer": "Understand industry exposure, domain depth, and relevance of past experience to the current role.",
        "source": "predefined",
        "topic": "Domain Experience",
    },
    {
        "question": "How would you describe your communication style, especially when working with teams or stakeholders?",
        "expected_answer": "Assess clarity, empathy, collaboration skills, and effectiveness in cross-functional communication.",
        "source": "predefined",
        "topic": "Communication & Behavioral",
    },
    {
        "question": "Can you share your reason for considering a change at this point in your career?",
        "expected_answer": "Understand motivation for change, career goals, and whether the reasons are growth-driven and aligned with the role.",
        "source": "predefined",
        "topic": "Career Motivation",
    },
    {
        "question": "What are your current and expected compensation expectations? Are you currently holding any other offers?",
        "expected_answer": "Evaluate compensation alignment, market positioning, offer competitiveness, and decision urgency.",
        "source": "predefined",
        "topic": "Compensation Fit",
    },
]



# =========================================================
# PYDANTIC SCHEMAS
# =========================================================

class AssessmentItemPayload(BaseModel):
    item_id: str
    question: str
    expected_answer: str | None = None
    source: str = "manual"
    topic: str | None = None
    score: float | None = None
    is_na: bool = False
    comment: str | None = None

    @field_validator("score")
    @classmethod
    def validate_score(cls, v: float | None) -> float | None:
        if v is None:
            return v
        if v < 0 or v > 7:
            raise ValueError("score must be between 0 and 10")
        return v

    @field_validator("source")
    @classmethod
    def validate_source(cls, v: str) -> str:
        allowed = {"predefined", "llm", "manual"}
        if v not in allowed:
            raise ValueError(f"source must be one of {allowed}")
        return v


class AssessmentFormLoadRequest(BaseModel):
    application_id: int
    assessment_type: str

    # @field_validator("assessment_type")
    # @classmethod
    # def validate_assessment_type(cls, v: str) -> str:
    #     if v not in VALID_ASSESSMENT_TYPES:
    #         raise ValueError("invalid assessment_type")
    #     return v



class GenerateAnswerRequest(BaseModel):
    application_id: int
    assessment_type: str
    question: str

    @field_validator("assessment_type")
    @classmethod
    def validate_assessment_type(cls, v: str) -> str:
        if v not in VALID_ASSESSMENT_TYPES:
            raise ValueError("invalid assessment_type")
        return v


class SaveAssessmentRequest(BaseModel):
    application_id: int
    assessment_type: str
    assessment_items: list[AssessmentItemPayload]
    summary_feedback: str | None = None

    @field_validator("assessment_type")
    @classmethod
    def validate_assessment_type(cls, v: str) -> str:
        if v not in VALID_ASSESSMENT_TYPES:
            raise ValueError("invalid assessment_type")
        return v


class SubmitAssessmentRequest(BaseModel):
    application_id: int
    assessment_type: str
    assessment_items: list[AssessmentItemPayload] | None = None
    summary_feedback: str | None = None
    final_recommendation: str

    @field_validator("assessment_type")
    @classmethod
    def validate_assessment_type(cls, v: str) -> str:
        if v not in VALID_ASSESSMENT_TYPES:
            raise ValueError("invalid assessment_type")
        return v

    @field_validator("final_recommendation")
    @classmethod
    def validate_final_recommendation(cls, v: str) -> str:
        if v not in VALID_FINAL_RECOMMENDATIONS:
            raise ValueError("invalid final_recommendation")
        return v


# =========================================================
# HELPERS
# =========================================================

def _serialize_assessment(assessment: Assessment) -> dict[str, Any]:
    return {
        "assessment_id": assessment.assessment_id,
        "application_id": assessment.application_id,
        "assessment_type": assessment.assessment_type,
        "assessment_items": assessment.assessment_items or [],
        "summary_feedback": assessment.summary_feedback,
        "final_recommendation": getattr(assessment, "final_recommendation", None),
        "overall_score": getattr(assessment, "overall_score", None),
        "status": assessment.status,
        "assessment_transcript_file_name": assessment.transcript_file_name,
        "assessment_transcript_s3key": assessment.transcript_s3_key
    }


def _get_application_context(application_id: int, db: Session) -> tuple[Application, JobDescription, str]:
    application = db.query(Application).filter(
        Application.application_id == application_id
    ).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    jd = db.query(JobDescription).filter(
        JobDescription.jd_id == application.jd_id
    ).first()
    if not jd:
        raise HTTPException(status_code=404, detail="JD not found")

    resume_text = ""

    if getattr(application, "current_resume_id", None):
        resume = db.query(Resume).filter(
            Resume.resume_id == application.current_resume_id
        ).first()
        if resume:
            resume_text = (
                getattr(resume, "extracted_text", None)
                or getattr(resume, "resume_text", None)
                or getattr(resume, "raw_text", None)
                or ""
            )

    return application, jd, resume_text


def _build_default_assessment_items(assessment_type: str) -> list[dict[str, Any]]:
    if assessment_type != "RECRUITER_GENERAL":
        return []

    items: list[dict[str, Any]] = []
    for q in RECRUITER_GENERAL_QUESTIONS:
        items.append({
            "item_id": str(uuid.uuid4()),
            "question": q["question"],
            "expected_answer": q["expected_answer"],
            "source": q["source"],
            "topic": q["topic"],
            "score": None,
            "is_na": False,
            "comment": None,
        })
    return items


def _compute_overall_score(items: list[dict[str, Any]]) -> float:
    valid_scores = [
        item["score"]
        for item in items
        if item.get("is_na", False) is False
        and item.get("score") is not None
    ]
    if not valid_scores:
        return 0.0
    return round(sum(valid_scores) / len(valid_scores), 2)


def _ensure_item_ids(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in items:
        row = dict(item)
        if not row.get("item_id"):
            row["item_id"] = str(uuid.uuid4())
        normalized.append(row)
    return normalized




def _llm_generate_questions(
    stage_code: str,
    section_type: str,
    jd_title: str | None,
    role_summary: str | None,
    mandatory_skills: list[str],
    good_to_have_skills: list[str],
    stage_information: str | None,
    experience: str | None,
    topic_prompt: str | None,
    question_count: int,
    resume_text: str | None,
    existing_questions: list[str] | None = None,
) -> list[dict[str, str]]:

    settings = get_settings()
    client = _azure_client(settings.azure_openai_api_key,settings.azure_openai_api_version,settings.azure_openai_endpoint)

    existing_questions = existing_questions or []

    # -----------------------------------------
    # Resume Context Normalization
    # -----------------------------------------
    resume_context = (resume_text or "").strip()

    # Default supports a typical 2–3 page resume.
    # Can be overridden from settings if needed.
    max_resume_chars =  18000

    if max_resume_chars and len(resume_context) > max_resume_chars:
        resume_context = (
            resume_context[:max_resume_chars]
            + "\n...[resume truncated because it exceeded the configured resume context limit]"
        )

    # -----------------------------------------
    # Dynamic Context Interpretation
    # -----------------------------------------
    dynamic_context = f"""
CONTEXT INTERPRETATION — VERY IMPORTANT

You must generate interview questions by combining ALL provided signals correctly.

The goal is not to generate questions from only one input.
The goal is to balance every relevant input and produce questions that are:
- stage-aligned
- section-appropriate
- topic-aware
- experience-appropriate
- JD-relevant
- skill-aligned
- resume-aware where useful
- non-duplicative

SIGNAL PURPOSE:

1. stage_information
   - This is the overall direction of the interview stage.
   - It defines WHY this question is being asked.
   - It defines the evaluation intent, style, and broad focus.
   - Examples:
     screening, hands-on implementation, debugging, architecture, leadership,
     communication, problem solving, ownership, domain depth.

2. topic_prompt
   - This is the recruiter's specific requested focus inside the stage direction.
   - It defines WHAT the question should primarily be about.
   - If provided, generated questions MUST primarily focus on topic_prompt.
   - topic_prompt should not override stage_information.
   - It must be interpreted inside the direction provided by stage_information.

3. section_type
   - This defines HOW the question should be framed.
   - section_type is NOT restricted to predefined values.
   - It may be anything such as:
     Backend Deep Dive, System Design Round, Debugging Focus,
     Client Communication, Leadership Evaluation, Initial Screening,
     Architecture Review, Culture Fit, Coding Round, QA Automation,
     Data Engineering, Product Thinking, etc.
   - You must infer the section intent dynamically from the section_type text.

4. experience
   - This controls HOW DEEP the question should go.
   - It defines seniority, complexity, and expected answer depth.

5. skills and JD context
   - These provide role/domain context.
   - Use mandatory skills strongly when relevant.
   - Use good-to-have skills only when they strengthen the question.
   - Keep questions aligned with the job title and role summary.

6. resume_text
   - This provides candidate-specific background.
   - It may include projects, previous roles, responsibilities, tools, skills,
     achievements, domains, certifications, and impact.
   - Use resume_text to personalize and sharpen questions where relevant.
   - Resume should not override stage_information, section_type, topic_prompt,
     JD context, or mandatory skills.
   - Resume should help create more candidate-specific questions, not generic
     resume walkthrough questions.
   - If the resume includes relevant experience connected to the JD, skills,
     stage, section_type, or topic_prompt, probe depth, ownership, trade-offs,
     implementation, debugging, decision-making, scalability, communication,
     or impact.

INPUT SIGNALS:

Stage Code:
{stage_code}

Section Type:
{section_type}

Stage Information:
{stage_information or ""}

Recruiter Topic Prompt:
{topic_prompt or ""}

Candidate Experience:
{experience or ""}

Job Title:
{jd_title or ""}

Role Summary:
{role_summary or ""}

Mandatory Skills:
{json.dumps(mandatory_skills or [], ensure_ascii=False, indent=2)}

Good To Have Skills:
{json.dumps(good_to_have_skills or [], ensure_ascii=False, indent=2)}

Resume Context:
{resume_context}

INTERPRETATION RULES:

- Do NOT rely on predefined stage labels like L1, L2, L3, Recruiter, Manager, etc.
- Do NOT rely on predefined section labels like TECH, GENERAL, BEHAVIORAL, PROBLEM_SOLVING.
- stage_information is the overall direction.
- topic_prompt is the specific focus inside that direction.
- section_type is the framing/category inferred dynamically at runtime.
- experience controls depth and complexity.
- resume_text is candidate-specific supporting context.
- JD title, role summary, mandatory skills, and good-to-have skills provide role alignment.
- existing_questions are used to prevent duplicate or overlapping evaluation intent.

BALANCED INPUT INTERPRETATION:

- You must consider ALL non-empty inputs before generating each question.
- Do not generate questions using only one signal such as resume_text, mandatory_skills,
  topic_prompt, section_type, or stage_information.
- Every question must be the result of balancing:
  stage_information + section_type + topic_prompt + experience + JD context
  + mandatory skills + good-to-have skills where useful + resume_text where relevant
  + existing_questions duplicate avoidance.
- No input should be ignored unless it is empty, irrelevant, contradictory,
  or impossible to apply without making the question worse.
- If two inputs conflict:
  - Preserve stage_information as the overall interview direction.
  - Preserve section_type as the question framing.
  - Preserve topic_prompt as the specific focus when provided.
  - Preserve JD and mandatory skills for role relevance.
  - Use resume_text only where it strengthens the question.
  - Use good-to-have skills only when they naturally fit.
- The final question should not be generic.
- It should be specific, role-aligned, seniority-appropriate, section-appropriate,
  topic-aware, resume-aware where useful, and non-duplicative.

TOPIC PROMPT RULES:

- If topic_prompt is provided, every generated question MUST primarily relate to it.
- If topic_prompt is empty, generate questions from stage_information, section_type,
  JD context, mandatory skills, experience, and resume_text where relevant.
- If topic_prompt conflicts with section_type, preserve section_type framing and adapt the topic accordingly.
- If topic_prompt conflicts with stage_information, preserve stage_information and use topic_prompt only where compatible.
- If topic_prompt is broad, convert it into focused interview questions.
- If topic_prompt is narrow, stay close to it but vary the evaluation angle across questions.

SECTION TYPE RULES:

- If section_type is unusual or custom, infer its meaning from the words used.
- If section_type suggests technical depth, ask technical/scenario/design/debugging questions.
- If section_type suggests communication, collaboration, leadership, ownership, or culture,
  ask behavioral/situational questions.
- If section_type suggests screening or introductory evaluation, ask concise alignment,
  background, or fundamental questions.
- If section_type suggests problem solving, debugging, troubleshooting, or reasoning,
  ask analytical and case-based questions.
- If section_type has mixed intent, combine the most relevant styles.
- If section_type is unclear, use stage_information and topic_prompt to infer the most appropriate framing.

RESUME CONTEXT RULES:

- If resume_text is provided, use it as candidate-specific evidence where relevant.
- Prefer questions that validate the candidate's claimed skills, projects, responsibilities,
  tools, achievements, domains, or impact.
- Resume-based questions must still follow stage_information, section_type, topic_prompt,
  experience, JD, and skills.
- Do not simply ask:
  "Tell me about your project"
  "Explain your resume"
  "Walk me through your experience"
  unless the section is clearly screening/background-oriented.
- Convert resume claims into evaluation-ready probes.
- If topic_prompt is provided, use resume only if it helps create a stronger question about topic_prompt.
- If topic_prompt is empty, use resume to personalize questions around relevant JD skills and stage intent.
- If resume_text is empty or irrelevant, ignore it and generate using JD, skills,
  stage_information, section_type, and experience.

EXPERIENCE DEPTH GUIDELINES:

- 0–2 years:
  Fundamentals, basic implementation, simple debugging, clarity of concepts.
  Resume-based questions should validate actual contribution and understanding.

- 2–5 years:
  Practical usage, real-world implementation, debugging, basic trade-offs.
  Resume-based questions should test hands-on ownership and implementation choices.

- 5–10 years:
  Design decisions, deeper debugging, scalability, maintainability, trade-offs, system thinking.
  Resume-based questions should test architecture decisions, impact, and trade-offs.

- 10+ years:
  Architecture, cross-team impact, leadership, strategy, reliability, scalability, mentoring.
  Resume-based questions should test influence, strategy, ownership, and organizational impact.

FINAL DECISION RULE:

Question =
stage_information direction
+ dynamically inferred section_type framing
+ topic_prompt focus when provided
+ experience-based depth
+ JD title and role summary relevance
+ mandatory skills alignment
+ good-to-have skills support where useful
+ resume_text personalization where relevant
+ existing_questions duplicate avoidance.

Before finalizing each question, verify that no important non-empty input was ignored
without reason.
"""

    user_prompt = f"""
================================================================================
ASSESSMENT CONTEXT
================================================================================

Stage Code:
{stage_code}

Section Type:
{section_type}

Stage Information:
{stage_information or ""}

Candidate Experience:
{experience or ""}

Job Title:
{jd_title or ""}

Role Summary:
{role_summary or ""}

Mandatory Skills:
{json.dumps(mandatory_skills or [], ensure_ascii=False, indent=2)}

Good To Have Skills:
{json.dumps(good_to_have_skills or [], ensure_ascii=False, indent=2)}

Resume Context:
{resume_context}

Existing Questions Already Present:
{json.dumps(existing_questions, ensure_ascii=False, indent=2)}

Recruiter Topic Prompt:
{topic_prompt or ""}

{dynamic_context}

================================================================================
QUESTION COUNT REQUIREMENT
================================================================================

Generate exactly {question_count} interview question(s) and expected answer(s).

Do not generate fewer than {question_count}.
Do not generate more than {question_count}.

================================================================================
GENERATION RULES
================================================================================

- You must consider all non-empty inputs before generating each question.
- Do not over-focus on only one input unless the other inputs are empty or irrelevant.
- stage_information, section_type, topic_prompt, experience, JD, skills, resume_text,
  and existing_questions must work together.
- stage_information defines the overall direction and evaluation intent.
- section_type must be interpreted dynamically and defines the framing/style.
- topic_prompt defines the specific focus within that direction when provided.
- experience must influence depth, complexity, and expected answer quality.
- Job title and role summary must keep the question role-relevant.
- Mandatory skills should strongly influence questions when relevant to the stage,
  section_type, topic_prompt, JD, or resume.
- Good-to-have skills should only be included when they naturally improve the question.
- Resume context should personalize the question where relevant, but must not replace
  the JD, stage direction, section framing, topic_prompt, or mandatory skills.
- If resume mentions projects, tools, achievements, or responsibilities relevant to the JD,
  ask probing questions about implementation, trade-offs, debugging, impact, ownership,
  communication, or decisions.
- If topic_prompt is provided, every generated question MUST primarily relate to it,
  while still considering JD, skills, experience, section_type, and resume.
- If topic_prompt is empty, generate from the combined context of stage_information,
  section_type, JD, skills, experience, and resume.
- Do not ask about irrelevant resume details that do not connect to the role, stage,
  topic, section, or skills.
- Questions must be suitable for the role and JD context.
- Avoid generic, shallow, or template-style questions.
- Expected answers must be specific, practical, and evaluation-ready.
- Do not generate generic experience-based questions unless the inferred section_type
  is screening/general/background-oriented.
- Each question must have a clear evaluation purpose and must not leave behind relevant
  context that could make the question stronger.

================================================================================
DYNAMIC SECTION TYPE INTERPRETATION — CRITICAL
================================================================================

section_type is not restricted to predefined values.

You must infer the intent of section_type at runtime.

Examples:

section_type = "Backend Deep Dive"
- Treat as technical backend evaluation.
- Ask implementation, debugging, design, scalability, API, database, or service-level questions.

section_type = "System Design Round"
- Treat as architecture and scalability evaluation.
- Ask design, trade-off, reliability, data flow, scaling, observability, and failure-handling questions.

section_type = "Debugging Focus"
- Treat as troubleshooting/problem-solving evaluation.
- Ask root-cause analysis, investigation steps, logs, metrics, failure scenarios, and fixes.

section_type = "Client Communication"
- Treat as communication/stakeholder evaluation.
- Ask situational questions around explaining trade-offs, handling expectations, escalations, and clarity.

section_type = "Leadership Evaluation"
- Treat as leadership/ownership evaluation.
- Ask questions around decision-making, mentoring, ambiguity, conflict, delivery ownership, and cross-team influence.

section_type = "Initial Screening"
- Treat as screening/general alignment.
- Ask concise questions around background, role fit, motivation, availability, relevant exposure, and basic clarity.

section_type = "Coding Round"
- Treat as implementation/problem-solving.
- Ask practical coding, algorithmic, data-structure, debugging, or implementation-oriented questions.

section_type = "QA Automation"
- Treat as technical QA/testing evaluation.
- Ask automation framework, flaky tests, CI/CD, reporting, test design, API/UI testing, maintainability, and debugging questions.

section_type = "Product Thinking"
- Treat as product/problem-framing evaluation.
- Ask questions around user impact, prioritization, trade-offs, metrics, requirements, and ambiguity.

IMPORTANT:
- Do not depend only on exact keywords.
- Infer intent semantically.
- The question style must match the inferred section intent.
- If section_type has mixed intent, combine the most relevant styles.
- If section_type is unclear, use stage_information and topic_prompt to infer the most appropriate framing.

================================================================================
TOPIC PROMPT HANDLING — CRITICAL
================================================================================

If Recruiter Topic Prompt is provided:

- Treat it as the specific subject the recruiter wants to assess.
- Do not ignore it.
- Do not replace it with unrelated mandatory skills or unrelated resume details.
- Do not generate broad JD questions unless they are clearly connected to topic_prompt.
- Keep the question inside the stage_information direction.
- Keep the question inside the inferred section_type framing.
- Adjust depth using experience.
- Use JD, mandatory skills, and resume context only where they strengthen the topic-focused question.
- If multiple questions are requested, each question must cover a different angle of topic_prompt.
- If topic_prompt is already covered by existing questions, generate a different angle,
  constraint, scenario, failure mode, decision point, or trade-off.

Examples:

If stage_information = "hands-on debugging"
and section_type = "Backend Deep Dive"
and topic_prompt = "Kafka consumer lag":

Good:
"How would you investigate increasing Kafka consumer lag in a production backend service, and what changes would you consider at the consumer, partitioning, and processing levels?"

Bad:
"What is Kafka?"

If stage_information = "architecture and scalability"
and section_type = "System Design Round"
and topic_prompt = "Redis caching":

Good:
"How would you design a Redis caching strategy for a high-traffic service while handling cache invalidation, hot keys, fallback behavior, and consistency?"

Bad:
"Have you used Redis before?"

If stage_information = "ownership and communication"
and section_type = "Leadership Evaluation"
and topic_prompt = "production incidents":

Good:
"Tell me about a time you took ownership during a production incident. How did you coordinate stakeholders, communicate impact, and prevent recurrence?"

Bad:
"How do you configure monitoring alerts?"

================================================================================
RESUME CONTEXT HANDLING — IMPORTANT
================================================================================

If Resume Context is provided:

- Use resume_text as candidate-specific evidence.
- Prefer questions that validate the candidate's claimed skills, projects, responsibilities,
  tools, achievements, domains, or impact.
- Resume-based questions should still follow stage_information, section_type, topic_prompt,
  experience, JD, and skills.
- Do not simply ask:
  "Tell me about your project"
  "Explain your resume"
  "Walk me through your experience"
  unless the section is screening or background-oriented.
- Convert resume claims into evaluation-ready probes.

Good resume-personalized questions:

If resume mentions building a payment service:
"Your resume mentions work on a payment service. How would you handle idempotency, retries, and failure recovery when integrating with an external payment gateway?"

If resume mentions Kafka:
"Your resume mentions Kafka-based data pipelines. How would you debug a sudden increase in consumer lag, and what metrics would help you distinguish slow processing from partition imbalance?"

If resume mentions leading a team:
"Your resume mentions leading a team delivery. How did you handle technical disagreement, delivery risk, and stakeholder communication?"

Bad resume-personalized questions:

"What projects have you worked on?"
"Explain your resume."
"Tell me about your Kafka experience."
"What are your responsibilities in your current role?"

Resume usage priority:

1. If topic_prompt is provided:
   - Use resume only if it helps create a stronger question about topic_prompt.
   - Do not move away from topic_prompt.

2. If topic_prompt is empty:
   - Use resume to personalize questions around relevant JD skills and stage intent.

3. If resume_text is empty or irrelevant:
   - Ignore it and generate using JD, skills, stage_information, section_type, and experience.

================================================================================
EXPECTED ANSWER RULES
================================================================================

Expected answers must be useful for evaluation.

They should include:

- Key points the candidate should cover.
- Practical reasoning or steps.
- Trade-offs where relevant.
- Seniority-appropriate depth.
- Section-appropriate evaluation criteria.
- Topic-specific details when topic_prompt is provided.
- Resume-specific evaluation depth when the question references resume context.
- JD and skill relevance where applicable.

Avoid vague expected answers like:
- "Candidate should explain clearly."
- "Candidate should have good understanding."
- "Answer may vary."

Instead, provide concrete evaluation points.

================================================================================
CROSS-SECTION DUPLICATE AND OVERLAP PREVENTION — CRITICAL
================================================================================

Existing Questions Already Present contains questions from the FULL assessment stage,
including questions from any section type.

You must compare every new question against ALL existing questions before returning it.

Do NOT generate a question that is:

- exactly the same as an existing question
- a reworded version of an existing question
- semantically similar to an existing question
- testing the same evaluation intent
- asking the same candidate experience in a different way
- repeating the same topic using different wording
- converting a broad/general question into a deeper question without changing evaluation intent
- converting a technical topic into a behavioral/general question without changing the actual evaluation angle

IMPORTANT DUPLICATE RULES:

1. If an existing question asks about general experience/background,
do not ask another experience/background question unless the inferred section_type clearly requires it.

Bad:
"Can you describe your experience with test automation?"

Better:
"How would you structure a Selenium-based automation framework to reduce flaky tests and improve regression reliability?"

2. If an existing question asks about a topic generally,
the new question must test a different angle.

Example:
Existing:
"Have you worked with Kafka?"

Bad:
"Can you describe your Kafka experience?"

Better:
"How would you troubleshoot Kafka consumer lag caused by slow processing, poor partitioning, or downstream dependency latency?"

3. If an existing question already covers topic_prompt,
generate a different evaluation angle.

Different angles may include:
- implementation
- debugging
- architecture
- trade-offs
- scalability
- reliability
- security
- maintainability
- communication
- ownership
- prioritization
- failure handling
- optimization
- stakeholder impact
- resume-claim validation

================================================================================
MULTIPLE QUESTION RULE
================================================================================

If multiple questions are requested:

- Each must test a DIFFERENT concept or angle.
- No overlap.
- If topic_prompt is provided, all questions should relate to it but evaluate different aspects.
- Cover different scenarios, constraints, failure modes, trade-offs, behaviors, or decision points.
- Do not create multiple questions that are only wording variations of each other.
- If resume context is relevant, use it across questions carefully without repeatedly asking
  the same resume-based intent.

================================================================================
FINAL QUALITY CHECK — MUST DO INTERNALLY
================================================================================

Before returning the final JSON, internally verify each generated question:

1. Does it follow stage_information?
2. Does it match the inferred section_type framing?
3. If topic_prompt is provided, does it primarily focus on topic_prompt?
4. Is the depth appropriate for experience?
5. Is it relevant to the job title and role summary?
6. Does it use mandatory skills where relevant?
7. Does it use good-to-have skills only when naturally helpful?
8. If resume_text is relevant, does it personalize or sharpen the question?
9. Is it different from existing_questions?
10. Is it different from the other generated questions?
11. Is the expected answer practical, specific, and evaluation-ready?
12. Does the question avoid being generic, shallow, or template-like?
13. Has every important non-empty input been considered?

If any answer is "no", revise the question before returning JSON.

================================================================================
OUTPUT FORMAT
================================================================================

Return STRICT JSON ONLY:

[
  {{
    "question": "string",
    "expected_answer": "string"
  }}
]
""".strip()

    response = client.chat.completions.create(
        model=settings.azure_openai_deployment,
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": """
You are a strict JSON generator for interview assessment questions.

Return only valid JSON.
No markdown.
No explanation.
No extra text.

You must generate questions by balancing all provided inputs together.

You must:
- Consider every non-empty input before generating each question.
- Follow stage_information as the overall interview direction.
- Infer section_type intent dynamically and use it as the question framing.
- Follow topic_prompt as the specific focus when provided.
- Adapt depth and complexity using candidate experience.
- Keep questions relevant to the job title and role summary.
- Use mandatory skills strongly where relevant.
- Use good-to-have skills only when they naturally strengthen the question.
- Use resume_text as candidate-specific supporting context where relevant.
- Do not let resume_text override stage_information, section_type, topic_prompt, JD, or mandatory skills.
- Avoid duplicate or semantically similar questions using existing_questions.
- Generate exactly the requested number of questions.
- Return expected answers that are practical, specific, and evaluation-ready.
""".strip(),
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
    )

    content = response.choices[0].message.content or "[]"
    content = _strip_json_fence(content)

    parsed = json.loads(content)

    if not isinstance(parsed, list):
        raise ValueError("LLM response must be a list")

    cleaned: list[dict[str, str]] = []

    for item in parsed:
        if not isinstance(item, dict):
            continue

        q = str(item.get("question") or "").strip()
        a = str(item.get("expected_answer") or "").strip()

        if q:
            cleaned.append(
                {
                    "question": q,
                    "expected_answer": a,
                }
            )

    if len(cleaned) > question_count:
        cleaned = cleaned[:question_count]

    if len(cleaned) < question_count:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "LLM generated fewer questions than requested",
                "requested": question_count,
                "generated": len(cleaned),
            },
        )

    return cleaned


def _llm_generate_expected_answer(
    assessment_type: str,
    jd_title: str | None,
    mandatory_skills: list[str],
    resume_text: str,
    question: str,
) -> str:
    settings = get_settings()
    client = _azure_client(settings.azure_openai_api_key,settings.azure_openai_api_version,settings.azure_openai_endpoint)

    user_prompt = f"""
Assessment Type: {assessment_type}
Job Title: {jd_title or ""}
Mandatory Skills: {mandatory_skills}
Candidate Resume Text:
{resume_text}

Question:
{question}

Generate a concise but useful expected answer / evaluation guideline for the interviewer.
Return STRICT JSON ONLY:
{{
  "expected_answer": "string"
}}
""".strip()

    response = client.chat.completions.create(
        model=settings.azure_openai_deployment,
        temperature=0,
        messages=[
            {"role": "system", "content": "You are a strict JSON generator."},
            {"role": "user", "content": user_prompt},
        ],
    )

    content = response.choices[0].message.content or "{}"
    content = _strip_json_fence(content)
    parsed = json.loads(content)
    return (parsed.get("expected_answer") or "").strip()





# =========================================================
# API 3: LLM GENERATE EXPECTED ANSWER
# =========================================================

@router.post("/assessments/llm/generate-answer")
def generate_assessment_expected_answer(
    payload: GenerateAnswerRequest,
    current_user: CurrentUser = Depends(require_any_role),
    db: Session = Depends(get_db),
):
    """
    NO DB WRITE.
    Returns expected answer only.
    """
    _, jd, resume_text = _get_application_context(payload.application_id, db)

    expected_answer = _llm_generate_expected_answer(
        assessment_type=payload.assessment_type,
        jd_title=jd.title,
        mandatory_skills=jd.mandatory_skills or [],
        resume_text=resume_text,
        question=payload.question,
    )

    return {"expected_answer": expected_answer}


# =========================================================
# API 4: SAVE DRAFT
# =========================================================
@router.post("/assessments/save")
def save_assessment_stage(
    payload: AssessmentSaveRequest,
    current_user: CurrentUser = Depends(require_any_role),
    db: Session = Depends(get_db),
):
    try:
        stage_code = normalize_stage_code(payload.stage_code)

        assessment = db.query(Assessment).filter(
            Assessment.application_id == payload.application_id,
            Assessment.stage_code == stage_code,
        ).first()

        if not assessment:
            raise HTTPException(status_code=404, detail="Assessment stage not found")

        if assessment.status == "submitted":
            raise HTTPException(
                status_code=400,
                detail="Submitted assessment cannot be saved as draft because it is already submitted !",
            )

        cleaned_sections = validate_assessment_sections(
            stage_code=stage_code,
            assessment_sections=payload.assessment_sections,
        )

        assessment.assessment_sections = cleaned_sections
        assessment.status = "draft"
        assessment.summary_feedback = payload.summary_feedback

        # Form changed, so previous summary is stale
        assessment.ai_assessment_summary = None
        assessment.ai_summary_generated_at = None
        assessment.overall_score = None

        
        assessment.areas_of_concern = payload.areas_of_concern
        assessment.areas_to_probe_in_next_round = payload.areas_to_probe_in_next_round
        assessment.problem_statements = payload.problem_statements or {}

        db.commit()
        db.refresh(assessment)

        return {
            "message": "Assessment draft saved successfully",
            "assessment_id": assessment.assessment_id,
            "application_id": assessment.application_id,
            "stage_code": assessment.stage_code,
            "status": assessment.status,
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Failed to save assessment draft: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to save assessment draft")


import traceback
from fastapi import HTTPException
@router.post("/assessments/submit")
def submit_assessment_stage(
    payload: AssessmentSubmitRequest,
    current_user: CurrentUser = Depends(require_any_role),
    db: Session = Depends(get_db),
):
    try:
        settings = get_settings()
        stage_code = normalize_stage_code(payload.stage_code)

        

        if not payload.summary_feedback.strip():
            raise HTTPException(
                status_code=400,
                detail="summary_feedback is required",
            )

        assessment = db.query(Assessment).filter(
            Assessment.application_id == payload.application_id,
            Assessment.stage_code == stage_code,
        ).first()

        if not assessment:
            raise HTTPException(status_code=404, detail="Assessment stage not found")

        cleaned_sections = validate_assessment_sections(
            stage_code=stage_code,
            assessment_sections=payload.assessment_sections,
        )

        overall_score = calculate_stage_score_out_of_10(cleaned_sections)

        application, jd, resume_text = _get_application_context(
            payload.application_id,
            db,
        )

        jd_context = {
            "title": jd.title,
            "location": jd.location,
            "experience": jd.experience,
            "role_summary": jd.role_summary,
            "responsibilities": jd.responsibilities or [],
            "mandatory_skills": jd.mandatory_skills or [],
            "good_to_have_skills": jd.good_to_have_skills or [],
            "qualifications": getattr(jd, "qualifications", []) or [],
        }

        resume_context = {
            "resume_text": resume_text,
        }



        if(stage_code == "RECRUITER"):
            print("temp")
            ai_summary = generate_recruiter_stage_assessment_ai_summary_with_llm(
                settings=settings,
                jd_context=jd_context,
                resume_context=resume_context,
                stage_code=stage_code,
                assessment_sections=cleaned_sections,
                summary_feedback=payload.summary_feedback,
                transcript_text=assessment.transcript_text,
            )       
        else:

            ai_summary = generate_stage_assessment_ai_summary_with_llm(
                settings=settings,
                jd_context=jd_context,
                resume_context=resume_context,
                stage_code=stage_code,
                assessment_sections=cleaned_sections,
                summary_feedback=payload.summary_feedback,
                # final_recommendation=final_recommendation,
                overall_score_out_of_10=overall_score,
                transcript_text=assessment.transcript_text,
            )

        assessment.assessment_sections = cleaned_sections
        assessment.summary_feedback = payload.summary_feedback
        # assessment.final_recommendation = final_recommendation
        # assessment.overall_score = overall_score
        
        assessment.areas_of_concern = payload.areas_of_concern
        assessment.areas_to_probe_in_next_round = payload.areas_to_probe_in_next_round
        assessment.problem_statements = payload.problem_statements or {}



        if stage_code == "RECRUITER":
            assessment.overall_score = (
                ai_summary.get("overall_score_out_of_10")
                if isinstance(ai_summary, dict)
                else None
            )
        else:
            assessment.overall_score = overall_score

        assessment.ai_assessment_summary = ai_summary
        assessment.ai_summary_generated_at = datetime.now(timezone.utc)
        # assessment.status = "submitted"

        db.commit()
        db.refresh(assessment)

        return {
            "message": "Assessment submitted successfully",
            "assessment_id": assessment.assessment_id,
            "application_id": assessment.application_id,
            "stage_code": assessment.stage_code,
            "status": assessment.status,
            "overall_score": float(assessment.overall_score) if assessment.overall_score is not None else None,
            # "final_recommendation": assessment.final_recommendation,
            "transcript_used": bool(assessment.transcript_text),
            "ai_assessment_summary": assessment.ai_assessment_summary,
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception(f"Failed to submit assessment : {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to submit assessment")

# =========================================================
# API 6: GET ONE ASSESSMENT
# =========================================================

@router.get("/assessments")
def get_assessment(
    id: int,
    current_user: CurrentUser = Depends(require_any_role),
    db: Session = Depends(get_db),
):
    assessment = db.query(Assessment).filter(
        Assessment.assessment_id == id
    ).first()

    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    return _serialize_assessment(assessment)


# =========================================================
# API 7: LIST ALL ASSESSMENTS FOR APPLICATION
# =========================================================
@router.get("/assessments/application_id={application_id}")
def list_assessments_for_application(
    application_id: int,
    current_user: CurrentUser = Depends(require_any_role),
    db: Session = Depends(get_db),
):
    assessments = db.query(Assessment).filter(
        Assessment.application_id == application_id,
    ).order_by(
        Assessment.stage_level.asc()
    ).all()

    return {
        "application_id": application_id,
        "assessments": [
            {
                "assessment_id": a.assessment_id,
                "stage_code": a.stage_code,
                "stage_level": a.stage_level,
                "status": a.status,
                "overall_score": float(a.overall_score) if a.overall_score is not None else None,
                "summary_feedback": a.summary_feedback,
                "final_recommendation": a.final_recommendation,
                "transcript_uploaded": bool(a.transcript_s3_key),
                "ai_summary_available": bool(a.ai_assessment_summary),
            }
            for a in assessments
        ],
    }




@router.get("/assessments/get_resume_details")
def get_application_details(
    application_id: int,
    current_user: CurrentUser = Depends(require_any_role),
    db: Session = Depends(get_db),
):
    stmt = (
        select(Application, Candidate, Resume, ScreeningResult)
        .join(Candidate, Candidate.candidate_id == Application.candidate_id)
        .outerjoin(Resume, Resume.resume_id == Application.current_resume_id)
        .outerjoin(ScreeningResult,ScreeningResult.screening_result_id == Application.latest_screening_result_id)
        .where(Application.application_id == application_id)
    )


    result = db.execute(stmt).first()

    if not result:
        raise HTTPException(status_code=404, detail="Application not found")

    application, candidate, resume , screening_result = result


    
    resume_download_link = None

    if resume:
        settings = get_settings()
        resume_download_link = generate_download_link(
            settings,
            resume.s3_key if settings.file_storage_mode == "s3" else None,
            resume.s3_key if settings.file_storage_mode != "s3" else None,
            resume.file_name or "Resume"
        )


    return {
        
        "candidate": {
            "candidate_id": candidate.candidate_id,
            "full_name": candidate.full_name,
            "email": candidate.email,
            "phone": candidate.phone,
        },
        "resume": (
            {
                "resume_id": resume.resume_id,
                "file_name": resume.file_name,
                "uploaded_at": resume.uploaded_at,
                "parsed_resume": resume.parsed_resume_json,
                "s3_key": resume.s3_key  # ✅ work_experience, education, etc.
            }
            if resume
            else None
        ),
        
        "screening_result": (
            {
                "screening_result_id": screening_result.screening_result_id,
                "skill_score": float(screening_result.skill_score),
                "other_score": float(screening_result.other_score),
                "overall_score": float(screening_result.overall_score),
                "skills_matched": screening_result.skills_matched,
                "total_skills": screening_result.total_skills,
                "matched_skills": screening_result.matched_skills,
                "missing_skills": screening_result.missing_skills,
                "other_score_breakdown": screening_result.other_score_breakdown,
                "match_status": screening_result.match_status,
                "screened_at": screening_result.screened_at,
                "resume_download_link": resume_download_link

            }
            if screening_result
            else None
        ),

    }


@router.get("/assessments/application_id={application_id}/stage_code={stage_code}")
def get_assessment_stage(
    application_id: int,
    stage_code: str,
    current_user: CurrentUser = Depends(require_any_role),
    db: Session = Depends(get_db),
):
    try:
        stage_code = normalize_stage_code(stage_code)

        assessment = db.query(Assessment).filter(
            Assessment.application_id == application_id,
            Assessment.stage_code == stage_code,
        ).first()

        if not assessment:
            raise HTTPException(status_code=404, detail="Assessment stage not found")

        s3_download_link = None

        if assessment.transcript_s3_key:
            settings = get_settings()
            s3_download_link = generate_download_link(
                settings,
                assessment.transcript_s3_key if settings.file_storage_mode == "s3" else None,
                assessment.transcript_s3_key if settings.file_storage_mode != "s3" else None,
                assessment.transcript_file_name
            )

        return {
            "assessment_id": assessment.assessment_id,
            "application_id": assessment.application_id,
            "stage_code": assessment.stage_code,
            "stage_level": assessment.stage_level,
            "status": assessment.status,
            "assessment_sections": assessment.assessment_sections or {},
            "transcript_uploaded": bool(assessment.transcript_s3_key),
            "transcript_s3_key": s3_download_link,
            "overall_score": float(assessment.overall_score) if assessment.overall_score is not None else None,
            "summary_feedback": assessment.summary_feedback,
            "final_recommendation": assessment.final_recommendation,
            "ai_assessment_summary": assessment.ai_assessment_summary,
            "discrepency_reason": assessment.discrepency_reason,

            "areas_of_concern": assessment.areas_of_concern,
            "areas_to_probe_in_next_round": assessment.areas_to_probe_in_next_round
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception as e:
        db.rollback()

        root_cause = str(e) or type(e).__name__

        logger.exception(f"Failed assessment get api reason --> : {e}")

        raise HTTPException(
            status_code=500,
            detail={
                "error": "Failed assessment get api"
                
            },
        )

@router.post("/assessments/llm/generate-questions")
def generate_assessment_questions(
    payload: GenerateQuestionsRequest,
    current_user: CurrentUser = Depends(require_any_role),
    db: Session = Depends(get_db),
):
    try:
        stage_code = normalize_stage_code(payload.stage_code)
        section_type = normalize_section_type(payload.section_type)

        validate_section_for_stage(stage_code, section_type)

        application, jd, resume_text = _get_application_context(
            payload.application_id,
            db,
        )

        assessment = db.query(Assessment).filter(
            Assessment.application_id == payload.application_id,
            Assessment.stage_code == stage_code,
        ).first()

        if not assessment:
            raise HTTPException(status_code=404, detail="Assessment stage not found")

        # Use all existing questions from full stage to avoid repeats across sections.
        saved_existing_questions = _extract_existing_questions_from_sections(
            assessment.assessment_sections or {},
            section_type=None,
        )

        existing_questions = _dedupe_questions(
            saved_existing_questions + (payload.existing_questions or [])
        )



        
        resolved_stage_information = ""

        for stage in jd.stages or []:
            stage_name = str(stage.get("stage_name") or "").strip().lower()
            requested_stage_name = str(stage_code or "").strip().lower()

            if stage_name == requested_stage_name:
                resolved_stage_information = str(stage.get("stage_information") or "").strip()
                break


        generated = _llm_generate_questions(
            stage_code=stage_code,
            section_type=section_type,
            jd_title=jd.title,
            role_summary=jd.role_summary,
            mandatory_skills=jd.mandatory_skills or [],
            good_to_have_skills=jd.good_to_have_skills or [],
            stage_information=resolved_stage_information,
            experience=jd.experience,
            topic_prompt=payload.topic_prompt,
            question_count=payload.question_count,
            resume_text=resume_text,
            existing_questions=existing_questions,
        )

        return {
            "questions": [
                {
                "item_id": str(uuid.uuid4()),
                    "question": row["question"],
                    "expected_answer": row["expected_answer"],
                    "source": "llm",
                    "topic": row.get("topic") or payload.topic_prompt,
                    "score": None,
                    "is_na": False,
                    "comment": None,
                    "is_fixed": False,
                }    
                for row in generated
            ]
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        
        root_cause = str(e) or type(e).__name__
        
        logger.exception(f"Failed to generate llm question : {e}")

        
        raise HTTPException(
                status_code=500,
                detail={
                    "error": "Failed to generate llm question"
                    
                },
            )



from fastapi import UploadFile, File, Form


@router.post("/assessments/transcript/upload")
async def upload_assessment_transcript(
    application_id: int = Form(...),
    stage_code: str = Form(...),
    current_user: CurrentUser = Depends(require_any_role),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    try:
        if not file:
            raise HTTPException(400, "File is required transcript upload!")
         
        settings = get_settings()
        stage_code = normalize_stage_code(stage_code)

        assessment = db.query(Assessment).filter(
            Assessment.application_id == application_id,
            Assessment.stage_code == stage_code,
        ).first()

        if not assessment:
            raise HTTPException(status_code=404, detail="Assessment stage not found")

        content = await file.read()

        transcript_text = extract_text_from_bytes(
            content,
            file.filename or "transcript.txt",
            document_type="transcript",
        )

        if not transcript_text or not transcript_text.strip():
            raise HTTPException(
                status_code=400,
                detail="Transcript text could not be extracted",
            )

        # fixed_s3_key = build_transcript_s3_key(
        #     application_id=application_id,
        #     stage_code=stage_code,
        # )

        # storage = save_file_at_key(
        #     settings=settings,
        #     content=content,
        #     s3_key=fixed_s3_key,
        #     filename=file.filename or "transcript.txt",
        # )

        storage = save_file(settings, content, file.filename or "transcript.bin", "transcripts")

        assessment.transcript_s3_key = storage.get("s3_key") or storage.get("local_path")
        assessment.transcript_text = transcript_text.strip()
        assessment.transcript_file_name = file.filename
        # Transcript changed, previous AI summary is stale.
        assessment.ai_assessment_summary = None
        assessment.ai_summary_generated_at = None

        assessment.status = "draft"

        db.commit()
        db.refresh(assessment)

        return {
            "message": "Transcript uploaded successfully",
            "assessment_id": assessment.assessment_id,
            "application_id": assessment.application_id,
            "stage_code": assessment.stage_code,
            "transcript_s3_key": assessment.transcript_s3_key,
            "transcript_preview": assessment.transcript_text[:700],
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        
        root_cause = str(e) or type(e).__name__
        
        logger.exception(f"Failed to upload transcript : {e}")

        
        raise HTTPException(
                status_code=500,
                detail={
                    "error": "Failed to upload transcript",
                    "cause": root_cause,
                },
            )

       
    


@router.post("/assessments/transcript/remove")
def remove_assessment_transcript(
    payload: TranscriptRemoveRequest,
    current_user: CurrentUser = Depends(require_any_role),
    db: Session = Depends(get_db),
):
    try:
        stage_code = normalize_stage_code(payload.stage_code)

        assessment = db.query(Assessment).filter(
            Assessment.application_id == payload.application_id,
            Assessment.stage_code == stage_code,
        ).first()

        if not assessment:
            raise HTTPException(status_code=404, detail="Assessment stage not found")

        assessment.transcript_s3_key = None
        assessment.transcript_text = None
        assessment.ai_assessment_summary = None
        assessment.ai_summary_generated_at = None

        db.commit()
        db.refresh(assessment)

        return {
            "message": "Transcript removed successfully",
            "assessment_id": assessment.assessment_id,
            "application_id": assessment.application_id,
            "stage_code": assessment.stage_code,
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        logger.exception("Failed to remove transcript")
        
        raise HTTPException(status_code=500, detail="Failed to remove transcript")
        



# @router.post("/assessments/final-recommendation/save")
# # def save_assessment_final_recommendation(
# #     payload: AssessmentFinalRecommendationRequest,
# #     current_user: CurrentUser = Depends(require_any_role),
# #     db: Session = Depends(get_db),
# # ):
# #     try:
# #         stage_code = normalize_stage_code(payload.stage_code)

# #         final_recommendation = payload.final_recommendation.strip().upper()

# #         # if final_recommendation not in VALID_FINAL_RECOMMENDATIONS:
# #         #     raise HTTPException(
# #         #         status_code=400,
# #         #         detail="final_recommendation must be RECOMMENDED, HOLD, or NOT RECOMMENDED",
# #         #     )

# #         assessment = db.query(Assessment).filter(
# #             Assessment.application_id == payload.application_id,
# #             Assessment.stage_code == stage_code,
# #         ).first()

# #         if not assessment:
# #             raise HTTPException(
# #                 status_code=404,
# #                 detail="Assessment stage not found",
# #             )

# #         # if assessment.status != "submitted":
# #         #     raise HTTPException(
# #         #         status_code=400,
# #         #         detail="Final recommendation can be saved only after assessment is submitted",
# #         #     )

# #         assessment.status = "Submitted"

# #         assessment.final_recommendation = final_recommendation

# #         # if payload.discrepency_reason:
# #         assessment.discrepency_reason = payload.discrepency_reason
# #         assessment.assessment_taken_by = current_user.full_name
# #         db.commit()
# #         db.refresh(assessment)

# #         return {
# #             "message": "Final recommendation saved successfully",
# #             "assessment_id": assessment.assessment_id,
# #             "application_id": assessment.application_id,
# #             "stage_code": assessment.stage_code,
# #             "status": assessment.status,
# #             "overall_score": float(assessment.overall_score) if assessment.overall_score is not None else None,
# #             "final_recommendation": assessment.final_recommendation,
# #         }

# #     except HTTPException:
# #         db.rollback()
# #         raise
# #     except Exception as e:
# #         db.rollback()
        
# #         root_cause = str(e) or type(e).__name__
        
# #         logger.exception(f"Failed to update final recommendation : {e}")

        
# #         raise HTTPException(
# #                 status_code=500,
# #                 detail={
# #                     "error": "Failed to update final recommendation",
                   
# #                 },
# #             )





# @router.post("/assessments/final-recommendation/save")
# def save_assessment_final_recommendation(
#     payload: AssessmentFinalRecommendationRequest,
#     background_tasks: BackgroundTasks,
#     current_user: CurrentUser = Depends(require_any_role),
#     db: Session = Depends(get_db),
# ):
#     try:
#         settings = get_settings()
#         stage_code = normalize_stage_code(payload.stage_code)
#         round_name = stage_code

#         final_recommendation = payload.final_recommendation.strip().upper()

#         assessment = db.query(Assessment).filter(
#             Assessment.application_id == payload.application_id,
#             Assessment.stage_code == stage_code,
#         ).first()

#         if not assessment:
#             raise HTTPException(
#                 status_code=404,
#                 detail="Assessment stage not found",
#             )

#         application = db.query(Application).filter(
#             Application.application_id == payload.application_id,
#         ).first()

#         if not application:
#             raise HTTPException(
#                 status_code=404,
#                 detail="Application not found",
#             )

#         job_description = db.query(JobDescription).filter(
#             JobDescription.jd_id == application.jd_id,
#         ).first()

#         if not job_description:
#             raise HTTPException(
#                 status_code=404,
#                 detail="Job description not found",
#             )

#         candidate = db.query(Candidate).filter(
#             Candidate.candidate_id == application.candidate_id,
#         ).first()

#         if not candidate:
#             raise HTTPException(
#                 status_code=404,
#                 detail="Candidate not found",
#             )

#         assessment.status = "Submitted"
#         assessment.final_recommendation = final_recommendation
#         assessment.discrepency_reason = payload.discrepency_reason
#         assessment.assessment_taken_by = current_user.full_name

#         db.commit()
#         db.refresh(assessment)

#         recruiter_email = job_description.created_by_email
#         recruiter_name = job_description.created_by or "Recruiter"

#         if recruiter_email:
#             candidate_name = candidate.full_name

#             assessment_link = (
#                 f"{settings.intellihire_base_url}"  
#             )

#             background_tasks.add_task(
#                 send_assessment_completed_email,
#                 recruiter_email=recruiter_email,
#                 recruiter_name=recruiter_name,
#                 candidate_name=candidate_name,
#                 req_id=job_description.req_id or "-",
#                 jd_title=job_description.title or "-",
#                 round_name=round_name,
#                 interviewer_name=current_user.full_name,
#                 recommendation=final_recommendation,
#                 assessment_link=assessment_link,
#             )
#         else:
#             logger.warning(
#                 "Assessment submitted but recruiter email not found for jd_id=%s",
#                 job_description.jd_id,
#             )

#         return {
#             "message": "Final recommendation saved successfully",
#             "assessment_id": assessment.assessment_id,
#             "application_id": assessment.application_id,
#             "stage_code": assessment.stage_code,
#             "status": assessment.status,
#             "overall_score": float(assessment.overall_score)
#             if assessment.overall_score is not None
#             else None,
#             "final_recommendation": assessment.final_recommendation,
#         }

#     except HTTPException:
#         db.rollback()
#         raise

#     except Exception as e:
#         db.rollback()

#         logger.exception(f"Failed to update final recommendation : {e}")

#         raise HTTPException(
#             status_code=500,
#             detail={
#                 "error": "Failed to update final recommendation",
#             },
#         )




@router.post("/assessments/final-recommendation/save")
def save_assessment_final_recommendation(
    payload: AssessmentFinalRecommendationRequest,
    current_user: CurrentUser = Depends(require_any_role),
    db: Session = Depends(get_db),
):
    try:
        settings = get_settings()

        stage_code = normalize_stage_code(payload.stage_code)
        round_name = stage_code

        final_recommendation = payload.final_recommendation.strip().upper()

        assessment = db.query(Assessment).filter(
            Assessment.application_id == payload.application_id,
            Assessment.stage_code == stage_code,
        ).first()

        if not assessment:
            raise HTTPException(
                status_code=404,
                detail="Assessment stage not found",
            )

        application = db.query(Application).filter(
            Application.application_id == payload.application_id,
        ).first()

        if not application:
            raise HTTPException(
                status_code=404,
                detail="Application not found",
            )

        job_description = db.query(JobDescription).filter(
            JobDescription.jd_id == application.jd_id,
        ).first()

        if not job_description:
            raise HTTPException(
                status_code=404,
                detail="Job description not found",
            )

        candidate = db.query(Candidate).filter(
            Candidate.candidate_id == application.candidate_id,
        ).first()

        if not candidate:
            raise HTTPException(
                status_code=404,
                detail="Candidate not found",
            )

        recruiter_email = job_description.created_by_email
        recruiter_name = job_description.created_by or "Recruiter"

        if not recruiter_email:
            raise HTTPException(
                status_code=400,
                detail="Recruiter email not found",
            )

        assessment.status = "Submitted"
        assessment.final_recommendation = final_recommendation
        assessment.discrepency_reason = payload.discrepency_reason
        assessment.assessment_taken_by = current_user.full_name

        # Flush DB changes but do not commit yet
        db.flush()

        candidate_name = candidate.full_name
        assessment_link = settings.intellihire_base_url

        send_email_or_raise(
            send_assessment_completed_email,
            recruiter_email=recruiter_email,
            recruiter_name=recruiter_name,
            candidate_name=candidate_name,
            req_id=job_description.req_id or "-",
            jd_title=job_description.title or "-",
            round_name=round_name,
            interviewer_name=current_user.full_name,
            recommendation=final_recommendation,
            assessment_link=assessment_link,
        )

        send_email_or_raise(
            send_assessment_submission_confirmation_email,
            interviewer_email=current_user.email,
            interviewer_name=current_user.full_name,
            candidate_name=candidate.full_name,
            round_name=round_name,
            recommendation=final_recommendation,
        )

        db.commit()
        db.refresh(assessment)

        return {
            "message": "Final recommendation saved successfully",
            "assessment_id": assessment.assessment_id,
            "application_id": assessment.application_id,
            "stage_code": assessment.stage_code,
            "status": assessment.status,
            "overall_score": float(assessment.overall_score)
            if assessment.overall_score is not None
            else None,
            "final_recommendation": assessment.final_recommendation,
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception as e:
        db.rollback()

        logger.exception("Failed to update final recommendation: %s", str(e))

        raise HTTPException(
            status_code=500,
            detail={
                "error": "Failed to update final recommendation",
            },
        )



@router.get("/downloadlink/get-download-link/uuid_name={uuid_name}")
def get_download_link(uuid_name : str,current_user: CurrentUser = Depends(require_any_role)):

    try:
        settings = Settings()
        download_link = generate_download_link(
                settings,
                uuid_name if settings.file_storage_mode == "s3" else None,
                uuid_name if settings.file_storage_mode != "s3" else None,
        )
        return download_link


    except Exception as e:
        
        
        root_cause = str(e) or type(e).__name__
        
        logger.exception(f"Failed to get link : {e}")

        
        raise HTTPException(
                status_code=500,
                detail={
                    "error": f"Failed!",
                   
                },
            )




@router.post("/assessments/llm/generate-competencies")
def generate_assessment_competencies(
    payload: GenerateCompetenciesRequest,
    current_user: CurrentUser = Depends(require_any_role),
    db: Session = Depends(get_db),
):
    try:
        stage_code = normalize_stage_code(payload.stage_code)

        stage_information = str(payload.stage_information or "").strip()

        mandatory_skills = [
            str(skill).strip()
            for skill in payload.mandatory_skills
            if str(skill).strip()
        ]

        if not mandatory_skills:
            raise HTTPException(
                status_code=400,
                detail="mandatory_skills must contain at least one valid skill",
            )

        if stage_code == "TECHNICAL_ROUND_1":
            if not payload.req_id:
                raise HTTPException(
                    status_code=400,
                    detail="req_id is required for TECHNICAL_ROUND_1",
                )

            try:
                req_id = int(payload.req_id)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="req_id must be a valid integer",
                )

            existing_competencies = _get_existing_competencies_from_question_bank(
                db=db,
                req_id=req_id,
                stage_code=stage_code,
            )

            if existing_competencies:
                return {
                    "competencies": existing_competencies
                }

            generated = _llm_generate_competencies(
                stage_code=stage_code,
                stage_information=stage_information,
                mandatory_skills=mandatory_skills,
            )

            competencies = _format_llm_generated_competencies(generated)

            _store_competencies_in_question_bank(
                db=db,
                req_id=req_id,
                stage_code=stage_code,
                competencies=competencies,
            )

            return {
                "competencies": competencies
            }

        generated = _llm_generate_competencies(
            stage_code=stage_code,
            stage_information=stage_information,
            mandatory_skills=mandatory_skills,
        )

        return {
            "competencies": _format_llm_generated_competencies(generated)
        }

    except HTTPException:
        raise

    except Exception as e:
        root_cause = str(e) or type(e).__name__

        logger.exception(f"Failed to generate llm competencies: {e}")

        raise HTTPException(
            status_code=500,
            detail={
                "error":f"Failed to generate llm competencies, {str(e)}",
                "cause": root_cause,
            },
        )

@router.get("/getlistofallquestions")
def get_all_assessment_questions(db: Session = Depends(get_db),current_user: CurrentUser = Depends(require_any_role),):
    try:
        questions = (
            db.query(AssessmentQuestionBank)
            .order_by(
                AssessmentQuestionBank.stage_code.asc(),
                AssessmentQuestionBank.display_order.asc(),
                AssessmentQuestionBank.question_id.asc(),
            )
            .all()
        )

        return {
            "success": True,
            "count": len(questions),
            "data": [
                {
                    "question_id": q.question_id,
                    "stage_code": q.stage_code,
                    "section_type": q.section_type,
                    "question": q.question,
                    "expected_answer": q.expected_answer,
                    "topic": q.topic,
                    "difficulty": q.difficulty,
                    "source": q.source,
                    "is_active": q.is_active,
                    "display_order": q.display_order,
                    "answer_type": q.answer_type,
                    "created_at": q.created_at,
                    "updated_at": q.updated_at,
                }
                for q in questions
            ],
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch assessment question bank: {str(e)}",
        )
    


from fastapi import Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session




@router.get("/applications/all-stages/application-id={application_id}/stage_code={stage_code}")
def get_application_stages(
    application_id: int,
    stage_code: str | None = None,
    current_user: CurrentUser = Depends(require_any_role),
    db: Session = Depends(get_db),
):
    # 1. Get JD stages for this application
    app_jd_stmt = (
        select(JobDescription.stages)
        .join(Application, Application.jd_id == JobDescription.jd_id)
        .where(Application.application_id == application_id)
    )

    jd_stages = db.execute(app_jd_stmt).scalar_one_or_none()

    if jd_stages is None:
        raise HTTPException(
            status_code=404,
            detail="Application or job description not found",
        )

    jd_stages = jd_stages or []

    logger.info("JD stages: %s", jd_stages)

    # 2. Create lookup for stage information using stage number
    stage_info_by_number = {
        int(stage.get("stage_number")): stage.get("stage_information")
        for stage in jd_stages
        if stage.get("stage_number") is not None
    }

    # 3. Create lookup for stage information using stage name
    stage_info_by_name = {
        str(stage.get("stage_name", "")).strip().lower(): stage.get("stage_information")
        for stage in jd_stages
        if stage.get("stage_name") is not None
    }

    # 4. Get assessment feedback fields for this application
    assessment_stmt = (
        select(
            Assessment.stage_code,
            Assessment.summary_feedback,
            Assessment.areas_of_concern,
            Assessment.areas_to_probe_in_next_round,
            Assessment.overall_score,
            Assessment.updated_at,
            Assessment.assessment_taken_by,
            Assessment.final_recommendation
        )
        .where(Assessment.application_id == application_id)
    )

    assessment_rows = db.execute(assessment_stmt).mappings().all()

    assessment_by_stage_code = {
        str(row["stage_code"]).strip().lower(): row
        for row in assessment_rows
        if row["stage_code"] is not None
    }

    # 5. Get panel assignment + employee name for this application
    panel_stmt = (
        select(
            PanelAssignment.panel_stage,
            PanelAssignment.hris_employee_id,
            EmployeeMaster.EmpName.label("assessment_taker"),
            PanelAssignment.is_primary,
            PanelAssignment.sequence_no,
        )
        .join(
            EmployeeMaster,
            EmployeeMaster.EmpId == PanelAssignment.hris_employee_id,
        )
        .where(
            PanelAssignment.application_id == application_id,
            PanelAssignment.is_active.is_(True),
        )
        .order_by(
            PanelAssignment.panel_stage.asc(),
            PanelAssignment.is_primary.desc(),
            PanelAssignment.sequence_no.asc(),
        )
    )

    panel_rows = db.execute(panel_stmt).mappings().all()

    # 6. Create lookup: stage -> employee name
    # If multiple panelists exist for same stage:
    # primary panelist comes first.
    # If no primary, lowest sequence_no comes first.
    panel_by_stage = {}

    for row in panel_rows:
        panel_stage_key = str(row["panel_stage"]).strip().lower()

        if panel_stage_key not in panel_by_stage:
            panel_by_stage[panel_stage_key] = {
                "assessment_taker": row["assessment_taker"],
                "hris_employee_id": row["hris_employee_id"],
            }

    # 7. Get stages from ApplicationStageHistory
    stage_history_stmt = (
        select(
            func.row_number()
            .over(order_by=ApplicationStageHistory.changed_at.asc())
            .label("stage_number"),
            ApplicationStageHistory.to_stage.label("stage_name"),
        )
        .where(ApplicationStageHistory.application_id == application_id)
        .order_by(ApplicationStageHistory.changed_at.asc())
    )

    result = db.execute(stage_history_stmt).mappings().all()

    if not result:
        return []

    target_stage_code = stage_code.strip().lower() if stage_code else None
    found_stage_code = False

    response = []

    # 8. Build final response
    for row in result:
        stage_number = row["stage_number"]
        stage_name = row["stage_name"]

        normalized_stage_name = str(stage_name).strip().lower()

        # Get stage info from JD stages
        stage_information = stage_info_by_number.get(stage_number)

        if stage_information is None:
            stage_information = stage_info_by_name.get(normalized_stage_name)

        # Get assessment feedback for this stage
        assessment_data = assessment_by_stage_code.get(normalized_stage_name)

        # Get panel/assessment taker for this stage
        panel_data = panel_by_stage.get(normalized_stage_name)

        response.append(
            {
                "stage_number": stage_number,
                "stage_name": stage_name,
                "stageinfo": stage_information,

                "summary_feedback": (
                    assessment_data["summary_feedback"]
                    if assessment_data
                    else None
                ),
                "areas_of_concern": (
                    assessment_data["areas_of_concern"]
                    if assessment_data
                    else None
                ),
                "areas_to_probe_in_next_round": (
                    assessment_data["areas_to_probe_in_next_round"]
                    if assessment_data
                    else None
                ),
                "assessment_overall_score":(
                    assessment_data["overall_score"]
                    if assessment_data
                    else None
                ),

                # "assessment_taker": (
                #     panel_data["assessment_taker"]
                #     if panel_data
                #     else None
                # ),
                "assessment_submission_time":(
                    assessment_data["updated_at"]
                    if assessment_data
                    else None,
                ),
                "assessment_taker":(
                    assessment_data["assessment_taken_by"]
                    if assessment_data
                    else None,
                ),
                "final_recommendation":(
                    assessment_data["final_recommendation"]
                    if assessment_data
                    else None,
                )
            }
        )

        # stage_code acts as full stop
        if target_stage_code and normalized_stage_name == target_stage_code:
            found_stage_code = True
            break

    # 9. If stage_code was passed but not found in stage history
    if target_stage_code and not found_stage_code:
        raise HTTPException(
            status_code=404,
            detail="stage_code not found in application stage history",
        )

    return response





# @router.post(
#     "/ceo-round-assessment/save-submit",
#     response_model=CEORoundAssessmentSaveSubmitResponse,
# )
# def save_or_submit_ceo_round_assessment(
#     payload: CEORoundAssessmentSaveSubmitRequest,
#     current_user: CurrentUser = Depends(require_any_role),
#     db: Session = Depends(get_db),
# ):
#     application_id = payload.application_id
#     stage_code = payload.stage_code.strip().upper()

#     # 1. Validate stage
#     if stage_code != "CEO_ROUND":
#         raise HTTPException(
#             status_code=400,
#             detail="This API is only allowed for CEO_ROUND assessment.",
#         )

#     # 2. Validate submit data
#     if payload.flag == 2:
#         # if not payload.summary_feedback:
#         #     raise HTTPException(
#         #         status_code=400,
#         #         detail="summary_feedback is required while submitting CEO round assessment.",
#         #     )

#         if not payload.final_recommendation:
#             raise HTTPException(
#                 status_code=400,
#                 detail="final_recommendation is required while submitting CEO round assessment.",
#             )

#     # 3. Check application exists
#     application_stmt = (
#         select(Application.application_id)
#         .where(Application.application_id == application_id)
#     )

#     application_exists = db.execute(application_stmt).scalar_one_or_none()

#     if application_exists is None:
#         raise HTTPException(
#             status_code=404,
#             detail="Application not found.",
#         )

#     # 4. Check if assessment already exists
#     assessment_stmt = (
#         select(Assessment)
#         .where(
#             Assessment.application_id == application_id,
#             Assessment.stage_code == stage_code,
#         )
#     )

#     assessment = db.execute(assessment_stmt).scalar_one_or_none()

#     # 5. Decide status
#     assessment_status = "Saved" if payload.flag == 1 else "Submitted"

#     # 6. Update existing assessment
#     if assessment:
#         assessment.summary_feedback = payload.summary_feedback
#         assessment.final_recommendation = payload.final_recommendation
#         assessment.status = assessment_status

#     # 7. Create new assessment
#     else:
#         assessment = Assessment(
#             application_id=application_id,
#             stage_code=stage_code,
#             summary_feedback=payload.summary_feedback,
#             final_recommendation=payload.final_recommendation,
#             status=assessment_status,
#         )

#         db.add(assessment)

#     db.commit()
#     db.refresh(assessment)

#     return {
#         "message": (
#             "CEO round assessment saved successfully."
#             if payload.flag == 1
#             else "CEO round assessment submitted successfully."
#         ),
#         "assessment_id": assessment.assessment_id,
#         "application_id": assessment.application_id,
#         "stage_code": assessment.stage_code,
#         "summary_feedback": assessment.summary_feedback,
#         "final_recommendation": assessment.final_recommendation,
#         "status": assessment.status,
#     }



@router.post(
    "/ceo-round-assessment/save-submit",
    response_model=CEORoundAssessmentSaveSubmitResponse,
)
def save_or_submit_ceo_round_assessment(
    payload: CEORoundAssessmentSaveSubmitRequest,
    current_user: CurrentUser = Depends(require_any_role),
    db: Session = Depends(get_db),
):
    try:
        settings = get_settings()

        application_id = payload.application_id
        stage_code = payload.stage_code.strip().upper()

        # 1. Validate stage
        if stage_code != "CEO_ROUND":
            raise HTTPException(
                status_code=400,
                detail="This API is only allowed for CEO_ROUND assessment.",
            )

        # 2. Validate submit data
        if payload.flag == 2:
            if not payload.final_recommendation:
                raise HTTPException(
                    status_code=400,
                    detail="final_recommendation is required while submitting CEO round assessment.",
                )

        # 3. Check application exists
        application_stmt = (
            select(Application)
            .where(Application.application_id == application_id)
        )

        application = db.execute(application_stmt).scalar_one_or_none()

        if application is None:
            raise HTTPException(
                status_code=404,
                detail="Application not found.",
            )

        # 4. Check if assessment already exists
        assessment_stmt = (
            select(Assessment)
            .where(
                Assessment.application_id == application_id,
                Assessment.stage_code == stage_code,
            )
        )

        assessment = db.execute(assessment_stmt).scalar_one_or_none()

        # 5. Decide status
        assessment_status = "Saved" if payload.flag == 1 else "Submitted"

        # 6. Update existing assessment
        if assessment:
            assessment.summary_feedback = payload.summary_feedback
            assessment.final_recommendation = payload.final_recommendation
            assessment.status = assessment_status
            assessment.assessment_taken_by = current_user.full_name

        # 7. Create new assessment
        else:
            assessment = Assessment(
                application_id=application_id,
                stage_code=stage_code,
                summary_feedback=payload.summary_feedback,
                final_recommendation=payload.final_recommendation,
                status=assessment_status,
                assessment_taken_by=current_user.full_name,
            )

            db.add(assessment)

        # Flush before sending email so assessment_id is available if needed
        db.flush()

        # 8. Send email only when assessment is submitted
        if payload.flag == 2:
            candidate = (
                db.execute(
                    select(Candidate).where(
                        Candidate.candidate_id == application.candidate_id
                    )
                )
                .scalar_one_or_none()
            )

            if not candidate:
                raise HTTPException(
                    status_code=404,
                    detail="Candidate not found.",
                )

            job_description = (
                db.execute(
                    select(JobDescription).where(
                        JobDescription.jd_id == application.jd_id
                    )
                )
                .scalar_one_or_none()
            )

            if not job_description:
                raise HTTPException(
                    status_code=404,
                    detail="Job description not found.",
                )

            if not job_description.created_by_email:
                raise HTTPException(
                    status_code=400,
                    detail="Recruiter email not found.",
                )

            send_email_or_raise(
                send_assessment_completed_email,
                recruiter_email=job_description.created_by_email,
                recruiter_name=job_description.created_by or "Recruiter",
                candidate_name=candidate.full_name,
                req_id=job_description.req_id or "-",
                jd_title=job_description.title or "-",
                round_name=stage_code,
                interviewer_name=current_user.full_name,
                recommendation=assessment.final_recommendation,
                assessment_link=settings.intellihire_base_url,
            )

            send_email_or_raise(
                send_assessment_submission_confirmation_email,
                interviewer_email=current_user.email,
                interviewer_name=current_user.full_name,
                candidate_name=candidate.full_name,
                round_name=stage_code,
                recommendation=assessment.final_recommendation,
            )

        db.commit()
        db.refresh(assessment)

        return {
            "message": (
                "CEO round assessment saved successfully."
                if payload.flag == 1
                else "CEO round assessment submitted successfully."
            ),
            "assessment_id": assessment.assessment_id,
            "application_id": assessment.application_id,
            "stage_code": assessment.stage_code,
            "summary_feedback": assessment.summary_feedback,
            "final_recommendation": assessment.final_recommendation,
            "status": assessment.status,
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception as e:
        db.rollback()

        logger.exception(
            "Failed to save or submit CEO round assessment: %s",
            str(e),
        )

        raise HTTPException(
            status_code=500,
            detail="Failed to save or submit CEO round assessment.",
        )



@router.get("/applications/ceo-ai-summary/application_id={application_id}/stage_code={stage_code}")
def get_or_generate_ceo_assessment_summary(
    application_id: int,
    stage_code: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    ceo_stage_code = stage_code.strip()
    normalized_ceo_stage_code = ceo_stage_code.lower()


    ceo_assessment_stmt = (
        select(Assessment)
        .where(
            Assessment.application_id == application_id,
            func.lower(func.trim(Assessment.stage_code))
            == normalized_ceo_stage_code,
        )
    )

    ceo_assessment = db.execute(ceo_assessment_stmt).scalar_one_or_none()

    # Existing generated CEO summary found.
    # Return saved data directly. No LLM call.
    if ceo_assessment and ceo_assessment.ai_assessment_summary:
        return ceo_assessment.ai_assessment_summary

    application_stmt = (
        select(Application)
        .where(Application.application_id == application_id)
    )

    application = db.execute(application_stmt).scalar_one_or_none()

    if application is None:
        raise HTTPException(
            status_code=404,
            detail="Application not found",
        )

    jd_stmt = (
        select(JobDescription)
        .join(Application, Application.jd_id == JobDescription.jd_id)
        .where(Application.application_id == application_id)
    )

    jd = db.execute(jd_stmt).scalar_one_or_none()

    if jd is None:
        raise HTTPException(
            status_code=404,
            detail="Application or job description not found",
        )

    previous_assessments_context = build_previous_assessments_context(
        db=db,
        application_id=application_id,
        ceo_stage_code=ceo_stage_code,
    )

    if not previous_assessments_context:
        raise HTTPException(
            status_code=400,
            detail="No previous assessments found. CEO AI summary cannot be generated.",
        )

    # Create CEO assessment row only if missing.
    if ceo_assessment is None:
        ceo_assessment = Assessment(
            application_id=application_id,
            stage_code=ceo_stage_code,
            # stage_level=CEO_STAGE_LEVEL,
            assessment_sections={},
            transcript_s3_key=None,
            transcript_text=None,
            overall_score=None,
            summary_feedback=None,
            final_recommendation=None,
            ai_assessment_summary=None,
            ai_summary_generated_at=None,
            status="Completed",
            discrepency_reason=None,
            areas_of_concern=None,
            areas_to_probe_in_next_round=None,
            problem_statements={},
            assessment_taken_by="AI",
        )

        db.add(ceo_assessment)

        try:
            db.flush()

        except IntegrityError:
            db.rollback()

            # Handles concurrent first-call requests.
            ceo_assessment = db.execute(
                ceo_assessment_stmt
            ).scalar_one_or_none()

            if ceo_assessment and ceo_assessment.ai_assessment_summary:
                return ceo_assessment.ai_assessment_summary

            if ceo_assessment is None:
                raise HTTPException(
                    status_code=409,
                    detail="Unable to create CEO assessment row due to concurrent request.",
                )

    jd_context = build_jd_context(jd)
    resume_context = build_resume_context(application)

    ai_summary = generate_ceo_assessment_ai_summary_with_llm(
        settings=settings,
        jd_context=jd_context,
        resume_context=resume_context,
        ceo_stage_code=ceo_stage_code,
        previous_assessments_context=previous_assessments_context,
    )

    ceo_assessment.ai_assessment_summary = ai_summary
    ceo_assessment.ai_summary_generated_at = datetime.now()

    # Make CEO row compatible/readable in existing stage APIs.
    ceo_assessment.summary_feedback = ai_summary.get("final_ai_summary")
    ceo_assessment.areas_of_concern = "\n".join(
        ai_summary.get("overall_risks") or []
    )
    ceo_assessment.areas_to_probe_in_next_round = None

    ai_score = ai_summary.get("overall_score_out_of_10")

    if ai_score is not None:
        try:
            ai_score_decimal = Decimal(str(ai_score))

            if Decimal("0") <= ai_score_decimal <= Decimal("10"):
                ceo_assessment.overall_score = ai_score_decimal
            else:
                ceo_assessment.overall_score = None

        except Exception:
            ceo_assessment.overall_score = None
    else:
        ceo_assessment.overall_score = None

    # ai_signal = ai_summary.get("ai_recommendation_signal")

    # if ai_signal == "recommended":
    #     ceo_assessment.final_recommendation = "Recommended"
    # elif ai_signal == "hold":
    #     ceo_assessment.final_recommendation = "Hold"
    # elif ai_signal == "not recommended":
    #     ceo_assessment.final_recommendation = "Not Recommended"
    # else:
    #     ceo_assessment.final_recommendation = "Insufficient Evidence"

    # ceo_assessment.status = "Completed"
    # ceo_assessment.assessment_taken_by = "AI"

    db.add(ceo_assessment)
    db.commit()
    db.refresh(ceo_assessment)

    return ceo_assessment.ai_assessment_summary