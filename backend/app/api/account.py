"""Sign-in, own account, internal team management and the security overview."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models as M
from ..auth import (ASSIGNABLE, ROLE_SCOPE, ROLES, SECURITY_VIEW, TEAM_ADMINS, User, clear_session_cookies,
                    client_ip, current_user, issue_session, require, set_session_cookies)
from ..config import get_settings
from ..db import get_db
from ..security import (burn_verify_time, check_password, generate_password, hash_password, limiter,
                        policy_message, policy_rules, pseudonymise_ip, verify_password)
from ..services.audit import audit

router = APIRouter(prefix="/api")

SECURITY_ACTIONS = ["LOGIN_SUCCEEDED", "LOGIN_FAILED", "LOGIN_THROTTLED", "ACCOUNT_LOCKED", "ACCOUNT_UNLOCKED",
                    "PASSWORD_CHANGED", "PASSWORD_RESET", "USER_CREATED", "USER_UPDATED", "USER_DEACTIVATED",
                    "USER_ACTIVATED", "SESSIONS_REVOKED", "LOGOUT", "EXPORT_DOWNLOADED", "ASSISTANT_QUERY"]
SECURITY_HEADERS = ["Content-Security-Policy", "Strict-Transport-Security (HTTPS)", "X-Frame-Options: DENY",
                    "X-Content-Type-Options: nosniff", "Referrer-Policy: no-referrer",
                    "Permissions-Policy", "Cross-Origin-Opener-Policy: same-origin",
                    "Cache-Control: no-store (API)"]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; everything we store is UTC."""
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def _iso(dt: datetime | None) -> str | None:
    dt = _aware(dt)
    return dt.isoformat() if dt else None


def account_out(a: M.UserAccount) -> dict:
    locked = bool(a.locked_until and _aware(a.locked_until) > _utcnow())
    return {"id": a.id, "username": a.username, "full_name": a.full_name, "role": a.role,
            "scope_level": a.scope_level, "scope_id": a.scope_id, "employee_id": a.employee_id,
            "active": a.active, "locked": locked, "locked_until": _iso(a.locked_until) if locked else None,
            "must_change_password": a.must_change_password, "has_password": bool(a.password_hash),
            "failed_attempts": a.failed_attempts, "last_login_at": _iso(a.last_login_at),
            "password_changed_at": _iso(a.password_changed_at), "created_at": _iso(a.created_at),
            "created_by": a.created_by}


def _weak(failed: list[str]) -> HTTPException:
    return HTTPException(422, detail={"code": "WEAK_PASSWORD", "failed": failed, "message": policy_message(failed)})


# ===================================================================== auth
class LoginIn(BaseModel):
    username: str = Field(max_length=120)
    password: str = Field(max_length=256)


LOCKED_MSG = ("Too many failed attempts. This account is locked for {m} minutes; "
              "an administrator can unlock it sooner.")


@router.post("/auth/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    s = get_settings()
    ip = client_ip(request)
    uname = body.username.strip().lower()[:60]
    window = s.lockout_minutes * 60
    if not limiter.hit(f"login-ip:{ip}", s.login_rate_per_minute, 60):
        audit(db, uname or "?", "LOGIN_THROTTLED", "auth", None, None, {"ip": pseudonymise_ip(ip), "by": "ip"})
        db.commit()
        raise HTTPException(429, "Too many sign-in attempts from this network. Wait a minute and try again.",
                            headers={"Retry-After": "60"})
    # The per-username counter also covers names that don't exist, so the
    # lockout response can't be used to discover which accounts are real.
    if limiter.count(f"login-user:{uname}", window) >= s.login_max_failures:
        burn_verify_time(body.password)
        raise HTTPException(429, LOCKED_MSG.format(m=s.lockout_minutes), headers={"Retry-After": str(window)})
    acct = db.scalar(select(M.UserAccount).where(M.UserAccount.username == uname)) if uname else None
    now = _utcnow()
    if acct is not None and acct.locked_until and _aware(acct.locked_until) > now:
        burn_verify_time(body.password)
        raise HTTPException(429, LOCKED_MSG.format(m=s.lockout_minutes), headers={"Retry-After": str(window)})

    if acct is None:
        burn_verify_time(body.password)
        ok, rehash = False, False
    else:
        ok, rehash = verify_password(body.password, acct.password_hash)
    if not ok or not acct.active:
        limiter.hit(f"login-user:{uname}", 1_000_000, window)
        reason = "unknown_user" if acct is None else ("inactive" if ok else "bad_password")
        if acct is not None:
            acct.failed_attempts = (acct.failed_attempts or 0) + 1
            if acct.failed_attempts >= s.login_max_failures:
                acct.locked_until = now + timedelta(minutes=s.lockout_minutes)
                audit(db, "system", "ACCOUNT_LOCKED", "user", acct.id, None,
                      {"username": acct.username, "after_failures": acct.failed_attempts})
        audit(db, uname or "?", "LOGIN_FAILED", "auth", acct.id if acct else None, None,
              {"ip": pseudonymise_ip(ip), "reason": reason})
        db.commit()
        raise HTTPException(401, "Username or password is incorrect.")

    acct.failed_attempts, acct.locked_until, acct.last_login_at = 0, None, now
    if rehash:  # transparent upgrade of an old PBKDF2 / weaker Argon2 hash
        acct.password_hash = hash_password(body.password)
    limiter.clear(f"login-user:{uname}")
    audit(db, acct.username, "LOGIN_SUCCEEDED", "auth", acct.id, None, {"ip": pseudonymise_ip(ip)})
    db.commit()
    token, csrf = issue_session(acct)
    set_session_cookies(response, token, csrf)
    return {"user": account_out(acct), "csrf": csrf}


@router.post("/auth/logout")
def logout(response: Response, db: Session = Depends(get_db), user: User = Depends(current_user)):
    audit(db, user.username, "LOGOUT", "auth", user.id)
    db.commit()
    clear_session_cookies(response)
    return {"ok": True}


@router.get("/auth/me")
def me(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return account_out(db.get(M.UserAccount, user.id))


@router.get("/auth/password-policy")
def password_policy():
    s = get_settings()
    return {"min_length": s.password_min_length, "rules": [r.__dict__ for r in policy_rules()]}


class PasswordCheckIn(BaseModel):
    password: str = Field(max_length=256)
    username: str = ""
    full_name: str = ""


@router.post("/auth/password-check")
def password_check(body: PasswordCheckIn, user: User = Depends(current_user)):
    """Server-side verdict for the live checklist (the client mirrors the
    simple rules; the common-password list stays on the server)."""
    return {"failed": check_password(body.password, body.username or user.username, body.full_name or user.full_name)}


class ChangePasswordIn(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


@router.post("/auth/change-password")
def change_password(body: ChangePasswordIn, request: Request, response: Response,
                    db: Session = Depends(get_db), user: User = Depends(current_user)):
    acct = db.get(M.UserAccount, user.id)
    if not limiter.hit(f"pwchange:{acct.id}", 5, 900):
        raise HTTPException(429, "Too many attempts. Wait 15 minutes and try again.")
    ok, _ = verify_password(body.current_password, acct.password_hash)
    if not ok:
        audit(db, acct.username, "PASSWORD_CHANGE_FAILED", "user", acct.id, None,
              {"ip": pseudonymise_ip(client_ip(request))})
        db.commit()
        raise HTTPException(400, "Your current password is incorrect.")
    failed = check_password(body.new_password, acct.username, acct.full_name)
    if failed:
        raise _weak(failed)
    if body.new_password == body.current_password:
        raise HTTPException(422, "Choose a new password, not the current one.")
    acct.password_hash = hash_password(body.new_password)
    acct.must_change_password = False
    acct.password_changed_at = _utcnow()
    acct.session_version += 1          # every other session signs out
    audit(db, acct.username, "PASSWORD_CHANGED", "user", acct.id)
    db.commit()
    token, csrf = issue_session(acct)  # this session continues
    set_session_cookies(response, token, csrf)
    return {"user": account_out(acct), "csrf": csrf}


@router.post("/auth/logout-all")
def logout_all(response: Response, db: Session = Depends(get_db), user: User = Depends(current_user)):
    acct = db.get(M.UserAccount, user.id)
    acct.session_version += 1
    audit(db, acct.username, "SESSIONS_REVOKED", "user", acct.id, None, {"by": "self"})
    db.commit()
    clear_session_cookies(response)
    return {"ok": True}


# ===================================================================== team
class NewMemberIn(BaseModel):
    username: str = Field(min_length=3, max_length=40, pattern=r"^[a-z][a-z0-9._-]{2,39}$")
    full_name: str = Field(min_length=2, max_length=120)
    role: str
    scope_id: str | None = None
    employee_id: str | None = None
    password: str | None = Field(default=None, max_length=256)   # else a temporary one is generated


class UpdateMemberIn(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    role: str | None = None
    scope_id: str | None = None
    employee_id: str | None = None


def _can_manage(actor: User, role: str) -> bool:
    return role in ASSIGNABLE.get(actor.role, set())


def _scope_for(db: Session, role: str, scope_id: str | None, employee_id: str | None):
    if role not in ROLES:
        raise HTTPException(422, f"Unknown role {role}.")
    level = ROLE_SCOPE[role]
    if employee_id and db.get(M.Employee, employee_id) is None:
        raise HTTPException(422, "That employee doesn't exist.")
    if level == "COMPANY":
        return level, None, employee_id
    if level == "POD":
        pod = db.get(M.Pod, scope_id) if scope_id else None
        if pod is None:
            raise HTTPException(422, "Choose the pod this lead manages.")
        return level, pod.id, employee_id or pod.lead_id
    if level == "BRAND":
        if not scope_id or db.get(M.Brand, scope_id) is None:
            raise HTTPException(422, "Choose the brand this owner manages.")
        return level, scope_id, employee_id
    if not employee_id:
        raise HTTPException(422, "Link the employee whose schedule this account can see.")
    return level, None, employee_id


def _active_admins(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(M.UserAccount).where(
        M.UserAccount.role == "SUPER_ADMIN", M.UserAccount.active.is_(True))) or 0


def _target(db: Session, actor: User, uid: str, *, allow_self: bool = False) -> M.UserAccount:
    a = db.get(M.UserAccount, uid)
    if a is None:
        raise HTTPException(404, "Team member not found.")
    if a.id == actor.id and not allow_self:
        raise HTTPException(409, "You can't do that to your own account. Ask another administrator.")
    if not _can_manage(actor, a.role):
        raise HTTPException(403, f"Your role can't manage {a.role.replace('_', ' ').lower()} accounts.")
    return a


@router.get("/team/users")
def list_members(db: Session = Depends(get_db), user: User = Depends(require(TEAM_ADMINS | {"AUDITOR"}))):
    rows = db.scalars(select(M.UserAccount).order_by(M.UserAccount.role, M.UserAccount.username)).all()
    return {"users": [{**account_out(a), "can_manage": a.id != user.id and _can_manage(user, a.role)} for a in rows],
            "assignable_roles": sorted(ASSIGNABLE.get(user.role, set()), key=ROLES.index),
            "role_scope": ROLE_SCOPE}


@router.post("/team/users")
def create_member(body: NewMemberIn, db: Session = Depends(get_db), user: User = Depends(require(TEAM_ADMINS))):
    if not _can_manage(user, body.role):
        raise HTTPException(403, f"Your role can't create {body.role.replace('_', ' ').lower()} accounts.")
    if db.scalar(select(M.UserAccount).where(M.UserAccount.username == body.username)):
        raise HTTPException(409, "That username is taken.")
    level, scope_id, emp_id = _scope_for(db, body.role, body.scope_id, body.employee_id)
    if level == "SELF" and db.scalar(select(M.UserAccount).where(
            M.UserAccount.employee_id == emp_id, M.UserAccount.scope_level == "SELF", M.UserAccount.active.is_(True))):
        raise HTTPException(409, "That employee already has an active account.")
    temp = None
    if body.password:
        failed = check_password(body.password, body.username, body.full_name)
        if failed:
            raise _weak(failed)
        pw = body.password
    else:
        pw = temp = generate_password()
    a = M.UserAccount(username=body.username, full_name=body.full_name.strip(), role=body.role, scope_level=level,
                      scope_id=scope_id, employee_id=emp_id, password_hash=hash_password(pw),
                      must_change_password=True, password_changed_at=_utcnow(), created_by=user.username)
    db.add(a)
    db.flush()
    audit(db, user.username, "USER_CREATED", "user", a.id, None,
          {"username": a.username, "role": a.role, "scope_level": level, "scope_id": scope_id})
    db.commit()
    return {"user": account_out(a), "temporary_password": temp}


@router.patch("/team/users/{uid}")
def update_member(uid: str, body: UpdateMemberIn, db: Session = Depends(get_db),
                  user: User = Depends(require(TEAM_ADMINS))):
    a = _target(db, user, uid, allow_self=True)
    before = account_out(a)
    if a.id == user.id and body.role and body.role != a.role:
        raise HTTPException(409, "You can't change your own role. Ask another administrator.")
    if body.full_name is not None:
        a.full_name = body.full_name.strip()
    role_changed = False
    if body.role is not None or body.scope_id is not None or body.employee_id is not None:
        role = body.role or a.role
        if not _can_manage(user, role):
            raise HTTPException(403, f"Your role can't grant {role.replace('_', ' ').lower()}.")
        if a.role == "SUPER_ADMIN" and role != "SUPER_ADMIN" and a.active and _active_admins(db) <= 1:
            raise HTTPException(409, "Keep at least one active super admin.")
        level, scope_id, emp_id = _scope_for(db, role, body.scope_id if body.scope_id is not None else a.scope_id,
                                             body.employee_id if body.employee_id is not None else a.employee_id)
        role_changed = (role, level, scope_id) != (a.role, a.scope_level, a.scope_id)
        a.role, a.scope_level, a.scope_id, a.employee_id = role, level, scope_id, emp_id
    if role_changed:
        a.session_version += 1   # new permissions apply from the next sign-in
    audit(db, user.username, "USER_UPDATED", "user", a.id,
          {k: before[k] for k in ("full_name", "role", "scope_level", "scope_id")},
          {"full_name": a.full_name, "role": a.role, "scope_level": a.scope_level, "scope_id": a.scope_id})
    db.commit()
    return {"user": account_out(a)}


@router.post("/team/users/{uid}/reset-password")
def reset_password(uid: str, db: Session = Depends(get_db), user: User = Depends(require(TEAM_ADMINS))):
    a = _target(db, user, uid)
    temp = generate_password()
    a.password_hash = hash_password(temp)
    a.must_change_password = True
    a.password_changed_at = _utcnow()
    a.failed_attempts, a.locked_until = 0, None
    a.session_version += 1
    limiter.clear(f"login-user:{a.username}")
    audit(db, user.username, "PASSWORD_RESET", "user", a.id, None, {"username": a.username})
    db.commit()
    return {"user": account_out(a), "temporary_password": temp}


@router.post("/team/users/{uid}/deactivate")
def deactivate(uid: str, db: Session = Depends(get_db), user: User = Depends(require(TEAM_ADMINS))):
    a = _target(db, user, uid)
    if a.role == "SUPER_ADMIN" and a.active and _active_admins(db) <= 1:
        raise HTTPException(409, "Keep at least one active super admin.")
    a.active = False
    a.session_version += 1
    audit(db, user.username, "USER_DEACTIVATED", "user", a.id, None, {"username": a.username})
    db.commit()
    return {"user": account_out(a)}


@router.post("/team/users/{uid}/activate")
def activate(uid: str, db: Session = Depends(get_db), user: User = Depends(require(TEAM_ADMINS))):
    a = _target(db, user, uid)
    a.active = True
    audit(db, user.username, "USER_ACTIVATED", "user", a.id, None, {"username": a.username})
    db.commit()
    return {"user": account_out(a)}


@router.post("/team/users/{uid}/unlock")
def unlock(uid: str, db: Session = Depends(get_db), user: User = Depends(require(TEAM_ADMINS))):
    a = _target(db, user, uid)
    a.failed_attempts, a.locked_until = 0, None
    limiter.clear(f"login-user:{a.username}")
    audit(db, user.username, "ACCOUNT_UNLOCKED", "user", a.id, None, {"username": a.username})
    db.commit()
    return {"user": account_out(a)}


@router.post("/team/users/{uid}/revoke-sessions")
def revoke_sessions(uid: str, db: Session = Depends(get_db), user: User = Depends(require(TEAM_ADMINS))):
    a = _target(db, user, uid)
    a.session_version += 1
    audit(db, user.username, "SESSIONS_REVOKED", "user", a.id, None, {"username": a.username, "by": "admin"})
    db.commit()
    return {"user": account_out(a)}


# ================================================================= security
@router.get("/security/overview")
def security_overview(db: Session = Depends(get_db), _: User = Depends(require(SECURITY_VIEW))):
    s = get_settings()
    accts = db.scalars(select(M.UserAccount)).all()
    now = _utcnow()
    since = now - timedelta(hours=24)
    counts = {a: 0 for a in SECURITY_ACTIONS}
    for action, n in db.execute(select(M.AuditEvent.action, func.count()).where(
            M.AuditEvent.at >= since, M.AuditEvent.action.in_(SECURITY_ACTIONS)).group_by(M.AuditEvent.action)):
        counts[action] = n
    recent = db.scalars(select(M.AuditEvent).where(M.AuditEvent.action.in_(SECURITY_ACTIONS))
                        .order_by(M.AuditEvent.id.desc()).limit(25)).all()
    by_role: dict[str, int] = {}
    for a in accts:
        by_role[a.role] = by_role.get(a.role, 0) + 1
    return {
        "environment": {"production": s.production, "api_docs_public": not s.production,
                        "secure_cookies": s.secure_cookies},
        "hashing": {"algorithm": "Argon2id", "memory_kib": s.argon2_memory_kib, "time_cost": s.argon2_time_cost,
                    "parallelism": s.argon2_parallelism,
                    "legacy_hashes": sum(1 for a in accts if a.password_hash and not a.password_hash.startswith("$argon2"))},
        "policy": {"min_length": s.password_min_length, "rules": [r.__dict__ for r in policy_rules()]},
        "lockout": {"max_failures": s.login_max_failures, "minutes": s.lockout_minutes,
                    "ip_rate_per_minute": s.login_rate_per_minute},
        "sessions": {"ttl_minutes": s.session_ttl_minutes,
                     "cookie": "httpOnly · SameSite=Strict" + (" · Secure" if s.secure_cookies else ""),
                     "csrf": "Signed double-submit token bound to the session",
                     "revocation": "Session version bumps on password change, reset, role change, deactivation"},
        "headers": SECURITY_HEADERS,
        "accounts": {"total": len(accts), "active": sum(1 for a in accts if a.active),
                     "locked": sum(1 for a in accts if a.locked_until and _aware(a.locked_until) > now),
                     "must_change": sum(1 for a in accts if a.must_change_password),
                     "disabled_no_password": sum(1 for a in accts if not a.password_hash),
                     "by_role": by_role},
        "events_24h": counts,
        "recent": [{"id": e.id, "at": _iso(e.at), "actor": e.actor, "action": e.action, "detail": e.after}
                   for e in recent],
        "privacy": [
            "Accounts hold a username, display name, role and scope only: no email or phone.",
            "Client IPs are stored in the audit log as keyed hashes, never as addresses.",
            "The AI assistant receives employee codes, not names; names are restored only in the reply shown to you.",
            "Leave notes are visible only to the employee, their pod lead and managers.",
            "Exports contain only the caller's scope, are audited, and neutralise spreadsheet formula injection.",
            "Bootstrap passwords come from deployment secrets; none are stored in the repository.",
        ],
    }
