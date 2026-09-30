"""Run once with API and judge stopped, after backing up the database.
Creates additive tables, repairs legacy counters, and recovers pending jobs.
"""

from sqlalchemy import select, func
from shared.core import Base, engine, SessionLocal
from shared.models import Problem, Submission, Verdict, JudgeJob

Base.metadata.create_all(bind=engine)
with SessionLocal.begin() as db:
    for p in db.query(Problem).with_for_update().all():
        p.total_submissions = db.query(Submission).filter_by(problem_id=p.id).count()
        p.accepted_submissions = (
            db.query(Submission)
            .filter_by(problem_id=p.id, verdict=Verdict.ACCEPTED)
            .count()
        )
    for s in db.query(Submission).filter_by(verdict=Verdict.PENDING).all():
        if not db.get(JudgeJob, s.id):
            db.add(JudgeJob(submission_id=s.id))
print("Additive schema, legacy counters, and pending jobs reconciled.")
