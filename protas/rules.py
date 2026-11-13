"""The rules of protas that need no database.

``Store`` fetches the rows and writes the results; the decisions about
what a project's state is and which entry of a lineage travels live here,
where they can be read and tested on their own.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date as Date
from typing import Callable, Mapping, Sequence


def project_counts(
    rows: Sequence[Mapping],
    seen: frozenset[int],
    inner_is_done: Callable[[int], bool],
) -> dict[str, int]:
    """How many entries a project holds and how many are done.

    ``rows`` are the entries of the project (``done``, ``project_id``). A
    project inside the project counts as one entry with its live state,
    asked through ``inner_is_done``. ``seen`` holds the projects already
    being counted, so two projects that mention each other cannot loop:
    an entry pointing back at one of them counts by its own mark.
    """
    total = len(rows)
    done = 0
    for row in rows:
        inner = row["project_id"]
        if inner is not None and inner not in seen:
            done += 1 if inner_is_done(inner) else 0
        elif row["done"]:
            done += 1
    return {"total": total, "done": done, "open": total - done}


def project_is_done(counts: Mapping[str, int], mentioned_done: bool) -> bool:
    """The live state of a project.

    A project with tasks is done when all of them are. A project without
    tasks has nothing to derive its state from, so it keeps it on the
    entries that mention it (``mentioned_done``), like a plain task would.
    """
    if counts["total"] == 0:
        return mentioned_done
    return counts["open"] == 0


def lineage_heads(rows: Sequence[Mapping]) -> list[Mapping]:
    """The newest appearance of every lineage, once each, in row order.

    ``rows`` are day entries (``id``, ``origin_id``, ``day_date``). A
    carried copy points at its original through ``origin_id``; only the
    newest appearance travels on, so a task walks one day at a time
    instead of piling up copies.
    """
    by_id = {row["id"]: row for row in rows}
    descendants: dict[int, list[Mapping]] = defaultdict(list)
    for row in rows:
        if row["origin_id"] is not None:
            descendants[row["origin_id"]].append(row)

    def newest_in_lineage(task_id: int) -> Mapping:
        newest = by_id[task_id]
        seen = {task_id}
        frontier = [task_id]
        while frontier:
            current = frontier.pop()
            for child in descendants.get(current, []):
                if child["id"] in seen:
                    continue
                seen.add(child["id"])
                frontier.append(child["id"])
                if (child["day_date"], child["id"]) > (newest["day_date"], newest["id"]):
                    newest = child
        return newest

    heads: list[Mapping] = []
    taken: set[int] = set()
    for row in rows:
        head = newest_in_lineage(row["id"])
        if head["id"] not in taken:
            taken.add(head["id"])
            heads.append(head)
    return heads


# ----------------------------------------------------------------------
# recurring tasks
# ----------------------------------------------------------------------
WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")

_DAILY_WORDS = frozenset({"day", "daily", "dia", "día", "diario", "diaria"})

_WEEKDAY_WORDS = {
    word: number
    for number, words in enumerate(
        (
            ("lun", "lunes", "mon", "monday"),
            ("mar", "martes", "tue", "tuesday"),
            ("mie", "mié", "miercoles", "miércoles", "wed", "wednesday"),
            ("jue", "jueves", "thu", "thursday"),
            ("vie", "viernes", "fri", "friday"),
            ("sab", "sáb", "sabado", "sábado", "sat", "saturday"),
            ("dom", "domingo", "sun", "sunday"),
        )
    )
    for word in words
}


def parse_recurrence(spec: str) -> str:
    """Turn what the user typed into the pattern that is stored.

    ``day`` is every day, ``lun,jue`` (or ``mon,thu``) the days of the
    week, and a number from 1 to 31 the day of the month.
    """
    cleaned = spec.strip().lower()
    if cleaned in _DAILY_WORDS:
        return "daily"

    if cleaned.isascii() and cleaned.isdigit():
        if 1 <= int(cleaned) <= 31:
            return f"monthly:{int(cleaned)}"
    else:
        words = cleaned.replace(",", " ").split()
        if words and all(word in _WEEKDAY_WORDS for word in words):
            days = sorted({_WEEKDAY_WORDS[word] for word in words})
            return "weekly:" + ",".join(str(day) for day in days)

    raise ValueError(
        f"no entiendo «{spec}» como repetición: usa day, días de la semana"
        " como lun,jue o un día del mes como 15"
    )


def recurrence_fires(pattern: str, day: Date) -> bool:
    """Whether a stored pattern names ``day``.

    A day of the month that a shorter month does not have fires on the
    last day of that month, so a rule for the 31 never skips a month.
    """
    kind, _, detail = pattern.partition(":")
    if kind == "daily":
        return True
    if kind == "weekly":
        return str(day.weekday()) in detail.split(",")
    if kind == "monthly":
        last = calendar.monthrange(day.year, day.month)[1]
        return day.day == min(int(detail), last)
    return False


def describe_recurrence(pattern: str) -> str:
    """A stored pattern in words, for listings."""
    kind, _, detail = pattern.partition(":")
    if kind == "daily":
        return "cada día"
    if kind == "weekly":
        names = [WEEKDAYS[int(number)] for number in detail.split(",")]
        if len(names) == 1:
            return names[0]
        return ", ".join(names[:-1]) + " y " + names[-1]
    if kind == "monthly":
        return f"el día {detail} de cada mes"
    return pattern

