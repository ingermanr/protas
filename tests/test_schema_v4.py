"""Schema 4: the tables of the recurring tasks reach every database.

The current schema is newer; these tests keep the version numbers from
``db.SCHEMA_VERSION`` so they stay about the recurring tables.
"""

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
    "SELECT id, workspace_id, project_id, parent_id, text, done, done_at, "
    "origin_id, position, created_at FROM tasks ORDER BY id",
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

    def test_a_new_database_has_the_recurring_tables(self):
        Store(path=self.db).close()

        self.assertEqual(self.version(), [(str(db.SCHEMA_VERSION),)])
        self.assertLessEqual(NEW_TABLES, self.tables())
        self.assertEqual([p.name for p in self.dir.iterdir()], ["protas.db"])

    def test_the_version_command_names_the_current_schema(self):
        import contextlib
        import io

        import protas
        from protas import cli

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["--db", str(self.db), "version"])

        self.assertEqual(code, 0)
        self.assertEqual(
            out.getvalue(), f"protas {protas.__version__} (schema {db.SCHEMA_VERSION})\n"
        )

    def test_a_version_3_database_is_updated_and_keeps_every_row(self):
        self.build_version_3()
        self.assertEqual(self.version(), [("3",)])
        self.assertFalse(NEW_TABLES & self.tables())
        before = [self.query(sql) for sql in DATA]
        notices = []

        Store(path=self.db, notify=notices.append).close()

        self.assertEqual(self.version(), [(str(db.SCHEMA_VERSION),)])
        self.assertLessEqual(NEW_TABLES, self.tables())
        self.assertEqual([self.query(sql) for sql in DATA], before)
        self.assertEqual(self.query("SELECT count(*) FROM recurrences"), [(0,)])

        copy = self.dir / "protas.db.v3.bak"
        self.assertTrue(copy.is_file())
        self.assertEqual(self.version(copy), [("3",)])
        self.assertFalse(NEW_TABLES & self.tables(copy))
        self.assertEqual(len(notices), 1)
        self.assertIn(f"from version 3 to {db.SCHEMA_VERSION}", notices[0])
        self.assertIn(str(copy), notices[0])

    def doctor(self):
        import contextlib
        import io

        from protas import cli

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["--db", str(self.db), "doctor"])
        return code, out.getvalue()

    def test_doctor_finds_a_new_database_healthy(self):
        Store(path=self.db).close()

        code, out = self.doctor()

        self.assertEqual(code, 0)
        self.assertIn(f"schema:       version {db.SCHEMA_VERSION}, up to date\n", out)
        self.assertIn("integrity:    ok\n", out)
        self.assertIn("copies:       none\n", out)

    def test_doctor_reports_a_version_3_database_and_then_its_copy(self):
        self.build_version_3()

        code, out = self.doctor()
        self.assertEqual(code, 0)
        self.assertIn(
            f"schema:       version 3, it will be updated to "
            f"{db.SCHEMA_VERSION} when protas opens it\n",
            out,
        )
        self.assertEqual(self.version(), [("3",)])

        Store(path=self.db).close()
        code, out = self.doctor()
        self.assertEqual(code, 0)
        self.assertIn(f"schema:       version {db.SCHEMA_VERSION}, up to date\n", out)
        self.assertIn("copies:       protas.db.v3.bak\n", out)

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

    def test_a_database_from_before_the_workspaces_reaches_the_current_version(self):
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

        self.assertEqual(self.version(), [(str(db.SCHEMA_VERSION),)])
        self.assertLessEqual(NEW_TABLES, self.tables())
        self.assertIn("Tarea vieja", texts)
        names = sorted(p.name for p in self.dir.iterdir())
        self.assertIn("protas.db.before-workspaces.bak", names)
        self.assertIn("protas.db.v3.bak", names)


if __name__ == "__main__":
    unittest.main()
