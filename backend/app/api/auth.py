import hashlib
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.auth import (
    CurrentUser,
    DatabaseSession,
    create_auth_session,
    hash_password,
    verify_password,
)
from app.models.auth_session import AuthSession
from app.models.user import User
from app.schemas.auth import AuthResponse, LoginInput, RegisterInput, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(input_data: RegisterInput, session: DatabaseSession) -> UserResponse:
    user = User(
        username=input_data.username,
        password_hash=hash_password(input_data.password),
        full_name=input_data.full_name,
        role="STUDENT",
    )
    session.add(user)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="用户名已被使用"
        ) from error
    session.refresh(user)
    return user


@router.post("/login", response_model=AuthResponse)
def login(input_data: LoginInput, session: DatabaseSession, request: Request) -> AuthResponse:
    user = session.scalar(select(User).where(User.username == input_data.username))
    if user is None or not verify_password(input_data.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    days = request.app.state.settings.auth_session_days
    token, expires_at = create_auth_session(session, user, days)
    return AuthResponse(token=token, expires_at=expires_at, user=user)


@router.get("/me", response_model=UserResponse)
def me(user: CurrentUser) -> UserResponse:
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(user: CurrentUser, session: DatabaseSession, request: Request) -> None:
    authorization = request.headers.get("Authorization", "")
    raw_token = authorization.split(" ", maxsplit=1)[1]
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    auth_session = session.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash))
    if auth_session is not None:
        auth_session.revoked_at = datetime.now(UTC)
        session.commit()
