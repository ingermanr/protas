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

import hashlib
import os
import sqlite3
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

SCHEMA_VERSION = 4

# The first numbered shape: what the move from days to workspaces produces.
BASELINE_VERSION = 3

# The shape of version 3, frozen. The move from days to workspaces builds
# exactly this, and the steps below take it from there.
SCHEMA_V3 = """
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

# Version 4: recurring tasks. A rule names the days it fires on, and the
# ledger records the task it produced on each of them, so opening a day
# twice never spawns twice and a deleted task does not come back that day.
SCHEMA_RECURRENCES = """
CREATE TABLE IF NOT EXISTS recurrences (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    text        TEXT NOT NULL,
    pattern     TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recurrence_tasks (
    recurrence_id INTEGER NOT NULL REFERENCES recurrences(id) ON DELETE CASCADE,
    date          TEXT NOT NULL,
    task_id       INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
    PRIMARY KEY (recurrence_id, date)
);

CREATE INDEX IF NOT EXISTS idx_recurrence_tasks_task ON recurrence_tasks(task_id);
"""

# What a new database gets: the newest shape.
SCHEMA = SCHEMA_V3 + SCHEMA_RECURRENCES

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


class MigrationError(RuntimeError):
    """The database could not be brought to the schema of this protas.

    Either an update failed, and the database was left as it was, or the
    database belongs to a newer protas and was not touched.
    """


# The old schema used ``days``, ``tasks`` and ``carries``; the new one uses
# ``workspaces``, ``tasks`` and ``carries``. Renaming first avoids mixing
# two different shapes under the same name.
LEGACY_RENAME = """
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

# The children go first: a table that still points to a dropped one makes
# SQLite fail while reparsing the schema.
LEGACY_DROP = """
DROP TABLE IF EXISTS carries_v1;
DROP TABLE IF EXISTS tasks_v1;
DROP TABLE IF EXISTS days_v1;
"""


def _statements(script: str) -> list[str]:
    """Split a script into statements.

    ``executescript`` commits whatever is open, so a script that must run
    inside a transaction is executed one statement at a time instead.
    """
    statements: list[str] = []
    current = ""
    for line in script.splitlines():
        current += line + "\n"
        if sqlite3.complete_statement(current):
            statements.append(current)
            current = ""
    if current.strip():
        statements.append(current)
    return statements


def legacy_backup_path(path: Path, attempt: int = 1) -> Path:
    """Where the copy of a database from before the workspaces is kept.

    The first copy has the plain name; a later one, needed when that name
    is taken by a different database, carries its number.
    """
    suffix = ".before-workspaces.bak" if attempt == 1 else f".before-workspaces.{attempt}.bak"
    return path.with_name(path.name + suffix)


LEGACY_TABLES = ("days", "tasks", "carries")


def _legacy_fingerprint(conn: sqlite3.Connection) -> str:
    """A digest of everything the old tables hold."""
    digest = hashlib.sha256()
    for table in LEGACY_TABLES:
        digest.update(table.encode())
        for row in conn.execute(f"SELECT * FROM {table} ORDER BY 1, 2"):
            digest.update(repr(tuple(row)).encode())
    return digest.hexdigest()


def _fingerprint(conn: sqlite3.Connection) -> str:
    """A digest of the shape and the rows of every table.

    The search index is left out: it is rebuilt from the tables and a
    SQLite without FTS5 cannot read it.
    """
    digest = hashlib.sha256()
    tables = conn.execute(
        """SELECT name, sql FROM sqlite_master
           WHERE type = 'table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '%_fts%'
           ORDER BY name"""
    ).fetchall()
    for name, sql in tables:
        digest.update(f"{name}\n{sql}\n".encode())
        for row in conn.execute(f'SELECT * FROM "{name}" ORDER BY rowid'):
            digest.update(repr(tuple(row)).encode())
    return digest.hexdigest()


def _file_fingerprint(
    path: Path, fingerprint: Callable[[sqlite3.Connection], str] = _legacy_fingerprint
) -> str | None:
    """The fingerprint of a copy, or None when it cannot be read as one."""
    try:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        return fingerprint(conn)
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def _write_copy(conn: sqlite3.Connection, target: Path) -> None:
    """Write a full copy of the database into ``target``."""
    copy = sqlite3.connect(str(target))
    try:
        conn.backup(copy)
    finally:
        copy.close()


def _backup(
    conn: sqlite3.Connection,
    path: Path,
    name_for: Callable[[int], Path],
    fingerprint: Callable[[sqlite3.Connection], str],
) -> Path:
    """Copy the database aside before touching it.

    ``name_for`` gives the name of the copy for an attempt number and
    ``fingerprint`` says what two databases must share to be the same.

    A copy is only trusted when it holds exactly what the database holds
    now. An existing file with other content is never replaced: it may be
    the only copy of something else, so the new copy takes the next name.
    """
    wanted = fingerprint(conn)

    attempt = 1
    while True:
        backup = name_for(attempt)
        if not backup.exists():
            break
        if _file_fingerprint(backup, fingerprint) == wanted:
            return backup
        attempt += 1

    # The copy is written under a name nobody else uses and only shown
    # under its final name once it is complete and checked.
    handle, name = tempfile.mkstemp(dir=backup.parent, prefix=backup.name + ".", suffix=".partial")
    os.close(handle)
    partial = Path(name)
    try:
        _write_copy(conn, partial)
        # The temporary file is private; the copy gets the permissions of
        # the database it is a copy of.
        os.chmod(partial, stat.S_IMODE(os.stat(path).st_mode))
        if _file_fingerprint(partial, fingerprint) != wanted:
            raise OSError(f"the copy written to {backup} does not match the database")
        try:
            # A link never replaces a file: if another protas got there
            # first, its copy stays and must hold the same data.
            os.link(partial, backup)
        except FileExistsError:
            if _file_fingerprint(backup, fingerprint) != wanted:
                raise
        except OSError:
            # No hard links on this file system.
            partial.replace(backup)
    finally:
        partial.unlink(missing_ok=True)
    return backup


def _backup_legacy(conn: sqlite3.Connection, path: Path) -> Path:
    """Copy a database from before the workspaces aside before moving it."""
    return _backup(
        conn, path, lambda attempt: legacy_backup_path(path, attempt), _legacy_fingerprint
    )


def _is_legacy(conn: sqlite3.Connection) -> bool:
    """True when the database still has the shape from before the workspaces."""
    return _table_exists(conn, "days") and not _table_exists(conn, "workspaces")


def _migrate_legacy(conn: sqlite3.Connection, path: Path) -> Path | None:
    """Move a database from days to workspaces, all or nothing.

    The whole move runs in one transaction: when any step fails the file
    keeps its old shape, so the next start can try again. Returns where
    the copy was kept, or None when another protas made the move.
    """
    try:
        backup = _backup_legacy(conn, path)
    except (OSError, sqlite3.Error) as error:
        if not _is_legacy(conn):
            # Another protas migrated it while this one was starting.
            return None
        raise MigrationError(
            f"could not copy {path} before migrating it: {error}. "
            "The database was left untouched."
        ) from error

    isolation_level = conn.isolation_level
    conn.isolation_level = None
    try:
        conn.execute("BEGIN IMMEDIATE")
        if not _is_legacy(conn):
            # Another protas migrated it while this one waited for the lock.
            conn.execute("ROLLBACK")
            return None
        for statement in _statements(LEGACY_RENAME + SCHEMA_V3):
            conn.execute(statement)
        _migrate_v2(conn)
        for statement in _statements(LEGACY_DROP):
            conn.execute(statement)
        conn.execute("COMMIT")
    except BaseException as error:
        try:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
        except sqlite3.Error:
            # The first error is the one worth reporting. SQLite undoes an
            # open transaction by itself when the connection goes away.
            pass
        if not isinstance(error, Exception):
            # Ctrl-C and the like: undo and let them through.
            raise
        raise MigrationError(
            f"could not migrate {path}: {error}. "
            f"The database was left untouched and a copy is kept at {backup}."
        ) from error
    finally:
        try:
            conn.isolation_level = isolation_level
        except sqlite3.Error:
            pass
    return backup


def _migrate_v2(conn: sqlite3.Connection) -> None:
    """Move a database that used days and nested tasks to workspaces.

    Every day becomes a workspace of kind ``day`` and every task that owned
    children becomes a project workspace with those children inside.

    It runs inside the transaction of ``_migrate_legacy`` and never commits.
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

    def day_of(task: sqlite3.Row) -> int:
        workspace_id = day_workspace.get(task["day_id"])
        if workspace_id is None:
            raise ValueError(
                f"task {task['id']} belongs to day {task['day_id']}, which does not exist"
            )
        return workspace_id

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
    parents = {task["parent_id"] for task in task_rows if task["parent_id"] is not None}
    project_workspace: dict[int, int] = {}
    for task in task_rows:
        if task["id"] in parents and task["parent_id"] is None:
            cursor = conn.execute(
                """INSERT INTO workspaces (kind, title, date, note, parent_id, created_at)
                   VALUES ('project', ?, NULL, '', NULL, ?)""",
                (task["text"], task["created_at"]),
            )
            project_workspace[task["id"]] = cursor.lastrowid

    id_map: dict[int, int] = {}
    for task in task_rows:
        project_id = project_workspace.get(task["id"])
        # Every task must belong to a real day, wherever it ends up.
        day_id = day_of(task)

        if project_id is not None:
            # The task itself stays in its day as a mention of the project.
            workspace_id = day_id
        elif task["parent_id"] is not None:
            # Children move inside the workspace of their project.
            root = top_ancestor(task)
            workspace_id = project_workspace.get(root["id"], day_id)
        else:
            workspace_id = day_id

        cursor = conn.execute(
            """INSERT INTO tasks
               (workspace_id, project_id, parent_id, text, done, done_at, origin_id,
                position, created_at)
               VALUES (?, ?, NULL, ?, ?, ?, NULL, ?, ?)""",
            (
                workspace_id,
                project_id,
                task["text"],
                task["done"],
                task["done_at"],
                task["position"],
                task["created_at"],
            ),
        )
        id_map[task["id"]] = cursor.lastrowid

    # The ids changed, so every link between tasks is rewritten with the
    # new ones once all the rows exist.
    for task in task_rows:
        if task["origin_id"] in id_map:
            conn.execute(
                "UPDATE tasks SET origin_id = ? WHERE id = ?",
                (id_map[task["origin_id"]], id_map[task["id"]]),
            )

        # The children of a project hang from its workspace, not from the
        # mention the day keeps: deleting the mention must not take them.
        parent_id = task["parent_id"]
        if parent_id in id_map and parent_id not in project_workspace:
            conn.execute(
                "UPDATE tasks SET parent_id = ? WHERE id = ?",
                (id_map[parent_id], id_map[task["id"]]),
            )

    for carry in carry_rows:
        origin_id = id_map.get(carry["origin_id"])
        if origin_id is None:
            continue
        # The ledger records the day that received the task.
        workspace_id = day_workspace.get(carry["day_id"])
        if workspace_id is None:
            continue
        conn.execute(
            "INSERT OR IGNORE INTO carries (origin_id, workspace_id, created_at) "
            "VALUES (?, ?, ?)",
            (origin_id, workspace_id, carry["created_at"]),
        )


# One step per schema change. The step registered under a version takes a
# database from that version to the next one; opening an older database
# walks them in order. To change the schema: change SCHEMA (what a new
# database gets), raise SCHEMA_VERSION and register the step here.
#
# A step receives the connection inside the transaction of the update. It
# must not commit, roll back or call ``executescript`` (which commits).
#
# The move from days to workspaces builds SCHEMA_V3, the baseline shape,
# and the steps take it from there like any other version 3 database.
def _add_recurrences(conn: sqlite3.Connection) -> None:
    """Version 3 to 4: the tables of the recurring tasks. Nothing else moves."""
    for statement in _statements(SCHEMA_RECURRENCES):
        conn.execute(statement)


MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {3: _add_recurrences}


def version_backup_path(path: Path, version: int, attempt: int = 1) -> Path:
    """Where the copy of a database at ``version`` is kept before an update."""
    suffix = f".v{version}.bak" if attempt == 1 else f".v{version}.{attempt}.bak"
    return path.with_name(path.name + suffix)


def _stored_version(conn: sqlite3.Connection, path: Path) -> int | None:
    """The schema version of the database, or None when it is still empty.

    A database from a newer protas, or one whose version cannot be read,
    is refused: this protas does not know its shape.
    """
    if not _table_exists(conn, "workspaces"):
        return None

    row = None
    if _table_exists(conn, "meta"):
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    if row is None:
        # Workspaces without a number: the shape the baseline started with.
        return BASELINE_VERSION

    try:
        version = int(row["value"])
    except (TypeError, ValueError):
        raise MigrationError(
            f"{path} has schema version {row['value']!r}, which this protas cannot read. "
            "The database was left untouched."
        ) from None

    if version > SCHEMA_VERSION:
        raise MigrationError(
            f"{path} was written by a newer protas: it is at version {version} and this "
            f"protas understands up to version {SCHEMA_VERSION}. Update protas to open it. "
            "The database was left untouched."
        )
    # Numbers below the baseline belong to the days before the workspaces.
    return max(version, BASELINE_VERSION)


def _stamp(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(version),),
    )


@contextmanager
def _all_or_nothing(conn: sqlite3.Connection) -> Iterator[None]:
    """One transaction that holds the write lock from its first moment.

    Whatever stops the block, Ctrl-C included, undoes everything and is
    raised again as it was.
    """
    isolation_level = conn.isolation_level
    conn.isolation_level = None
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield
            conn.execute("COMMIT")
        except BaseException:
            try:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
            except sqlite3.Error:
                # The first error is the one worth reporting. SQLite undoes
                # an open transaction by itself when the connection goes away.
                pass
            raise
    finally:
        try:
            conn.isolation_level = isolation_level
        except sqlite3.Error:
            pass


def _update(conn: sqlite3.Connection, path: Path, version: int) -> Path | None:
    """Walk the steps from ``version`` to the current one, all or nothing.

    Returns where the copy was kept, or None when another protas changed
    the version meanwhile, so the caller looks at the database again.
    """
    steps = []
    for number in range(version, SCHEMA_VERSION):
        step = MIGRATIONS.get(number)
        if step is None:
            raise MigrationError(
                f"this protas does not know how to update version {number} of {path}. "
                "The database was left untouched."
            )
        steps.append(step)

    try:
        backup = _backup(
            conn,
            path,
            lambda attempt: version_backup_path(path, version, attempt),
            _fingerprint,
        )
    except (OSError, sqlite3.Error) as error:
        if _stored_version(conn, path) != version:
            return None
        raise MigrationError(
            f"could not copy {path} before updating it: {error}. "
            "The database was left untouched."
        ) from error

    try:
        with _all_or_nothing(conn):
            if _stored_version(conn, path) != version:
                # Another protas updated it while this one waited for the lock.
                return None
            for step in steps:
                step(conn)
            _stamp(conn, SCHEMA_VERSION)
    except MigrationError:
        raise
    except Exception as error:
        raise MigrationError(
            f"could not update {path} from version {version} to {SCHEMA_VERSION}: {error}. "
            f"The database was left untouched and a copy is kept at {backup}."
        ) from error
    return backup


Notify = Callable[[str], None]


def _bring_up_to_date(conn: sqlite3.Connection, path: Path, notify: Notify | None) -> None:
    """Update an older database; refuse one this protas does not know."""
    while True:
        version = _stored_version(conn, path)
        if version is None or version == SCHEMA_VERSION:
            return
        backup = _update(conn, path, version)
        if backup is not None:
            if notify is not None:
                notify(
                    f"database updated from version {version} to {SCHEMA_VERSION}; "
                    f"the previous one is kept at {backup}"
                )
            return


def _stamp_current(conn: sqlite3.Connection) -> None:
    """Write the version down when the database does not carry it yet."""
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    if row is None or row["value"] != str(SCHEMA_VERSION):
        _stamp(conn, SCHEMA_VERSION)
        conn.commit()


def connect(
    path: Path | str | None = None, notify: Notify | None = None
) -> sqlite3.Connection:
    """Open the database, creating or migrating the schema when needed.

    ``notify`` receives one line when the database was changed to fit
    this protas, saying where the previous one is kept.
    """
    target = Path(path).expanduser() if path else default_db_path()
    target.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(target))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    try:
        if _is_legacy(conn):
            backup = _migrate_legacy(conn, target)
            if backup is not None and notify is not None:
                notify(f"database moved to workspaces; the previous one is kept at {backup}")

        # The steps run before SCHEMA: it describes the newest shape and
        # must not be laid over a database that is still an older one.
        _bring_up_to_date(conn, target, notify)

        conn.executescript(SCHEMA)
        _stamp_current(conn)

        if fts5_available():
            fresh_index = not _has_index(conn)
            conn.executescript(SCHEMA_FTS)
            if fresh_index:
                # The index is new: it must cover the rows that came before it.
                _rebuild_indexes(conn)
            elif not _index_is_consistent(conn):
                # Something wrote to the tables while the index was missing.
                _rebuild_indexes(conn)
    except BaseException:
        # Nothing may keep the file locked after a failed start.
        conn.close()
        raise

    conn.commit()
    return conn
