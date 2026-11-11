"""Behaviour tests for the statistics."""

import contextlib
import io
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from protas import cli
from protas.store import Store


def day_offset(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).strftime("%Y-%m-%d")


class StatsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(path=Path(self.tmp.name) / "protas.db")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_the_rhythm_counts_the_tasks_completed_each_day(self):
        first = self.store.ensure_day(day_offset(-2))
        second = self.store.ensure_day(day_offset(-1))

        done = self.store.add_task("Hecha", first.id)
        self.store.add_task("Pendiente", second.id)
        self.store.set_done(done.id, True)

        stats = self.store.stats(days=3)

        by_date = {stat.date: stat for stat in stats.window}
        self.assertEqual(by_date[day_offset(-2)].done, 1)
        self.assertEqual(by_date[day_offset(-1)].done, 0)

    def test_a_carried_task_counts_once_in_the_compliance(self):
        """A task that survives three days is one commitment, not three."""
        day = self.store.ensure_day(day_offset(-2))
        self.store.add_task("Pendiente", day.id)

        self.store.rollover(day_offset(-1))
        self.store.rollover(day_offset(0))

        stats = self.store.stats(days=5)

        self.assertEqual(stats.started, 1)
        self.assertEqual(stats.finished, 0)

    def test_completing_a_carried_task_finishes_the_commitment(self):
        day = self.store.ensure_day(day_offset(-2))
        self.store.add_task("Pendiente", day.id)
        self.store.rollover(day_offset(-1))
        self.store.rollover(day_offset(0))

        copied = self.store.tasks_of(self.store.ensure_day(day_offset(0)).id)[0]
        self.store.set_done(copied.id, True)

        stats = self.store.stats(days=5)

        self.assertEqual(stats.started, 1)
        self.assertEqual(stats.finished, 1)

    def test_the_window_only_covers_the_requested_days(self):
        old = self.store.ensure_day(day_offset(-30))
        self.store.add_task("Vieja", old.id)

        stats = self.store.stats(days=7)

        self.assertEqual(len(stats.window), 7)
        self.assertNotIn(day_offset(-30), [stat.date for stat in stats.window])

    def test_the_streak_counts_consecutive_active_days(self):
        for offset in (-2, -1, 0):
            day = self.store.ensure_day(day_offset(offset))
            task = self.store.add_task(f"Trabajo {offset}", day.id)
            self.store.set_done(task.id, True)

        stats = self.store.stats(days=7)

        self.assertEqual(stats.streak, 3)

    def test_the_streak_survives_a_day_without_activity(self):
        """Today just started: the streak is alive until a whole day is missed."""
        for offset in (-2, -1):
            day = self.store.ensure_day(day_offset(offset))
            task = self.store.add_task(f"Trabajo {offset}", day.id)
            self.store.set_done(task.id, True)

        stats = self.store.stats(days=7)

        self.assertEqual(stats.streak, 2)

    def test_the_streak_breaks_after_a_missed_day(self):
        for offset in (-3, -1, 0):
            day = self.store.ensure_day(day_offset(offset))
            task = self.store.add_task(f"Trabajo {offset}", day.id)
            self.store.set_done(task.id, True)

        stats = self.store.stats(days=7)

        self.assertEqual(stats.streak, 2)

    def test_the_project_activity_counts_the_days_it_was_on_the_agenda(self):
        day = self.store.ensure_day(day_offset(-2))
        task = self.store.add_task("Migrar", day.id)
        project = self.store.promote(task.id, day_id=day.id)
        self.store.add_mention(project.id, self.store.ensure_day(day_offset(-1)).id)

        stats = self.store.stats(days=7)

        self.assertEqual(len(stats.projects), 1)
        self.assertEqual(stats.projects[0].days_active, 2)
        self.assertEqual(stats.projects[0].first_day, day_offset(-2))

    def test_a_task_done_the_same_day_it_was_created_counts_as_finished(self):
        day = self.store.ensure_day(day_offset(0))
        task = self.store.add_task("Rápida", day.id)
        self.store.set_done(task.id, True)

        stats = self.store.stats(days=7)

        self.assertEqual(stats.started, 1)
        self.assertEqual(stats.finished, 1)

    def test_the_completion_of_the_project_is_activity(self):
        """Creating the project on one day and working on it the next is
        two consecutive active days."""
        day = self.store.ensure_day(day_offset(-2))
        task = self.store.add_task("Migrar", day.id)
        project = self.store.promote(task.id, day_id=day.id)
        inner = self.store.add_task("Esquema", project.id, day_id=day.id)
        yesterday = self.store.ensure_day(day_offset(-1))

        self.store.set_done(inner.id, True, day_id=yesterday.id)

        stats = self.store.stats(days=7)

        self.assertEqual(stats.streak, 2)

    def test_the_tui_can_draw_the_numbers(self):
        from protas.tui import _stats_lines

        day = self.store.ensure_day(day_offset(0))
        task = self.store.add_task("Algo", day.id)
        self.store.set_done(task.id, True)

        lines = _stats_lines(self.store)

        self.assertTrue(any("Ritmo" in line for line in lines))
        self.assertTrue(any("Racha" in line for line in lines))


class StatsCliTest(unittest.TestCase):
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

    def test_stats_prints_the_sections(self):
        self.run_cli("add", "Algo que hacer", "--date", day_offset(0))

        code, out = self.run_cli("stats")

        self.assertEqual(code, 0)
        self.assertIn("Hoy", out)
        self.assertIn("Ritmo", out)
        self.assertIn("Cumplimiento", out)
        self.assertIn("Proyectos", out)
        self.assertIn("Racha", out)

    def test_stats_json_is_machine_readable(self):
        import json

        self.run_cli("add", "Algo que hacer", "--date", day_offset(0))

        code, out = self.run_cli("stats", "--json")

        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["window_days"], 14)
        self.assertEqual(len(payload["days"]), 14)
        self.assertIn("streak", payload)


if __name__ == "__main__":
    unittest.main()
