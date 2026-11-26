"""Password hashing, password policy, brute-force throttling and small
privacy helpers. Pure functions plus one in-memory limiter; no FastAPI here.

Hashing: Argon2id (OWASP's first choice) with m=19 MiB, t=2, p=1 by default,
tunable from settings. Older PBKDF2 hashes still verify and are upgraded to
Argon2id on the next successful sign-in.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import string
import threading
import time
from collections import deque
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from .config import get_settings


# ------------------------------------------------------------------ hashing
def _hasher() -> PasswordHasher:
    s = get_settings()
    return PasswordHasher(time_cost=s.argon2_time_cost, memory_cost=s.argon2_memory_kib,
                          parallelism=s.argon2_parallelism)


def hash_password(pw: str) -> str:
    return _hasher().hash(pw)


def verify_password(pw: str, stored: str | None) -> tuple[bool, bool]:
    """Returns (ok, needs_rehash). Constant-time for both hash formats."""
    if not stored:  # account without a password (disabled bootstrap account)
        burn_verify_time(pw)
        return False, False
    if stored.startswith("$argon2"):
        ph = _hasher()
        try:
            ph.verify(stored, pw)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False, False
        return True, ph.check_needs_rehash(stored)
    try:  # legacy PBKDF2-SHA256 (salt16 + dk32, base64)
        raw = base64.b64decode(stored)
        salt, dk = raw[:16], raw[16:]
    except (ValueError, TypeError):
        return False, False
    ok = hmac.compare_digest(dk, hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 200_000))
    return ok, ok


DUMMY_HASH = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1).hash("timing-equaliser")


def burn_verify_time(pw: str) -> None:
    """Spend the same time as a real verification when the account doesn't
    exist or has no password, so response timing doesn't reveal usernames."""
    try:
        _hasher().verify(DUMMY_HASH, pw)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        pass


# ------------------------------------------------------------------- policy
# A short list of the most common passwords and roster-specific guesses. The
# length and character rules already rule out most of the public top-10k.
COMMON = {
    "password", "password1", "password123", "passw0rd", "qwerty", "qwerty123", "letmein", "welcome",
    "welcome1", "admin", "admin123", "administrator", "iloveyou", "monkey", "dragon", "sunshine",
    "football", "baseball", "superman", "trustno1", "123456", "1234567", "12345678", "123456789",
    "1234567890", "111111", "000000", "abc123", "changeme", "secret", "roster", "rosteros", "datastraw",
    "roster@123", "summer", "winter", "india", "mumbai", "bangalore",
}
SEQUENCES = ["abcdefghijklmnopqrstuvwxyz", "qwertyuiopasdfghjklzxcvbnm", "01234567890"]


@dataclass(frozen=True)
class Rule:
    id: str
    label: str


def policy_rules() -> list[Rule]:
    n = get_settings().password_min_length
    return [
        Rule("length", f"At least {n} characters"),
        Rule("max", "No more than 128 characters"),
        Rule("lower", "A lowercase letter"),
        Rule("upper", "An uppercase letter"),
        Rule("digit", "A number"),
        Rule("symbol", "A symbol, such as ! ? @ # or -"),
        Rule("personal", "Doesn't contain your username or name"),
        Rule("common", "Not a common or easily guessed password"),
        Rule("pattern", "No runs like aaaa, 1234 or qwer"),
    ]


def _has_run(pw: str) -> bool:
    low = pw.lower()
    if re.search(r"(.)\1{3,}", low):
        return True
    for seq in SEQUENCES:
        for i in range(len(seq) - 3):
            chunk = seq[i:i + 4]
            if chunk in low or chunk[::-1] in low:
                return True
    return False


def check_password(pw: str, username: str = "", full_name: str = "") -> list[str]:
    """IDs of the rules this password breaks (empty list = acceptable)."""
    failed = []
    n = get_settings().password_min_length
    if len(pw) < n:
        failed.append("length")
    if len(pw) > 128:
        failed.append("max")
    if not re.search(r"[a-z]", pw):
        failed.append("lower")
    if not re.search(r"[A-Z]", pw):
        failed.append("upper")
    if not re.search(r"\d", pw):
        failed.append("digit")
    if not re.search(r"[^A-Za-z0-9]", pw):
        failed.append("symbol")
    low = pw.lower()
    parts = [p for p in re.split(r"[\s._@-]+", f"{username} {full_name}".lower()) if len(p) >= 3]
    if any(p in low for p in parts):
        failed.append("personal")
    core = re.sub(r"[^a-z]", "", low)
    if low in COMMON or core in COMMON or any(low.startswith(c) and len(low) - len(c) <= 4 for c in COMMON if len(c) >= 6):
        failed.append("common")
    if _has_run(pw):
        failed.append("pattern")
    return failed


def policy_message(failed: list[str]) -> str:
    labels = {r.id: r.label for r in policy_rules()}
    return "Password doesn't meet the policy: " + "; ".join(labels[f].lower() for f in failed) + "."


def generate_password(length: int = 18) -> str:
    """Random password that satisfies the policy (used for temporary passwords)."""
    # no $ or backtick: generated values must survive .env files and shells unquoted
    alphabet = string.ascii_letters + string.digits + "!@#%^&*-_=+?"
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        if not check_password(pw):
            return pw


# --------------------------------------------------------------- throttling
class SlidingWindow:
    """In-process sliding-window counter. One API instance in the demo; with
    several replicas this moves to Redis (same interface, INCR + EXPIRE)."""

    def __init__(self):
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window_s: float) -> bool:
        """Record a hit; False when the key is over its limit."""
        now = time.monotonic()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] > window_s:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def count(self, key: str, window_s: float) -> int:
        now = time.monotonic()
        with self._lock:
            q = self._hits.get(key, deque())
            return sum(1 for t in q if now - t <= window_s)

    def clear(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = SlidingWindow()


# ------------------------------------------------------------------ privacy
def pseudonymise_ip(ip: str | None) -> str | None:
    """Keyed hash of the client IP for the audit log: lets an admin correlate
    attempts from one source without storing the address itself."""
    if not ip:
        return None
    key = get_settings().jwt_secret.encode()
    return "ip_" + hmac.new(key, ip.encode(), hashlib.sha256).hexdigest()[:12]


FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value):
    """Neutralise spreadsheet formula injection (CSV/XLSX exports): text that
    starts with = + - @ is prefixed with an apostrophe so Excel and Sheets show
    it as text instead of executing it."""
    if isinstance(value, str) and value.startswith(FORMULA_START):
        return "'" + value
    return value
