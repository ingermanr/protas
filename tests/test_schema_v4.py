"""Schema 4: the tables of the recurring tasks reach every database."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from protas import db
from protas.store import Store
from tests.support import at_version_3
from tests.test_updates_chain import LEGACY_SCHEMA

NEW_TABLES = {"recurrences", "recurrence_tasks"}
DATA = (
    "SELECT * FROM workspaces ORDER BY id",
    "SELECT * FROM tasks ORDER BY id",
    "SELECT * FROM carries ORDER BY origin_id, workspace_id",
    "SELECT * FROM events ORDER BY id",
)


class SchemaV4Test(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.db = self.dir / "protas.db"

    def query(self, sql, path=None):
        conn = sqlite3.connect(str(path or self.db))
        try:
            return conn.execute(sql).fetchall()
        finally:
            conn.close()

    def tables(self, path=None):
        rows = self.query("SELECT name FROM sqlite_master WHERE type = 'table'", path)
        return {row[0] for row in rows}

    def version(self, path=None):
        return self.query("SELECT value FROM meta WHERE key = 'schema_version'", path)

    def build_version_3(self):
        with at_version_3():
            store = Store(path=self.db)
            day = store.open_day("2026-01-05")
            store.set_note(day.id, "una nota")
            first = store.add_task("Comprar pan", day.id)
            store.add_task("Pan integral", day.id, parent_id=first.id)
            project = store.promote(store.add_task("Mudanza", day.id).id)
            store.add_task("Cajas", project.id)
            store.set_done(first.id)
            store.close()

    def test_a_new_database_is_version_4_and_has_the_tables(self):
        Store(path=self.db).close()

        self.assertEqual(self.version(), [("4",)])
        self.assertLessEqual(NEW_TABLES, self.tables())
        self.assertEqual([p.name for p in self.dir.iterdir()], ["protas.db"])

    def test_the_version_command_names_schema_4(self):
        import contextlib
        import io

        import protas
        from protas import cli

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["--db", str(self.db), "version"])

        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue(), f"protas {protas.__version__} (schema 4)\n")

    def test_a_version_3_database_is_updated_and_keeps_every_row(self):
        self.build_version_3()
        self.assertEqual(self.version(), [("3",)])
        self.assertFalse(NEW_TABLES & self.tables())
        before = [self.query(sql) for sql in DATA]
        notices = []

        Store(path=self.db, notify=notices.append).close()

        self.assertEqual(self.version(), [("4",)])
        self.assertLessEqual(NEW_TABLES, self.tables())
        self.assertEqual([self.query(sql) for sql in DATA], before)
        self.assertEqual(self.query("SELECT count(*) FROM recurrences"), [(0,)])

        copy = self.dir / "protas.db.v3.bak"
        self.assertTrue(copy.is_file())
        self.assertEqual(self.version(copy), [("3",)])
        self.assertFalse(NEW_TABLES & self.tables(copy))
        self.assertEqual(len(notices), 1)
        self.assertIn("from version 3 to 4", notices[0])
        self.assertIn(str(copy), notices[0])

    def test_an_updated_database_opens_again_without_another_copy(self):
        self.build_version_3()
        Store(path=self.db).close()
        notices = []

        Store(path=self.db, notify=notices.append).close()

        self.assertEqual(notices, [])
        self.assertEqual(
            sorted(p.name for p in self.dir.iterdir()), ["protas.db", "protas.db.v3.bak"]
        )

    def test_the_step_leaves_a_version_3_database_untouched_when_it_fails(self):
        self.build_version_3()
        before = [self.query(sql) for sql in DATA]

        def broken(conn):
            db._add_recurrences(conn)
            raise RuntimeError("disk on fire")

        from unittest import mock

        with mock.patch.dict(db.MIGRATIONS, {3: broken}):
            with self.assertRaises(db.MigrationError):
                Store(path=self.db)

        self.assertEqual(self.version(), [("3",)])
        self.assertFalse(NEW_TABLES & self.tables())
        self.assertEqual([self.query(sql) for sql in DATA], before)

    def test_a_database_from_before_the_workspaces_reaches_version_4(self):
        conn = sqlite3.connect(str(self.db))
        conn.executescript(LEGACY_SCHEMA)
        conn.close()

        store = Store(path=self.db)
        try:
            texts = sorted(
                task.text
                for day in store.workspaces("day")
                for task in store.tasks_of(day.id)
            )
        finally:
            store.close()

        self.assertEqual(self.version(), [("4",)])
        self.assertLessEqual(NEW_TABLES, self.tables())
        self.assertIn("Tarea vieja", texts)
        names = sorted(p.name for p in self.dir.iterdir())
        self.assertIn("protas.db.before-workspaces.bak", names)
        self.assertIn("protas.db.v3.bak", names)


if __name__ == "__main__":
    unittest.main()
