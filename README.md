# RosterOS: Smart Roster Management System

A browser-based tool that plans, generates, validates and manages monthly rosters for a multi-brand CX operations team. Working rules and minimum coverage live in a Google Sheet. A constraint solver (Google OR-Tools CP-SAT) builds the month, proving the fewest possible coverage gaps before it optimises anything else, and an independent rule engine checks every roster. Any gap the system can't close is reported with its cause and ranked fixes, never hidden.

- **Architecture:** [docs/architecture.html](docs/architecture.html) covers the topology, solver model, data model, change flow, sync/backup, roles and security.
- **Sample data:** 32 employees in 4 pods, and 22 brands. 18 brands are run by one dedicated person (82%). 2 brands have two people and 2 have three, with both separate and shared processes. There are 46 service lines across 5 processes (CS, ACC, NDR, RET, ESC).
- **Sign-in:** no password appears in this repository or in the app. See [Accounts and credentials](#accounts-and-credentials).

## Run it

### Local (no Docker)

```bash
# API (Python 3.11+); seeds the sample data and publishes December 2026 on first start
cd backend
python -m venv .venv && .venv/Scripts/activate        # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --port 8000                      # prints generated passwords once (see below)

# Web (Node 20+), in another terminal
cd frontend
npm install
npm run dev                                           # http://localhost:5173
```

If you run `npm run build` first, the API also serves the built app at http://localhost:8000.

### Docker (full stack)

```bash
cp .env.example .env        # set JWT_SECRET, ADMIN_PASSWORD, DEMO_PASSWORD and the Postgres secrets
docker compose up --build   # http://localhost:8080
```

The Compose stack runs:
- the web app (nginx, with the same security headers as the API)
- the API
- 2 solver workers, which have no database credentials
- the scheduler
- a Google Sheets/Calendar mock (reachable from this machine only)
- a PostgreSQL 16 primary with continuous WAL archiving to `./backups`
- a streaming read replica
- a backup job that writes a `pg_dump` every 15 minutes
- Redis

An existing database from an older version is upgraded in place on start-up: missing columns are added, and seeded accounts that still carry an old password hash are given the passwords from `.env`. Run `docker compose down -v` first if you want a completely fresh seed.

### Hosted demo (Render)

The root `Dockerfile` builds a single container: FastAPI serves the API, the built React app and the embedded Google mock on one port. `render.yaml` is a Render Blueprint for it plus a managed PostgreSQL 16 database. To deploy, open Render, choose **New → Blueprint**, and pick this repository. Render asks for `ADMIN_PASSWORD` (required) and `DEMO_PASSWORD` (optional) as secrets; `JWT_SECRET` is generated and `DATABASE_URL` is wired to the database for you. The image itself defaults to `ENV=production`, so a host that skips the Blueprint's settings still gets production mode rather than development mode.

Data lives in Render Postgres and survives deploys and restarts. The database accepts no connections from the internet; only the web service reaches it, over Render's private network. On the first start against an empty database the app seeds the sample data and publishes December. Later starts only add missing columns and missing demo accounts, and set passwords for accounts that don't have one yet. The hosted demo was migrated from the Compose database with `pg_dump`/`pg_restore`, so it carries the same rosters, leaves and audit trail.

Without `DATABASE_URL` the image falls back to a SQLite file seeded at build time, which resets on every deploy.

On Render's free plan:
- The service sleeps after 15 minutes idle. The first request after that takes about a minute.
- Generating a month takes 45–55 seconds on the plan's 0.1 vCPU. Coverage is still proven optimal; the measured result matched an 8-core run.
- A free Postgres database expires 30 days after it is created unless it is upgraded to a paid plan.

The replica, backups and Redis workers are in the Compose stack and the AWS design, not in this single container.

## Accounts and credentials

Credentials are deployment secrets, never source code:

| Setting | Used for | If it's missing |
|---|---|---|
| `ADMIN_PASSWORD` | the `admin` account | Production refuses to start. Development generates one and prints it once. |
| `DEMO_PASSWORD` | every other seeded account | Production leaves those accounts disabled until the admin issues one-time passwords from **Team**. Development generates them and prints them once. |

Both must pass the password policy, or the app refuses to start. Reviewers of the hosted demo receive credentials privately with the submission.

| User | Role | Sees and does |
|---|---|---|
| `admin` | Super Admin | Everything, including Team, Security and solver settings |
| `ops` | Ops Manager | Plans, generates and publishes; manages pod leads, brand owners and employees |
| `lead.north`, `lead.south`, `lead.east`, `lead.west` | Pod Lead | Their pod; approves leave and edits schedules in the pod |
| `brand.kesar` | Brand Owner | One brand's coverage; sees that someone is away, not why |
| `meera`, `arjun` | Employee | Their own schedule, plus who covers their brands |
| `auditor` | Auditor | Read-only: rosters, audit log and security overview |

New people are added under **Team**. An admin creates the account with a role and scope and receives a one-time password, shown once, to hand over privately. The new member must set their own password at first sign-in before anything else works.

## Security and privacy

The **Security** page shows the live state of each control below, and the **Audit log** records every sign-in, team change and export.

**Passwords**
- Hashed with **Argon2id** (OWASP parameters: 19 MiB, 2 iterations), with a unique salt each. Older PBKDF2 hashes still verify and are upgraded on the next sign-in.
- The policy is enforced on the server and mirrored live in the UI. A password needs:
  - 12–128 characters, with upper and lower case, a number and a symbol
  - not to contain the username or name
  - not to be a common password
  - no runs like `aaaa` or `1234`
- Password fields have a show/hide toggle and a Caps Lock warning, plus a strength meter.

**Brute force**
- An account locks for 15 minutes after 5 failed attempts. An admin can unlock it.
- Each IP address gets 20 sign-in attempts per minute.
- Unknown usernames get the same answer, timing and lockout as wrong passwords, so the sign-in form can't be used to discover accounts.

**Sessions**
- The session is a signed JWT in an `httpOnly`, `SameSite=Strict` cookie, marked `Secure` in production. Page scripts can never read it, and nothing is kept in `localStorage`.
- Every state-changing request must carry a CSRF token that is bound to the session.
- Changing a password, an admin reset, a role change, deactivation or "sign out everywhere" bumps a session version, which kills every older session at once.

**Least privilege**
- There are six roles and five scope levels. All filtering happens on the server.
- Nobody can grant a role at or above their own; for example, an ops manager can't create admins or auditors.
- Nobody can deactivate or demote themselves, and the last active super admin can't be removed.

**HTTP hardening**
- Headers: CSP (scripts from self only, `frame-ancestors 'none'`), HSTS over HTTPS, `X-Frame-Options`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, COOP, and `no-store` on API responses.
- The API docs are disabled in production, and the server banner is hidden.
- The app shell never answers for unknown `/api` paths or for files outside the web root.

**Privacy**
- Accounts hold no contact data.
- Client IPs are stored in the audit log only as keyed hashes.
- Leave reasons and notes are visible only to the employee, their pod lead and managers.
- Non-managers see the staff directory, not other people's capacity or preferences.
- The company-wide dashboard workbook is limited to roles that already see company or pod rosters.
- **The AI assistant never sees a name.** Names in questions and tool results are swapped for employee codes before anything leaves the server, and swapped back only in the reply shown to the reader. Each request is rate limited and audited without its content.

**Exports**
- An export contains only the exporter's scope, and every export is audited.
- Text from the database that starts with `=`, `+`, `-` or `@` is neutralised so it can't run as a spreadsheet formula.

**Deployment**
- Production mode refuses to start with a weak `JWT_SECRET` or without `ADMIN_PASSWORD`.
- An unset `JWT_SECRET` never falls back to the placeholder in the code (which is public): the app generates a random signing key at start-up instead.
- Secrets never enter an image layer.
- Containers run as a non-root user.

## Optimisation

### Solver

The solver runs in two lexicographic phases on each independent part of the problem:

1. **Phase 1** minimises only the number of uncovered line-days and proves that minimum. This model is easy, with a tight bound.
2. **Phase 2** fixes coverage at that proven minimum. Starting from phase 1's solution, it then optimises fairness, preferences, backup use and stability.

Coverage can never be traded for comfort. Even when phase 2 runs out of time, the roster's coverage is provably the best the rules allow.

The problem is also split into the connected components of the employee–line graph. In the sample data that gives three groups: East, West, and North+South, which are linked by a cross-pod backup. Each group is solved with every worker in turn.

On small hosts the quality phase also stops once it stops improving, rather than burning the whole time limit.

Measured on the sample data:

| Setup | Before | After |
|---|---|---|
| 1 full core, December, 60 s limit | timed out with **16 false hard gaps** | the 1 real gap, **proven in about 1 s** |
| 0.1 vCPU (Render free plan), January | **22 false gaps** at a 20 s limit | coverage proven, 4 real gaps (identical to the 8-core optimum), 52 s |
| 8 cores, December | optimal in 3–7 s | optimal in 5 s |
| 8 cores, January | optimal in 13 s | optimal in **6.6 s** |

January's 4 gaps fall on 1 January. December ends with some owners at their maximum run of consecutive days, so they must rest that day. The validator explains each one.

Solving the parts one after another beat running them in parallel: three parts with two workers each never proved optimality within 30 s. The tests pin the single-core guarantee.

### Web and API

- Each page loads its own small chunk of code (the largest page is 6 KB gzipped).
- Assets have content-hashed file names and are cached for a year.
- JSON is gzipped: the month grid goes from 349 KB to 17 KB on the wire.
- The audit log is indexed by action and time.

## Excel export: a linked workbook

**Excel** downloads a workbook in which the sheets reference each other through formulas and named ranges:

| Sheet | What it holds |
|---|---|
| **Roster** | One status code per person per day. This is the sheet to edit, and it has a dropdown and colour coding. |
| **Covers** | Who the solver put on which line each day, with a live check of whether that person still counts: `=IF(INDEX(RosterGrid, MATCH(code,…), MATCH(date,…))="W",1,0)` |
| **Requirements** | Required heads per line per day, taken from the rules. |
| **Coverage** | `=SUMIFS(CoverCounts, CoverDates, date, CoverLines, line)`, compared against Requirements. Gaps turn red. |
| **Employees**, **Pods**, **Lines**, **Assignments** | Lookups across sheets: pod lead, headcount, working days, gaps per pod, staffing depth per line. |
| **Overview** | KPIs, with links to every sheet and back to the app. |

Change a `W` to `L` on the Roster sheet and Coverage, Pods, Employees and Overview recalculate. A planner can try a what-if in Excel before making the change in RosterOS.

This was verified in Microsoft Excel. Excel's figures matched the app's validator exactly: 1,272 required line-days, 1 uncovered, 99.92% coverage. Marking one employee on leave in the sheet raised the uncovered count from 1 to 3 and turned those cells red. The workbook had no formula errors.

## Tests

```bash
cd backend && python -m pytest -q   # 42 tests
```

- **Engine:** each hard rule, infeasibility reporting, minimal-change repair, the sample month, how the problem splits into parts, and the single-core coverage proof.
- **API:** the full change flow (leave after publishing, gap, suggestions, repair, publish), scoped views, a rules change from the Sheet, and exports, including the workbook's formulas and its audit entry.
- **Security:** the hashing format and the upgrade of old hashes, the password policy, the cookie flags, CSRF enforcement, lockout and unlock, identical answers for unknown users, the IP rate limit, forced password change, privilege escalation attempts, session revocation, data scoping, security headers, path traversal, and the start-up checks on secrets.

## Demo script (about 5 minutes)

1. Open the app's URL. The landing page explains the approach. Sign in as `ops`. The dashboard shows December v1 at 99.9% coverage, with one gap acknowledged with a reason: Bloom Basket ACC on 22 Dec, when both people trained on it are on leave. The solver card says the coverage is proven to have the fewest possible gaps.
2. **Roster:** switch between the company, pod, brand, process and employee views. Click any date to see every line's coverage that day and who is away. Kesar Kitchen is a single-resource brand; trained backups cover its owner's weekly offs.
3. **Leaves:** sign in as `meera` and request a day off on a day she alone covers Kesar Kitchen. Sign in as `lead.south` and approve it. The impact dialog lists the new gaps and the leave clash right away.
4. Open a gap to see ranked backups, each with its cost and the rule that blocks the rejected ones. Click **Auto-repair**: only a handful of cells near the change move. Review **Changes**, then **Publish**. The affected people are notified and the Google Sheet tabs update.
5. **Excel:** download the workbook, change a status on the Roster sheet, and watch Coverage recalculate.
6. **Google Sheets:** raise a minimum-heads value in the rules sheet and save. Under **Brands & rules**, click **Check Sheet for changes** to see the diff and any bad rows, then import it. The roster is flagged as stale and the new shortfall shows up.
7. Sign in as `admin`. On **Team**, add a member to get a one-time password, then sign in as them to see the forced password change. **Security** shows the controls and the sign-in events you just created.

## Tell us how you think

**1. How did you model employees, brands, processes, pods and their relationships?**
The unit of coverage is the **service line**: one brand × one process. Each line has its own operating calendar (365 days, daily with public holidays off, Sundays and public holidays off, or custom weekdays), minimum heads, per-weekday minimums, date-specific overrides and a shift window. People attach to lines through **assignments**, which carry a role (`PRIMARY` or `BACKUP`) and a load percentage against the person's daily capacity. This allows one person to own a whole brand, several people to split or share a brand's processes, and one person to back up lines across brands. Pods group employees and brands, and each pod has a lead. Rosters are versioned. Each `roster_day` records a person's status for a date and the lines they carry that day, which keeps a brand's operating calendar separate from each person's schedule. Sign-in accounts are a separate entity with a role and a scope (company, pod, brand or self), linked to an employee where relevant.

**2. How does the system generate a roster and check it?**
Generation takes a frozen snapshot of the month, expands demand per line per day, and runs a pre-check that finds slots no roster could fill. It then builds a CP-SAT model:
- **Hard constraints:** leave and holidays, coverage, capacity, shift compatibility, weekly offs, maximum consecutive days across month boundaries, and manual locks.
- **Optimised second:** using a backup, overriding a preferred off-day, working a public holiday, an unfair Sunday spread, and, in repair mode, changed cells.

The model is solved lexicographically. Phase 1 proves the minimum number of uncovered slots. Phase 2 holds coverage at that minimum and optimises the rest. Coverage uses slack, so a month that can't be fully staffed still yields the best possible roster, along with an exact list of unfilled slots. The model is split into independent groups of people and lines, which halved the solve time for January. Each result, and every manual edit, then goes through a separate deterministic validator. A draft can't be published while a hard conflict is open, unless a manager acknowledges it in writing.

**3. Single-resource brands vs. brands with several people?**
The model treats them the same; only the data differs. A single owner carries all of a brand's lines at a combined load of 100% or less, so their weekly off must fall on a day the brand is closed, or a trained backup must cover it. The solver staggers owners' offs so that each pod lead (a backup on every line in the pod) and cross-trained peers can absorb them. For multi-person brands, the solver staggers offs within the brand. Two people sharing a line can't both be off on a day that needs one head. The validator also flags single-resource lines that have no trained backup at all.

**4. What happens when the sole owner of a brand is unavailable on a required day?**
Approving the leave immediately re-validates the published roster. It flags `C05` (the owner is scheduled during leave) and `C01` on each of the brand's open lines. The recommender ranks every trained person:
- Can they take all the lines, or only some?
- Would it break their capacity, a shift window, the streak limit or their weekly off?
- What does it cost?

Each option comes with concrete cell changes. If no single move works, **Auto-repair** re-solves a window around the change with the rest of the month frozen, minimising changed cells. It can chain moves, for example handing a backup's own line to someone else to free them. The manager reviews the diff and publishes.

**5. Conflicting requirements or insufficient staffing?**
There are three layers:
- The pre-check names impossible slots and their cause, such as "only Priya is trained, and she is on leave".
- The solver proves the minimum number of slots that must stay short and reports exactly which ones.
- The validator lists every violation with a structured explanation.

Mandatory rules always outrank preferences. That holds by construction (coverage is settled in phase 1, before preferences are even considered), not merely because of weighting. Anything left over stays visible until it's fixed or acknowledged with a reason, and the acknowledgement carries forward to later versions.

**6. What is automated, and what stays under human control?**
- **Automated:** generating rosters, validating every edit, re-validating when leaves or rules change, ranking backups, repairing rosters with minimal changes, importing rules from the Sheet, pushing to the dashboards, comp-off credits, notifications, account lockout and the audit trail.
- **Human:** approving leave, publishing, acknowledging unfixable gaps, locking cells, changing assignments and rules, and granting access to people.

Staffing trade-offs affect clients and people, so the system proposes and explains but never publishes on its own. The AI assistant follows the same rule: it can draft a change, but a manager publishes it.

**7. What would change if the team and brand count doubled?**
The solver already splits into independent groups of pods and settles coverage first, so a larger company mostly means more, similarly sized groups. At larger sizes I would:
- solve the groups on separate workers in parallel (each with its own cores), with a coordination pass for cross-pod backups;
- keep repair windows small;
- move the validator to incremental, per-cell checks;
- split the Sheets sync and the assistant into their own services, as Figure 1 shows;
- move rate limits and lockout counters to Redis, and add PostgreSQL row-level security in the database to back up the API scoping;
- put sign-in behind the company identity provider (Cognito or Google Workspace SSO with MFA);
- run multiple API replicas behind the load balancer, with WebSocket fan-out through Redis.

**8. With one more week, what would I improve first?**
1. Shift-level rostering (morning/evening slots), not just day-level.
2. Two or three alternative rosters (fairness-first, stability-first), offered side by side with their trade-offs.
3. A pod-lead sign-off step before publishing.
4. Multi-factor authentication for admins and single sign-on through the company's identity provider.
5. Live updates over WebSockets in place of reloads.
6. Real Google Workspace credentials through Workload Identity Federation.

## Project layout

```
backend/app/domain/        pure engine: calendars, CP-SAT solver, validator, recommender, pre-check, rules parser
backend/app/services/      snapshot (DB -> problem), roster lifecycle, Sheets sync, Excel workbook, audit
backend/app/api/           FastAPI routes: accounts & team, rosters, master data, AI assistant, scope filtering
backend/app/security.py    Argon2id hashing, password policy, rate limiting, export sanitising
backend/app/auth.py        cookie sessions, CSRF, session revocation, role checks
backend/app/bootstrap.py   start-up credentials from secrets, production checks
backend/app/integrations/  Google Sheets/Drive/Calendar client + mock
backend/tests/             engine, API and security tests
frontend/src/              React app: landing, sign-in, dashboard, roster views, conflicts, leaves, people,
                           brands & rules, Sheets, team, security, account, audit
infra/postgres/            replication + backup scripts
docs/architecture.html     architecture document
```

## Assumptions

All assumptions can be configured; see section 12 of the architecture document. In brief:
- Rosters are day-level.
- Each employee gets 1 weekly off per Mon–Sun week, and works at most 6 days in a row.
- The national holiday list applies to everyone, plus a regional calendar for each employee's location.
- Working a public holiday earns a comp-off valid for 30 days.
- Only approved leave is binding.
- Sunday fairness is measured among people who can cover for each other (the same group of pods), not across the whole company.
- All times are IST.
- The Google Sheet is the source of truth for rules, and the database for everything else.
