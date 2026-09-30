from pydantic import BaseModel, Field
from typing import Dict, List

from shared.models import Difficulty


class ProblemResponse(BaseModel):
    id: str
    title: str
    difficulty: Difficulty
    tags: List[str]
    accepted_submissions: int
    total_submissions: int = 0


class ProblemDetailResponse(ProblemResponse):
    description: str
    constraints: List[str]
    input_desc: str
    output_desc: str
    sample_io: Dict[str, str]
    explanation: str | None

    memory_limit_mb: int
    time_limit_sec: int

    source: str | None
    editorial: str | None
    visibility: bool


class ProblemArrayDataValidator(BaseModel):
    tags: List[str]
    constraints: List[str]
    sample_io: Dict[str, str]


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,39}$")


class ProblemCreateResponse(BaseModel):
    id: str
    title: str
    difficulty: Difficulty
    tags: List[str]
    testcases: int


class ProblemPage(BaseModel):
    items: List[ProblemResponse]
    total: int
    page: int
    limit: int
    has_more: bool
