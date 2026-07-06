from app.db.base_class import Base

# import models so metadata is populated
from app.models.job_description import JobDescription,HorizontalMaster,EmployeeMaster,ProjectMaster,HRISTranscation
from app.models.candidate import Candidate
from app.models.resume import Resume
from app.models.screening_result import ScreeningResult
from app.models.application import Application, ApplicationStageHistory
from app.models.assessments import Assessment , AssessmentQuestionBank
from app.models.panel_assignments import PanelAssignment

from app.models.screeningweightconfigs import ScreeningWeightConfig


from app.models.auth import Role, UserRole, User