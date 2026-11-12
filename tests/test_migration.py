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


if __name__ == "__main__":
    unittest.main()
