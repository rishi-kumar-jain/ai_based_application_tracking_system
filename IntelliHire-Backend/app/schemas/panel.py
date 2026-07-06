from pydantic import BaseModel, Field
from typing import List, Optional

class PanelistItem(BaseModel):
    hris_employee_id: int
    is_primary: Optional[bool] = False

class AssignPanelistsRequest(BaseModel):
    application_id: int
    panel_stage: str
    panelists: List[PanelistItem] = Field(default_factory=list)
    candidate_purpose: str | None = None
