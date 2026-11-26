"""AI admin assistant: explains conflicts and proposes fixes, never publishes.

A Messages API tool loop hosted inside the API service: every tool runs with
the caller's permissions against the same services a human uses.

Privacy: the model never sees an employee's name. Names in the user's
messages and in every tool result are replaced with employee codes (E12)
before the request leaves our infrastructure, and codes in the model's reply
are turned back into names only for the person reading it. Only schedule
facts (codes, brands, dates, statuses) are sent; no contact data exists to
send. Each request is rate limited per user and audited without its content.
Without ANTHROPIC_API_KEY it degrades to the validator's templated explanations.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models as M
from ..auth import MANAGE, User, require
from ..config import get_settings
from ..db import get_db
from ..domain.calendar import required_heads
from ..domain.precheck import diff_plans
from ..domain.solver import solve
from ..domain.types import Status
from ..domain.validator import heads_on, summarize, validate, why_unavailable
from ..services import rosters as R
from ..security import limiter
from ..services.audit import audit
from ..services.snapshot import build_problem, roster_plan
from .scope import filter_grid

router = APIRouter(prefix="/api/assistant")

SYSTEM = """You are the roster assistant for an operations manager at a customer-experience company that staffs \
many D2C brands. Each brand has service lines (brand x process, e.g. "Kesar Kitchen · CS") with their own operating \
calendar and minimum heads. Employees have weekly offs, leave, preferences and a daily load capacity.

Use the tools to look up facts before answering; never guess dates, names or numbers. Hard conflicts (coverage gaps, \
leave clashes, missing weekly offs, streaks over the limit, over-allocation) must be fixed or explicitly acknowledged; \
preferences are soft and yield to coverage.

You can explain, compare options and run what-if checks. You can also draft a change, which creates an unpublished \
draft roster for a human to review. You cannot publish, delete, or change master data; if asked, say a manager does \
that in the app. Keep answers short and concrete: name the people, dates and lines, and say what each option costs.

For privacy, employees appear only as codes such as E12, in questions and in tool results. Refer to people by their \
code exactly as written (the app shows the reader the real name) and pass codes to tools that take a name."""


class Pseudonymiser:
    """Swaps employee names for codes on the way to the model and back."""

    def __init__(self, employees):
        self.names = sorted(((e.name, e.code) for e in employees), key=lambda t: -len(t[0]))
        firsts = Counter(e.name.split()[0].lower() for e in employees)
        self.first = {e.name.split()[0]: e.code for e in employees if firsts[e.name.split()[0].lower()] == 1}
        self.code_name = {e.code: e.name for e in employees}

    def mask(self, text: str) -> str:
        for name, code in self.names:
            text = re.sub(re.escape(name), code, text, flags=re.IGNORECASE)
        for first, code in self.first.items():
            text = re.sub(rf"\b{re.escape(first)}\b", code, text, flags=re.IGNORECASE)
        return text

    def unmask(self, text: str) -> str:
        return re.sub(r"\b(E\d{2,5})\b", lambda m: self.code_name.get(m.group(1), m.group(1)), text)

TOOLS: list[dict[str, Any]] = [
    {"name": "list_conflicts", "strict": True,
     "description": "Open conflicts on the roster being viewed. Filter by severity (HARD, SOFT, INFO) or ALL.",
     "input_schema": {"type": "object", "additionalProperties": False, "required": ["severity"],
                      "properties": {"severity": {"type": "string", "enum": ["HARD", "SOFT", "INFO", "ALL"]}}}},
    {"name": "get_coverage", "strict": True,
     "description": "Heads scheduled vs required for every line of one brand between two dates (YYYY-MM-DD).",
     "input_schema": {"type": "object", "additionalProperties": False, "required": ["brand", "from_date", "to_date"],
                      "properties": {"brand": {"type": "string"}, "from_date": {"type": "string"},
                                     "to_date": {"type": "string"}}}},
    {"name": "explain_slot", "strict": True,
     "description": "For one brand line on one date: who is trained, and why each person is or isn't covering it.",
     "input_schema": {"type": "object", "additionalProperties": False, "required": ["brand", "process", "date"],
                      "properties": {"brand": {"type": "string"}, "process": {"type": "string"},
                                     "date": {"type": "string"}}}},
    {"name": "suggest_backups", "strict": True,
     "description": "Ranked candidates to cover the open lines of a brand on a date, with costs and blocking rules.",
     "input_schema": {"type": "object", "additionalProperties": False, "required": ["brand", "date"],
                      "properties": {"brand": {"type": "string"}, "date": {"type": "string"}}}},
    {"name": "employee_schedule", "strict": True,
     "description": "One employee's statuses for the month and the lines they carry each working day.",
     "input_schema": {"type": "object", "additionalProperties": False, "required": ["name"],
                      "properties": {"name": {"type": "string"}}}},
    {"name": "what_if_leave", "strict": True,
     "description": "Sandbox: if this employee were on leave for these dates, what breaks and how would a "
                    "minimal-change repair look? Saves nothing.",
     "input_schema": {"type": "object", "additionalProperties": False, "required": ["name", "from_date", "to_date"],
                      "properties": {"name": {"type": "string"}, "from_date": {"type": "string"},
                                     "to_date": {"type": "string"}}}},
    {"name": "draft_change_request", "strict": True,
     "description": "Create an UNPUBLISHED draft applying one suggestion: put an employee to work on a date covering "
                    "the named brand's open lines. A manager must review and publish it.",
     "input_schema": {"type": "object", "additionalProperties": False, "required": ["name", "brand", "date", "reason"],
                      "properties": {"name": {"type": "string"}, "brand": {"type": "string"},
                                     "date": {"type": "string"}, "reason": {"type": "string"}}}},
]


class Ctx:
    def __init__(self, db: Session, roster: M.Roster, user: User):
        self.db, self.roster, self.user = db, roster, user
        self.p = build_problem(db, roster.month)
        self.plan = roster_plan(roster)

    def emp(self, name: str):
        n = name.strip().lower()
        hits = [e for e in self.p.employees if n == e.code.lower()] or \
               [e for e in self.p.employees if n in e.name.lower()]
        if self.user.scope_level == "POD":   # tools respect the caller's scope like the UI does
            hits = [e for e in hits if e.pod_id == self.user.scope_id]
        if not hits:
            raise ValueError(f"No employee in your scope matches '{name}'")
        return hits[0]

    def lines_of(self, brand: str):
        b = brand.strip().lower()
        ls = [l for l in self.p.lines if b in l.brand_name.lower()]
        if self.user.scope_level == "POD":
            ls = [l for l in ls if l.pod_id == self.user.scope_id]
        if not ls:
            raise ValueError(f"No brand in your scope matches '{brand}'")
        return ls

    def first(self, e_id: str) -> str:
        return self.p.emp_by_id[e_id].name


def run_tool(ctx: Ctx, name: str, args: dict) -> Any:
    p, plan = ctx.p, ctx.plan
    if name == "list_conflicts":
        g = filter_grid({"employees": [{"id": e.id, "pod_id": e.pod_id, "cells": [], "assignments": []}
                                       for e in p.employees],
                         "coverage": [], "conflicts": [c.to_dict() for c in validate(p, plan)]}, ctx.user) \
            if ctx.user.scope_level != "COMPANY" else {"conflicts": [c.to_dict() for c in validate(p, plan)]}
        out = [c for c in g["conflicts"] if args["severity"] == "ALL" or c["severity"] == args["severity"]]
        return [{"code": c["code"], "severity": c["severity"], "date": c["date"], "title": c["title"],
                 "detail": c["detail"]} for c in out[:40]] + ([{"note": f"{len(out) - 40} more"}] if len(out) > 40 else [])
    if name == "get_coverage":
        d0, d1 = date.fromisoformat(args["from_date"]), date.fromisoformat(args["to_date"])
        rows = []
        for l in ctx.lines_of(args["brand"]):
            for d in p.days:
                if d0 <= d <= d1:
                    req = required_heads(p, l, d)
                    rows.append({"line": l.label, "date": d.isoformat(), "required": req,
                                 "covering": [ctx.first(x) for x in heads_on(p, plan, l.id, d)] if req else []})
        return rows
    if name == "explain_slot":
        d = date.fromisoformat(args["date"])
        line = next((l for l in ctx.lines_of(args["brand"]) if l.process_code == args["process"].upper()), None)
        if line is None:
            raise ValueError("That brand has no such process")
        return {"line": line.label, "date": d.isoformat(), "required": required_heads(p, line, d),
                "covering": [ctx.first(x) for x in heads_on(p, plan, line.id, d)],
                "trained": [{"name": ctx.first(a.employee_id), "role": a.role,
                             "status": why_unavailable(p, plan, a.employee_id, line.id, d)}
                            for a in p.assign_by_line[line.id]]}
    if name == "suggest_backups":
        d = date.fromisoformat(args["date"])
        ids = [l.id for l in ctx.lines_of(args["brand"])]
        return R.suggestions(ctx.db, ctx.roster.id, d, ids)[:6] or [{"note": "No open lines for that brand on that date."}]
    if name == "employee_schedule":
        e = ctx.emp(args["name"])
        return {"employee": e.name, "days": [{"date": d.isoformat(), "status": plan.get(e.id, d).status.value,
                                              "lines": [p.line_by_id[l].label for l in plan.get(e.id, d).covers]}
                                             for d in p.days if plan.get(e.id, d)]}
    if name == "what_if_leave":
        e = ctx.emp(args["name"])
        d0, d1 = date.fromisoformat(args["from_date"]), date.fromisoformat(args["to_date"])
        p2 = build_problem(ctx.db, ctx.roster.month, baseline=plan,
                           repair_window=(max(p.start, d0 - timedelta(days=7)), min(p.end, d1 + timedelta(days=7))),
                           locks_from=plan)
        d = d0
        while d <= d1:
            if p2.start <= d <= p2.end:
                p2.leaves[(e.id, d)] = Status.LEAVE
            d += timedelta(days=1)
        broken = [c for c in validate(p2, plan) if c.severity == "HARD"]
        res = solve(p2)
        after = validate(p2, res.plan)
        changes = diff_plans(plan, res.plan)
        return {"breaks_without_repair": [c.title + f" ({c.date})" for c in broken][:15],
                "repair": {"cells_changed": len(changes),
                           "changes": [{"who": ctx.first(c["employee_id"]), "date": c["date"],
                                        "before": c["before"]["status"] if c["before"] else None,
                                        "after": c["after"]["status"],
                                        "lines": [p.line_by_id[l].label for l in c["after"]["covers"]]}
                                       for c in changes][:20],
                           "conflicts_after": summarize(after)}}
    if name == "draft_change_request":
        if ctx.user.role not in MANAGE | {"POD_LEAD"}:
            raise ValueError("Your role can't draft roster changes.")
        e = ctx.emp(args["name"])
        d = date.fromisoformat(args["date"])
        ids = [l.id for l in ctx.lines_of(args["brand"])]
        sugg = next((s for s in R.suggestions(ctx.db, ctx.roster.id, d, ids) if s["employee_id"] == e.id), None)
        if sugg is None or sugg["verdict"] == "REJECTED":
            raise ValueError(f"{e.name} can't cover {args['brand']} on {d}: "
                             + "; ".join(sugg["reasons"] if sugg else ["not trained on those lines"]))
        r, result = R.apply_edits(ctx.db, ctx.roster.id, sugg["actions"], f"assistant via {ctx.user.username}")
        audit(ctx.db, ctx.user.username, "ASSISTANT_DRAFTED_CHANGE", "roster", r.id, None,
              {"reason": args["reason"], "actions": sugg["actions"]})
        ctx.db.commit()
        return {"draft_roster_id": r.id, "version": r.version, "status": r.status,
                "conflicts_now": result["summary"], "note": "Unpublished draft. A manager must review and publish."}
    raise ValueError(f"Unknown tool {name}")


class ChatIn(BaseModel):
    roster_id: str
    messages: list[dict]  # [{role: user|assistant, content: str}]


def offline_answer(ctx: Ctx) -> str:
    hard = [c for c in validate(ctx.p, ctx.plan) if c.severity == "HARD"]
    if not hard:
        return "No hard conflicts on this roster. (AI is offline: set ANTHROPIC_API_KEY for free-form questions.)"
    lines = [f"{len(hard)} hard conflict(s). The first ones:"]
    for c in hard[:5]:
        lines.append(f"• {c.title} on {c.date:%a %d %b}: {c.detail}")
        if c.code in ("C01", "C02") and c.line_id:
            sugg = R.suggestions(ctx.db, ctx.roster.id, c.date, [c.line_id])
            best = next((s for s in sugg if s["verdict"] != "REJECTED"), None)
            lines.append(f"  Best option: {best['name']} ({'; '.join(best['reasons'])})." if best
                         else "  No single person can cover it; try Auto-repair or acknowledge with a reason.")
    lines.append("(AI is offline: these are the validator's own explanations. Set ANTHROPIC_API_KEY for chat.)")
    return "\n".join(lines)


@router.post("/chat")
def chat(body: ChatIn, db: Session = Depends(get_db),
         user: User = Depends(require({"SUPER_ADMIN", "OPS_MANAGER", "POD_LEAD", "AUDITOR"}))):
    roster = db.get(M.Roster, body.roster_id)
    if roster is None:
        raise HTTPException(404, "Roster not found")
    s = get_settings()
    if not limiter.hit(f"assistant:{user.id}", s.assistant_rate_per_10min, 600):
        raise HTTPException(429, "You've asked a lot in the last few minutes. Try again shortly.")
    if len(body.messages) > 40 or sum(len(str(m.get("content", ""))) for m in body.messages) > 40_000:
        raise HTTPException(413, "This conversation is too long. Start a new one.")
    ctx = Ctx(db, roster, user)
    if not s.anthropic_api_key:
        _audit_query(db, user, roster, "offline", [])
        return {"reply": offline_answer(ctx), "tool_calls": [], "mode": "offline"}

    import anthropic
    client = anthropic.Anthropic(api_key=s.anthropic_api_key)
    pz = Pseudonymiser(ctx.p.employees)
    context = (f"Viewing roster for {roster.month:%B %Y}, version {roster.version} ({roster.status}). "
               f"Today is {date.today():%d %b %Y}. User role: {user.role}, scope {user.scope_level}.")
    messages: list[Any] = [{"role": m["role"], "content": pz.mask(m["content"])} for m in body.messages
                           if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)]
    if not messages or messages[0]["role"] != "user":
        raise HTTPException(422, "Start the conversation with a user message.")
    calls: list[dict] = []
    try:
        return _loop(client, s, context, messages, ctx, pz, calls)
    finally:
        _audit_query(db, user, roster, "ai", [c["tool"] for c in calls])


def _audit_query(db: Session, user: User, roster: M.Roster, mode: str, tools: list[str]) -> None:
    audit(db, user.username, "ASSISTANT_QUERY", "roster", roster.id, None, {"mode": mode, "tools": tools})
    db.commit()


def _loop(client, s, context: str, messages: list[Any], ctx: Ctx, pz: Pseudonymiser, calls: list[dict]) -> dict:
    import anthropic
    for _ in range(8):  # bounded agent loop
        try:
            resp = client.beta.messages.create(
                model=s.assistant_model, max_tokens=16000,
                system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}},
                        {"type": "text", "text": context}],
                tools=TOOLS, tool_choice={"type": "auto"},
                output_config={"effort": "medium"},
                betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                messages=messages,
            )
        except anthropic.RateLimitError:
            raise HTTPException(429, "The AI service is busy. Try again in a minute.")
        except anthropic.APIStatusError as e:
            if e.status_code >= 500:
                raise HTTPException(502, "The AI service is unavailable right now.")
            raise HTTPException(502, f"AI request failed: {e.message}")
        except anthropic.APIConnectionError:
            return {"reply": offline_answer(ctx), "tool_calls": calls, "mode": "offline"}
        if resp.stop_reason == "refusal":
            return {"reply": "The assistant declined this request. Rephrase it as a roster question.",
                    "tool_calls": calls, "mode": "ai"}
        # keep the full content (incl. thinking blocks) so the next turn stays valid
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason != "tool_use":
            text = "\n".join(b.text for b in resp.content if b.type == "text").strip()
            return {"reply": pz.unmask(text) or "(no answer)", "tool_calls": calls, "mode": "ai"}
        results = []
        for b in resp.content:
            if b.type != "tool_use":
                continue
            try:
                out = run_tool(ctx, b.name, dict(b.input))
                results.append({"type": "tool_result", "tool_use_id": b.id,
                                "content": pz.mask(json.dumps(out, default=str, ensure_ascii=False))[:20000]})
                calls.append({"tool": b.name, "input": b.input, "ok": True})
            except Exception as exc:  # report tool errors back to the model
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": pz.mask(str(exc)),
                                "is_error": True})
                calls.append({"tool": b.name, "input": b.input, "ok": False, "error": str(exc)})
        messages.append({"role": "user", "content": results})
    return {"reply": "I ran out of steps on that one. Try a narrower question.", "tool_calls": calls, "mode": "ai"}
