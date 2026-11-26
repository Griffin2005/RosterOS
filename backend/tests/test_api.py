"""End-to-end API flow on a throwaway SQLite database (see conftest):
seed -> published December -> leave approved after publishing -> gap flagged ->
suggestions -> repair -> publish -> scoped views -> rules change from the Sheet."""
import io
import time

from openpyxl import load_workbook

from conftest import login


def wait_job(client, h, job_id):
    for _ in range(240):
        j = client.get(f"/api/jobs/{job_id}", headers=h).json()
        if j["status"] in ("DONE", "FAILED"):
            return j
        time.sleep(0.25)
    raise AssertionError("job timed out")


def hard_open(grid):
    return [c for c in grid["conflicts"] if c["severity"] == "HARD" and not c.get("acknowledged")]


def test_full_change_flow(client):
    ops = login(client, "ops")
    g = client.get("/api/rosters/current?month=2026-12", headers=ops).json()
    assert g["roster"]["status"] == "PUBLISHED"
    assert len(g["employees"]) == 32 and not hard_open(g)
    # the one structural gap is visible, but acknowledged with a reason
    acked = [c for c in g["conflicts"] if c["severity"] == "HARD"]
    assert len(acked) == 1 and acked[0]["acknowledged"]["reason"]

    emps = {e["code"]: e for e in client.get("/api/employees", headers=ops).json()}
    meera = emps["E12"]["id"]
    # pick a December day Meera works and she alone covers Kesar Kitchen CS
    cs_line = next(c for c in g["coverage"] if c["label"] == "Kesar Kitchen · CS")
    idx = next(i for i, d in enumerate(cs_line["days"]) if d["heads"] == [meera] and i >= 7)
    day = g["days"][idx]

    lv = client.post("/api/leaves", headers=login(client, "meera"),
                     json={"employee_id": meera, "start_date": day, "end_date": day, "type": "SL"}).json()
    res = client.post(f"/api/leaves/{lv['id']}/approve", headers=login(client, "lead.south")).json()
    codes = {c["code"] for c in res["impact"]["conflicts"]}
    assert "C05" in codes and "C01" in codes          # gap + leave clash flagged immediately

    kesar = [c["line_id"] for c in g["coverage"] if c["brand"] == "Kesar Kitchen"]
    sugg = client.post(f"/api/rosters/{g['roster']['id']}/suggest", headers=ops,
                       json={"date": day, "line_ids": kesar}).json()["suggestions"]
    assert sugg and all(s["reasons"] for s in sugg)

    job = client.post(f"/api/rosters/{g['roster']['id']}/repair", headers=ops).json()
    j = wait_job(client, ops, job["job_id"])
    assert j["status"] == "DONE", j
    rg = client.get(f"/api/rosters/{j['roster_id']}/grid", headers=ops).json()
    assert rg["roster"]["kind"] == "REPAIR" and not hard_open(rg)
    diff = client.get(f"/api/rosters/{j['roster_id']}/diff", headers=ops).json()["changes"]
    assert 1 <= len(diff) <= 12                        # minimal change, not a full rebuild

    pub = client.post(f"/api/rosters/{j['roster_id']}/publish", headers=ops).json()
    assert pub["roster"]["status"] == "PUBLISHED" and pub["notified"] >= 1
    assert pub["sheets"]["ok"]


def test_scopes_and_permissions(client):
    me = login(client, "meera")
    g = client.get("/api/rosters/current?month=2026-12", headers=me).json()
    assert g.get("scoped") and len(g["employees"]) < 32
    assert {c["brand"] for c in g["coverage"]} == {"Kesar Kitchen"}
    assert client.post("/api/rosters/generate", headers=me, json={"month": "2027-01"}).status_code == 403
    lead = login(client, "lead.north")
    g2 = client.get("/api/rosters/current?month=2026-12", headers=lead).json()
    assert {c["pod_id"] for c in g2["coverage"]} == {"pod-north"}


def test_rules_change_from_sheet_marks_roster_stale(client):
    ops = login(client, "ops")
    sheet = client.get("/api/sheets/rules", headers=ops).json()
    rows = sheet["tabs"]["ServiceLines"]
    for r in rows:
        if r[0] == "Kesar Kitchen" and r[1] == "CS":
            r[4] = "2"
    rows.append(["Kesar Kitchen", "CHAT", "NO_SUN_PH", "", "1", "", "10:00-19:00"])  # new process
    rows.append(["Ghost Brand", "CS", "ALL_DAYS", "", "1", "", "09:00-18:00"])       # invalid
    client.put("/api/sheets/rules/ServiceLines", headers=ops, json={"rows": rows})
    prev = client.get("/api/rules/preview", headers=ops).json()
    assert any(c["line"] == "Kesar Kitchen · CS" for c in prev["changed"])
    assert any(a["line"] == "Kesar Kitchen · CHAT" and a["new_process"] for a in prev["added"])
    assert any("Ghost Brand" in e["message"] for e in prev["errors"])
    client.post("/api/rules/import", headers=ops)
    g = client.get("/api/rosters/current?month=2026-12", headers=ops).json()
    codes = {c["code"] for c in g["conflicts"]}
    assert "C12" in codes and ("C02" in codes or "C01" in codes)  # stale + new requirement unmet


def test_generate_next_month_and_exports(client):
    ops = login(client, "ops")
    j = wait_job(client, ops, client.post("/api/rosters/generate", headers=ops,
                                          json={"month": "2027-01"}).json()["job_id"])
    assert j["status"] == "DONE", j
    assert client.get(f"/api/rosters/{j['roster_id']}/export.csv", headers=ops).status_code == 200
    x = client.get(f"/api/rosters/{j['roster_id']}/export.xlsx", headers=ops)
    assert x.status_code == 200 and x.content[:2] == b"PK"
    wb = load_workbook(io.BytesIO(x.content))
    assert wb.sheetnames[:4] == ["Overview", "Roster", "Coverage", "Requirements"]
    assert {"RosterGrid", "RosterCodes", "RosterDates", "CoverCounts", "CoverDates", "CoverLines"} <= set(wb.defined_names)
    # cross-sheet references: coverage is computed from Covers, Covers checks Roster live
    assert wb["Coverage"]["E2"].value.startswith("=SUMIFS(CoverCounts,CoverDates,E$1,CoverLines,$A2)")
    assert "INDEX(RosterGrid" in wb["Covers"]["F2"].value
    assert wb["Roster"]["B2"].value.startswith("=IFERROR(INDEX(Employees!")
    assert wb["Overview"]["B14"].value == "=IF(B12=0,1,1-B13/B12)"
    assert wb["Roster"].data_validations.dataValidation    # status codes constrained
    audit = client.get("/api/audit?limit=20", headers=ops).json()
    assert any(a["action"] == "EXPORT_DOWNLOADED" and a["after"]["format"] == "xlsx" for a in audit)
    chat = client.post("/api/assistant/chat", headers=ops,
                       json={"roster_id": j["roster_id"], "messages": [{"role": "user", "content": "What's wrong?"}]})
    assert chat.status_code == 200 and chat.json()["reply"]
