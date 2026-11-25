# RosterOS: Smart Roster Management System

A browser-based tool that plans, generates, validates and manages monthly rosters for a multi-brand CX operations team. Working rules and minimum coverage live in a Google Sheet. A constraint solver (Google OR-Tools CP-SAT) builds the month, and an independent rule engine checks every roster. Any gap the system can't close is reported with its cause and ranked fixes, never hidden.

- **Architecture:** [docs/architecture.html](docs/architecture.html) covers the topology, solver model, data model, change flow, sync/backup, roles and security.
- **Sample data:** 32 employees in 4 pods, and 22 brands. 18 brands are run by one dedicated person (82%). 2 brands have two people and 2 have three, with both separate and shared processes. There are 46 service lines across 5 processes (CS, ACC, NDR, RET, ESC).

## Run it

### Local (no Docker)

```bash
# API (Python 3.11+); seeds the sample data and publishes December 2026 on first start
cd backend
python -m venv .venv && .venv/Scripts/activate        # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --port 8000

# Web (Node 20+), in another terminal
cd frontend
npm install
npm run dev                                           # http://localhost:5173
```

If you run `npm run build` first, the API also serves the built app at http://localhost:8000.

### Docker (full stack)

```bash
cp .env.example .env        # change the secrets
docker compose up --build   # http://localhost:8080
```

The Compose stack runs:
- the web app (nginx)
- the API
- 2 solver workers, which have no database credentials
- the scheduler
- a Google Sheets/Calendar mock
- a PostgreSQL 16 primary with continuous WAL archiving to `./backups`
- a streaming read replica
- a backup job that writes a `pg_dump` every 15 minutes
- Redis

### Demo accounts

All accounts use the password `roster@123`.

| User | Role | Sees |
|---|---|---|
| `admin` | Super Admin | Everything, plus solver settings |
| `ops` | Ops Manager | Everything; can generate and publish |
| `lead.south`, `lead.north` | Pod Lead | Their pod; approves leave and edits schedules in the pod |
| `brand.kesar` | Brand Owner | One brand's coverage |
| `meera` | Employee | Her own schedule, plus who covers her brand |
| `auditor` | Auditor | Read-only, including the audit log |

### Tests

```bash
cd backend && python -m pytest -q   # 14 tests: each hard rule, infeasibility reporting, repair, the full API change flow
```

## Demo script (about 4 minutes)

1. Sign in as `ops`. The dashboard shows December v1 at 99.9% coverage and one gap, acknowledged with a reason: Bloom Basket ACC on 22 Dec, when both people trained on it are on leave.
2. **Roster:** switch between the company, pod, brand, process and employee views. Kesar Kitchen is a single-resource brand; its owner's weekly offs are covered by trained backups.
3. **Leaves:** sign in as `meera` and request a day off on a day she alone covers Kesar Kitchen. Sign in as `lead.south` and approve it. The impact dialog lists the new gaps and the leave clash right away.
4. Open a gap to see ranked backups, each with its cost and the rule that blocks the rejected ones. Click **Auto-repair**: only a handful of cells near the change move. Review **Changes**, then **Publish**. The affected people are notified and the Google Sheet tabs update.
5. **Google Sheets:** raise a minimum-heads value in the rules sheet and save. Under **Brands & rules**, click **Check Sheet for changes** to see the diff and any bad rows, then import it. The roster is flagged as stale and the new shortfall shows up.
6. Generate January 2027 from scratch, and ask the assistant what breaks if someone takes leave.

## Tell us how you think

**1. How did you model employees, brands, processes, pods and their relationships?**
The unit of coverage is the **service line**: one brand × one process. Each line has its own operating calendar (365 days, daily with public holidays off, Sundays and public holidays off, or custom weekdays), minimum heads, per-weekday minimums, date-specific overrides and a shift window. People attach to lines through **assignments**, which carry a role (`PRIMARY` or `BACKUP`) and a load percentage against the person's daily capacity. This allows one person to own a whole brand, several people to split or share a brand's processes, and one person to back up lines across brands. Pods group employees and brands, and each pod has a lead. The roster is versioned. `roster_day` records whether a person works, and `roster_cover` records which lines they carry that day, which keeps a brand's calendar separate from each person's schedule.

**2. How does the system generate a roster and check it?**
Generation takes a frozen snapshot of the month, expands demand per line per day, and runs a pre-check that finds slots no roster could fill. It then builds a CP-SAT model:
- **Hard constraints:** leave and holidays, coverage, capacity, shift compatibility, weekly offs, maximum consecutive days across month boundaries, and manual locks.
- **Weighted penalties:** using a backup, overriding a preferred off-day, working a public holiday, unfair Sunday spread, and, in repair mode, changed cells.

Coverage uses penalised slack, so a month that can't be fully staffed still yields the best possible roster, along with an exact list of unfilled slots. Each result, and every manual edit, then goes through a separate deterministic validator. A draft can't be published while a hard conflict is open, unless a manager acknowledges it in writing.

**3. Single-resource brands vs. brands with several people?**
The model treats them the same; only the data differs. A single owner carries all of a brand's lines at a combined load of 100% or less, so their weekly off must fall on a day the brand is closed, or a trained backup must cover it. The solver staggers owners' offs so that each pod lead (a backup on every line in the pod) and cross-trained peers can absorb them. For multi-person brands, the solver staggers offs within the brand. Two people sharing a line can't both be off on a day that needs one head.

**4. What happens when the sole owner of a brand is unavailable on a required day?**
Approving the leave immediately re-validates the published roster. It flags `C05` (the owner is scheduled during leave) and `C01` on each of the brand's open lines. The recommender ranks every trained person:
- Can they take all the lines, or only some?
- Would it break their capacity, a shift window, the streak limit or their weekly off?
- What does it cost?

Each option comes with concrete cell changes. If no single move works, **Auto-repair** re-solves a window around the change with the rest of the month frozen, minimising changed cells. It can chain moves, for example handing a backup's own line to someone else to free them. The manager reviews the diff and publishes.

**5. Conflicting requirements or insufficient staffing?**
There are three layers:
- The pre-check names impossible slots and their cause, such as "only Priya is trained, and she is on leave".
- The solver reports the slots it had to leave short.
- The validator lists every violation with a structured explanation.

Mandatory rules always outrank preferences, because a gap is weighted above any combination of soft penalties. Anything left over stays visible until it's fixed or acknowledged with a reason, and the acknowledgement carries forward to later versions.

**6. What is automated, and what stays under human control?**
- **Automated:** generating rosters, validating every edit, re-validating when leaves or rules change, ranking backups, repairing rosters with minimal changes, importing rules from the Sheet, pushing to the dashboards, comp-off credits, notifications and the audit trail.
- **Human:** approving leave, publishing, acknowledging unfixable gaps, locking cells, and changing assignments and rules.

Staffing trade-offs affect clients and people, so the system proposes and explains but never publishes on its own. The AI assistant follows the same rule: it can draft a change, but a manager publishes it.

**7. What would change if the team and brand count doubled?**
The solver itself scales: the sample month has about 4,000 booleans and solves in 3–4 seconds. At larger sizes I would:
- solve per pod in parallel, with a coordination pass for cross-pod backups;
- keep repair windows small;
- move the validator to incremental, per-cell checks;
- split the Sheets sync and the assistant into their own services, as Figure 1 shows;
- add PostgreSQL row-level security in the database to back up the API scoping;
- run multiple API replicas behind the load balancer, with WebSocket fan-out through Redis.

**8. With one more week, what would I improve first?**
1. Shift-level rostering (morning/evening slots), not just day-level.
2. Two or three alternative rosters, offered side by side with their trade-offs.
3. A pod-lead sign-off step before publishing.
4. Live updates over WebSockets in place of reloads.
5. Real Google Workspace credentials through Workload Identity Federation.
6. Fairness reports over several months.

## Project layout

```
backend/app/domain/     pure engine: calendars, CP-SAT solver, validator, recommender, pre-check, rules parser
backend/app/services/   snapshot (DB -> problem), roster lifecycle, Sheets sync, audit
backend/app/api/        FastAPI routes, scope filtering, AI assistant
backend/app/integrations/  Google Sheets/Drive/Calendar client + mock
backend/tests/          engine + end-to-end API tests
frontend/src/           React app (dashboard, roster views, conflicts, leaves, people, brands & rules, Sheets, audit)
infra/postgres/         replication + backup scripts
docs/architecture.html  architecture document
```

## Assumptions

All assumptions can be configured; see section 12 of the architecture document. In brief:
- Rosters are day-level.
- Each employee gets 1 weekly off per Mon–Sun week, and works at most 6 days in a row.
- The national holiday list applies to everyone, plus a regional calendar for each employee's location.
- Working a public holiday earns a comp-off valid for 30 days.
- Only approved leave is binding.
- All times are IST.
- The Google Sheet is the source of truth for rules, and the database for everything else.
