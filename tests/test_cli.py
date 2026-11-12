"""Behaviour tests for the command line interface."""

import contextlib
import io
import json
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
    # list --json
    # ------------------------------------------------------------------
    def test_list_json_does_not_create_a_missing_day(self):
        code, out = self.run_cli("list", "--date", "2020-01-01", "--json")

        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertIsNone(payload["workspace"]["id"])
        self.assertEqual(payload["workspace"]["date"], "2020-01-01")
        self.assertEqual(payload["counts"], {"total": 0, "done": 0, "open": 0, "projects": 0})
        self.assertEqual(payload["entries"], [])

        from protas.store import Store

        store = Store(path=self.db)
        try:
            self.assertIsNone(store.day("2020-01-01"))
        finally:
            store.close()

    def test_list_json_reports_the_day_with_entries_and_counts(self):
        self.run_cli("note", "Resumen del dia", "--date", "2026-11-11")
        self.run_cli("add", "Pendiente", "--date", "2026-11-11")
        self.run_cli("add", "Terminada", "--date", "2026-11-11")
        _, out = self.run_cli("list", "--date", "2026-11-11")
        second_id = int(out.strip().splitlines()[1].split()[0])
        self.run_cli("done", str(second_id))

        code, out = self.run_cli("list", "--date", "2026-11-11", "--json")

        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["workspace"]["date"], "2026-11-11")
        self.assertEqual(payload["note"], "Resumen del dia")
        self.assertEqual(payload["counts"], {"total": 2, "done": 1, "open": 1, "projects": 0})
        entries = payload["entries"]
        self.assertEqual([entry["text"] for entry in entries], ["Pendiente"])
        self.assertEqual(entries[0]["depth"], 0)
        self.assertFalse(entries[0]["done"])
        self.assertIsNone(entries[0]["origin"])
        self.assertIsNone(entries[0]["progress"])

    def test_list_json_includes_finished_entries_only_with_all(self):
        self.run_cli("add", "Terminada", "--date", "2026-11-11")
        _, out = self.run_cli("list", "--date", "2026-11-11")
        task_id = int(out.strip().split()[0])
        self.run_cli("done", str(task_id))

        _, out = self.run_cli("list", "--date", "2026-11-11", "--json")
        self.assertEqual(json.loads(out)["entries"], [])

        _, out = self.run_cli("list", "--date", "2026-11-11", "--all", "--json")
        entries = json.loads(out)["entries"]
        self.assertEqual([entry["text"] for entry in entries], ["Terminada"])
        self.assertTrue(entries[0]["done"])

    def test_list_json_reports_project_progress_for_a_mention(self):
        self.run_cli("add", "Migrar la base de datos", "--date", "2026-11-11")
        _, out = self.run_cli("list", "--date", "2026-11-11")
        task_id = int(out.strip().split()[0])
        project_id = int(self.run_cli("promote", str(task_id))[1].strip())
        self.run_cli("add", "Esquema", "--project", str(project_id))

        _, out = self.run_cli("list", "--date", "2026-11-11", "--json")

        entries = json.loads(out)["entries"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["project_id"], project_id)
        self.assertEqual(entries[0]["progress"], {"total": 1, "done": 0, "open": 1})

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


    def test_add_with_a_parent_in_a_day_makes_a_project(self):
        _, out = self.run_cli("add", "Preparar el viaje", "--date", "2026-11-11")
        parent_id = out.strip()

        code, out = self.run_cli("add", "Comprar pasajes", "--date", "2026-11-11", "--parent", parent_id)
        self.assertEqual(code, 0)
        self.assertTrue(out.strip().isdigit())

        _, out = self.run_cli("show", "2026-11-11")
        self.assertIn("[ ] Preparar el viaje  (proyecto 0/1)", out)
        self.assertNotIn("Comprar pasajes", out)

        _, out = self.run_cli("projects")
        self.assertIn("Preparar el viaje  (0/1)", out)

    def test_looking_at_a_day_does_not_create_it(self):
        from protas.store import Store

        code, out = self.run_cli("show", "2026-01-05")
        self.assertEqual(code, 0)
        self.assertIn("2026-01-05", out)
        self.assertIn("(no tasks yet)", out)
        self.assertEqual(self.run_cli("list", "--date", "2026-01-06")[0], 0)
        self.assertEqual(self.run_cli("note", "--date", "2026-01-07")[0], 0)

        self.run_cli("add", "Queda", "--date", "2026-01-08")
        self.run_cli("note", "apunte", "--date", "2026-01-09")
        self.run_cli("show", "2026-01-08")
        self.run_cli("show", "2026-01-09")

        store = Store(path=self.db)
        try:
            dates = sorted(day.date for day in store.workspaces("day"))
        finally:
            store.close()
        self.assertEqual(dates, ["2026-01-08", "2026-01-09"])


class InvalidDateTest(unittest.TestCase):
    """A day only exists for a real date written as YYYY-MM-DD."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "protas.db")

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["--db", self.db, *args])
        return code, out.getvalue(), err.getvalue()

    def days(self):
        from protas.store import Store

        store = Store(path=self.db)
        try:
            return sorted(day.date for day in store.workspaces("day"))
        finally:
            store.close()

    def test_commands_refuse_a_date_that_is_not_a_date(self):
        self.run_cli("add", "Pendiente", "--date", "2026-11-10")

        attempts = [
            ("add", "Otra", "--date", "foo"),
            ("show", "mañana"),
            ("list", "--date", "2026-13-40"),
            ("list", "--json", "--date", "2026-13-40"),
            ("note", "texto", "--date", "2026-1-5"),
            ("mention", "1", "--date", "20261111"),
            ("roll", "--to", "foo"),
            ("tui", "foo"),
        ]
        for args in attempts:
            with self.subTest(args=args):
                code, out, err = self.run_cli(*args)
                self.assertEqual(code, 1)
                self.assertEqual(out, "")
                self.assertIn(f"protas: '{args[-1]}' is not a valid date, use YYYY-MM-DD", err)

        # nothing was created and nothing was carried anywhere
        self.assertEqual(self.days(), ["2026-11-10"])

    def test_a_real_date_keeps_working(self):
        code, out, _ = self.run_cli("add", "Vale", "--date", "2024-02-29")
        self.assertEqual(code, 0)
        code, out, _ = self.run_cli("show", "2024-02-29")
        self.assertEqual(code, 0)
        self.assertIn("Vale", out)


if __name__ == "__main__":
    unittest.main()
