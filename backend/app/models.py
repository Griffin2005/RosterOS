"""ORM models. Mirrors Figure 3 of docs/architecture.html.

String UUID keys and JSON columns keep the schema portable between SQLite
(local dev, tests) and PostgreSQL (docker / AWS RDS).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text,
                        UniqueConstraint, Float)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def uid() -> str:
    return str(uuid.uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc)


class Pod(Base):
    __tablename__ = "pod"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    lead_id: Mapped[str | None] = mapped_column(ForeignKey("employee.id", use_alter=True, ondelete="SET NULL"))


class Employee(Base):
    __tablename__ = "employee"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    pod_id: Mapped[str | None] = mapped_column(ForeignKey("pod.id", ondelete="SET NULL"))
    capacity: Mapped[int] = mapped_column(Integer, default=100)
    weekly_offs: Mapped[int] = mapped_column(Integer, default=1)
    max_consecutive: Mapped[int] = mapped_column(Integer, default=6)
    holiday_calendar_id: Mapped[str | None] = mapped_column(String(40))
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    assignments: Mapped[list["Assignment"]] = relationship(back_populates="employee", cascade="all, delete-orphan")


class Brand(Base):
    __tablename__ = "brand"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    pod_id: Mapped[str | None] = mapped_column(ForeignKey("pod.id", ondelete="SET NULL"))
    tier: Mapped[str] = mapped_column(String(4), default="C")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Process(Base):
    __tablename__ = "process"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    code: Mapped[str] = mapped_column(String(12), unique=True)
    name: Mapped[str] = mapped_column(String(120))


class RuleSet(Base):
    __tablename__ = "rule_set"
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    sheet_revision: Mapped[str] = mapped_column(String(64))
    checksum: Mapped[str] = mapped_column(String(64))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    imported_by: Mapped[str | None] = mapped_column(String(80))
    summary: Mapped[dict] = mapped_column(JSON, default=dict)


class ServiceLine(Base):
    __tablename__ = "service_line"
    __table_args__ = (UniqueConstraint("brand_id", "process_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    brand_id: Mapped[str] = mapped_column(ForeignKey("brand.id", ondelete="CASCADE"))
    process_id: Mapped[str] = mapped_column(ForeignKey("process.id", ondelete="CASCADE"))
    calendar_kind: Mapped[str] = mapped_column(String(16), default="ALL_DAYS")
    weekday_mask: Mapped[int] = mapped_column(Integer, default=127)
    works_ph: Mapped[bool] = mapped_column(Boolean, default=True)
    min_heads: Mapped[int] = mapped_column(Integer, default=1)
    weekday_min: Mapped[dict] = mapped_column(JSON, default=dict)
    shift_start: Mapped[int] = mapped_column(Integer, default=540)
    shift_end: Mapped[int] = mapped_column(Integer, default=1080)
    rule_set_version: Mapped[int | None] = mapped_column(ForeignKey("rule_set.version"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    brand: Mapped[Brand] = relationship()
    process: Mapped[Process] = relationship()


class CoverageOverride(Base):
    __tablename__ = "coverage_override"
    __table_args__ = (UniqueConstraint("service_line_id", "on_date"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    service_line_id: Mapped[str] = mapped_column(ForeignKey("service_line.id", ondelete="CASCADE"))
    on_date: Mapped[date] = mapped_column(Date)
    min_heads: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(200), default="")


class Assignment(Base):
    __tablename__ = "assignment"
    __table_args__ = (UniqueConstraint("employee_id", "service_line_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employee.id", ondelete="CASCADE"))
    service_line_id: Mapped[str] = mapped_column(ForeignKey("service_line.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(10), default="PRIMARY")
    load_pct: Mapped[int] = mapped_column(Integer, default=100)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)

    employee: Mapped[Employee] = relationship(back_populates="assignments")
    service_line: Mapped[ServiceLine] = relationship()


class Leave(Base):
    __tablename__ = "leave"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employee.id", ondelete="CASCADE"))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    type: Mapped[str] = mapped_column(String(12), default="PL")       # PL SL COMP_OFF
    status: Mapped[str] = mapped_column(String(12), default="PENDING")  # PENDING APPROVED REJECTED CANCELLED
    note: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CompOffCredit(Base):
    __tablename__ = "comp_off_credit"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employee.id", ondelete="CASCADE"))
    earned_on: Mapped[date] = mapped_column(Date)
    expires_on: Mapped[date] = mapped_column(Date)
    roster_id: Mapped[str | None] = mapped_column(String(36))
    used_by_leave: Mapped[str | None] = mapped_column(ForeignKey("leave.id", ondelete="SET NULL"))


class Preference(Base):
    __tablename__ = "preference"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employee.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16), default="OFF_DAY")
    value: Mapped[str] = mapped_column(String(40))  # weekday index for OFF_DAY
    weight: Mapped[int] = mapped_column(Integer, default=1)


class Holiday(Base):
    __tablename__ = "holiday"
    __table_args__ = (UniqueConstraint("calendar_id", "on_date"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    calendar_id: Mapped[str] = mapped_column(String(40))
    on_date: Mapped[date] = mapped_column(Date)
    name: Mapped[str] = mapped_column(String(120))


class SolverSetting(Base):
    __tablename__ = "solver_setting"
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[float] = mapped_column(Float)


class Roster(Base):
    __tablename__ = "roster"
    __table_args__ = (UniqueConstraint("month", "version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    month: Mapped[date] = mapped_column(Date)           # first day of the month
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(12), default="DRAFT")  # DRAFT PUBLISHED SUPERSEDED DISCARDED
    parent_id: Mapped[str | None] = mapped_column(String(36))
    rule_set_version: Mapped[int | None] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(12), default="FULL")    # FULL REPAIR EDIT
    note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    solver_stats: Mapped[dict] = mapped_column(JSON, default=dict)

    days: Mapped[list["RosterDay"]] = relationship(back_populates="roster", cascade="all, delete-orphan")


class RosterDay(Base):
    __tablename__ = "roster_day"
    __table_args__ = (UniqueConstraint("roster_id", "employee_id", "on_date"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    roster_id: Mapped[str] = mapped_column(ForeignKey("roster.id", ondelete="CASCADE"), index=True)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employee.id", ondelete="CASCADE"))
    on_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10))
    source: Mapped[str] = mapped_column(String(8), default="SOLVER")
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    covers: Mapped[dict] = mapped_column(JSON, default=dict)  # service_line_id -> as_backup

    roster: Mapped[Roster] = relationship(back_populates="days")


class ConflictAck(Base):
    __tablename__ = "conflict_ack"
    __table_args__ = (UniqueConstraint("roster_id", "conflict_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    roster_id: Mapped[str] = mapped_column(ForeignKey("roster.id", ondelete="CASCADE"))
    conflict_key: Mapped[str] = mapped_column(String(200))
    reason: Mapped[str] = mapped_column(String(400))
    acked_by: Mapped[str] = mapped_column(String(80))
    acked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Job(Base):
    __tablename__ = "job"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String(16))     # GENERATE REPAIR
    status: Mapped[str] = mapped_column(String(12), default="QUEUED")  # QUEUED RUNNING DONE FAILED
    month: Mapped[date] = mapped_column(Date)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    result_roster_id: Mapped[str | None] = mapped_column(String(36))
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserAccount(Base):
    __tablename__ = "user_account"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    username: Mapped[str] = mapped_column(String(60), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(16))
    scope_level: Mapped[str] = mapped_column(String(10))   # COMPANY POD BRAND PROCESS SELF
    scope_id: Mapped[str | None] = mapped_column(String(36))
    employee_id: Mapped[str | None] = mapped_column(ForeignKey("employee.id", ondelete="SET NULL"))


class AuditEvent(Base):
    __tablename__ = "audit_event"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(40))
    entity: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(80))
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Notification(Base):
    __tablename__ = "notification"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    employee_id: Mapped[str | None] = mapped_column(String(36))
    audience: Mapped[str] = mapped_column(String(40), default="ALL")  # ALL | POD:<id> | EMP:<id>
    message: Mapped[str] = mapped_column(Text)
    roster_id: Mapped[str | None] = mapped_column(String(36))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
