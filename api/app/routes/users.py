from fastapi import APIRouter, status, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from sqlalchemy import text, update, func
from sqlalchemy.exc import IntegrityError
import secrets
from config import ADMIN_BOOTSTRAP_TOKEN
from shared.jobs import queue_deletion

from ..utils import oauth2, password_manager
from ..schemas.user import UserResponse, UserUpdate, UserResponseUnknown
from ..database import get_db

from shared.models import User, UserType, Problem, Submission, Verdict

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/me", status_code=status.HTTP_200_OK, response_model=UserResponse)
def get_current_user(current_user: User = Depends(oauth2.get_current_user)):
    return current_user


@router.patch("/me", status_code=status.HTTP_200_OK, response_model=UserResponse)
def update_current_user(
    updates: UserUpdate,
    current_user: User = Depends(oauth2.get_current_user),
    db: Session = Depends(get_db),
):

    if updates.password and updates.conf_password:
        if updates.password != updates.conf_password:
            raise HTTPException(
                detail="confirm password and given password don't match",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        else:
            current_user.password_hash = password_manager.hash(updates.password)
    elif updates.password or updates.conf_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)

    if updates.username:
        if (
            current_user.username != updates.username
            and db.query(User).filter(User.username == updates.username).first()
        ):
            raise HTTPException(
                detail="username already in use", status_code=status.HTTP_409_CONFLICT
            )
        else:
            current_user.username = updates.username

    if updates.email:
        if (
            current_user.email != updates.email
            and db.query(User).filter(User.email == updates.email).first()
        ):
            raise HTTPException(
                detail="email already in use", status_code=status.HTTP_409_CONFLICT
            )
        else:
            current_user.email = updates.email

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Username or email already exists")
    db.refresh(current_user)

    return current_user


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_current_user(
    current_user: User = Depends(oauth2.get_current_user), db: Session = Depends(get_db)
):
    if current_user.user_type == UserType.ADMIN:
        db.execute(text("SELECT pg_advisory_xact_lock(7349201)"))
        if db.query(User).filter_by(user_type=UserType.ADMIN).count() <= 1:
            raise HTTPException(
                409, "Promote another administrator before deleting the last admin"
            )
    counts = {}
    locked_submissions = (
        db.query(Submission)
        .filter_by(user_id=current_user.id)
        .order_by(Submission.id)
        .with_for_update()
        .all()
    )
    for sub in locked_submissions:
        queue_deletion(db, "submission", sub.code_object_key)
        total, accepted = counts.get(sub.problem_id, (0, 0))
        counts[sub.problem_id] = (
            total + 1,
            accepted + int(sub.verdict == Verdict.ACCEPTED),
        )
    for pid, (total, accepted) in counts.items():
        db.execute(
            update(Problem)
            .where(Problem.id == pid)
            .values(
                total_submissions=func.greatest(0, Problem.total_submissions - total),
                accepted_submissions=func.greatest(
                    0, Problem.accepted_submissions - accepted
                ),
            )
        )
    db.delete(current_user)
    db.commit()


@router.post("/bootstrap-admin", response_model=UserResponse)
def bootstrap_admin(
    current_user: User = Depends(oauth2.get_current_user),
    db: Session = Depends(get_db),
    x_bootstrap_token: str = Header(""),
):
    if not ADMIN_BOOTSTRAP_TOKEN or not secrets.compare_digest(
        x_bootstrap_token, ADMIN_BOOTSTRAP_TOKEN
    ):
        raise HTTPException(403, "Invalid bootstrap token")
    db.execute(text("SELECT pg_advisory_xact_lock(7349201)"))
    if db.query(User).filter_by(user_type=UserType.ADMIN).first():
        raise HTTPException(409, "An administrator already exists")
    current_user.user_type = UserType.ADMIN
    db.commit()
    return current_user


@router.post("/{username}/promote", response_model=UserResponse)
def promote_user(
    username: str,
    current_user: User = Depends(oauth2.get_current_admin),
    db: Session = Depends(get_db),
):
    db.execute(text("SELECT pg_advisory_xact_lock(7349201)"))
    user = db.query(User).filter_by(username=username).first()
    if not user:
        raise HTTPException(404, "User not found")
    user.user_type = UserType.ADMIN
    db.commit()
    return user


@router.get("/{username}", status_code=status.HTTP_200_OK)
def get_user(
    username: str,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(oauth2.get_optional_current_user),
):
    if current_user and current_user.username == username:
        return UserResponse(
            user_type=current_user.user_type.value,
            username=current_user.username,
            email=current_user.email,
            created_at=current_user.created_at,
            is_verified=current_user.is_verified,
        )

    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(
            detail="User with the given username was not found",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return UserResponseUnknown(
        username=user.username, is_verified=user.is_verified, created_at=user.created_at
    )
