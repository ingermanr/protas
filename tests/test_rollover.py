"""Behaviour tests for the rollover of unfinished work to the next day."""

import tempfile
import unittest
from pathlib import Path

from protas.store import Store


class RolloverTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(path=Path(self.tmp.name) / "protas.db")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def day(self, date_str):
        return self.store.ensure_day(date_str)

    def test_pending_tasks_are_copied_to_the_next_day(self):
        day = self.day("2026-11-10")
        self.store.add_task("Pendiente", day.id)
        finished = self.store.add_task("Hecho", day.id)
        self.store.set_done(finished.id, True)

        carried = self.store.rollover("2026-11-11")

        next_day = self.day("2026-11-11")
        self.assertEqual([e.text for e in self.store.tasks_of(next_day.id)], ["Pendiente"])
        self.assertEqual(len(carried), 1)

    def test_the_source_day_keeps_its_history(self):
        day = self.day("2026-11-10")
        self.store.add_task("Pendiente", day.id)

        self.store.rollover("2026-11-11")

        self.assertEqual(len(self.store.tasks_of(day.id)), 1)
        self.assertFalse(self.store.tasks_of(day.id)[0].done)

    def test_rollover_is_idempotent(self):
        day = self.day("2026-11-10")
        self.store.add_task("Pendiente", day.id)

        self.store.rollover("2026-11-11")
        self.store.rollover("2026-11-11")

        next_day = self.day("2026-11-11")
        self.assertEqual(len(self.store.tasks_of(next_day.id)), 1)

    def test_carried_task_keeps_its_origin(self):
        day = self.day("2026-11-10")
        original = self.store.add_task("Pendiente", day.id)

        self.store.rollover("2026-11-11")

        next_day = self.day("2026-11-11")
        self.assertEqual(self.store.tasks_of(next_day.id)[0].origin_id, original.id)

    def test_a_task_travels_one_day_at_a_time(self):
        day = self.day("2026-11-10")
        self.store.add_task("Pendiente", day.id)

        self.store.rollover("2026-11-11")
        self.store.rollover("2026-11-12")

        self.assertEqual(len(self.store.tasks_of(self.day("2026-11-11").id)), 1)
        self.assertEqual(len(self.store.tasks_of(self.day("2026-11-12").id)), 1)

    def test_skipping_days_carries_straight_to_the_opened_day(self):
        day = self.day("2026-11-10")
        self.store.add_task("Pendiente", day.id)

        self.store.rollover("2026-11-13")

        self.assertEqual(
            [e.text for e in self.store.tasks_of(self.day("2026-11-13").id)], ["Pendiente"]
        )

    def test_a_deleted_copy_is_not_resurrected(self):
        day = self.day("2026-11-10")
        self.store.add_task("Pendiente", day.id)
        self.store.rollover("2026-11-11")
        copied = self.store.tasks_of(self.day("2026-11-11").id)[0]
        self.store.delete_task(copied.id)

        self.store.rollover("2026-11-11")

        self.assertEqual(self.store.tasks_of(self.day("2026-11-11").id), [])

    def test_completing_the_copy_stops_the_chain(self):
        day = self.day("2026-11-10")
        self.store.add_task("Pendiente", day.id)
        self.store.rollover("2026-11-11")
        copied = self.store.tasks_of(self.day("2026-11-11").id)[0]
        self.store.set_done(copied.id, True)

        self.store.rollover("2026-11-12")

        self.assertEqual(self.store.tasks_of(self.day("2026-11-12").id), [])

    # ------------------------------------------------------------------
    # projects
    # ------------------------------------------------------------------
    def test_a_project_is_carried_as_a_mention(self):
        day = self.day("2026-11-10")
        task = self.store.add_task("Migrar", day.id)
        project = self.store.promote(task.id)
        self.store.add_task("Esquema", project.id)

        self.store.rollover("2026-11-11")

        entries = self.store.tasks_of(self.day("2026-11-11").id)
        self.assertEqual(len(entries), 1)
        self.assertTrue(entries[0].is_mention)
        self.assertEqual(entries[0].project_id, project.id)

    def test_the_tasks_of_a_project_are_not_duplicated_in_the_day(self):
        day = self.day("2026-11-10")
        task = self.store.add_task("Migrar", day.id)
        project = self.store.promote(task.id)
        self.store.add_task("Esquema", project.id)
        self.store.add_task("Script", project.id)

        self.store.rollover("2026-11-11")

        entries = self.store.tasks_of(self.day("2026-11-11").id)
        self.assertEqual(len(entries), 1)
        self.assertEqual(len(self.store.tasks_of(project.id)), 2)

    def test_a_finished_project_stops_being_carried(self):
        day = self.day("2026-11-10")
        task = self.store.add_task("Migrar", day.id)
        project = self.store.promote(task.id)
        inner = self.store.add_task("Esquema", project.id)
        self.store.set_done(inner.id, True)

        self.store.rollover("2026-11-11")

        self.assertEqual(self.store.tasks_of(self.day("2026-11-11").id), [])

    def test_a_project_with_open_work_keeps_being_carried(self):
        day = self.day("2026-11-10")
        task = self.store.add_task("Migrar", day.id)
        project = self.store.promote(task.id)
        self.store.add_task("Esquema", project.id)

        self.store.rollover("2026-11-11")
        self.store.rollover("2026-11-12")

        self.assertEqual(len(self.store.tasks_of(self.day("2026-11-12").id)), 1)


if __name__ == "__main__":
    unittest.main()
