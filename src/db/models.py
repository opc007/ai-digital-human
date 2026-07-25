from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Avatar(Base):
    __tablename__ = "avatars"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str] = mapped_column(String(64), default="demo")
    root_path: Mapped[str] = mapped_column(Text, default="data/avatars/demo")
    status: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Persona(Base):
    __tablename__ = "personas"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, default=1)
    avatar_id: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str] = mapped_column(String(64), default="小助手")
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    greeting: Mapped[str] = mapped_column(Text, default="")
    temperature: Mapped[float] = mapped_column(Float, default=0.7)


class LiveRoom(Base):
    __tablename__ = "live_rooms"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    room_key: Mapped[str] = mapped_column(String(64), unique=True, default="demo")
    user_id: Mapped[int] = mapped_column(Integer, default=1)
    avatar_id: Mapped[int] = mapped_column(Integer, default=1)
    persona_id: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(String(128), default="")
    platform: Mapped[str] = mapped_column(String(20), default="douyin")
    rtmp_url: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[int] = mapped_column(Integer, default=0)  # 0 idle 1 live
    mode: Mapped[str] = mapped_column(String(20), default="interactive")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class LiveEvent(Base):
    __tablename__ = "live_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    room_key: Mapped[str] = mapped_column(String(64), default="demo", index=True)
    type: Mapped[str] = mapped_column(String(32), default="")
    payload: Mapped[str] = mapped_column(Text, default="{}")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
