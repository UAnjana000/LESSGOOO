"""Staff authentication (prototype: password + JWT; PROD: SSO/MFA) and role checks."""

from __future__ import annotations

import datetime as dt
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from archive.config import get_settings
from archive.db import get_db
from archive.models import StaffUser

ROLES = ("admin", "archivist", "reviewer", "curator", "translation_reviewer")
_hasher = PasswordHash.recommended()
_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return _hasher.verify(password, hashed)


def create_token(user: StaffUser) -> str:
    s = get_settings()
    now = dt.datetime.now(dt.UTC)
    return jwt.encode({"sub": str(user.id), "email": user.email, "roles": user.roles, "iat": now,
                       "exp": now + dt.timedelta(minutes=s.jwt_ttl_minutes)}, s.jwt_secret, algorithm="HS256")


def authenticate(db: Session, email: str, password: str) -> StaffUser | None:
    user = db.execute(select(StaffUser).where(StaffUser.email == email.lower(), StaffUser.active.is_(True))).scalar()
    if user is None or not verify_password(password, user.password_hash):
        return None
    return user


def current_staff(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> StaffUser:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required",
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        claims = jwt.decode(creds.credentials, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token") from exc
    user = db.get(StaffUser, int(claims["sub"]))
    if user is None or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "account disabled")
    return user


def require_roles(*roles: str):
    def dep(user: Annotated[StaffUser, Depends(current_staff)]) -> StaffUser:
        if "admin" in user.roles or any(r in user.roles for r in roles):
            return user
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"requires role: {', '.join(roles)}")

    return dep


Staff = Annotated[StaffUser, Depends(current_staff)]
Archivist = Annotated[StaffUser, Depends(require_roles("archivist"))]
Curator = Annotated[StaffUser, Depends(require_roles("curator"))]
Admin = Annotated[StaffUser, Depends(require_roles("admin"))]
TranslationReviewer = Annotated[StaffUser, Depends(require_roles("translation_reviewer", "archivist"))]
