"""Priority and estimate: the words, the columns, the order and the copy."""

import tempfile
import unittest
from pathlib import Path

from protas.models import format_estimate, parse_estimate, parse_priority, priority_label
from protas.store import Store


class ModelTest(unittest.TestCase):
    def test_a_priority_is_written_with_its_word(self):
        self.assertEqual(parse_priority("alta"), 1)
        self.assertEqual(parse_priority("Media"), 2)
        self.assertEqual(parse_priority(" BAJA "), 3)
        self.assertEqual(parse_priority("sin prioridad"), None)
        self.assertEqual(parse_priority("ninguna"), None)
        self.assertEqual(parse_priority(""), None)

    def test_a_priority_outside_the_three_is_refused(self):
        for value in ("urgente", "4", "alta media"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_priority(value)

    def test_the_label_goes_back_to_the_word(self):
        self.assertEqual(priority_label(1), "alta")
        self.assertEqual(priority_label(3), "baja")
        self.assertEqual(priority_label(None), "")

    def test_an_estimate_accepts_the_usual_ways_of_writing_time(self):
        for text, minutes in (
            ("30", 30),
            ("30m", 30),
            ("1h", 60),
            ("1h30", 90),
            ("1 h 30 m", 90),
            ("1.5h", 90),
            ("2h", 120),
        ):
            with self.subTest(text=text):
                self.assertEqual(parse_estimate(text), minutes)
        self.assertEqual(parse_estimate("ninguna"), None)
        self.assertEqual(parse_estimate(""), None)

    def test_an_estimate_that_is_not_time_is_refused(self):
        for text in ("0", "0m", "media", "-5"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    parse_estimate(text)

    def test_minutes_are_shown_as_time(self):
        self.assertEqual(format_estimate(30), "30m")
        self.assertEqual(format_estimate(60), "1h")
        self.assertEqual(format_estimate(90), "1h 30m")
        self.assertEqual(format_estimate(None), "")


class StoreDetailsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(path=Path(self.tmp.name) / "protas.db")
        self.addCleanup(self.store.close)
        self.day = self.store.ensure_day("2026-11-10")

    def test_an_entry_without_details_says_nothing(self):
        task = self.store.add_task("Sin nada", self.day.id)

        self.assertIsNone(task.priority)
        self.assertIsNone(task.estimate)
        self.assertEqual(task.details, "")

    def test_add_task_stores_priority_and_estimate(self):
        task = self.store.add_task("Con todo", self.day.id, priority=1, estimate=90)

        stored = self.store.task(task.id)
        self.assertEqual(stored.priority, 1)
        self.assertEqual(stored.estimate, 90)
        self.assertEqual(stored.details, "alta, 1h 30m")

    def test_an_invalid_detail_writes_nothing(self):
        for kwargs in ({"priority": 4}, {"priority": 0}, {"estimate": 0}, {"estimate": -1}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    self.store.add_task("Mala", self.day.id, **kwargs)

        self.assertEqual(self.store.tasks_of(self.day.id), [])

    def test_the_list_puts_the_priorities_first_and_keeps_the_rest_in_order(self):
        none_a = self.store.add_task("sin prioridad A", self.day.id)
        low = self.store.add_task("baja", self.day.id, priority=3)
        none_b = self.store.add_task("sin prioridad B", self.day.id)
        high = self.store.add_task("alta", self.day.id, priority=1)
        medium = self.store.add_task("media", self.day.id, priority=2)

        self.assertEqual(
            [task.id for task in self.store.tasks_of(self.day.id)],
            [high.id, medium.id, low.id, none_a.id, none_b.id],
        )

    def test_without_priorities_the_manual_order_does_not_move(self):
        first = self.store.add_task("primera", self.day.id)
        second = self.store.add_task("segunda", self.day.id)
        third = self.store.add_task("tercera", self.day.id)

        self.assertEqual(
            [task.id for task in self.store.tasks_of(self.day.id)],
            [first.id, second.id, third.id],
        )

    def test_set_details_moves_only_what_it_names(self):
        task = self.store.add_task("Con todo", self.day.id, priority=1, estimate=30)

        self.store.set_details(task.id, estimate=90)
        stored = self.store.task(task.id)
        self.assertEqual((stored.priority, stored.estimate), (1, 90))

        self.store.set_details(task.id, priority=None)
        stored = self.store.task(task.id)
        self.assertEqual((stored.priority, stored.estimate), (None, 90))

    def test_set_details_refuses_an_invalid_value(self):
        task = self.store.add_task("Con todo", self.day.id, priority=1)

        with self.assertRaises(ValueError):
            self.store.set_details(task.id, priority=4)
        with self.assertRaises(ValueError):
            self.store.set_details(task.id, estimate=0)

        self.assertEqual(self.store.task(task.id).priority, 1)
        self.assertIsNone(self.store.task(task.id).estimate)

    def test_set_details_needs_an_existing_entry(self):
        with self.assertRaises(ValueError):
            self.store.set_details(9999, priority=1)

    def test_the_rollover_copies_priority_and_estimate(self):
        task = self.store.add_task("Con todo", self.day.id, priority=2, estimate=45)

        self.store.rollover("2026-11-11")

        tomorrow = self.store.day("2026-11-11")
        copies = self.store.tasks_of(tomorrow.id)
        self.assertEqual([copy.text for copy in copies], ["Con todo"])
        self.assertEqual((copies[0].priority, copies[0].estimate), (2, 45))

    def test_promoting_keeps_the_details_on_the_mention(self):
        task = self.store.add_task("Proyecto", self.day.id, priority=1, estimate=60)

        project = self.store.promote(task.id)

        mention = self.store.task(task.id)
        self.assertEqual(mention.project_id, project.id)
        self.assertEqual((mention.priority, mention.estimate), (1, 60))


if __name__ == "__main__":
    unittest.main()
