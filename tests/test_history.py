"""Behaviour tests for the story of a project."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from protas import cli
from protas.store import Store


class HistoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(path=Path(self.tmp.name) / "protas.db")

        self.day = self.store.ensure_day("2026-11-09")
        self.task = self.store.add_task("Migrar la base de datos", self.day.id)
        self.project = self.store.promote(self.task.id, day_id=self.day.id)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def kinds(self, history):
        return [entry.kind for entry in history.entries]

    def test_the_project_starts_with_its_creation(self):
        history = self.store.history(self.project.id)
        self.assertIn("created", self.kinds(history))

    def test_the_day_the_project_was_promoted_is_the_first_day(self):
        history = self.store.history(self.project.id)
        self.assertEqual(history.first_day, "2026-11-09")

    def test_adding_a_task_is_recorded(self):
        self.store.add_task("Esquema nuevo", self.project.id, day_id=self.day.id)

        history = self.store.history(self.project.id)

        added = [e for e in history.entries if e.kind == "task_added"]
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0].text, "Esquema nuevo")
        self.assertEqual(added[0].date, "2026-11-09")

    def test_completing_a_task_is_recorded(self):
        inner = self.store.add_task("Esquema nuevo", self.project.id, day_id=self.day.id)
        later = self.store.ensure_day("2026-11-12")

        self.store.set_done(inner.id, True, day_id=later.id)

        history = self.store.history(self.project.id)
        completed = [e for e in history.entries if e.kind == "task_done"]
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0].date, "2026-11-12")

    def test_reopening_a_task_is_recorded(self):
        inner = self.store.add_task("Esquema nuevo", self.project.id, day_id=self.day.id)
        self.store.set_done(inner.id, True, day_id=self.day.id)

        self.store.set_done(inner.id, False, day_id=self.day.id)

        history = self.store.history(self.project.id)
        self.assertIn("task_undone", self.kinds(history))

    def test_the_event_keeps_the_day_the_user_was_working_from(self):
        """The day of the event is the agenda day, not the clock."""
        later = self.store.ensure_day("2026-11-12")
        self.store.add_task("Esquema nuevo", self.project.id, day_id=later.id)

        history = self.store.history(self.project.id)

        added = [e for e in history.entries if e.kind == "task_added"]
        self.assertEqual(added[0].date, "2026-11-12")

    def test_the_days_the_project_was_on_the_agenda_are_part_of_the_story(self):
        self.store.add_mention(self.project.id, self.store.ensure_day("2026-11-10").id)

        history = self.store.history(self.project.id)

        self.assertIn("mentioned", self.kinds(history))
        self.assertEqual(history.days, ["2026-11-09", "2026-11-10"])

    def test_completing_the_project_is_recorded_once(self):
        inner = self.store.add_task("Esquema nuevo", self.project.id, day_id=self.day.id)
        self.store.set_done(inner.id, True, day_id=self.day.id)

        self.store.set_done(self.store.tasks_of(self.day.id)[0].id, True, day_id=self.day.id)

        history = self.store.history(self.project.id)
        self.assertEqual(self.kinds(history).count("project_completed"), 1)

    def test_the_story_is_ordered_by_day(self):
        later = self.store.ensure_day("2026-11-12")
        self.store.add_task("Tarde", self.project.id, day_id=later.id)
        self.store.add_task("Temprano", self.project.id, day_id=self.day.id)

        history = self.store.history(self.project.id)

        dates = [entry.date for entry in history.entries]
        self.assertEqual(dates, sorted(dates))

    def test_the_story_survives_the_mention_being_deleted(self):
        self.store.delete_task(self.store.tasks_of(self.day.id)[0].id)

        history = self.store.history(self.project.id)

        self.assertIn("created", self.kinds(history))

    def test_an_unknown_project_raises(self):
        with self.assertRaises(ValueError):
            self.store.history(9999)

    def test_the_context_of_a_project_is_the_last_day_it_was_scheduled(self):
        self.store.add_mention(self.project.id, self.store.ensure_day("2026-11-10").id)

        context = self.store.context_day(self.project.id)

        self.assertEqual(self.store.workspace(context).date, "2026-11-10")

    def test_a_project_that_was_never_scheduled_works_from_today(self):
        project = self.store.create_project("Nunca agendado")

        context = self.store.context_day(project.id)

        self.assertEqual(self.store.workspace(context).date, self.store.workspace(context).date)

    def test_the_tui_can_draw_the_story(self):
        from protas.tui import _history_lines

        self.store.add_task("Esquema nuevo", self.project.id, day_id=self.day.id)

        lines = _history_lines(self.store, self.store.workspace(self.project.id))

        self.assertTrue(any("2026-11-09" in line for line in lines))
        self.assertTrue(any("Esquema nuevo" in line for line in lines))


class HistoryCliTest(unittest.TestCase):
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
        return code, out.getvalue()

    def test_history_prints_the_story(self):
        self.run_cli("add", "Migrar la base de datos", "--date", "2026-11-09")
        _, out = self.run_cli("list", "--date", "2026-11-09")
        task_id = int(out.strip().split()[0])
        _, out = self.run_cli("promote", str(task_id))
        project_id = int(out.strip())
        self.run_cli("add", "Esquema nuevo", "--project", str(project_id))

        code, out = self.run_cli("history", str(project_id))

        self.assertEqual(code, 0)
        self.assertIn("creado el proyecto", out)
        self.assertIn("Esquema nuevo", out)
        self.assertIn("2026-11-09", out)

    def test_history_json_is_machine_readable(self):
        import json

        self.run_cli("add", "Migrar la base de datos", "--date", "2026-11-09")
        _, out = self.run_cli("list", "--date", "2026-11-09")
        task_id = int(out.strip().split()[0])
        _, out = self.run_cli("promote", str(task_id))
        project_id = int(out.strip())

        code, out = self.run_cli("history", str(project_id), "--json")

        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["project"], "Migrar la base de datos")
        self.assertTrue(payload["entries"])


if __name__ == "__main__":
    unittest.main()
