"""Security and privacy behaviour: hashing, password policy, sessions and CSRF,
brute-force protection, team management permissions, data scoping, headers."""
import base64
import hashlib
import os

from fastapi.testclient import TestClient

from conftest import ADMIN_PW, DEMO_PW, login

STRONG = "Gx4!rTq9#Lm2@Wv"


def fresh(client) -> TestClient:
    """A second browser: its own cookie jar, same app."""
    return TestClient(client.app)


def browser_login(c: TestClient, user: str, pw: str):
    r = c.post("/api/auth/login", json={"username": user, "password": pw})
    assert r.status_code == 200, r.text
    return r


def create_member(client, admin, **body):
    r = client.post("/api/team/users", headers=admin, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def activate_with_new_password(client, username, temp, new=STRONG):
    """First sign-in with a temporary password, then the forced change."""
    h = login(client, username, temp)
    r = client.post("/api/auth/change-password", headers=h, json={"current_password": temp, "new_password": new})
    assert r.status_code == 200, r.text
    return login(client, username, new)


# ------------------------------------------------------------- unit level
def test_password_policy_rules():
    from app.security import check_password, generate_password
    assert check_password(STRONG) == []
    assert "length" in check_password("Ab1!short")
    assert {"upper", "symbol"} <= set(check_password("alllowercase1234567"))
    assert "common" in check_password("Password123!")
    assert "personal" in check_password("Meera#Iyer2026x", username="meera", full_name="Meera Iyer")
    assert "pattern" in check_password("Zz!9aaaaQwert")
    for _ in range(20):
        assert check_password(generate_password()) == []


def test_argon2id_hashes_and_legacy_upgrade():
    from app.security import hash_password, verify_password
    h = hash_password(STRONG)
    assert h.startswith("$argon2id$") and STRONG not in h
    assert verify_password(STRONG, h) == (True, False)
    assert verify_password("wrong-password!", h)[0] is False
    assert hash_password(STRONG) != h                       # unique salt per hash
    salt = os.urandom(16)                                    # an old PBKDF2 hash still verifies...
    legacy = base64.b64encode(salt + hashlib.pbkdf2_hmac("sha256", b"old-Passw0rd!", salt, 200_000)).decode()
    assert verify_password("old-Passw0rd!", legacy) == (True, True)   # ...and asks to be upgraded


def test_formula_injection_is_neutralised():
    from app.security import safe_cell
    assert safe_cell('=HYPERLINK("http://evil","x")').startswith("'=")
    assert safe_cell("+1+1") == "'+1+1" and safe_cell("@SUM(A1)") == "'@SUM(A1)"
    assert safe_cell("Meera Iyer") == "Meera Iyer" and safe_cell(3) == 3


def test_assistant_pseudonymiser_keeps_names_away_from_the_model():
    from app.api.assistant import Pseudonymiser
    from app.domain.types import Employee
    pz = Pseudonymiser([Employee("1", "E12", "Meera Iyer", "p"), Employee("2", "E13", "Arjun Rao", "p")])
    masked = pz.mask("Can Arjun cover for meera iyer on Friday? Ask Meera.")
    assert "Meera" not in masked and "Arjun" not in masked and "E12" in masked and "E13" in masked
    assert pz.unmask("E13 can cover E12.") == "Arjun Rao can cover Meera Iyer."


# ------------------------------------------------------ sessions and CSRF
def test_login_uses_httponly_cookie_and_no_token_in_body(client):
    c = fresh(client)
    r = browser_login(c, "ops", DEMO_PW)
    assert "token" not in r.json() and r.json()["csrf"]
    cookie = r.headers.get_list("set-cookie")
    session = next(x for x in cookie if x.startswith("rosteros_session="))
    assert "HttpOnly" in session and "samesite=strict" in session.lower()
    assert c.get("/api/auth/me").json()["username"] == "ops"


def test_state_changing_requests_need_the_csrf_token(client):
    c = fresh(client)
    csrf = browser_login(c, "ops", DEMO_PW).json()["csrf"]
    body = {"password": "x"}
    assert c.post("/api/auth/password-check", json=body).status_code == 403
    assert c.post("/api/auth/password-check", json=body, headers={"X-CSRF-Token": "forged"}).status_code == 403
    assert c.post("/api/auth/password-check", json=body, headers={"X-CSRF-Token": csrf}).status_code == 200


def test_tampered_or_missing_session_is_rejected(client):
    assert client.get("/api/rosters/current?month=2026-12").status_code == 401
    h = login(client, "ops")
    bad = {"Authorization": h["Authorization"][:-3] + "abc"}
    assert client.get("/api/auth/me", headers=bad).status_code == 401


# ------------------------------------------------- brute-force protection
def test_wrong_password_and_unknown_user_look_identical(client):
    a = client.post("/api/auth/login", json={"username": "ops", "password": "Wrong#Pass123"})
    b = client.post("/api/auth/login", json={"username": "nobody.here", "password": "Wrong#Pass123"})
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


def test_account_locks_after_repeated_failures_and_admin_unlocks(client):
    admin = login(client, "admin")
    m = create_member(client, admin, username="temp.lock", full_name="Lock Test", role="AUDITOR")
    for _ in range(5):
        assert client.post("/api/auth/login", json={"username": "temp.lock", "password": "Nope#12345xy"}).status_code == 401
    # even the right password is refused while locked
    r = client.post("/api/auth/login", json={"username": "temp.lock", "password": m["temporary_password"]})
    assert r.status_code == 429 and "locked" in r.json()["detail"]
    team = {u["username"]: u for u in client.get("/api/team/users", headers=admin).json()["users"]}
    assert team["temp.lock"]["locked"]
    assert client.post(f"/api/team/users/{m['user']['id']}/unlock", headers=admin).status_code == 200
    assert client.post("/api/auth/login", json={"username": "temp.lock", "password": m["temporary_password"]}).status_code == 200
    actions = [e["action"] for e in client.get("/api/security/overview", headers=admin).json()["recent"]]
    assert "ACCOUNT_LOCKED" in actions and "ACCOUNT_UNLOCKED" in actions


def test_unknown_usernames_are_throttled_too(client):
    for _ in range(5):
        client.post("/api/auth/login", json={"username": "ghost.user", "password": "Nope#12345xy"})
    assert client.post("/api/auth/login", json={"username": "ghost.user", "password": "Nope#12345xy"}).status_code == 429


def test_ip_rate_limit(client, monkeypatch):
    from app.config import get_settings
    from app.security import limiter
    monkeypatch.setattr(get_settings(), "login_rate_per_minute", 3)
    limiter.reset()
    codes = [client.post("/api/auth/login", json={"username": "ops", "password": "Wrong#Pass123"}).status_code
             for _ in range(4)]
    assert codes[:3] == [401, 401, 401] and codes[3] == 429
    limiter.reset()


# --------------------------------------------------------- team management
def test_new_member_must_replace_temporary_password(client):
    admin = login(client, "admin")
    emps = {e["code"]: e for e in client.get("/api/employees", headers=admin).json()}
    m = create_member(client, admin, username="tenzin", full_name="Tenzin Dorje", role="EMPLOYEE",
                      employee_id=emps["E11"]["id"])
    temp = m["temporary_password"]
    assert temp and m["user"]["must_change_password"]
    h = login(client, "tenzin", temp)
    blocked = client.get("/api/rosters/current?month=2026-12", headers=h)
    assert blocked.status_code == 403 and blocked.json()["detail"]["code"] == "PASSWORD_CHANGE_REQUIRED"
    weak = client.post("/api/auth/change-password", headers=h, json={"current_password": temp, "new_password": "tenzin123"})
    assert weak.status_code == 422 and "personal" in weak.json()["detail"]["failed"]
    ok = client.post("/api/auth/change-password", headers=h, json={"current_password": temp, "new_password": STRONG})
    assert ok.status_code == 200
    assert client.get("/api/auth/me", headers=h).status_code == 401      # older sessions end
    h2 = login(client, "tenzin", STRONG)
    g = client.get("/api/rosters/current?month=2026-12", headers=h2).json()
    assert g["scoped"] and any(e["code"] == "E11" for e in g["employees"])


def test_role_hierarchy_blocks_privilege_escalation(client):
    ops, admin = login(client, "ops"), login(client, "admin")
    for role in ("SUPER_ADMIN", "OPS_MANAGER", "AUDITOR"):
        r = client.post("/api/team/users", headers=ops, json={"username": f"x{role.lower()[:5]}",
                                                              "full_name": "Escalation Try", "role": role})
        assert r.status_code == 403, role
    users = {u["username"]: u for u in client.get("/api/team/users", headers=ops).json()["users"]}
    assert client.post(f"/api/team/users/{users['admin']['id']}/reset-password", headers=ops).status_code == 403
    assert client.patch(f"/api/team/users/{users['lead.west']['id']}", headers=ops,
                        json={"role": "SUPER_ADMIN"}).status_code == 403
    me = client.get("/api/auth/me", headers=admin).json()
    assert client.post(f"/api/team/users/{me['id']}/deactivate", headers=admin).status_code == 409
    assert client.get("/api/team/users", headers=login(client, "lead.north")).status_code == 403
    assert client.get("/api/team/users", headers=login(client, "meera")).status_code == 403


def test_ops_can_add_a_pod_lead_with_their_own_password(client):
    ops = login(client, "ops")
    weak = client.post("/api/team/users", headers=ops, json={"username": "lead.extra", "full_name": "Extra Lead",
                                                              "role": "POD_LEAD", "scope_id": "pod-east",
                                                              "password": "short"})
    assert weak.status_code == 422
    m = create_member(client, ops, username="lead.extra", full_name="Extra Lead", role="POD_LEAD",
                      scope_id="pod-east", password=STRONG)
    assert m["temporary_password"] is None and m["user"]["scope_id"] == "pod-east"


def test_deactivation_and_reset_end_existing_sessions(client):
    admin = login(client, "admin")
    m = create_member(client, admin, username="temp.cut", full_name="Cut Test", role="AUDITOR")
    h = activate_with_new_password(client, "temp.cut", m["temporary_password"])
    assert client.get("/api/auth/me", headers=h).status_code == 200
    assert client.post(f"/api/team/users/{m['user']['id']}/reset-password", headers=admin).status_code == 200
    assert client.get("/api/auth/me", headers=h).status_code == 401
    assert client.post(f"/api/team/users/{m['user']['id']}/deactivate", headers=admin).status_code == 200
    r = client.post("/api/auth/login", json={"username": "temp.cut", "password": STRONG})
    assert r.status_code == 401


# ------------------------------------------------------- privacy & scope
def test_no_account_list_or_password_exposed(client):
    assert client.get("/api/auth/demo-users").status_code == 404
    me = client.get("/api/auth/me", headers=login(client, "ops")).json()
    assert not any("hash" in k or "password" == k for k in me)


def test_leave_reasons_hidden_from_brand_owner(client):
    brand = client.get("/api/leaves", headers=login(client, "brand.kesar")).json()
    assert brand and all(lv["type"] == "AWAY" and lv["note"] == "" and lv["status"] == "APPROVED" for lv in brand)
    mine = client.get("/api/leaves", headers=login(client, "meera")).json()
    emp_ids = {lv["employee_id"] for lv in mine}
    assert len(emp_ids) <= 1


def test_directory_only_for_non_managers(client):
    rows = client.get("/api/employees", headers=login(client, "meera")).json()
    assert rows and all(r["assignments"] == [] and "capacity" not in r for r in rows)


def test_company_dashboard_sheet_restricted(client):
    me = login(client, "meera")
    assert client.get("/api/sheets/dashboards", headers=me).status_code == 403
    assert client.get("/api/sheets/rules", headers=me).status_code == 200


def test_mock_google_http_surface_needs_a_manager(client):
    assert client.get("/mock-google/mock/spreadsheets/rules-and-coverage").status_code == 401
    assert client.get("/mock-google/mock/spreadsheets/rules-and-coverage",
                      headers=login(client, "meera")).status_code == 403


def test_spa_fallback_never_swallows_api_paths(client):
    assert client.get("/api/does-not-exist").status_code == 404
    for probe in ("/..%2F..%2Fbackend%2Fapp%2Fconfig.py", "/%2E%2E/%2E%2E/backend/app/config.py"):
        assert b"jwt_secret" not in client.get(probe).content      # no file outside the web root


def test_security_headers(client):
    r = client.get("/api/health")
    h = r.headers
    assert "frame-ancestors 'none'" in h["content-security-policy"] and "script-src 'self'" in h["content-security-policy"]
    assert h["x-frame-options"] == "DENY" and h["x-content-type-options"] == "nosniff"
    assert h["cache-control"] == "no-store" and h["referrer-policy"] == "no-referrer"


def test_security_overview_for_auditor(client):
    o = client.get("/api/security/overview", headers=login(client, "auditor")).json()
    assert o["hashing"]["algorithm"] == "Argon2id" and o["hashing"]["legacy_hashes"] == 0
    assert o["policy"]["min_length"] >= 12 and o["lockout"]["max_failures"] == 5
    assert o["events_24h"]["LOGIN_SUCCEEDED"] >= 1
    assert client.get("/api/security/overview", headers=login(client, "meera")).status_code == 403


def test_bootstrap_rejects_weak_secret(monkeypatch):
    import pytest
    from app import bootstrap
    from app.config import get_settings
    from app.db import SessionLocal
    from app import models as M
    with SessionLocal() as db:   # make one seeded account need bootstrapping again
        a = db.query(M.UserAccount).filter_by(username="arjun").one()
        saved, a.password_hash = a.password_hash, None
        db.commit()
    monkeypatch.setattr(get_settings(), "demo_password", "weakpass")
    with pytest.raises(bootstrap.BootstrapError):
        bootstrap.bootstrap_credentials()
    with SessionLocal() as db:
        db.query(M.UserAccount).filter_by(username="arjun").one().password_hash = saved
        db.commit()


def test_unset_jwt_secret_never_uses_the_public_placeholder(monkeypatch):
    import pytest
    from app import bootstrap
    from app.config import DEV_JWT_SECRET, get_settings
    s = get_settings()
    for env in ("development", "production"):
        monkeypatch.setattr(s, "env", env)
        monkeypatch.setattr(s, "jwt_secret", DEV_JWT_SECRET)
        bootstrap.check_production_config()
        assert s.jwt_secret != DEV_JWT_SECRET and len(s.jwt_secret) >= 32
    monkeypatch.setattr(s, "jwt_secret", "too-short")
    with pytest.raises(bootstrap.BootstrapError):
        bootstrap.check_production_config()


def test_settings_ignore_pasted_whitespace(monkeypatch):
    from app.config import Settings
    monkeypatch.setenv("ENV", "production\r\n")
    monkeypatch.setenv("ADMIN_PASSWORD", " Kv8#mPq2!wZr4t\r")
    s = Settings(_env_file=None)
    assert s.production and s.admin_password == "Kv8#mPq2!wZr4t"


def test_missing_demo_accounts_are_added_to_an_existing_database():
    from app import models as M
    from app.db import SessionLocal
    from app.seed import _ensure_demo_accounts
    with SessionLocal() as db:
        assert _ensure_demo_accounts(db) == 0                       # complete database: nothing to do
        old = db.query(M.UserAccount).filter_by(username="arjun").one()
        old.username = "arjun.renamed"                              # simulate an older database
        db.commit()
        try:
            assert _ensure_demo_accounts(db) == 1
            new = db.query(M.UserAccount).filter_by(username="arjun").one()
            assert new.password_hash is None and new.role == "EMPLOYEE" and new.employee_id == old.employee_id
            db.delete(new)
            db.commit()
        finally:
            old.username = "arjun"
            db.commit()


def test_hosted_postgres_urls_use_the_installed_driver():
    from app.db import normalise_url
    assert normalise_url("postgres://u:p@h:5432/d") == "postgresql+psycopg://u:p@h:5432/d"
    assert normalise_url("postgresql://u:p@h/d?sslmode=require") == "postgresql+psycopg://u:p@h/d?sslmode=require"
    assert normalise_url("postgresql+psycopg://u:p@h/d") == "postgresql+psycopg://u:p@h/d"
    assert normalise_url("sqlite:///./x.db") == "sqlite:///./x.db"


def test_admin_secret_password_works(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PW})
    assert r.status_code == 200 and r.json()["user"]["role"] == "SUPER_ADMIN"
    client.cookies.clear()
