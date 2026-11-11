"""Behaviour tests for the provenance of the entries.

An entry that was carried from another day must say so, so the user can
tell what came from yesterday and what was added today.
"""

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from protas.store import Store


def day_offset(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).strftime("%Y-%m-%d")


class OriginTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(path=Path(self.tmp.name) / "protas.db")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_a_new_entry_has_no_origin(self):
        day = self.store.ensure_day(day_offset(0))
        task = self.store.add_task("Nueva", day.id)

        self.assertIsNone(self.store.origin_date(task))
        self.assertEqual(self.store.origin_label(task), "")

    def test_a_carried_entry_says_it_came_from_yesterday(self):
        yesterday = self.store.ensure_day(day_offset(-1))
        self.store.add_task("Pendiente", yesterday.id)

        self.store.rollover(day_offset(0))

        today = self.store.ensure_day(day_offset(0))
        carried = self.store.tasks_of(today.id)[0]

        self.assertEqual(self.store.origin_date(carried), day_offset(-1))
        self.assertEqual(self.store.origin_label(carried), "  (de ayer)")

    def test_an_entry_from_older_days_says_the_date(self):
        old = self.store.ensure_day(day_offset(-5))
        self.store.add_task("Vieja", old.id)

        self.store.rollover(day_offset(0))

        today = self.store.ensure_day(day_offset(0))
        carried = self.store.tasks_of(today.id)[0]

        self.assertEqual(self.store.origin_label(carried), f"  (de {day_offset(-5)})")

    def test_an_entry_added_today_has_no_label(self):
        day = self.store.ensure_day(day_offset(0))
        task = self.store.add_task("Nueva de hoy", day.id)

        self.assertEqual(self.store.origin_label(task, day.date), "")

    def test_the_label_uses_the_day_being_shown(self):
        """Looking at an old day, yesterday means the day before it."""
        day = self.store.ensure_day(day_offset(-3))
        self.store.add_task("Pendiente", day.id)
        self.store.rollover(day_offset(-2))

        shown = self.store.ensure_day(day_offset(-2))
        carried = self.store.tasks_of(shown.id)[0]

        self.assertEqual(self.store.origin_label(carried, shown.date), "  (de ayer)")

    def test_a_project_mention_keeps_its_origin_but_the_interfaces_hide_it(self):
        """A carried mention comes from the previous mention.

        The label is not shown for mentions: the project already says
        everything that matters.
        """
        day = self.store.ensure_day(day_offset(-1))
        task = self.store.add_task("Migrar", day.id)
        project = self.store.promote(task.id, day_id=day.id)

        self.store.rollover(day_offset(0))

        today = self.store.ensure_day(day_offset(0))
        mention = self.store.tasks_of(today.id)[0]

        self.assertTrue(mention.is_mention)
        self.assertEqual(self.store.origin_date(mention), day_offset(-1))


if __name__ == "__main__":
    unittest.main()
