"""`protas doctor`: what state the database is in, without changing it.

The file is opened read-only and copied into memory; every check runs on
that copy. Nothing here creates, migrates or writes the database.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from . import db

LABEL_WIDTH = 14


@dataclass
class Report:
    """The lines to print and whether something needs the user."""

    lines: list[str] = field(default_factory=list)
    healthy: bool = True

    def add(self, label: str, text: str) -> None:
        self.lines.append(f"{label + ':':<{LABEL_WIDTH}}{text}")

    def detail(self, text: str) -> None:
        self.lines.append(" " * LABEL_WIDTH + text)

    def problem(self, label: str, text: str) -> None:
        self.add(label, text)
        self.healthy = False


def _load(path: Path) -> sqlite3.Connection:
    """A copy of the database in memory; the file is only read."""
    source = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        copy = sqlite3.connect(":memory:")
        try:
            source.backup(copy)
        except BaseException:
            copy.close()
            raise
    finally:
        source.close()
    copy.row_factory = sqlite3.Row
    return copy


def _schema(conn: sqlite3.Connection, report: Report) -> bool:
    """Report the schema version. True when it is a shape this protas reads."""
    if db._is_legacy(conn):
        report.add(
            "schema", "from before the workspaces, it will be migrated when protas opens it"
        )
        return False
    if not db._table_exists(conn, "workspaces"):
        report.add("schema", "empty, it is created when protas opens the database")
        return False

    row = None
    if db._table_exists(conn, "meta"):
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    if row is None:
        version = db.BASELINE_VERSION
    else:
        try:
            version = max(int(row["value"]), db.BASELINE_VERSION)
        except (TypeError, ValueError):
            report.problem("schema", f"version {row['value']!r} cannot be read")
            return False

    current = db.SCHEMA_VERSION
    if version > current:
        report.problem(
            "schema",
            f"version {version}, newer than this protas ({current}): update protas to open it",
        )
        return False
    if version < current:
        report.add(
            "schema", f"version {version}, it will be updated to {current} when protas opens it"
        )
    else:
        report.add("schema", f"version {version}, up to date")
    return True


def _integrity(conn: sqlite3.Connection, report: Report) -> None:
    problems: list[str] = []
    try:
        found = [row[0] for row in conn.execute("PRAGMA integrity_check").fetchall()]
        if found != ["ok"]:
            problems.extend(found)
        broken = conn.execute("PRAGMA foreign_key_check").fetchall()
    except sqlite3.Error as error:
        report.problem("integrity", f"could not be checked: {error}")
        return

    if broken:
        tables = ", ".join(sorted({row[0] for row in broken}))
        noun = "reference" if len(broken) == 1 else "references"
        problems.append(f"{len(broken)} broken {noun} ({tables})")

    if problems:
        report.problem("integrity", "; ".join(problems))
    else:
        report.add("integrity", "ok")


def _search_index(conn: sqlite3.Connection, report: Report) -> None:
    # Neither state needs the user: protas repairs the index when it opens.
    if not db.fts5_available():
        report.add("search index", "not available in this SQLite")
    elif not db._has_index(conn):
        report.add("search index", "missing, it is built when protas opens the database")
    elif db._index_is_consistent(conn):
        report.add("search index", "ok")
    else:
        report.add(
            "search index", "out of date, it is rebuilt when protas opens the database"
        )


def _copies(path: Path) -> list[str]:
    """The copies protas left next to the database before changing it."""
    prefix = path.name + "."
    return sorted(
        entry.name
        for entry in path.parent.iterdir()
        if entry.name.startswith(prefix) and entry.name.endswith(".bak")
    )


def examine(path: Path) -> Report:
    """Look at the database at ``path`` and say what was found."""
    report = Report()
    report.add("database", str(path))

    if not path.exists():
        report.detail("not created yet")
        return report

    try:
        conn = _load(path)
    except (sqlite3.Error, OSError) as error:
        report.healthy = False
        if isinstance(error, sqlite3.DatabaseError) and "not a database" in str(error):
            report.detail("not a SQLite database")
        else:
            report.detail(f"cannot be read: {error}")
        return report

    try:
        known_shape = _schema(conn, report)
        _integrity(conn, report)
        if known_shape:
            _search_index(conn, report)
    finally:
        conn.close()

    copies = _copies(path)
    report.add("copies", ", ".join(copies) if copies else "none")
    return report
