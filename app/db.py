"""SQLite storage: one profile row and the food log.

The profile is kept as a JSON document so new fields need no migration. Each
log entry keeps a few plain columns for fast daily totals (midpoint calories
and macros) and a JSON payload holding the full item and its evaluation.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterator, Optional

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text, create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import settings
from .schemas import Profile

MACRO_COLUMNS = ("calories", "protein_g", "carbs_g", "fat_g")


class Base(DeclarativeBase):
    pass


class ProfileRow(Base):
    __tablename__ = "profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class LogEntry(Base):
    __tablename__ = "log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    day: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    logged_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    servings: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    calories: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    protein_g: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    carbs_g: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fat_g: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    overall: Mapped[str] = mapped_column(String(10), nullable=False)
    thumbnail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)

    def to_dict(self) -> dict[str, Any]:
        payload = self.payload or {}
        return {
            "id": self.id,
            "day": self.day,
            "logged_at": self.logged_at.isoformat(timespec="seconds"),
            "kind": self.kind,
            "name": self.name,
            "servings": self.servings,
            "calories": self.calories,
            "protein_g": self.protein_g,
            "carbs_g": self.carbs_g,
            "fat_g": self.fat_g,
            "overall": self.overall,
            "thumbnail": self.thumbnail,
            "item": payload.get("item"),
            "evaluation": payload.get("evaluation"),
            "explanation": payload.get("explanation"),
        }


# ------------------------------------------------------------------ engine

_engine: Optional[Engine] = None
_session_factory: Optional[sessionmaker[Session]] = None


def init_db(url: Optional[str] = None) -> Engine:
    """Create the engine and tables. Pass "sqlite://" for an in-memory test database."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    if url is None:
        settings.db_path.parent.mkdir(parents=True, exist_ok=True)
        url = settings.database_url
    options: dict[str, Any] = {"connect_args": {"check_same_thread": False}}
    if url in ("sqlite://", "sqlite:///:memory:"):
        # One shared connection, so every session sees the same in-memory data.
        options["poolclass"] = StaticPool
    _engine = create_engine(url, **options)
    Base.metadata.create_all(_engine)
    _session_factory = sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    if _session_factory is None:
        init_db()
    assert _session_factory is not None
    with _session_factory() as session:
        yield session


# ----------------------------------------------------------------- profile


def load_profile(session: Session) -> tuple[Profile, bool]:
    """Return the profile and whether the user has saved one yet."""
    row = session.get(ProfileRow, 1)
    if row is None:
        return Profile(), False
    return Profile.model_validate(row.data), True


def save_profile(session: Session, profile: Profile) -> Profile:
    row = session.get(ProfileRow, 1)
    if row is None:
        row = ProfileRow(id=1)
        session.add(row)
    row.data = profile.model_dump()
    row.updated_at = datetime.now()
    session.commit()
    return profile


# --------------------------------------------------------------------- log


def _midpoint(value: Optional[dict]) -> Optional[float]:
    if not value:
        return None
    return round((value["lo"] + value["hi"]) / 2, 1)


def _fill(entry: LogEntry, item: dict, servings: float, evaluation: dict,
          explanation: Optional[str]) -> None:
    totals = evaluation.get("totals", {})
    entry.kind = item["source"]
    entry.name = item["name"]
    entry.servings = servings
    for column in MACRO_COLUMNS:
        setattr(entry, column, _midpoint(totals.get(column)))
    entry.overall = evaluation["overall"]
    entry.payload = {"item": item, "evaluation": evaluation, "explanation": explanation}


def add_log(session: Session, *, item: dict, servings: float, evaluation: dict,
            explanation: Optional[str] = None, thumbnail: Optional[str] = None,
            day: Optional[str] = None) -> LogEntry:
    entry = LogEntry(
        day=day or date.today().isoformat(),
        logged_at=datetime.now(),
        thumbnail=thumbnail,
    )
    _fill(entry, item, servings, evaluation, explanation)
    session.add(entry)
    session.commit()
    return entry


def update_log(session: Session, entry: LogEntry, *, item: dict, servings: float,
               evaluation: dict, explanation: Optional[str] = None) -> LogEntry:
    _fill(entry, item, servings, evaluation, explanation)
    session.commit()
    return entry


def get_log(session: Session, log_id: int) -> Optional[LogEntry]:
    return session.get(LogEntry, log_id)


def delete_log(session: Session, entry: LogEntry) -> None:
    session.delete(entry)
    session.commit()


def list_logs(session: Session, day: str) -> list[LogEntry]:
    """Entries for one day, newest first."""
    query = (
        select(LogEntry)
        .where(LogEntry.day == day)
        .order_by(LogEntry.logged_at.desc(), LogEntry.id.desc())
    )
    return list(session.scalars(query))


def logs_between(session: Session, first_day: str, last_day: str) -> list[LogEntry]:
    """Entries from first_day to last_day inclusive, oldest first."""
    query = (
        select(LogEntry)
        .where(LogEntry.day >= first_day, LogEntry.day <= last_day)
        .order_by(LogEntry.day, LogEntry.logged_at)
    )
    return list(session.scalars(query))


def logged_days(session: Session) -> set[str]:
    """Every day that has at least one entry. Used for the streak."""
    return set(session.scalars(select(LogEntry.day).distinct()))


def consumed(session: Session, day: str, exclude_id: Optional[int] = None) -> dict[str, float]:
    """Midpoint calories and macros already logged on a day.

    exclude_id leaves out the entry being edited, so it is not counted
    against itself.
    """
    totals = {column: 0.0 for column in MACRO_COLUMNS}
    for entry in list_logs(session, day):
        if entry.id == exclude_id:
            continue
        for column in MACRO_COLUMNS:
            totals[column] += getattr(entry, column) or 0.0
    return totals
