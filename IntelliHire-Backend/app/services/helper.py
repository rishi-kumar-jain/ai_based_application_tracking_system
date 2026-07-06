import json
import uuid

from sqlalchemy.orm import Session

from app.models.assessments import AssessmentQuestionBank


def normalizenone(value):
    return value if value not in ("", None) else None




def payload_to_string(payload) -> str:
    """
    Convert Pydantic payload to a JSON string suitable for LLM input.
    """
    return json.dumps(payload.model_dump(), indent=2)


