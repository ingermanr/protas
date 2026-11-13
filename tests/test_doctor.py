"""Tests for `protas version` and `protas doctor`.

Both answer questions about the installation without changing it: neither
creates, migrates nor writes the database.
"""

import contextlib
import hashlib
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import protas
from protas import cli
from protas.store import Store
from tests.support import pin_version_3


class DoctorCase(unittest.TestCase):
    def setUp(self):
        pin_version_3(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "protas.db"

    def create(self):
        store = Store(path=self.db)
        day = store.open_day("2026-01-05")
        store.add_task("Tarea de siempre", day.id)
        store.close()

    def raw(self, *statements):
        conn = sqlite3.connect(str(self.db))
        for statement in statements:
            conn.execute(statement)
        conn.commit()
        conn.close()

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["--db", str(self.db), *args])
        return code, out.getvalue(), err.getvalue()

    def names(self):
        return sorted(path.name for path in Path(self.tmp.name).iterdir())

    def digest(self):
        return hashlib.sha256(self.db.read_bytes()).hexdigest()


class VersionTest(DoctorCase):
    def test_it_prints_the_application_and_the_schema(self):
        code, out, err = self.run_cli("version")

        self.assertEqual(code, 0)
        self.assertEqual(out, f"protas {protas.__version__} (schema 3)\n")
        self.assertEqual(err, "")

    def test_it_does_not_open_the_database(self):
        self.run_cli("version")
        self.assertEqual(self.names(), [])

        self.create()
        self.raw("UPDATE meta SET value = '9' WHERE key = 'schema_version'")
        before = self.digest()
        self.assertEqual(self.run_cli("version")[0], 0)
        self.assertEqual(self.digest(), before)


class DoctorTest(DoctorCase):
    def test_a_healthy_database(self):
        self.create()
        before = self.digest()

        code, out, err = self.run_cli("doctor")

        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertEqual(
            out.splitlines(),
            [
                f"database:     {self.db}",
                "schema:       version 3, up to date",
                "integrity:    ok",
                "search index: ok",
                "copies:       none",
            ],
        )
        self.assertEqual(self.digest(), before)
        self.assertEqual(self.names(), ["protas.db"])

    def test_the_copies_kept_next_to_the_database_are_listed(self):
        self.create()
        for name in ("protas.db.v3.bak", "protas.db.before-workspaces.bak", "other.db.v3.bak"):
            (Path(self.tmp.name) / name).write_text("copy")

        code, out, _ = self.run_cli("doctor")

        self.assertEqual(code, 0)
        self.assertIn(
            "copies:       protas.db.before-workspaces.bak, protas.db.v3.bak\n", out
        )

    def test_a_database_that_does_not_exist_yet_is_not_created(self):
        code, out, err = self.run_cli("doctor")

        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertEqual(
            out.splitlines(),
            [f"database:     {self.db}", "              not created yet"],
        )
        self.assertEqual(self.names(), [])

    def test_a_database_from_a_newer_protas_is_a_problem(self):
        self.create()
        self.raw("UPDATE meta SET value = '5' WHERE key = 'schema_version'")
        before = self.digest()

        code, out, _ = self.run_cli("doctor")

        self.assertEqual(code, 1)
        self.assertIn(
            "schema:       version 5, newer than this protas (3): update protas to open it\n",
            out,
        )
        self.assertEqual(self.digest(), before)

    def test_a_version_that_cannot_be_read_is_a_problem(self):
        self.create()
        self.raw("UPDATE meta SET value = 'three' WHERE key = 'schema_version'")

        code, out, _ = self.run_cli("doctor")

        self.assertEqual(code, 1)
        self.assertIn("schema:       version 'three' cannot be read\n", out)

    def test_an_older_database_is_reported_and_not_updated(self):
        self.create()
        before = self.digest()

        with mock.patch.multiple("protas.db", MIGRATIONS={3: lambda conn: None}, SCHEMA_VERSION=4):
            code, out, _ = self.run_cli("doctor")

        self.assertEqual(code, 0)
        self.assertIn(
            "schema:       version 3, it will be updated to 4 when protas opens it\n", out
        )
        self.assertEqual(self.digest(), before)
        self.assertEqual(self.names(), ["protas.db"])

    def test_a_database_from_before_the_workspaces_is_not_migrated(self):
        legacy = sqlite3.connect(str(self.db))
        legacy.executescript(
            "CREATE TABLE days (id INTEGER PRIMARY KEY, date TEXT NOT NULL UNIQUE);"
            "CREATE TABLE tasks (id INTEGER PRIMARY KEY, day_id INTEGER NOT NULL, text TEXT);"
            "INSERT INTO days (date) VALUES ('2026-01-05');"
        )
        legacy.close()
        before = self.digest()

        code, out, _ = self.run_cli("doctor")

        self.assertEqual(code, 0)
        self.assertIn(
            "schema:       from before the workspaces, "
            "it will be migrated when protas opens it\n",
            out,
        )
        self.assertEqual(self.digest(), before)
        self.assertEqual(self.names(), ["protas.db"])

    def test_a_file_that_is_not_a_database_is_a_problem(self):
        self.db.write_text("this is not a database, it is a long enough line of text\n" * 40)
        before = self.digest()

        code, out, _ = self.run_cli("doctor")

        self.assertEqual(code, 1)
        self.assertEqual(
            out.splitlines(),
            [f"database:     {self.db}", "              not a SQLite database"],
        )
        self.assertEqual(self.digest(), before)

    def test_a_broken_reference_is_a_problem(self):
        self.create()
        self.raw(
            "INSERT INTO tasks (workspace_id, text, position, created_at) "
            "VALUES (999, 'Huerfana', 0, '2026-01-05T10:00:00')"
        )

        code, out, _ = self.run_cli("doctor")

        self.assertEqual(code, 1)
        self.assertIn("integrity:    1 broken reference (tasks)\n", out)

    def test_an_index_out_of_date_is_reported_and_heals_on_open(self):
        self.create()
        self.raw(
            "DROP TRIGGER tasks_fts_insert",
            "INSERT INTO tasks (workspace_id, text, position, created_at) "
            "SELECT id, 'Sin indexar', 5, '2026-01-05T10:00:00' FROM workspaces LIMIT 1",
        )
        before = self.digest()

        code, out, _ = self.run_cli("doctor")

        self.assertEqual(code, 0)
        self.assertIn(
            "search index: out of date, it is rebuilt when protas opens the database\n", out
        )
        self.assertEqual(self.digest(), before)

    def test_a_sqlite_without_fts5_has_no_index_to_check(self):
        with mock.patch("protas.db.fts5_available", return_value=False), mock.patch(
            "protas.store.fts5_available", return_value=False
        ):
            self.create()
            code, out, _ = self.run_cli("doctor")
            self.assertEqual(code, 0)
            self.assertIn("search index: not available in this SQLite\n", out)

        code, out, _ = self.run_cli("doctor")
        self.assertEqual(code, 0)
        self.assertIn(
            "search index: missing, it is built when protas opens the database\n", out
        )


if __name__ == "__main__":
    unittest.main()
