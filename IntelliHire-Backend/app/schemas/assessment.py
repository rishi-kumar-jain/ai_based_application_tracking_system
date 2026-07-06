from pydantic import BaseModel, Field
from typing import List, Literal, Optional

class AssessmentAnswerItem(BaseModel):
    question: str
    key_kpis: List[str] = Field(default_factory=list)
    rating: int | None = None
    note: str | None = None

class SaveAssessmentRequest(BaseModel):
    application_id: int
    answers: List[AssessmentAnswerItem]
    summary_feedback: Optional[str] = None
    status: str = "draft"


from pydantic import BaseModel, Field
from typing import Any, Optional


class AssessmentSaveRequest(BaseModel):
    application_id: int
    stage_code: str
    assessment_sections: dict[str, Any]
    summary_feedback: str | None = None
    areas_of_concern: str | None = None
    areas_to_probe_in_next_round: str | None = None
    problem_statements: dict[str, Any] = Field(default_factory=dict)



class AssessmentSubmitRequest(BaseModel):
    application_id: int
    stage_code: str
    assessment_sections: dict[str, Any]
    summary_feedback: str
    # final_recommendation: str
    
    areas_of_concern: str | None = None
    areas_to_probe_in_next_round: str | None = None
    problem_statements: dict[str, Any] = Field(default_factory=dict)



class GenerateQuestionsRequest(BaseModel):
    application_id: int
    stage_code: str
    section_type: str
    topic_prompt: Optional[str] = None
    question_count: int = Field(default=1, ge=1, le=10)

    # Frontend should pass all visible unsaved questions too
    existing_questions: list[str] = Field(default_factory=list)


class TranscriptRemoveRequest(BaseModel):
    application_id: int
    stage_code: str



class AssessmentFinalRecommendationRequest(BaseModel):
    application_id: int
    stage_code: str
    final_recommendation: str
    changed_by: Optional[str] = None
    remarks: Optional[str] = None
    discrepency_reason: Optional[str] = None




class GenerateCompetenciesRequest(BaseModel):
    req_id: str
    stage_code: str
    stage_information: str
    mandatory_skills: list[str]




class CEORoundAssessmentSaveSubmitRequest(BaseModel):
    application_id: int = Field(..., description="Application ID")

    stage_code: str = Field(..., description="Stage code, example: CEO_ROUND")

    flag: Literal[1, 2] = Field(
        ...,
        description="1 = Save, 2 = Submit"
    )

    summary_feedback: Optional[str] = Field(
        None,
        description="Summary feedback for CEO round assessment"
    )

    final_recommendation: Optional[str] = Field(
        None,
        max_length=30,
        description="Final recommendation for candidate"
    )


class CEORoundAssessmentSaveSubmitResponse(BaseModel):
    message: str
    assessment_id: int
    application_id: int
    stage_code: str
    summary_feedback: Optional[str] = None
    final_recommendation: Optional[str] = None
    status: str

