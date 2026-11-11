"""Behaviour tests for the command line interface."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from protas import cli


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "protas.db")

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        buffer = io.StringIO()
        errors = io.StringIO()
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(errors):
            code = cli.main(["--db", self.db, *args])
        return code, buffer.getvalue()

    def test_show_prints_the_workspace_with_the_date_as_title(self):
        code, out = self.run_cli("show", "2026-11-11")
        self.assertEqual(code, 0)
        self.assertIn("2026-11-11", out)

    def test_add_then_show_lists_the_task(self):
        self.run_cli("add", "Escribir la propuesta", "--date", "2026-11-11")

        code, out = self.run_cli("show", "2026-11-11")

        self.assertEqual(code, 0)
        self.assertIn("Escribir la propuesta", out)
        self.assertIn("[ ]", out)

    def test_done_marks_the_task(self):
        self.run_cli("add", "Escribir la propuesta", "--date", "2026-11-11")
        _, out = self.run_cli("list", "--date", "2026-11-11")
        task_id = int(out.strip().split()[0])

        self.run_cli("done", str(task_id))

        _, out = self.run_cli("show", "2026-11-11")
        self.assertIn("[x]", out)

    def test_unknown_task_returns_an_error(self):
        code, _ = self.run_cli("done", "9999")
        self.assertEqual(code, 1)

    def test_roll_carries_yesterday_into_today(self):
        self.run_cli("add", "Pendiente", "--date", "2026-11-10")

        code, out = self.run_cli("roll", "--to", "2026-11-11")

        self.assertEqual(code, 0)
        self.assertIn("Pendiente", out)

    def test_note_is_stored_and_shown(self):
        self.run_cli("note", "Resumen del dia", "--date", "2026-11-11")

        _, out = self.run_cli("show", "2026-11-11")

        self.assertIn("Resumen del dia", out)

    def test_export_writes_a_markdown_file_per_day(self):
        self.run_cli("add", "Pendiente", "--date", "2026-11-11")
        out_dir = Path(self.tmp.name) / "export"

        code, _ = self.run_cli("export", "--out", str(out_dir))

        self.assertEqual(code, 0)
        exported = out_dir / "2026-11-11.md"
        self.assertTrue(exported.exists())
        self.assertIn("Pendiente", exported.read_text())

    # ------------------------------------------------------------------
    # projects
    # ------------------------------------------------------------------
    def test_promote_turns_a_task_into_a_project(self):
        self.run_cli("add", "Migrar la base de datos", "--date", "2026-11-11")
        _, out = self.run_cli("list", "--date", "2026-11-11")
        task_id = int(out.strip().split()[0])

        code, out = self.run_cli("promote", str(task_id))

        self.assertEqual(code, 0)
        project_id = int(out.strip())
        _, out = self.run_cli("show", "--project", str(project_id))
        self.assertIn("Migrar la base de datos", out)

    def test_the_day_shows_the_project_as_a_mention(self):
        self.run_cli("add", "Migrar la base de datos", "--date", "2026-11-11")
        _, out = self.run_cli("list", "--date", "2026-11-11")
        task_id = int(out.strip().split()[0])
        project_id = int(self.run_cli("promote", str(task_id))[1].strip())

        self.run_cli("add", "Esquema", "--project", str(project_id))

        _, out = self.run_cli("show", "2026-11-11")
        self.assertIn("Migrar la base de datos", out)
        self.assertIn("proyecto 0/1", out)

    def test_projects_lists_every_project_once(self):
        self.run_cli("add", "Migrar la base de datos", "--date", "2026-11-11")
        _, out = self.run_cli("list", "--date", "2026-11-11")
        task_id = int(out.strip().split()[0])
        self.run_cli("promote", str(task_id))
        self.run_cli("roll", "--to", "2026-11-12")

        _, out = self.run_cli("projects")

        self.assertEqual(out.count("Migrar la base de datos"), 1)

    def test_a_project_can_be_added_to_another_day(self):
        self.run_cli("add", "Migrar la base de datos", "--date", "2026-11-11")
        _, out = self.run_cli("list", "--date", "2026-11-11")
        task_id = int(out.strip().split()[0])
        project_id = int(self.run_cli("promote", str(task_id))[1].strip())

        code, _ = self.run_cli("mention", str(project_id), "--date", "2026-11-12")

        self.assertEqual(code, 0)
        _, out = self.run_cli("show", "2026-11-12")
        self.assertIn("Migrar la base de datos", out)


if __name__ == "__main__":
    unittest.main()
