from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from broadcast.config import project_root
from .models import Avatar, Base, LiveRoom, Persona, User

_engine = None
_SessionLocal = None


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    db_path = project_root() / "data" / "app.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path.as_posix()}"


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        url = get_database_url()
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        _engine = create_engine(url, future=True, connect_args=connect_args)
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    return _engine


def get_session() -> Session:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal()


def init_db() -> None:
    engine = get_engine()
    Base.metadata.create_all(engine)
    with get_session() as db:
        if not db.scalar(select(User).limit(1)):
            db.add(User(username="admin", password_hash="admin"))  # MVP 明文仅本地
        if not db.scalar(select(Avatar).limit(1)):
            db.add(Avatar(name="demo", root_path="data/avatars/demo", status=1))
        if not db.scalar(select(Persona).limit(1)):
            db.add(
                Persona(
                    name="小助手",
                    system_prompt="你是直播间数字人助手。回复不超过30字，口语化，友善。",
                    greeting="大家好，欢迎来到直播间。",
                    temperature=0.7,
                )
            )
        if not db.scalar(select(LiveRoom).where(LiveRoom.room_key == "demo")):
            db.add(
                LiveRoom(
                    room_key="demo",
                    title="演示直播间",
                    platform="douyin",
                    status=0,
                )
            )
        db.commit()
