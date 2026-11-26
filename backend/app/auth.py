"""Sessions, CSRF and role checks.

Browser sessions: a signed JWT in an httpOnly, SameSite=Strict cookie (never
readable by page scripts), plus a CSRF token bound to that JWT. State-changing
requests must echo the token in the X-CSRF-Token header (signed double-submit).
API clients may instead send "Authorization: Bearer <jwt>"; no cookie, so no
CSRF exposure.

The JWT carries only the account id, a session version and the CSRF token:
role and scope are re-read from the database on every request, and bumping
session_version (password change, reset, role change, deactivation, "sign out
everywhere") kills every older session at once.

In production on AWS, Cognito would issue the identity token and this module
would only map it to an account (docs section 08); the checks stay the same.
"""
from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from . import models as M
from .config import get_settings
from .db import get_db

ROLES = ["SUPER_ADMIN", "OPS_MANAGER", "POD_LEAD", "BRAND_OWNER", "EMPLOYEE", "AUDITOR"]
WRITE_ROSTER = {"SUPER_ADMIN", "OPS_MANAGER", "POD_LEAD"}
MANAGE = {"SUPER_ADMIN", "OPS_MANAGER"}
ADMIN = {"SUPER_ADMIN"}
TEAM_ADMINS = {"SUPER_ADMIN", "OPS_MANAGER"}
SECURITY_VIEW = {"SUPER_ADMIN", "OPS_MANAGER", "AUDITOR"}

# Who may create or change accounts of which role. Nobody grants a role at or
# above their own except a super admin; an ops manager can't create auditors
# (the people who audit ops).
ASSIGNABLE = {
    "SUPER_ADMIN": set(ROLES),
    "OPS_MANAGER": {"POD_LEAD", "BRAND_OWNER", "EMPLOYEE"},
}
ROLE_SCOPE = {"SUPER_ADMIN": "COMPANY", "OPS_MANAGER": "COMPANY", "AUDITOR": "COMPANY",
              "POD_LEAD": "POD", "BRAND_OWNER": "BRAND", "EMPLOYEE": "SELF"}

SESSION_COOKIE = "rosteros_session"
CSRF_COOKIE = "rosteros_csrf"
CSRF_HEADER = "x-csrf-token"
ISSUER, AUDIENCE = "rosteros", "rosteros-web"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# reachable while a temporary password still has to be replaced
PASSWORD_CHANGE_ALLOWED = {"/api/auth/me", "/api/auth/change-password", "/api/auth/logout",
                           "/api/auth/password-policy"}


@dataclass
class User:
    id: str
    username: str
    role: str
    scope_level: str
    scope_id: str | None
    employee_id: str | None
    full_name: str = ""
    must_change_password: bool = False

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def user_of(acct: M.UserAccount) -> User:
    return User(acct.id, acct.username, acct.role, acct.scope_level, acct.scope_id, acct.employee_id,
                acct.full_name or "", bool(acct.must_change_password))


# ------------------------------------------------------------------ tokens
def issue_session(acct: M.UserAccount) -> tuple[str, str]:
    """Returns (jwt, csrf_token)."""
    s = get_settings()
    csrf = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    payload = {"sub": acct.id, "sv": acct.session_version, "csrf": csrf, "iss": ISSUER, "aud": AUDIENCE,
               "iat": now, "exp": now + timedelta(minutes=s.session_ttl_minutes), "jti": uuid.uuid4().hex}
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256"), csrf


def set_session_cookies(resp: Response, token: str, csrf: str) -> None:
    s = get_settings()
    max_age = s.session_ttl_minutes * 60
    resp.set_cookie(SESSION_COOKIE, token, max_age=max_age, httponly=True, secure=s.secure_cookies,
                    samesite="strict", path="/")
    # readable by the page so it can echo it in X-CSRF-Token; useless on its own
    resp.set_cookie(CSRF_COOKIE, csrf, max_age=max_age, httponly=False, secure=s.secure_cookies,
                    samesite="strict", path="/")


def clear_session_cookies(resp: Response) -> None:
    for name in (SESSION_COOKIE, CSRF_COOKIE):
        resp.delete_cookie(name, path="/")


def decode(token: str) -> dict:
    return jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"], audience=AUDIENCE, issuer=ISSUER,
                      options={"require": ["exp", "iat", "sub", "sv"]})


# ------------------------------------------------------------ dependencies
def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    auth = request.headers.get("authorization", "")
    via_cookie = False
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    else:
        token = request.cookies.get(SESSION_COOKIE, "")
        via_cookie = True
    if not token:
        raise HTTPException(401, "Sign in to continue.")
    try:
        data = decode(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Your session expired. Sign in again.")
    except jwt.PyJWTError:
        raise HTTPException(401, "Sign in to continue.")
    if via_cookie and request.method not in SAFE_METHODS:
        sent = request.headers.get(CSRF_HEADER, "")
        if not sent or not secrets.compare_digest(sent, str(data.get("csrf", ""))):
            raise HTTPException(403, "Security check failed (missing or invalid CSRF token). Reload the page.")
    acct = db.get(M.UserAccount, data["sub"])
    if acct is None or not acct.active:
        raise HTTPException(401, "This account is no longer active.")
    if acct.session_version != data["sv"]:
        raise HTTPException(401, "You were signed out because your account changed. Sign in again.")
    if acct.must_change_password and request.url.path not in PASSWORD_CHANGE_ALLOWED:
        raise HTTPException(403, detail={"code": "PASSWORD_CHANGE_REQUIRED",
                                         "message": "Set a new password to continue."})
    return user_of(acct)


def require(roles: set[str]):
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, f"Your role ({user.role.replace('_', ' ').title()}) can't do this.")
        return user
    return dep


def client_ip(request: Request) -> str:
    # uvicorn runs with --proxy-headers behind Render/nginx, so client.host is
    # already the forwarded address
    return request.client.host if request.client else "unknown"
