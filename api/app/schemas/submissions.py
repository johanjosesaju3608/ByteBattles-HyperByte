from pydantic import BaseModel, Field, field_validator
from config import MAX_CODE_BYTES
from datetime import datetime

from shared.models import Verdict, Language


class SubmissionCreate(BaseModel):
    problem_id: str
    code: str = Field(min_length=1, max_length=MAX_CODE_BYTES)

    @field_validator("code")
    @classmethod
    def code_size(cls, value):
        if len(value.encode()) > MAX_CODE_BYTES:
            raise ValueError("Source code is too large")
        return value

    language: Language


class SubmissionResponse(BaseModel):
    id: int
    language: Language
    submitted_at: datetime
    problem_id: str
    username: str
    verdict: Verdict
    incorrect_testcase: str | None
    output: str | None
    walltime_ms: int | None
    memory_kb: int | None
    code: str


class SubmissionHeaderResponse(BaseModel):
    id: int
    submitted_at: datetime
    problem_id: str
    username: str
    verdict: Verdict
    walltime_ms: int | None
    memory_kb: int | None

    model_config = {"from_attributes": True}
