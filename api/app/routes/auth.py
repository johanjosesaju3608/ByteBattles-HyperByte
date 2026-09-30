from fastapi import APIRouter, Depends, status, HTTPException, Request
from fastapi.security.oauth2 import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from ..utils.redis_utils import rate_limit

from ..schemas.user import (
    UserCreate,
    UserResponse,
    RefreshAccessTokenRequest,
    TokenPayload,
)

from ..utils import password_manager, oauth2
from ..database import get_db

from shared.models import User

from config import DUMMY_PASS

router = APIRouter(prefix="/auth", tags=["Authentication"])

DUMMY_PASSWORD = password_manager.hash(DUMMY_PASS)


@router.post(
    "/register", status_code=status.HTTP_201_CREATED, response_model=UserResponse
)
def register(new_user: UserCreate, request: Request, db: Session = Depends(get_db)):

    rate_limit("register:" + request.client.host, 20, 60)
    if new_user.password != new_user.conf_password:
        raise HTTPException(
            detail="confirm password and given password don't match",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    user = db.query(User).filter(User.username == new_user.username).first()
    if not user:
        user = db.query(User).filter(User.email == new_user.email).first()

    if user:
        raise HTTPException(
            detail="user with this username or email already exists",
            status_code=status.HTTP_409_CONFLICT,
        )

    hashed_password = password_manager.hash(new_user.password)
    new_user = User(
        username=new_user.username, email=new_user.email, password_hash=hashed_password
    )

    db.add(new_user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Username or email already exists")
    db.refresh(new_user)

    return new_user


@router.post("/login", status_code=status.HTTP_200_OK)
def login(
    request: Request,
    cred: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):

    rate_limit("login:" + request.client.host, 30, 60)
    if len(cred.password) > 256:
        raise HTTPException(401, "Invalid username or password")
    user = db.query(User).filter(User.username == cred.username).first()
    if not user:
        user = db.query(User).filter(User.email == cred.username).first()

    if not user:
        password_manager.verify(cred.password, DUMMY_PASSWORD)
        raise HTTPException(
            detail="Invalid username or password",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    if not password_manager.verify(cred.password, user.password_hash):
        raise HTTPException(
            detail="Invalid username or password",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    payload = oauth2.user_payload(user)

    access_token = oauth2.create_access_token(payload)
    refresh_token = oauth2.create_refresh_token(payload)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


@router.post("/refresh", status_code=status.HTTP_200_OK)
def refresh(token: RefreshAccessTokenRequest, db: Session = Depends(get_db)):
    payload = oauth2.verify_token(token.refresh_token, "refresh")
    user = db.get(User, payload.sub)
    if not user or not oauth2.valid_session(payload, user):
        raise oauth2.credentials_exception
    return {"access_token": oauth2.create_access_token(oauth2.user_payload(user))}
