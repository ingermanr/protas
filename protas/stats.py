"""The numbers of a period, worked out from plain rows.

Nothing here reads the database or the clock: ``Store.stats`` fetches the
rows and says which day is today, and this module does the counting.
"""

from __future__ import annotations

from datetime import date as Date
from datetime import timedelta
from typing import Iterable, Mapping, Sequence

from .models import ISO_FORMAT, DayStat, ProjectStat, Stats


def compute_stats(
    rows: Sequence[Mapping],
    event_dates: Iterable[str],
    projects: list[ProjectStat],
    days: int,
    end: Date,
) -> Stats:
    """Numbers for the ``days`` days that finish on ``end``.

    ``rows`` are the day entries (``id``, ``origin_id``, ``done``,
    ``project_id``, ``date``) and ``event_dates`` the days a project had
    activity.

    A pending task rolls into the next day, so counting agenda rows
    would charge the same task once per day. The compliance is counted
    by lineage instead: one task is one commitment, no matter how many
    days it survived.
    """
    days = max(days, 1)
    start = end - timedelta(days=days - 1)
    window_dates = [
        (start + timedelta(days=offset)).strftime(ISO_FORMAT) for offset in range(days)
    ]

    by_id = {row["id"]: row for row in rows}

    def root_of(task_id: int) -> int:
        current = by_id[task_id]
        seen = {task_id}
        while current["origin_id"] in by_id and current["origin_id"] not in seen:
            seen.add(current["origin_id"])
            current = by_id[current["origin_id"]]
        return current["id"]

    lineages: dict[int, dict] = {}
    per_day: dict[str, dict[str, int]] = {}

    for row in rows:
        day = per_day.setdefault(row["date"], {"tasks": 0, "done": 0, "projects": 0})
        if row["project_id"] is not None:
            day["projects"] += 1
            continue

        day["tasks"] += 1
        if row["done"]:
            day["done"] += 1

        root = root_of(row["id"])
        info = lineages.get(root)
        if info is None:
            lineages[root] = {
                "first": row["date"],
                "newest": (row["date"], row["id"]),
                "done": bool(row["done"]),
            }
            continue

        if row["date"] < info["first"]:
            info["first"] = row["date"]
        if (row["date"], row["id"]) > info["newest"]:
            info["newest"] = (row["date"], row["id"])
            info["done"] = bool(row["done"])

    window = [
        DayStat(
            date=date,
            tasks=per_day.get(date, {}).get("tasks", 0),
            done=per_day.get(date, {}).get("done", 0),
            projects=per_day.get(date, {}).get("projects", 0),
        )
        for date in window_dates
    ]

    started = 0
    finished = 0
    for info in lineages.values():
        if info["first"] in window_dates:
            started += 1
            if info["done"]:
                finished += 1

    active = {
        row["date"]
        for row in rows
        if row["done"] and row["project_id"] is None
    }
    active.update(event_dates)

    streak = 0
    cursor = end
    if cursor.strftime(ISO_FORMAT) not in active:
        cursor -= timedelta(days=1)
    while cursor.strftime(ISO_FORMAT) in active:
        streak += 1
        cursor -= timedelta(days=1)

    completed_per_day = sum(stat.done for stat in window)
    active_days = sum(1 for stat in window if stat.done or stat.projects)

    return Stats(
        window=window,
        streak=streak,
        started=started,
        finished=finished,
        completed_per_day=completed_per_day,
        active_days=active_days,
        projects=projects,
    )
