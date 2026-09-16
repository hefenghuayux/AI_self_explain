import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.requests import HTTPConnection

from app.models.auth_session import AuthSession
from app.models.user import User

PBKDF2_ITERATIONS = 600_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations_text, salt_text, digest_text = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
        salt = bytes.fromhex(salt_text)
        expected = bytes.fromhex(digest_text)
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return hmac.compare_digest(actual, expected)


def create_auth_session(session: Session, user: User, days: int) -> tuple[str, datetime]:
    raw_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(days=days)
    auth_session = AuthSession(
        user_id=user.id,
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        expires_at=expires_at,
    )
    session.add(auth_session)
    session.commit()
    return raw_token, expires_at


def get_database_session(connection: HTTPConnection):
    session: Session = connection.app.state.database_session_factory()
    try:
        yield session
    finally:
        session.close()


DatabaseSession = Annotated[Session, Depends(get_database_session)]


def get_current_user(connection: HTTPConnection, session: DatabaseSession) -> User:
    authorization = connection.headers.get("Authorization", "")
    scheme, _, raw_token = authorization.partition(" ")
    if not raw_token:
        websocket_protocols = [
            item.strip()
            for item in connection.headers.get("Sec-WebSocket-Protocol", "").split(",")
        ]
        if len(websocket_protocols) == 2 and websocket_protocols[0].lower() == "bearer":
            scheme, raw_token = websocket_protocols
    if scheme.lower() != "bearer" or not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    statement = (
        select(User)
        .join(AuthSession, AuthSession.user_id == User.id)
        .where(
            AuthSession.token_hash == token_hash,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > datetime.now(UTC),
        )
    )
    user = session.scalar(statement)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录状态已失效")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_teacher(user: CurrentUser) -> User:
    if user.role != "TEACHER":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="当前账号没有题目管理权限"
        )
    return user


TeacherUser = Annotated[User, Depends(require_teacher)]
