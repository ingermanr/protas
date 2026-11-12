"""Tests for updating the database of an installed protas.

A schema change is a step from one version to the next. Opening an older
database copies it aside and walks the steps in one go; a database from a
newer protas is refused and never touched.
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
from protas.db import MigrationError
from protas.store import Store


def add_priority(conn):
    conn.execute("ALTER TABLE tasks ADD COLUMN priority INTEGER NOT NULL DEFAULT 0")


def raise_priority(conn):
    conn.execute("UPDATE tasks SET priority = 2")


def broken(conn):
    conn.execute("UPDATE tasks SET text = 'half way'")
    raise sqlite3.IntegrityError("boom")


def newer_protas(steps, version):
    """Run the block as a protas whose schema is ``version``."""
    return mock.patch.multiple("protas.db", MIGRATIONS=steps, SCHEMA_VERSION=version)


class UpdateCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "protas.db"
        store = Store(path=self.db)
        day = store.open_day("2026-01-05")
        store.add_task("Tarea de siempre", day.id)
        store.set_note(day.id, "una nota")
        store.close()

    def names(self):
        return sorted(path.name for path in Path(self.tmp.name).iterdir())

    def digest(self):
        return hashlib.sha256(self.db.read_bytes()).hexdigest()

    def query(self, sql, path=None):
        conn = sqlite3.connect(str(path or self.db))
        try:
            return conn.execute(sql).fetchall()
        finally:
            conn.close()

    def version(self, path=None):
        return self.query("SELECT value FROM meta WHERE key = 'schema_version'", path)

    def columns(self, path=None):
        return [row[1] for row in self.query("PRAGMA table_info(tasks)", path)]

    def set_version(self, value):
        conn = sqlite3.connect(str(self.db))
        if value is None:
            conn.execute("DELETE FROM meta WHERE key = 'schema_version'")
        else:
            conn.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (str(value),))
        conn.commit()
        conn.close()


class StepsTest(UpdateCase):
    def test_an_older_database_walks_every_step_in_order(self):
        with newer_protas({3: add_priority, 4: raise_priority}, 5):
            store = Store(path=self.db)
            store.close()

        self.assertEqual(self.version(), [("5",)])
        self.assertEqual(self.query("SELECT text, priority FROM tasks"), [("Tarea de siempre", 2)])
        self.assertEqual(self.query("SELECT note FROM workspaces"), [("una nota",)])

    def test_a_database_already_at_a_middle_version_only_walks_what_is_left(self):
        with newer_protas({3: add_priority}, 4):
            Store(path=self.db).close()
        with newer_protas({3: broken, 4: raise_priority}, 5):
            Store(path=self.db).close()

        self.assertEqual(self.version(), [("5",)])
        self.assertEqual(self.query("SELECT text, priority FROM tasks"), [("Tarea de siempre", 2)])
        self.assertEqual(self.names(), ["protas.db", "protas.db.v3.bak", "protas.db.v4.bak"])

    def test_the_database_as_it_was_is_copied_next_to_it(self):
        with newer_protas({3: add_priority, 4: raise_priority}, 5):
            Store(path=self.db).close()

        copy = self.db.with_name("protas.db.v3.bak")
        self.assertEqual(self.names(), ["protas.db", "protas.db.v3.bak"])
        self.assertEqual(self.version(copy), [("3",)])
        self.assertNotIn("priority", self.columns(copy))
        self.assertEqual(self.query("SELECT text FROM tasks", copy), [("Tarea de siempre",)])
        self.assertEqual(self.query("SELECT note FROM workspaces", copy), [("una nota",)])

    def test_a_database_of_this_version_is_opened_as_always(self):
        before = self.digest()

        store = Store(path=self.db)
        tasks = store.tasks_of(store.open_day("2026-01-05").id)
        store.close()

        self.assertEqual([task.text for task in tasks], ["Tarea de siempre"])
        self.assertEqual(self.names(), ["protas.db"])
        self.assertEqual(self.digest(), before)

    def test_a_new_database_starts_at_the_current_version(self):
        fresh = Path(self.tmp.name) / "fresh.db"
        with newer_protas({3: broken, 4: broken}, 5):
            Store(path=fresh).close()

        self.assertEqual(self.version(fresh), [("5",)])
        self.assertEqual(self.names(), ["fresh.db", "protas.db"])

    def test_a_database_with_workspaces_and_no_version_is_the_first_one(self):
        self.set_version(None)

        Store(path=self.db).close()
        self.assertEqual(self.version(), [("3",)])
        self.assertEqual(self.names(), ["protas.db"])

        self.set_version(None)
        with newer_protas({3: add_priority}, 4):
            Store(path=self.db).close()
        self.assertEqual(self.version(), [("4",)])
        self.assertIn("priority", self.columns())


class FailureTest(UpdateCase):
    def assert_untouched(self, before):
        self.assertEqual(self.digest(), before)
        self.assertEqual(self.version(), [("3",)])
        self.assertNotIn("priority", self.columns())
        self.assertEqual(self.query("SELECT text FROM tasks"), [("Tarea de siempre",)])

    def test_a_step_that_fails_leaves_the_database_as_it_was(self):
        before = self.digest()

        with newer_protas({3: add_priority, 4: broken}, 5):
            with self.assertRaises(MigrationError) as raised:
                Store(path=self.db)

        self.assert_untouched(before)
        message = str(raised.exception)
        self.assertIn(f"could not update {self.db} from version 3 to 5: boom", message)
        self.assertIn("The database was left untouched", message)
        self.assertIn(str(self.db.with_name("protas.db.v3.bak")), message)
        # nothing keeps the file locked
        conn = sqlite3.connect(str(self.db), timeout=0)
        conn.execute("BEGIN IMMEDIATE")
        conn.close()

    def test_the_command_line_reports_the_failure(self):
        stderr = io.StringIO()
        with newer_protas({3: broken}, 4), contextlib.redirect_stderr(stderr):
            code = cli.main(["--db", str(self.db), "list"])

        self.assertEqual(code, 1)
        self.assertIn("protas: could not update", stderr.getvalue())

    def test_a_retry_reuses_the_copy_it_already_took(self):
        with newer_protas({3: broken}, 4):
            with self.assertRaises(MigrationError):
                Store(path=self.db)
            with self.assertRaises(MigrationError):
                Store(path=self.db)
        with newer_protas({3: add_priority}, 4):
            Store(path=self.db).close()

        self.assertEqual(self.names(), ["protas.db", "protas.db.v3.bak"])
        self.assertEqual(self.version(), [("4",)])

    def test_a_copy_of_something_else_is_never_replaced(self):
        other = self.db.with_name("protas.db.v3.bak")
        other.write_text("the only copy of something else")

        with newer_protas({3: add_priority}, 4):
            Store(path=self.db).close()

        self.assertEqual(other.read_text(), "the only copy of something else")
        self.assertEqual(self.names(), ["protas.db", "protas.db.v3.2.bak", "protas.db.v3.bak"])
        self.assertEqual(self.version(self.db.with_name("protas.db.v3.2.bak")), [("3",)])

    def test_without_a_copy_there_is_no_update(self):
        before = self.digest()

        with newer_protas({3: add_priority}, 4), mock.patch(
            "protas.db._write_copy", side_effect=OSError("disk full")
        ):
            with self.assertRaises(MigrationError) as raised:
                Store(path=self.db)

        self.assert_untouched(before)
        self.assertIn("could not copy", str(raised.exception))
        self.assertIn("disk full", str(raised.exception))
        self.assertEqual(self.names(), ["protas.db"])

    def test_a_missing_step_stops_before_anything_changes(self):
        before = self.digest()

        with newer_protas({4: raise_priority}, 5):
            with self.assertRaises(MigrationError) as raised:
                Store(path=self.db)

        self.assert_untouched(before)
        self.assertIn("does not know how to update version 3", str(raised.exception))
        self.assertEqual(self.names(), ["protas.db"])

    def test_an_interrupted_update_changes_nothing(self):
        before = self.digest()

        def interrupted(conn):
            conn.execute("UPDATE tasks SET text = 'half way'")
            raise KeyboardInterrupt

        with newer_protas({3: interrupted}, 4):
            with self.assertRaises(KeyboardInterrupt):
                Store(path=self.db)

        self.assert_untouched(before)


class NewerDatabaseTest(UpdateCase):
    """A database written by a newer protas is not ours to touch."""

    def test_it_is_refused_and_left_alone(self):
        self.set_version(4)
        before = self.digest()

        with self.assertRaises(MigrationError) as raised:
            Store(path=self.db)

        self.assertEqual(self.digest(), before)
        self.assertEqual(self.version(), [("4",)])
        self.assertEqual(self.names(), ["protas.db"])
        message = str(raised.exception)
        self.assertIn(str(self.db), message)
        self.assertIn("newer protas", message)
        self.assertIn("version 4", message)
        self.assertIn("version 3", message)

    def test_the_command_line_says_so_and_fails(self):
        self.set_version(7)
        before = self.digest()

        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(["--db", str(self.db), "add", "No deberia entrar"])

        self.assertEqual(code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertTrue(stderr.getvalue().startswith("protas: "))
        self.assertIn("newer protas", stderr.getvalue())
        self.assertEqual(self.digest(), before)

    def test_a_version_that_is_not_a_number_is_refused_too(self):
        self.set_version("three")
        before = self.digest()

        with self.assertRaises(MigrationError) as raised:
            Store(path=self.db)

        self.assertEqual(self.digest(), before)
        self.assertIn("'three'", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
