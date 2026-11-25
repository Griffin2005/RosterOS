"""Demo-grade auth: PBKDF2 password hashes + short-lived JWTs carrying role and
scope. In production Cognito issues the token and this module only verifies it
(see docs section 08); the role/scope checks below stay the same."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from . import models as M
from .config import get_settings
from .db import get_db

ROLES = ["SUPER_ADMIN", "OPS_MANAGER", "POD_LEAD", "BRAND_OWNER", "EMPLOYEE", "AUDITOR"]
WRITE_ROSTER = {"SUPER_ADMIN", "OPS_MANAGER", "POD_LEAD"}
MANAGE = {"SUPER_ADMIN", "OPS_MANAGER"}
ADMIN = {"SUPER_ADMIN"}


def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 200_000)
    return base64.b64encode(salt + dk).decode()


def verify_password(pw: str, stored: str) -> bool:
    raw = base64.b64decode(stored)
    salt, dk = raw[:16], raw[16:]
    return hmac.compare_digest(dk, hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 200_000))


@dataclass
class User:
    id: str
    username: str
    role: str
    scope_level: str
    scope_id: str | None
    employee_id: str | None

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def issue_token(u: M.UserAccount) -> str:
    s = get_settings()
    payload = {"sub": u.id, "usr": u.username, "role": u.role, "lvl": u.scope_level, "sid": u.scope_id,
               "emp": u.employee_id, "exp": datetime.now(timezone.utc) + timedelta(minutes=s.jwt_ttl_minutes)}
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


def current_user(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Sign in to continue.")
    try:
        data = jwt.decode(authorization[7:], get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Your session expired. Sign in again.")
    acct = db.get(M.UserAccount, data["sub"])
    if acct is None:  # role and scope are re-read from the DB, not trusted from the token
        raise HTTPException(401, "Account no longer exists.")
    return User(acct.id, acct.username, acct.role, acct.scope_level, acct.scope_id, acct.employee_id)


def require(roles: set[str]):
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, f"Your role ({user.role.replace('_', ' ').title()}) can't do this.")
        return user
    return dep
