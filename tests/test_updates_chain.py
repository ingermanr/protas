"""Probes for the update chain: data, rollback and refusal.

Written by the independent verifier of the commit that added the chain.
"""

import contextlib
import hashlib
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from protas import cli
from protas.store import Store
from tests.support import pin_version_3


def add_priority(conn):
    conn.execute("ALTER TABLE tasks ADD COLUMN priority INTEGER NOT NULL DEFAULT 0")


def fill_priority(conn):
    conn.execute("UPDATE tasks SET priority = id % 3")


LEGACY_SCHEMA = """
CREATE TABLE days (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT,
  day_id INTEGER NOT NULL REFERENCES days(id) ON DELETE CASCADE,
  parent_id INTEGER REFERENCES tasks(id) ON DELETE CASCADE, text TEXT NOT NULL,
  done INTEGER NOT NULL DEFAULT 0, done_at TEXT,
  origin_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
  origin_day_id INTEGER REFERENCES days(id) ON DELETE SET NULL,
  position INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE carries (origin_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  day_id INTEGER NOT NULL REFERENCES days(id) ON DELETE CASCADE, created_at TEXT NOT NULL,
  PRIMARY KEY (origin_id, day_id));
INSERT INTO days (date, title, note, created_at)
  VALUES ('2026-11-10', '2026-11-10', 'nota vieja', '2026-11-10T10:00:00');
INSERT INTO tasks (day_id, parent_id, text, done, done_at, origin_id, origin_day_id, position, created_at)
  VALUES (1, NULL, 'Tarea vieja', 0, NULL, NULL, NULL, 0, '2026-11-10T10:00:00');
INSERT INTO tasks (day_id, parent_id, text, done, done_at, origin_id, origin_day_id, position, created_at)
  VALUES (1, NULL, 'Migrar la base', 0, NULL, NULL, NULL, 1, '2026-11-10T10:00:00');
INSERT INTO tasks (day_id, parent_id, text, done, done_at, origin_id, origin_day_id, position, created_at)
  VALUES (1, 2, 'Esquema nuevo', 0, NULL, NULL, NULL, 0, '2026-11-10T10:00:00');
"""


def newer(steps, version):
    return mock.patch.multiple("protas.db", MIGRATIONS=steps, SCHEMA_VERSION=version)


class ChainCase(unittest.TestCase):
    def setUp(self):
        pin_version_3(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.db = self.dir / "protas.db"
        store = Store(path=self.db)
        day = store.open_day("2026-01-05")
        store.set_note(day.id, "una nota")
        first = store.add_task("Comprar pan", day.id)
        store.add_task("Llamar al banco", day.id)
        store.add_task("Pan integral", day.id, parent_id=first.id)
        store.add_task("Harina", first.workspace_id, parent_id=first.id + 1)
        store.close()

    def names(self):
        return sorted(p.name for p in self.dir.iterdir())

    def digest(self):
        return hashlib.sha256(self.db.read_bytes()).hexdigest()

    def rows(self, sql, path=None):
        conn = sqlite3.connect(str(path or self.db))
        try:
            return conn.execute(sql).fetchall()
        finally:
            conn.close()


class ChainDataTest(ChainCase):
    def test_a_chained_update_keeps_every_row_and_the_index(self):
        """S7 + S3: v3 reaches v5 through v4, rows and index intact."""
        before = self.rows(
            "SELECT id, workspace_id, project_id, parent_id, text, done, position "
            "FROM tasks ORDER BY id"
        )
        workspaces = self.rows("SELECT id, kind, title, date, note FROM workspaces ORDER BY id")

        with newer({3: add_priority, 4: fill_priority}, 5):
            store = Store(path=self.db)
            hits = store.search("pan")
            store.close()

        self.assertEqual(self.rows("SELECT value FROM meta WHERE key='schema_version'"), [("5",)])
        self.assertEqual(
            self.rows(
                "SELECT id, workspace_id, project_id, parent_id, text, done, position "
                "FROM tasks ORDER BY id"
            ),
            before,
        )
        self.assertEqual(
            self.rows("SELECT id, kind, title, date, note FROM workspaces ORDER BY id"), workspaces
        )
        self.assertTrue(hits)
        self.assertEqual(
            sorted({r[0] for r in self.rows("SELECT priority FROM tasks")}), [0, 1, 2]
        )
        self.assertEqual(self.names(), ["protas.db", "protas.db.v3.bak"])

    def test_a_failing_step_undoes_ddl_and_dml_and_names_the_copy(self):
        """S3: writes and schema changes of the failed run are undone."""
        before = self.digest()
        events = self.rows("SELECT count(*) FROM events")

        def broken(conn):
            conn.execute("ALTER TABLE tasks ADD COLUMN reviewed INTEGER NOT NULL DEFAULT 0")
            conn.execute("DELETE FROM events")
            conn.execute("UPDATE tasks SET text = 'half way'")
            raise sqlite3.IntegrityError("boom")

        stderr = io.StringIO()
        with newer({3: add_priority, 4: broken}, 5), contextlib.redirect_stderr(stderr):
            code = cli.main(["--db", str(self.db), "list", "--date", "2026-01-05"])

        self.assertEqual(code, 1)
        self.assertEqual(self.digest(), before)
        self.assertEqual(self.rows("SELECT value FROM meta WHERE key='schema_version'"), [("3",)])
        self.assertNotIn("reviewed", [r[1] for r in self.rows("PRAGMA table_info(tasks)")])
        self.assertEqual(self.rows("SELECT count(*) FROM events"), events)
        self.assertIn(str(self.dir / "protas.db.v3.bak"), stderr.getvalue())

    def test_an_interrupted_step_changes_nothing(self):
        """S3: Ctrl-C in a step leaves the file as it was."""
        before = self.digest()

        def interrupted(conn):
            conn.execute("ALTER TABLE tasks ADD COLUMN priority INTEGER NOT NULL DEFAULT 0")
            raise KeyboardInterrupt

        with newer({3: interrupted}, 4):
            with self.assertRaises(KeyboardInterrupt):
                Store(path=self.db)

        self.assertEqual(self.digest(), before)
        self.assertEqual(self.rows("SELECT value FROM meta WHERE key='schema_version'"), [("3",)])


class RefusalTest(ChainCase):
    def test_a_newer_database_is_left_alone_and_never_restamped(self):
        """S6: a version from a newer protas is refused, not rewritten."""
        conn = sqlite3.connect(str(self.db))
        conn.execute("UPDATE meta SET value = '4' WHERE key = 'schema_version'")
        conn.commit()
        conn.close()
        before = self.digest()

        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(["--db", str(self.db), "list", "--date", "2026-01-05"])

        self.assertEqual(code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("newer protas", stderr.getvalue())
        self.assertEqual(self.digest(), before)
        self.assertEqual(self.rows("SELECT value FROM meta WHERE key='schema_version'"), [("4",)])
        self.assertEqual(self.names(), ["protas.db"])


class LegacyThenChainTest(unittest.TestCase):
    def test_a_database_from_before_the_workspaces_gets_both_copies(self):
        """S7: the legacy move and the chain compose, each with its copy."""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "protas.db"
            legacy = sqlite3.connect(str(db))
            legacy.executescript(LEGACY_SCHEMA)
            legacy.commit()
            legacy.close()

            with newer({3: add_priority, 4: fill_priority}, 5):
                store = Store(path=db)
                day = store.day("2026-11-10")
                self.assertIsNotNone(day)
                self.assertEqual(len(store.projects()), 1)
                store.close()

            names = sorted(p.name for p in Path(tmp).iterdir())
            self.assertEqual(
                names,
                [
                    "protas.db",
                    "protas.db.before-workspaces.bak",
                    "protas.db.v3.bak",
                ],
            )
            conn = sqlite3.connect(str(db))
            try:
                self.assertEqual(
                    conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone(),
                    ("5",),
                )
                self.assertEqual(conn.execute("SELECT count(*) FROM tasks").fetchone(), (3,))
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
