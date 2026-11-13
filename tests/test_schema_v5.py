"""Schema 5: every entry reaches the version that carries priority and estimate."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from protas import db
from protas.store import Store
from tests.support import at_version_3, at_version_4

DATA = (
    "SELECT * FROM workspaces ORDER BY id",
    "SELECT id, workspace_id, project_id, parent_id, text, done, done_at, "
    "origin_id, position, created_at FROM tasks ORDER BY id",
    "SELECT * FROM carries ORDER BY origin_id, workspace_id",
    "SELECT * FROM events ORDER BY id",
)

NEW_COLUMNS = {"priority", "estimate"}


class SchemaV5Test(unittest.TestCase):
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

    def columns(self, path=None):
        return {row[1] for row in self.query("PRAGMA table_info(tasks)", path)}

    def version(self, path=None):
        return self.query("SELECT value FROM meta WHERE key = 'schema_version'", path)

    def build_version_4(self):
        with at_version_4():
            store = Store(path=self.db)
            day = store.open_day("2026-01-05")
            store.set_note(day.id, "una nota")
            first = store.add_task("Comprar pan", day.id)
            store.add_task("Pan integral", day.id, parent_id=first.id)
            project = store.promote(store.add_task("Mudanza", day.id).id)
            store.add_task("Cajas", project.id)
            store.set_done(first.id)
            store.close()

    def test_a_new_database_is_version_5_and_has_the_columns_at_the_end(self):
        Store(path=self.db).close()

        self.assertEqual(self.version(), [("5",)])
        self.assertLessEqual(NEW_COLUMNS, self.columns())
        order = [row[1] for row in self.query("PRAGMA table_info(tasks)")]
        self.assertEqual(order[-2:], ["priority", "estimate"])
        self.assertEqual([p.name for p in self.dir.iterdir()], ["protas.db"])

    def test_a_version_4_database_is_updated_and_keeps_every_row(self):
        self.build_version_4()
        self.assertEqual(self.version(), [("4",)])
        self.assertFalse(NEW_COLUMNS & self.columns())
        before = [self.query(sql) for sql in DATA]
        notices = []

        Store(path=self.db, notify=notices.append).close()

        self.assertEqual(self.version(), [("5",)])
        self.assertLessEqual(NEW_COLUMNS, self.columns())
        self.assertEqual([self.query(sql) for sql in DATA], before)
        self.assertEqual(self.query("SELECT count(*) FROM tasks WHERE priority IS NOT NULL"), [(0,)])
        self.assertEqual(self.query("SELECT count(*) FROM tasks WHERE estimate IS NOT NULL"), [(0,)])

        copy = self.dir / "protas.db.v4.bak"
        self.assertTrue(copy.is_file())
        self.assertEqual(self.version(copy), [("4",)])
        self.assertFalse(NEW_COLUMNS & self.columns(copy))
        self.assertEqual(len(notices), 1)
        self.assertIn("from version 4 to 5", notices[0])
        self.assertIn(str(copy), notices[0])

    def test_a_version_3_database_reaches_version_5_in_one_open(self):
        with at_version_3():
            store = Store(path=self.db)
            day = store.open_day("2026-01-05")
            store.add_task("Tarea vieja", day.id)
            store.close()

        Store(path=self.db).close()

        self.assertEqual(self.version(), [("5",)])
        self.assertEqual(self.query("SELECT text FROM tasks"), [("Tarea vieja",)])
        self.assertEqual(
            sorted(p.name for p in self.dir.iterdir()),
            ["protas.db", "protas.db.v3.bak"],
        )

    def test_the_columns_refuse_values_outside_the_agreed_ones(self):
        Store(path=self.db).close()
        conn = sqlite3.connect(str(self.db))
        conn.execute("INSERT INTO workspaces (kind, title, date, note, created_at) "
                     "VALUES ('day', '2026-01-05', '2026-01-05', '', 'now')")
        conn.execute(
            "INSERT INTO tasks (workspace_id, text, done, position, created_at) "
            "VALUES (1, 'Algo', 0, 0, 'now')"
        )
        conn.commit()
        try:
            for sql in (
                "UPDATE tasks SET priority = 4",
                "UPDATE tasks SET priority = 0",
                "UPDATE tasks SET estimate = 0",
                "UPDATE tasks SET estimate = -5",
            ):
                with self.subTest(sql=sql):
                    with self.assertRaises(sqlite3.IntegrityError):
                        conn.execute(sql)
                        conn.commit()
                    conn.rollback()
            conn.execute("UPDATE tasks SET priority = 3, estimate = 90")
            conn.commit()
        finally:
            conn.close()

    def test_the_step_leaves_a_version_4_database_untouched_when_it_fails(self):
        self.build_version_4()
        before = [self.query(sql) for sql in DATA]

        def broken(conn):
            db._add_task_details(conn)
            raise RuntimeError("disk on fire")

        with mock.patch.dict(db.MIGRATIONS, {3: db._add_recurrences, 4: broken}):
            with self.assertRaises(db.MigrationError):
                Store(path=self.db)

        self.assertEqual(self.version(), [("4",)])
        self.assertFalse(NEW_COLUMNS & self.columns())
        self.assertEqual([self.query(sql) for sql in DATA], before)

    def test_an_updated_database_opens_again_without_another_copy(self):
        self.build_version_4()
        Store(path=self.db).close()
        notices = []

        Store(path=self.db, notify=notices.append).close()

        self.assertEqual(notices, [])
        self.assertEqual(
            sorted(p.name for p in self.dir.iterdir()),
            ["protas.db", "protas.db.v4.bak"],
        )


if __name__ == "__main__":
    unittest.main()
