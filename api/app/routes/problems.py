import io
import json
import zipfile
from pathlib import PurePosixPath
from typing import List
from pydantic import ValidationError
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    UploadFile,
    Form,
    File,
    Query,
    Response,
)
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from ..schemas.problems import (
    ProblemResponse,
    ProblemDetailResponse,
    ProblemArrayDataValidator,
    TagCreate,
    ProblemCreateResponse,
    ProblemPage,
)
from ..utils import oauth2
from ..database import get_db
from shared.core import get_storage_testcases
from shared.models import Problem, Category, TestCase, Submission, User, Difficulty
from shared.jobs import queue_deletion
from config import (
    MAX_UPLOAD_BYTES,
    MAX_TESTCASE_BYTES,
    MAX_TESTCASE_TOTAL_BYTES,
    MAX_TESTCASES,
    MAX_TIME_LIMIT_SEC,
    MAX_MEMORY_LIMIT_MB,
)

router = APIRouter(prefix="/problems", tags=["Problems"])


@router.post("/tag", status_code=201, response_model=TagCreate)
def create_tag(
    details: TagCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(oauth2.get_current_admin),
):
    tag = Category(**details.model_dump())
    db.add(tag)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Tag already exists")
    return details


@router.get("/tags", response_model=List[TagCreate])
def get_tags(db: Session = Depends(get_db)):
    return [
        {"name": t.name, "slug": t.slug}
        for t in db.query(Category).order_by(Category.name).all()
    ]


@router.get("/", response_model=List[ProblemResponse] | ProblemPage)
def get_problems(
    response: Response,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    title: str | None = Query(None, max_length=100),
    difficulty: Difficulty | None = None,
    tag: str | None = Query(None, max_length=40),
    metadata: bool = False,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(oauth2.get_optional_current_admin),
):
    query = db.query(Problem)
    if not current_user:
        query = query.filter(Problem.visibility.is_(True))
    if title:
        query = query.filter(Problem.title.icontains(title, autoescape=True))
    if difficulty:
        query = query.filter(Problem.difficulty == difficulty)
    if tag:
        query = query.filter(Problem.tags.any(Category.slug == tag))
    total = query.count()
    items = [
        {
            "id": p.id,
            "title": p.title,
            "difficulty": p.difficulty,
            "tags": [t.slug for t in p.tags],
            "accepted_submissions": p.accepted_submissions,
            "total_submissions": p.total_submissions,
        }
        for p in query.order_by(Problem.id)
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    ]
    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Has-More"] = str(page * limit < total).lower()
    return (
        {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
            "has_more": page * limit < total,
        }
        if metadata
        else items
    )


@router.get("/{problem_id}", response_model=ProblemDetailResponse)
def get_problem_by_id(
    problem_id: str,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(oauth2.get_optional_current_admin),
):
    query = db.query(Problem).filter(Problem.id == problem_id)
    if not current_user:
        query = query.filter(Problem.visibility.is_(True))
    p = query.first()
    if not p:
        raise HTTPException(404, "Problem not found")
    return {
        **{
            name: getattr(p, name)
            for name in ProblemDetailResponse.model_fields
            if name != "tags"
        },
        "tags": [t.slug for t in p.tags],
    }


def read_testcases(content):
    """Validate before storage writes; never extract user paths onto a filesystem."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            files = [f for f in archive.infolist() if not f.is_dir()]
            if not files or len(files) > MAX_TESTCASES * 2:
                raise ValueError("Provide between 1 and 100 testcase pairs")
            if len({f.filename for f in files}) != len(files):
                raise ValueError("Duplicate ZIP entries")
            if sum(f.file_size for f in files) > MAX_TESTCASE_TOTAL_BYTES:
                raise ValueError("Expanded ZIP is too large")
            groups = {"inputs": {}, "outputs": {}}
            roots = set()
            for info in files:
                path = PurePosixPath(info.filename)
                parts = path.parts
                if (
                    path.is_absolute()
                    or ".." in parts
                    or len(parts) not in (2, 3)
                    or parts[-2] not in groups
                ):
                    raise ValueError(
                        "ZIP must contain inputs/ and outputs/ in the root or one parent folder"
                    )
                roots.add(parts[0] if len(parts) == 3 else "")
                if info.file_size > MAX_TESTCASE_BYTES or info.flag_bits & 1:
                    raise ValueError("Testcase is too large or encrypted")
                if parts[-1] in groups[parts[-2]]:
                    raise ValueError("Duplicate testcase filename")
                with archive.open(info) as source:
                    data = source.read(MAX_TESTCASE_BYTES + 1)
                if len(data) > MAX_TESTCASE_BYTES:
                    raise ValueError("Testcase is too large")
                data.decode("utf-8")
                groups[parts[-2]][parts[-1]] = data
            if (
                len(roots) != 1
                or not groups["inputs"]
                or groups["inputs"].keys() != groups["outputs"].keys()
            ):
                raise ValueError("Each input must have a matching output filename")
            return [
                (name, groups["inputs"][name], groups["outputs"][name])
                for name in sorted(groups["inputs"])
            ]
    except (ValueError, zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise HTTPException(422, str(exc))


@router.post("/", status_code=201, response_model=ProblemCreateResponse)
async def create_problem(
    id: str = Form(..., pattern=r"^[A-Za-z0-9_-]{1,6}$"),
    title: str = Form(..., min_length=1, max_length=150),
    description: str = Form(..., min_length=1, max_length=50000),
    difficulty: Difficulty = Form(...),
    constraints: str = Form(..., max_length=10000),
    tags: str = Form(..., max_length=2000),
    sample_io: str = Form(..., max_length=20000),
    input_desc: str = Form(..., max_length=10000),
    output_desc: str = Form(..., max_length=10000),
    explanation: str | None = Form(None, max_length=20000),
    memory_limit_mb: int = Form(..., ge=16, le=MAX_MEMORY_LIMIT_MB),
    time_limit_sec: int = Form(..., ge=1, le=MAX_TIME_LIMIT_SEC),
    visibility: bool = Form(False),
    source: str | None = Form(None, max_length=1000),
    editorial: str | None = Form(None, max_length=50000),
    tests_zip: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(oauth2.get_current_admin),
):
    if db.get(Problem, id):
        raise HTTPException(409, "Problem ID already exists")
    if not (tests_zip.filename or "").lower().endswith(".zip"):
        raise HTTPException(422, "A ZIP file is required")
    content = await tests_zip.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "ZIP exceeds upload size limit")
    cases = read_testcases(content)
    try:
        arrays = ProblemArrayDataValidator(
            tags=json.loads(tags),
            constraints=json.loads(constraints),
            sample_io=json.loads(sample_io),
        )
    except (ValueError, ValidationError):
        raise HTTPException(422, "Invalid tags, constraints, or sample examples")
    categories = db.query(Category).filter(Category.slug.in_(arrays.tags)).all()
    if len(categories) != len(arrays.tags):
        raise HTTPException(422, "Tags must exist and must not be duplicated")
    p = Problem(
        id=id,
        title=title,
        description=description,
        difficulty=difficulty,
        constraints=arrays.constraints,
        tags=categories,
        sample_io=arrays.sample_io,
        input_desc=input_desc,
        output_desc=output_desc,
        explanation=explanation,
        memory_limit_mb=memory_limit_mb,
        time_limit_sec=time_limit_sec,
        visibility=visibility,
        source=source,
        editorial=editorial,
    )
    uploaded = []
    try:
        db.add(p)
        db.flush()
        storage = get_storage_testcases()
        for name, inp, out in cases:
            ik = storage.upload_bytes(problem_id=id, filename=name, data=inp)
            uploaded.append(ik)
            ok = storage.upload_bytes(problem_id=id, filename=name, data=out)
            uploaded.append(ok)
            db.add(TestCase(problem_id=id, input_key=ik, output_key=ok))
        db.commit()
    except Exception as exc:
        db.rollback()
        for key in uploaded:
            queue_deletion(db, "testcase", key)
        db.commit()
        raise HTTPException(
            409 if isinstance(exc, IntegrityError) else 503,
            "Could not create problem; uploaded objects are scheduled for cleanup",
        )
    return {
        "id": id,
        "title": title,
        "difficulty": difficulty,
        "tags": arrays.tags,
        "testcases": len(cases),
    }


@router.delete("/", status_code=204)
def delete_problem(
    problem_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(oauth2.get_current_admin),
):
    p = db.query(Problem).filter_by(id=problem_id).with_for_update().first()
    if not p:
        raise HTTPException(404, "Problem not found")
    for case in p.testcases:
        queue_deletion(db, "testcase", case.input_key)
        queue_deletion(db, "testcase", case.output_key)
    for sub in p.submissions:
        queue_deletion(db, "submission", sub.code_object_key)
    db.delete(p)
    db.commit()
