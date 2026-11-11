"""SQLite storage layer.

The database is a single file holding every workspace, day, note and task.
There are two kinds of workspace:

* **day** - one calendar day, its title is its date.
* **project** - a long lived space with its own title, note and tasks.

Keeping everything in one place makes the data easy to back up, easy to
query across days and easy to read later from another interface (the TUI,
the CLI or a future desktop shell).

Full text search lives in FTS5 indexes that SQLite keeps in sync with the
base tables through triggers, so the index never drifts from the data.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

SCHEMA_VERSION = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS workspaces (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL CHECK (kind IN ('day', 'project')),
    title       TEXT NOT NULL,
    date        TEXT UNIQUE,
    note        TEXT NOT NULL DEFAULT '',
    parent_id   INTEGER REFERENCES workspaces(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_workspaces_parent ON workspaces(parent_id);
CREATE INDEX IF NOT EXISTS idx_workspaces_kind   ON workspaces(kind);

CREATE TABLE IF NOT EXISTS tasks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    project_id   INTEGER REFERENCES workspaces(id) ON DELETE SET NULL,
    parent_id    INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
    text         TEXT NOT NULL,
    done         INTEGER NOT NULL DEFAULT 0,
    done_at      TEXT,
    origin_id    INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
    position     INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_workspace ON tasks(workspace_id);
CREATE INDEX IF NOT EXISTS idx_tasks_parent    ON tasks(parent_id);
CREATE INDEX IF NOT EXISTS idx_tasks_origin    ON tasks(origin_id);
CREATE INDEX IF NOT EXISTS idx_tasks_project   ON tasks(project_id);

-- Ledger of everything that ever travelled from one day to another.
-- It makes the rollover idempotent: a task is never carried twice into
-- the same day, even if the copy was deleted afterwards.
CREATE TABLE IF NOT EXISTS carries (
    origin_id    INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    created_at   TEXT NOT NULL,
    PRIMARY KEY (origin_id, workspace_id)
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Story of a project. The date is kept as text so the story survives even
-- if the day it belongs to is deleted.
CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    date         TEXT NOT NULL,
    task_id      INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
    kind         TEXT NOT NULL,
    text         TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_workspace ON events(workspace_id, created_at);
"""

# The search index is optional: some SQLite builds ship without FTS5 and
# the application must still start there, falling back to a plain scan.
SCHEMA_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS tasks_fts USING fts5(
    text,
    content='tasks',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS tasks_fts_insert AFTER INSERT ON tasks BEGIN
    INSERT INTO tasks_fts(rowid, text) VALUES (new.id, new.text);
END;

CREATE TRIGGER IF NOT EXISTS tasks_fts_delete AFTER DELETE ON tasks BEGIN
    INSERT INTO tasks_fts(tasks_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;

CREATE TRIGGER IF NOT EXISTS tasks_fts_update AFTER UPDATE OF text ON tasks BEGIN
    INSERT INTO tasks_fts(tasks_fts, rowid, text) VALUES ('delete', old.id, old.text);
    INSERT INTO tasks_fts(rowid, text) VALUES (new.id, new.text);
END;

CREATE VIRTUAL TABLE IF NOT EXISTS workspaces_fts USING fts5(
    title,
    note,
    content='workspaces',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS workspaces_fts_insert AFTER INSERT ON workspaces BEGIN
    INSERT INTO workspaces_fts(rowid, title, note) VALUES (new.id, new.title, new.note);
END;

CREATE TRIGGER IF NOT EXISTS workspaces_fts_delete AFTER DELETE ON workspaces BEGIN
    INSERT INTO workspaces_fts(workspaces_fts, rowid, title, note)
        VALUES ('delete', old.id, old.title, old.note);
END;

CREATE TRIGGER IF NOT EXISTS workspaces_fts_update AFTER UPDATE OF title, note ON workspaces BEGIN
    INSERT INTO workspaces_fts(workspaces_fts, rowid, title, note)
        VALUES ('delete', old.id, old.title, old.note);
    INSERT INTO workspaces_fts(rowid, title, note) VALUES (new.id, new.title, new.note);
END;
"""


def default_db_path() -> Path:
    """Return the path of the database, honouring PROTAS_DB and XDG."""
    override = os.environ.get("PROTAS_DB")
    if override:
        return Path(override).expanduser()

    data_home = os.environ.get("XDG_DATA_HOME")
    root = Path(data_home).expanduser() if data_home else Path.home() / ".local" / "share"
    return root / "protas" / "protas.db"


_FTS_AVAILABLE: bool | None = None


def fts5_available() -> bool:
    """True when this SQLite build can create FTS5 indexes."""
    global _FTS_AVAILABLE
    if _FTS_AVAILABLE is None:
        probe = sqlite3.connect(":memory:")
        try:
            probe.execute("CREATE VIRTUAL TABLE probe USING fts5(x)")
            _FTS_AVAILABLE = True
        except sqlite3.Error:
            _FTS_AVAILABLE = False
        finally:
            probe.close()
    return _FTS_AVAILABLE


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return row is not None


def _has_index(conn: sqlite3.Connection) -> bool:
    return _table_exists(conn, "tasks_fts")


def _rebuild_indexes(conn: sqlite3.Connection) -> None:
    """Rebuild the search index from the base tables."""
    conn.execute("INSERT INTO tasks_fts(tasks_fts) VALUES ('rebuild')")
    conn.execute("INSERT INTO workspaces_fts(workspaces_fts) VALUES ('rebuild')")
    conn.commit()


def _index_is_consistent(conn: sqlite3.Connection) -> bool:
    """True when the search index matches the base tables."""
    try:
        conn.execute("INSERT INTO tasks_fts(tasks_fts, rank) VALUES ('integrity-check', 1)")
        conn.execute(
            "INSERT INTO workspaces_fts(workspaces_fts, rank) VALUES ('integrity-check', 1)"
        )
        conn.commit()
        return True
    except sqlite3.Error:
        conn.rollback()
        return False


def _prepare_legacy(conn: sqlite3.Connection) -> None:
    """Move the old tables aside so the new ones can be created clean.

    The old schema used ``days``, ``tasks`` and ``carries``; the new one
    uses ``workspaces``, ``tasks`` and ``carries``. Renaming first avoids
    mixing two different shapes under the same name.
    """
    conn.executescript(
        """
        ALTER TABLE days RENAME TO days_v1;
        ALTER TABLE tasks RENAME TO tasks_v1;
        ALTER TABLE carries RENAME TO carries_v1;
        DROP TRIGGER IF EXISTS tasks_fts_insert;
        DROP TRIGGER IF EXISTS tasks_fts_delete;
        DROP TRIGGER IF EXISTS tasks_fts_update;
        DROP TRIGGER IF EXISTS days_fts_insert;
        DROP TRIGGER IF EXISTS days_fts_delete;
        DROP TRIGGER IF EXISTS days_fts_update;
        """
    )
    conn.commit()


def _migrate_v2(conn: sqlite3.Connection) -> None:
    """Move a database that used days and nested tasks to workspaces.

    Every day becomes a workspace of kind ``day`` and every task that owned
    children becomes a project workspace with those children inside.
    """
    day_rows = conn.execute("SELECT * FROM days_v1 ORDER BY id").fetchall()
    task_rows = conn.execute("SELECT * FROM tasks_v1 ORDER BY id").fetchall()
    carry_rows = conn.execute("SELECT * FROM carries_v1").fetchall()
    by_id = {task["id"]: task for task in task_rows}

    day_workspace: dict[int, int] = {}
    for day in day_rows:
        cursor = conn.execute(
            """INSERT INTO workspaces (kind, title, date, note, parent_id, created_at)
               VALUES ('day', ?, ?, ?, NULL, ?)""",
            (day["title"], day["date"], day["note"], day["created_at"]),
        )
        day_workspace[day["id"]] = cursor.lastrowid

    def top_ancestor(task: sqlite3.Row) -> sqlite3.Row:
        current = task
        seen = {current["id"]}
        while current["parent_id"] is not None:
            parent = by_id.get(current["parent_id"])
            if parent is None or parent["id"] in seen:
                # A missing or cyclic parent must not loop forever.
                break
            seen.add(parent["id"])
            current = parent
        return current

    # A top level task with children becomes a project workspace.
    project_workspace: dict[int, int] = {}
    for task in task_rows:
        has_children = any(other["parent_id"] == task["id"] for other in task_rows)
        if has_children and task["parent_id"] is None:
            cursor = conn.execute(
                """INSERT INTO workspaces (kind, title, date, note, parent_id, created_at)
                   VALUES ('project', ?, NULL, '', NULL, ?)""",
                (task["text"], task["created_at"]),
            )
            project_workspace[task["id"]] = cursor.lastrowid

    id_map: dict[int, int] = {}
    for task in task_rows:
        project_id = project_workspace.get(task["id"])
        parent_id = None

        if project_id is not None:
            # The task itself stays in its day as a mention of the project.
            workspace_id = day_workspace[task["day_id"]]
        elif task["parent_id"] is not None:
            # Children move inside the workspace of their project.
            root = top_ancestor(task)
            workspace_id = project_workspace.get(
                root["id"], day_workspace[task["day_id"]]
            )
            parent_id = task["parent_id"]
        else:
            workspace_id = day_workspace[task["day_id"]]

        cursor = conn.execute(
            """INSERT INTO tasks
               (workspace_id, project_id, parent_id, text, done, done_at, origin_id,
                position, created_at)
               VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)""",
            (
                workspace_id,
                project_id,
                parent_id,
                task["text"],
                task["done"],
                task["done_at"],
                task["position"],
                task["created_at"],
            ),
        )
        id_map[task["id"]] = cursor.lastrowid

    for task in task_rows:
        if task["origin_id"] is None or task["origin_id"] not in id_map:
            continue
        conn.execute(
            "UPDATE tasks SET origin_id = ? WHERE id = ?",
            (id_map[task["origin_id"]], id_map[task["id"]]),
        )

    for carry in carry_rows:
        origin_id = id_map.get(carry["origin_id"])
        if origin_id is None:
            continue
        origin = next(task for task in task_rows if task["id"] == carry["origin_id"])
        workspace_id = day_workspace.get(origin["day_id"])
        if workspace_id is None:
            continue
        conn.execute(
            "INSERT OR IGNORE INTO carries (origin_id, workspace_id, created_at) "
            "VALUES (?, ?, ?)",
            (origin_id, workspace_id, carry["created_at"]),
        )

    # The children go first: a table that still points to a dropped one
    # makes SQLite fail while reparsing the schema.
    conn.executescript(
        """
        DROP TABLE IF EXISTS carries_v1;
        DROP TABLE IF EXISTS tasks_v1;
        DROP TABLE IF EXISTS days_v1;
        """
    )
    conn.commit()


def _migrate(conn: sqlite3.Connection) -> None:
    """Bring an older database up to the current schema version."""
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    version = int(row["value"]) if row else None
    if version == SCHEMA_VERSION:
        return

    conn.execute(
        "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """Open the database, creating or migrating the schema when needed."""
    target = Path(path).expanduser() if path else default_db_path()
    target.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(target))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    legacy = _table_exists(conn, "days") and not _table_exists(conn, "workspaces")
    if legacy:
        _prepare_legacy(conn)

    conn.executescript(SCHEMA)

    if legacy:
        _migrate_v2(conn)

    _migrate(conn)

    if fts5_available():
        fresh_index = not _has_index(conn)
        conn.executescript(SCHEMA_FTS)
        if fresh_index:
            # The index is new: it must cover the rows that came before it.
            _rebuild_indexes(conn)
        elif not _index_is_consistent(conn):
            # Something wrote to the tables while the index was missing.
            _rebuild_indexes(conn)

    conn.commit()
    return conn
