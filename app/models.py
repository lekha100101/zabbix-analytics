from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class HostGroup(Base):
    __tablename__ = "host_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    zabbix_groupid: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Host(Base):
    __tablename__ = "hosts"

    id: Mapped[int] = mapped_column(primary_key=True)
    zabbix_hostid: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    technical_name: Mapped[str] = mapped_column(String(255), index=True)
    visible_name: Mapped[str] = mapped_column(String(255), index=True)
    status: Mapped[int] = mapped_column(Integer, default=0)
    groups: Mapped[list] = mapped_column(JSONB, default=list)
    tags: Mapped[list] = mapped_column(JSONB, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Trigger(Base):
    __tablename__ = "triggers"

    id: Mapped[int] = mapped_column(primary_key=True)
    zabbix_triggerid: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    description: Mapped[str] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[int] = mapped_column(Integer, default=0)
    hosts: Mapped[list] = mapped_column(JSONB, default=list)
    tags: Mapped[list] = mapped_column(JSONB, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Problem(Base):
    __tablename__ = "problems"

    id: Mapped[int] = mapped_column(primary_key=True)
    zabbix_eventid: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    zabbix_triggerid: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True)
    name: Mapped[str] = mapped_column(Text)
    severity: Mapped[int] = mapped_column(Integer, default=0, index=True)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    recovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    hosts: Mapped[list] = mapped_column(JSONB, default=list)
    tags: Mapped[list] = mapped_column(JSONB, default=list)
    impact_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    score_breakdown: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ScoringRule(Base):
    __tablename__ = "scoring_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    rule_type: Mapped[str] = mapped_column(String(32), index=True)
    key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    value: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    points: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
