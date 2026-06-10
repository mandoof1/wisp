"""SQLAlchemy models and database operations."""

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import create_engine, Column, String, Text, Integer, Float, DateTime, JSON
from sqlalchemy.orm import declarative_base, sessionmaker

from server.config import DATABASE_PATH

engine = create_engine(f"sqlite:///{DATABASE_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class Beacon(Base):
    __tablename__ = "beacons"

    id = Column(String, primary_key=True)
    hostname = Column(String)
    username = Column(String)
    os = Column(String)
    arch = Column(String)
    pid = Column(Integer)
    public_key = Column(Text, nullable=True)
    sleep_interval = Column(Integer, default=30)
    jitter = Column(Float, default=0.15)
    first_seen = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_seen = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    tags = Column(JSON, default=list)

    def to_dict(self):
        return {
            "id": self.id,
            "hostname": self.hostname,
            "username": self.username,
            "os": self.os,
            "arch": self.arch,
            "pid": self.pid,
            "sleep_interval": self.sleep_interval,
            "jitter": self.jitter,
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "tags": self.tags or [],
        }


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    beacon_id = Column(String, index=True, nullable=False)
    command = Column(String, nullable=False)
    args = Column(Text, default="")  # JSON string of args list
    timeout = Column(Integer, default=60)
    status = Column(String, default="pending")  # pending | delivered | running | complete | failed
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    delivered_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    output = Column(Text, nullable=True)
    error = Column(Text, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "beacon_id": self.beacon_id,
            "command": self.command,
            "args": json.loads(self.args) if self.args else [],
            "timeout": self.timeout,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "delivered_at": self.delivered_at.isoformat() if self.delivered_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "output": self.output,
            "error": self.error,
        }


def init_db():
    Base.metadata.create_all(engine)


def get_session():
    return SessionLocal()


# --- Beacon ops ---

def register_beacon(db, data: dict) -> Beacon:
    existing = db.query(Beacon).filter(Beacon.id == data["id"]).first()
    now = datetime.now(timezone.utc)
    if existing:
        existing.last_seen = now
        existing.hostname = data.get("hostname", existing.hostname)
        existing.username = data.get("username", existing.username)
        existing.os = data.get("os", existing.os)
        existing.arch = data.get("arch", existing.arch)
        existing.pid = data.get("pid", existing.pid)
        db.commit()
        db.refresh(existing)
        return existing
    beacon = Beacon(
        id=data["id"],
        hostname=data.get("hostname", ""),
        username=data.get("username", ""),
        os=data.get("os", ""),
        arch=data.get("arch", ""),
        pid=data.get("pid", 0),
        public_key=data.get("public_key"),
        sleep_interval=data.get("sleep_interval", 30),
        jitter=data.get("jitter", 0.15),
        first_seen=now,
        last_seen=now,
    )
    db.add(beacon)
    db.commit()
    db.refresh(beacon)
    return beacon


def update_beacon_heartbeat(db, beacon_id: str):
    beacon = db.query(Beacon).filter(Beacon.id == beacon_id).first()
    if beacon:
        beacon.last_seen = datetime.now(timezone.utc)
        db.commit()


# --- Task ops ---

def create_task(db, beacon_id: str, command: str, args: list = None, timeout: int = 60) -> Task:
    task = Task(
        beacon_id=beacon_id,
        command=command,
        args=json.dumps(args or []),
        timeout=timeout,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def get_pending_tasks(db, beacon_id: str) -> list[Task]:
    tasks = (
        db.query(Task)
        .filter(Task.beacon_id == beacon_id, Task.status == "pending")
        .order_by(Task.created_at)
        .all()
    )
    now = datetime.now(timezone.utc)
    for t in tasks:
        t.status = "delivered"
        t.delivered_at = now
    db.commit()
    return tasks


def complete_task(db, task_id: str, output: str = None, error: str = None):
    task = db.query(Task).filter(Task.id == task_id).first()
    if task:
        task.status = "complete" if error is None else "failed"
        task.completed_at = datetime.now(timezone.utc)
        task.output = output
        task.error = error
        db.commit()
        db.refresh(task)
    return task


def get_beacon_tasks(db, beacon_id: str, limit: int = 50) -> list[Task]:
    return (
        db.query(Task)
        .filter(Task.beacon_id == beacon_id)
        .order_by(Task.created_at.desc())
        .limit(limit)
        .all()
    )


def get_all_beacons(db) -> list[Beacon]:
    return db.query(Beacon).order_by(Beacon.last_seen.desc()).all()


def delete_beacon(db, beacon_id: str):
    db.query(Task).filter(Task.beacon_id == beacon_id).delete()
    db.query(Beacon).filter(Beacon.id == beacon_id).delete()
    db.commit()
