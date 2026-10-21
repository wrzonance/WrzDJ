from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.user import User
from app.schemas.auth import TokenData

# SECURITY (CRIT-1): JWT algorithm is a security invariant and must NEVER be
# sourced from config. Hardcoding prevents an `alg=none` confusion attack via
# env-var manipulation. See docs/security/audit-2026-04-08.md CRIT-1.
_JWT_ALGORITHM = "HS256"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    settings = get_settings()
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(minutes=settings.jwt_expire_minutes)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.jwt_secret, algorithm=_JWT_ALGORITHM)
    return encoded_jwt


def decode_token(token: str) -> TokenData | None:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[_JWT_ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            return None
        # CRIT-2: reject tokens without the tv claim (legacy pre-fix tokens)
        if "tv" not in payload:
            return None
        return TokenData(username=username, token_version=payload["tv"])
    except jwt.PyJWTError:
        return None


# Pre-computed hash for timing equalization when user is not found.
# Prevents attackers from enumerating valid usernames via response time differences.
_DUMMY_HASH = get_password_hash("dummy-timing-equalization")


def authenticate_user(db: Session, username: str, password: str) -> User | None:
    user = db.query(User).filter(User.username == username).first()
    if not user:
        # Perform a dummy bcrypt check to equalize timing with the found-user path
        verify_password(password, _DUMMY_HASH)
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def get_user_by_username(db: Session, username: str) -> User | None:
    return db.query(User).filter(User.username == username).first()


def create_user(db: Session, username: str, password: str, role: str = "dj") -> User:
    hashed_password = get_password_hash(password)
    user = User(username=username, password_hash=hashed_password, role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
