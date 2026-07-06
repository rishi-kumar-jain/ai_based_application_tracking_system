from typing import List, Optional
from pydantic import BaseModel, Field

class ProblemStatementItem(BaseModel):
    question: str
    key_kpis: List[str] = Field(default_factory=list)
    is_mandatory: bool = True


class JobDescriptionSaveRequest(BaseModel):
    jd_id: Optional[int] = None
    req_id: str
    grade: str
    title: Optional[str] = None
    location: Optional[str] = None
    experience: Optional[str] = None
    role_summary: Optional[str] = None
    responsibilities: List[str] = Field(default_factory=list)
    mandatory_skills: List[str] = Field(default_factory=list)
    good_to_have_skills: List[str] = Field(default_factory=list)
    qualifications : List[str] = Field(default_factory=list)
    status: str = "draft"
    jd_stage : str
    lob_id:  Optional[int] = None
    lob:  Optional[str] = None
    vertical:  Optional[str] = None
    
    

class ParseUploadedJdRequest(BaseModel):
    jd_id: int
    jd_stage: str



class ProblemStatementsSaveRequest(BaseModel):
    jd_id: int
    problem_statements: List[ProblemStatementItem]
    status: str = "draft"
    jd_stage: str
