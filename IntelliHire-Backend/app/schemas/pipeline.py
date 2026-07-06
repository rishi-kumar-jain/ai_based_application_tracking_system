from pydantic import BaseModel, Field
from typing import List, Optional

class AddToPipelineRequest(BaseModel):
    jd_id: int
    candidate_id: int
    resume_id: Optional[int] = None
    screening_result_id: Optional[int] = None


class MovePipelineRequest(BaseModel):
    application_id: int
    to_stage: str
    status: str | None = "IN_PROGRESS"
    changed_by: str | None = None
    remarks: str | None = None




class BulkAddToPipelineRequest(BaseModel):
    screening_ids: List[int]
    recruiter_id: Optional[str]


class AddStageRequest(BaseModel):
    req_id: str
    stage_name: str = Field(..., min_length=1, max_length=100)




class StageItem(BaseModel):
    stage_name: str
    stage_information: Optional[str] = None

class AddStagesRequest(BaseModel):
    req_id: str
    stages: List[StageItem]



class DynamicStageItem(BaseModel):
    stage_number: int
    stage_name: str
    stage_information: Optional[str] = None

class DynamicAddStagesRequest(BaseModel):
    req_id: str
    stages: List[DynamicStageItem]


