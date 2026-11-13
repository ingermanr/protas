"""The things protas talks about: days, projects, tasks and their numbers.

Nothing here touches the database. ``store`` builds these from rows and
``cli`` and ``tui`` draw them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as Date
from datetime import datetime
from typing import Optional

ISO_FORMAT = "%Y-%m-%d"


def today() -> str:
    """Today's date as an ISO string."""
    return Date.today().strftime(ISO_FORMAT)


def check_date(date_str: str) -> str:
    """Return ``date_str`` when it is a real day written as YYYY-MM-DD.

    Days are compared and sorted as text, so only the canonical form is
    accepted: anything else would create a day that sorts in the wrong
    place and receives work it should not.
    """
    try:
        canonical = Date.fromisoformat(date_str).strftime(ISO_FORMAT)
    except (TypeError, ValueError):
        canonical = None
    if canonical != date_str:
        raise ValueError(f"'{date_str}' is not a valid date, use YYYY-MM-DD")
    return date_str


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class Workspace:
    """A day or a project."""

    id: int
    kind: str
    title: str
    date: Optional[str]
    note: str
    parent_id: Optional[int]

    @property
    def is_day(self) -> bool:
        return self.kind == "day"

    @property
    def is_project(self) -> bool:
        return self.kind == "project"


@dataclass
class Task:
    """A task inside a workspace."""

    id: int
    workspace_id: int
    project_id: Optional[int]
    parent_id: Optional[int]
    text: str
    done: bool
    origin_id: Optional[int]
    position: int
    created_at: str
    done_at: Optional[str] = None
    children: list["Task"] = field(default_factory=list)

    @property
    def is_mention(self) -> bool:
        """True when the task is a day entry pointing at a project."""
        return self.project_id is not None


@dataclass
class Recurrence:
    """A rule that creates a task on the days it names."""

    id: int
    text: str
    # "daily", "weekly:0,3" (Monday is 0) or "monthly:15"
    pattern: str
    created_at: str


@dataclass
class ProjectRef:
    """A project seen from the project list."""

    workspace: Workspace
    total: int
    done: int
    open: int
    mentions: int
    days: list[str]


@dataclass
class HistoryEntry:
    """One line of the story of a project."""

    date: str
    kind: str
    text: str
    at: str


@dataclass
class ProjectHistory:
    """The story of a project, day by day."""

    project: Workspace
    entries: list[HistoryEntry]
    first_day: Optional[str]
    last_day: Optional[str]
    days: list[str]


@dataclass
class DayStat:
    """One day of the agenda."""

    date: str
    tasks: int
    done: int
    projects: int

    @property
    def adherence(self) -> float:
        if not self.tasks:
            return 0.0
        return self.done / self.tasks


@dataclass
class ProjectStat:
    """One project seen through its history."""

    workspace: Workspace
    total: int
    done: int
    days_active: int
    first_day: Optional[str]
    last_day: Optional[str]

    @property
    def progress(self) -> float:
        if not self.total:
            return 0.0
        return self.done / self.total


@dataclass
class Stats:
    """The numbers of a period."""

    window: list[DayStat]
    streak: int
    started: int
    finished: int
    completed_per_day: int
    active_days: int
    projects: list[ProjectStat]


def describe_event(entry: HistoryEntry) -> str:
    """One line of the story of a project."""
    if entry.kind == "created":
        return "creado el proyecto"
    if entry.kind == "task_added":
        return f'agregada "{entry.text}"'
    if entry.kind == "task_done":
        return f'completada "{entry.text}"'
    if entry.kind == "task_undone":
        return f'reabierta "{entry.text}"'
    if entry.kind == "project_completed":
        return "proyecto completado"
    if entry.kind == "project_reopened":
        return "proyecto reabierto"
    if entry.kind == "mentioned":
        return entry.text
    return entry.kind


@dataclass
class Hit:
    """A search result."""

    kind: str  # "task", "note", "day" or "project"
    date: str
    text: str
    task_id: Optional[int] = None
    score: float = 0.0
    # The day or project that holds it, so a result can be opened.
    workspace_id: Optional[int] = None
