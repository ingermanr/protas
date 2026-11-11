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


if __name__ == "__main__":
    unittest.main()
