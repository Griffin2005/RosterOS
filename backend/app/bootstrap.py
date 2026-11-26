"""Start-up credential bootstrap.

Seeded accounts are created without a password (the seed runs at image build
time, where secrets don't belong). At start-up:

* admin                 gets ADMIN_PASSWORD (required in production)
* the other demo users  get DEMO_PASSWORD; without it they stay disabled in
                        production until an admin resets them in Team
* in development, a missing password is generated and printed once

Both secrets must pass the same password policy as everyone else. Seeded
accounts still carrying a pre-Argon2 hash (from an older database) are
re-bootstrapped, so the old shared demo password stops working.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select

from . import models as M
from . import sample_data as S
from .config import get_settings
from .db import SessionLocal
from .security import check_password, generate_password, hash_password, policy_message

log = logging.getLogger("rosteros.bootstrap")


class BootstrapError(RuntimeError):
    pass


def bootstrap_credentials() -> list[tuple[str, str]]:
    """Returns the (username, password) pairs it generated (development only)."""
    s = get_settings()
    seeded = {u[0] for u in S.DEMO_USERS}
    generated: list[tuple[str, str]] = []
    with SessionLocal() as db:
        for acct in db.scalars(select(M.UserAccount).where(M.UserAccount.username.in_(seeded))):
            legacy = bool(acct.password_hash) and not acct.password_hash.startswith("$argon2")
            if acct.password_hash and not legacy:
                continue
            is_admin = acct.role == "SUPER_ADMIN"
            pw = s.admin_password if is_admin else s.demo_password
            var = "ADMIN_PASSWORD" if is_admin else "DEMO_PASSWORD"
            if pw:
                failed = check_password(pw, acct.username, acct.full_name)
                if failed:
                    raise BootstrapError(f"{var} is too weak for '{acct.username}'. {policy_message(failed)}")
            elif s.production:
                if is_admin:
                    raise BootstrapError("ADMIN_PASSWORD must be set in production (as a secret, not in the repo).")
                acct.password_hash = None      # disabled until an admin resets it
                continue
            else:
                pw = generate_password()
                generated.append((acct.username, pw))
            acct.password_hash = hash_password(pw)
            acct.password_changed_at = datetime.now(timezone.utc)
        db.commit()
    if generated:
        width = max(len(u) for u, _ in generated)
        lines = "\n".join(f"    {u.ljust(width)}  {p}" for u, p in generated)
        print("\n" + "=" * 72 + "\n  Development passwords generated (shown once; set ADMIN_PASSWORD and\n"
              "  DEMO_PASSWORD in backend/.env to choose your own):\n" + lines + "\n" + "=" * 72 + "\n", flush=True)
    return generated


def check_production_config() -> None:
    """Refuse or repair settings that would be unsafe on a public host.

    An unset JWT_SECRET never falls back to the placeholder in config.py (it
    is in the public repo, so anyone could sign sessions with it). Instead a
    random key is generated for this process: sessions end when it restarts,
    which on a single-instance host also restarts everything else. Set
    JWT_SECRET to keep sessions across restarts or to run several instances.
    An explicitly set secret that is too short is refused in production.
    """
    import secrets as _secrets
    from .config import DEV_JWT_SECRET
    s = get_settings()
    if s.jwt_secret == DEV_JWT_SECRET:
        s.jwt_secret = _secrets.token_urlsafe(48)
        print("JWT_SECRET is not set: using a random per-process signing key "
              "(sessions end on restart).", flush=True)
    elif s.production and len(s.jwt_secret) < 32:
        raise BootstrapError("JWT_SECRET must be a random string of at least 32 characters in production.")
