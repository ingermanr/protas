"""Tests for the schema migration.

A database created before the workspace model existed must keep working:
the days become workspaces and the tasks with children become projects.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from protas.store import Store

LEGACY_SCHEMA = """
CREATE TABLE days (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT NOT NULL UNIQUE,
    title       TEXT NOT NULL,
    note        TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);
CREATE TABLE tasks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    day_id        INTEGER NOT NULL REFERENCES days(id) ON DELETE CASCADE,
    parent_id     INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
    text          TEXT NOT NULL,
    done          INTEGER NOT NULL DEFAULT 0,
    done_at       TEXT,
    origin_id     INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
    origin_day_id INTEGER REFERENCES days(id) ON DELETE SET NULL,
    position      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);
CREATE TABLE carries (
    origin_id  INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    day_id     INTEGER NOT NULL REFERENCES days(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    PRIMARY KEY (origin_id, day_id)
);
INSERT INTO days (date, title, note, created_at)
    VALUES ('2026-11-10', '2026-11-10', 'nota vieja', '2026-11-10T10:00:00');
INSERT INTO tasks (day_id, parent_id, text, done, done_at, origin_id, origin_day_id,
                   position, created_at)
    VALUES (1, NULL, 'Tarea vieja', 0, NULL, NULL, NULL, 0, '2026-11-10T10:00:00');
INSERT INTO tasks (day_id, parent_id, text, done, done_at, origin_id, origin_day_id,
                   position, created_at)
    VALUES (1, NULL, 'Migrar la base de datos', 0, NULL, NULL, NULL, 1, '2026-11-10T10:00:00');
INSERT INTO tasks (day_id, parent_id, text, done, done_at, origin_id, origin_day_id,
                   position, created_at)
    VALUES (1, 2, 'Esquema nuevo', 0, NULL, NULL, NULL, 0, '2026-11-10T10:00:00');
"""


class MigrationTest(unittest.TestCase):
    def test_a_database_without_workspaces_is_migrated(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "legacy.db"

            legacy = sqlite3.connect(str(db))
            legacy.executescript(LEGACY_SCHEMA)
            legacy.commit()
            legacy.close()

            store = Store(path=db)
            try:
                day = store.day("2026-11-10")
                self.assertIsNotNone(day)
                self.assertEqual(day.kind, "day")
                self.assertEqual(day.note, "nota vieja")

                entries = store.tasks_of(day.id)
                self.assertEqual(len(entries), 2)

                # the task with children became a project
                projects = store.projects()
                self.assertEqual(len(projects), 1)
                self.assertEqual(projects[0].workspace.title, "Migrar la base de datos")
                self.assertEqual(projects[0].total, 1)

                # and the day mentions it
                mention = [entry for entry in entries if entry.is_mention]
                self.assertEqual(len(mention), 1)
                self.assertEqual(mention[0].project_id, projects[0].workspace.id)
            finally:
                store.close()

    def test_the_migrated_database_is_searchable(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "legacy.db"

            legacy = sqlite3.connect(str(db))
            legacy.executescript(LEGACY_SCHEMA)
            legacy.commit()
            legacy.close()

            store = Store(path=db)
            try:
                hits = store.search("vieja")
                kinds = sorted(hit.kind for hit in hits)
                self.assertIn("note", kinds)
                self.assertIn("task", kinds)
            finally:
                store.close()

    def test_the_application_starts_on_sqlite_without_fts5(self):
        """A SQLite build without FTS5 must not break the application."""
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "nofts.db"

            with mock.patch("protas.db.fts5_available", return_value=False), mock.patch(
                "protas.store.fts5_available", return_value=False
            ):
                store = Store(path=db)
                try:
                    day = store.ensure_day("2026-11-10")
                    store.add_task("Tarea sin indice", day.id)
                    hits = store.search("indice")
                    self.assertEqual([hit.text for hit in hits], ["Tarea sin indice"])
                finally:
                    store.close()

            # the index is created later, when the machine supports it
            store = Store(path=db)
            try:
                hits = store.search("indice")
                self.assertEqual([hit.text for hit in hits], ["Tarea sin indice"])
            finally:
                store.close()


# A database that lived for a while: the first task ids were deleted, a
# project holds a nested subtask and a pending task was carried to the
# next day.
LIVED_IN_SCHEMA = LEGACY_SCHEMA.split("INSERT INTO days")[0] + """
INSERT INTO days (id, date, title, note, created_at)
    VALUES (1, '2026-11-09', '2026-11-09', '', '2026-11-09T10:00:00');
INSERT INTO days (id, date, title, note, created_at)
    VALUES (2, '2026-11-10', '2026-11-10', '', '2026-11-10T10:00:00');
INSERT INTO tasks (id, day_id, parent_id, text, origin_id, position, created_at)
    VALUES (5, 1, NULL, 'Suelta', NULL, 0, '2026-11-09T10:00:00');
INSERT INTO tasks (id, day_id, parent_id, text, origin_id, position, created_at)
    VALUES (6, 1, NULL, 'Proyecto', NULL, 1, '2026-11-09T10:00:00');
INSERT INTO tasks (id, day_id, parent_id, text, origin_id, position, created_at)
    VALUES (7, 1, 6, 'Hijo', NULL, 0, '2026-11-09T10:00:00');
INSERT INTO tasks (id, day_id, parent_id, text, origin_id, position, created_at)
    VALUES (9, 1, 7, 'Nieto', NULL, 0, '2026-11-09T10:00:00');
INSERT INTO tasks (id, day_id, parent_id, text, origin_id, position, created_at)
    VALUES (12, 2, NULL, 'Suelta', 5, 0, '2026-11-10T10:00:00');
INSERT INTO carries (origin_id, day_id, created_at)
    VALUES (5, 2, '2026-11-10T10:00:00');
"""


def _create(db: Path, script: str) -> None:
    legacy = sqlite3.connect(str(db))
    legacy.executescript(script)
    legacy.commit()
    legacy.close()


def _tables(db: Path) -> set[str]:
    conn = sqlite3.connect(str(db))
    try:
        return {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    finally:
        conn.close()


class LivedInMigrationTest(unittest.TestCase):
    def test_a_database_with_deleted_ids_keeps_its_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "legacy.db"
            _create(db, LIVED_IN_SCHEMA)

            store = Store(path=db)
            try:
                projects = store.projects()
                self.assertEqual([p.workspace.title for p in projects], ["Proyecto"])

                inside = store.tasks_of(projects[0].workspace.id)
                self.assertEqual([task.text for task in inside], ["Hijo"])
                self.assertIsNone(inside[0].parent_id)
                self.assertEqual([task.text for task in inside[0].children], ["Nieto"])

                first_day = store.tasks_of(store.day("2026-11-09").id)
                self.assertEqual([task.text for task in first_day], ["Suelta", "Proyecto"])
                self.assertEqual([task.children for task in first_day], [[], []])

                # the carried copy still knows where it comes from
                copy = store.tasks_of(store.day("2026-11-10").id)[0]
                self.assertEqual(copy.origin_id, first_day[0].id)
            finally:
                store.close()

    def test_deleting_the_mention_keeps_the_migrated_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "legacy.db"
            _create(db, LEGACY_SCHEMA)

            store = Store(path=db)
            try:
                day = store.day("2026-11-10")
                mention = next(task for task in store.tasks_of(day.id) if task.is_mention)
                store.delete_task(mention.id)

                inside = store.tasks_of(mention.project_id)
                self.assertEqual([task.text for task in inside], ["Esquema nuevo"])
            finally:
                store.close()

    def test_the_carry_ledger_points_at_the_day_that_received_the_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "legacy.db"
            _create(db, LIVED_IN_SCHEMA)

            store = Store(path=db)
            try:
                origin = store.tasks_of(store.day("2026-11-09").id)[0]
                rows = store.conn.execute("SELECT origin_id, workspace_id FROM carries").fetchall()
                self.assertEqual(
                    [(row["origin_id"], row["workspace_id"]) for row in rows],
                    [(origin.id, store.day("2026-11-10").id)],
                )
                # so the task is not carried a second time into that day
                carried = [store.task(i).text for i in store.rollover("2026-11-10")]
                self.assertNotIn("Suelta", carried)
            finally:
                store.close()

    def test_a_failed_migration_leaves_the_database_as_it_was(self):
        from unittest import mock

        from protas import db as db_module

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "legacy.db"
            _create(db, LEGACY_SCHEMA)

            original = db_module._migrate_v2

            def broken(conn):
                original(conn)
                raise sqlite3.IntegrityError("boom")

            with mock.patch("protas.db._migrate_v2", side_effect=broken):
                with self.assertRaises(db_module.MigrationError) as raised:
                    Store(path=db)
            self.assertIn(str(db), str(raised.exception))

            # nothing changed: the old tables are intact and nothing new exists
            self.assertEqual(
                _tables(db) - {"sqlite_sequence"}, {"days", "tasks", "carries"}
            )
            conn = sqlite3.connect(str(db))
            try:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 3)
                self.assertEqual(
                    conn.execute("SELECT note FROM days").fetchone()[0], "nota vieja"
                )
            finally:
                conn.close()

            # and the next start migrates it for real
            store = Store(path=db)
            try:
                self.assertEqual(len(store.tasks_of(store.day("2026-11-10").id)), 2)
                self.assertEqual(len(store.projects()), 1)
            finally:
                store.close()

    def test_the_command_line_reports_a_failed_migration(self):
        import contextlib
        import io
        from unittest import mock

        from protas.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "legacy.db"
            _create(db, LEGACY_SCHEMA)

            stderr = io.StringIO()
            with mock.patch("protas.db._migrate_v2", side_effect=sqlite3.IntegrityError("boom")):
                with contextlib.redirect_stderr(stderr):
                    code = main(["--db", str(db), "show"])

            self.assertEqual(code, 1)
            self.assertIn("protas: could not migrate", stderr.getvalue())
            self.assertIn("legacy.db.before-workspaces.bak", stderr.getvalue())

    def test_a_copy_of_the_old_database_is_kept(self):
        from protas.db import legacy_backup_path

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "legacy.db"
            _create(db, LEGACY_SCHEMA)

            Store(path=db).close()

            backup = legacy_backup_path(db)
            self.assertEqual(backup, Path(tmp) / "legacy.db.before-workspaces.bak")
            self.assertTrue(backup.exists())
            self.assertEqual(_tables(backup) - {"sqlite_sequence"}, {"days", "tasks", "carries"})
            conn = sqlite3.connect(str(backup))
            try:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 3)
            finally:
                conn.close()

    def test_a_new_database_gets_no_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "new.db"
            Store(path=db).close()
            self.assertEqual([path.name for path in Path(tmp).iterdir()], ["new.db"])



def _legacy_rows(db: Path) -> list:
    conn = sqlite3.connect(str(db))
    try:
        return [
            conn.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall()
            for table in ("days", "tasks", "carries")
        ]
    finally:
        conn.close()


class BackupTest(unittest.TestCase):
    """The copy taken before migrating is the database being migrated."""

    def setUp(self):
        from protas import db as db_module

        self.db_module = db_module
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.db = self.dir / "legacy.db"
        _create(self.db, LEGACY_SCHEMA)
        self.before = _legacy_rows(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def names(self):
        return sorted(path.name for path in self.dir.iterdir())

    def fail_migration(self, error=None):
        from unittest import mock

        with mock.patch(
            "protas.db._migrate_v2", side_effect=error or sqlite3.IntegrityError("boom")
        ):
            with self.assertRaises(self.db_module.MigrationError) as raised:
                Store(path=self.db)
        return str(raised.exception)

    def test_an_old_copy_of_another_database_is_not_taken_as_the_copy(self):
        stale = self.dir / "legacy.db.before-workspaces.bak"
        _create(stale, LIVED_IN_SCHEMA)
        stale_rows = _legacy_rows(stale)

        Store(path=self.db).close()

        fresh = self.dir / "legacy.db.before-workspaces.2.bak"
        self.assertEqual(self.names(), sorted(["legacy.db", stale.name, fresh.name]))
        self.assertEqual(_legacy_rows(fresh), self.before)
        # the old copy is somebody's data: it is left alone
        self.assertEqual(_legacy_rows(stale), stale_rows)

    def test_a_retry_reuses_the_copy_it_already_took(self):
        message = self.fail_migration()
        self.assertIn("legacy.db.before-workspaces.bak", message)
        self.fail_migration()
        Store(path=self.db).close()

        self.assertEqual(self.names(), ["legacy.db", "legacy.db.before-workspaces.bak"])
        self.assertEqual(
            _legacy_rows(self.dir / "legacy.db.before-workspaces.bak"), self.before
        )

    def test_a_copy_that_cannot_be_read_is_not_trusted(self):
        broken = self.dir / "legacy.db.before-workspaces.bak"
        broken.write_bytes(b"this is not a database")

        Store(path=self.db).close()

        self.assertEqual(broken.read_bytes(), b"this is not a database")
        self.assertEqual(
            _legacy_rows(self.dir / "legacy.db.before-workspaces.2.bak"), self.before
        )

    def test_without_a_copy_there_is_no_migration(self):
        from unittest import mock

        def half_written(conn, target):
            Path(target).write_bytes(b"half a copy")
            raise sqlite3.OperationalError("disk full")

        with mock.patch("protas.db._write_copy", side_effect=half_written):
            with self.assertRaises(self.db_module.MigrationError) as raised:
                Store(path=self.db)

        self.assertIn("could not copy", str(raised.exception))
        self.assertIn("disk full", str(raised.exception))
        # nothing half written stays behind and the database was not touched
        self.assertEqual(self.names(), ["legacy.db"])
        self.assertEqual(_legacy_rows(self.db), self.before)

        Store(path=self.db).close()
        self.assertEqual(self.names(), ["legacy.db", "legacy.db.before-workspaces.bak"])

    def test_a_copy_that_does_not_match_stops_the_migration(self):
        from unittest import mock

        def wrong_copy(conn, target):
            _create(Path(target), LIVED_IN_SCHEMA)

        with mock.patch("protas.db._write_copy", side_effect=wrong_copy):
            with self.assertRaises(self.db_module.MigrationError) as raised:
                Store(path=self.db)

        self.assertIn("could not copy", str(raised.exception))
        self.assertEqual(self.names(), ["legacy.db"])
        self.assertEqual(_legacy_rows(self.db), self.before)

    def test_the_first_error_is_the_one_reported(self):
        def closes_then_fails(conn):
            conn.close()
            raise ValueError("the real reason")

        message = self.fail_migration(closes_then_fails)

        self.assertIn("the real reason", message)
        self.assertEqual(_legacy_rows(self.db), self.before)

    def test_an_interrupted_migration_changes_nothing(self):
        from unittest import mock

        original = self.db_module._migrate_v2

        def interrupted(conn):
            original(conn)
            raise KeyboardInterrupt

        with mock.patch("protas.db._migrate_v2", side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                Store(path=self.db)

        self.assertEqual(_tables(self.db) - {"sqlite_sequence"}, {"days", "tasks", "carries"})
        self.assertEqual(_legacy_rows(self.db), self.before)

        # the file is free: the next start migrates it
        store = Store(path=self.db)
        try:
            self.assertEqual(len(store.projects()), 1)
        finally:
            store.close()

    def test_a_task_of_a_missing_day_is_named_in_the_error(self):
        conn = sqlite3.connect(str(self.db))
        conn.execute(
            "INSERT INTO tasks (day_id, parent_id, text, position, created_at) "
            "VALUES (99, NULL, 'Huerfana', 5, '2026-11-10T10:00:00')"
        )
        conn.commit()
        conn.close()
        before = _legacy_rows(self.db)

        with self.assertRaises(self.db_module.MigrationError) as raised:
            Store(path=self.db)

        self.assertIn("task 4 belongs to day 99, which does not exist", str(raised.exception))
        self.assertEqual(_legacy_rows(self.db), before)

    def test_a_project_subtask_of_a_missing_day_is_named_too(self):
        conn = sqlite3.connect(str(self.db))
        conn.execute("UPDATE tasks SET day_id = 42 WHERE id = 3")
        conn.commit()
        conn.close()
        before = _legacy_rows(self.db)

        with self.assertRaises(self.db_module.MigrationError) as raised:
            Store(path=self.db)

        self.assertIn("task 3 belongs to day 42, which does not exist", str(raised.exception))
        self.assertEqual(_legacy_rows(self.db), before)

    def test_the_copy_has_the_permissions_of_the_database(self):
        import os
        import stat

        os.chmod(self.db, 0o640)
        Store(path=self.db).close()

        backup = self.dir / "legacy.db.before-workspaces.bak"
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o640)

    def test_a_database_migrated_by_someone_else_meanwhile_is_left_alone(self):
        from unittest import mock

        original = self.db_module._backup_legacy
        calls = []

        def racing(conn, path):
            calls.append(path)
            if len(calls) == 1:
                # another protas finishes the migration first
                self.db_module.connect(path).close()
            return original(conn, path)

        with mock.patch("protas.db._backup_legacy", side_effect=racing):
            store = Store(path=self.db)

        try:
            self.assertEqual(len(calls), 2)
            self.assertEqual(len(store.tasks_of(store.day("2026-11-10").id)), 2)
            self.assertEqual(len(store.projects()), 1)
            self.assertEqual(
                store.conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 3
            )
        finally:
            store.close()
        self.assertEqual(self.names(), ["legacy.db", "legacy.db.before-workspaces.bak"])

    def test_every_schema_script_splits_into_single_statements(self):
        module = self.db_module
        script = module.LEGACY_RENAME + module.SCHEMA + module.LEGACY_DROP
        statements = module._statements(script)

        for statement in statements:
            self.assertTrue(sqlite3.complete_statement(statement), statement)
            self.assertEqual(statement.count(";"), 1, statement)

        # one by one they build the same schema as the script run whole
        def schema_of(run):
            conn = sqlite3.connect(":memory:")
            try:
                run(conn)
                return conn.execute(
                    "SELECT type, name, sql FROM sqlite_master ORDER BY name"
                ).fetchall()
            finally:
                conn.close()

        def one_by_one(conn):
            for statement in module._statements(module.SCHEMA):
                conn.execute(statement)

        self.assertEqual(
            schema_of(one_by_one), schema_of(lambda conn: conn.executescript(module.SCHEMA))
        )


if __name__ == "__main__":
    unittest.main()
