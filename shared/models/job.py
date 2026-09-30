from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from ..core import Base


class JudgeJob(Base):
    """Transactional outbox and renewable execution lease, one job per submission."""

    __tablename__ = "judge_jobs"
    submission_id = Column(
        ForeignKey("submissions.id", ondelete="CASCADE"), primary_key=True
    )
    attempts = Column(Integer, nullable=False, default=0)
    lease_token = Column(String, nullable=True)
    lease_until = Column(DateTime(timezone=True), nullable=True, index=True)
    next_dispatch = Column(DateTime(timezone=True), nullable=True)
    container_id = Column(String, nullable=True)


class StorageDeletion(Base):
    """Deletion intent is committed with metadata deletion, retried by the judge."""

    __tablename__ = "storage_deletions"
    id = Column(Integer, primary_key=True)
    kind = Column(String, nullable=False)
    object_key = Column(String, nullable=False)
