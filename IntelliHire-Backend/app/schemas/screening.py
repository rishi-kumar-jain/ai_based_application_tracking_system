from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class ScreeningResultsDeleteRequest(BaseModel):
    screening_result_ids: list[int] = Field(..., min_length=1)
    delete_pipeline_records: bool = False
    delete_resume_records: bool = False



class ScreeningWeightsSaveRequest(BaseModel):
    jd_id: int

    experience: float = Field(..., ge=0, le=100)
    responsibilities: float = Field(..., ge=0, le=100)
    projects: float = Field(..., ge=0, le=100)
    location: float = Field(..., ge=0, le=100)
    certification: float = Field(..., ge=0, le=100)
    education: float = Field(..., ge=0, le=100)

    changed_by: Optional[str] = None

    @model_validator(mode="after")
    def validate_total_weight(self):
        total = (
            self.experience
            + self.responsibilities
            + self.projects
            + self.location
            + self.certification
            + self.education
        )

        if round(total, 2) != 100:
            raise ValueError(f"Screening weights must total 100. Current total is {total}")

        return self

    def to_weights_dict(self) -> dict[str, float]:
        return {
            "experience": self.experience,
            "responsibilities": self.responsibilities,
            "projects": self.projects,
            "location": self.location,
            "certification": self.certification,
            "education": self.education,
        }


class ScreeningWeightsResetRequest(BaseModel):
    jd_id: int
    changed_by: Optional[str] = None


class ScreeningResultManageAction(str, Enum):
    REMOVE_FROM_PIPELINE = "REMOVE_FROM_PIPELINE"
    DELETE_SCREENING_RESULT = "DELETE_SCREENING_RESULT"


class ScreeningResultsManageRequest(BaseModel):
    screening_result_ids: list[int] = Field(..., min_length=1)
    action: ScreeningResultManageAction
    delete_resume_records: bool = True
    changed_by: Optional[str] = None