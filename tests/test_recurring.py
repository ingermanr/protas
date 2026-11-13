"""Behaviour tests for recurring tasks."""

import contextlib
import io
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from protas import cli, rules
from protas.store import Store, today

MONDAY = "2026-03-02"
TUESDAY = "2026-03-03"
WEDNESDAY = "2026-03-04"
THURSDAY = "2026-03-05"


class PatternTest(unittest.TestCase):
    def test_the_three_patterns_are_understood(self):
        self.assertEqual(rules.parse_recurrence("day"), "daily")
        self.assertEqual(rules.parse_recurrence("Diario"), "daily")
        self.assertEqual(rules.parse_recurrence("lun,jue"), "weekly:0,3")
        self.assertEqual(rules.parse_recurrence("thu, mon, mon"), "weekly:0,3")
        self.assertEqual(rules.parse_recurrence("sábado"), "weekly:5")
        self.assertEqual(rules.parse_recurrence("15"), "monthly:15")

    def test_anything_else_is_refused(self):
        for spec in ("", "cada 3 dias", "0", "32", "lun,xyz", "3d", "\u00b2", "\u0663"):
            with self.assertRaises(ValueError, msg=spec):
                rules.parse_recurrence(spec)

    def test_a_pattern_fires_on_the_days_it_names(self):
        monday, tuesday = date(2026, 3, 2), date(2026, 3, 3)
        self.assertTrue(rules.recurrence_fires("daily", tuesday))
        self.assertTrue(rules.recurrence_fires("weekly:0,3", monday))
        self.assertFalse(rules.recurrence_fires("weekly:0,3", tuesday))
        self.assertTrue(rules.recurrence_fires("monthly:15", date(2026, 3, 15)))
        self.assertFalse(rules.recurrence_fires("monthly:15", date(2026, 3, 14)))

    def test_a_day_the_month_does_not_have_fires_on_its_last_day(self):
        self.assertTrue(rules.recurrence_fires("monthly:31", date(2026, 2, 28)))
        self.assertFalse(rules.recurrence_fires("monthly:31", date(2026, 2, 27)))
        self.assertTrue(rules.recurrence_fires("monthly:31", date(2026, 3, 31)))
        self.assertFalse(rules.recurrence_fires("monthly:31", date(2026, 3, 30)))

    def test_a_pattern_is_described_in_words(self):
        self.assertEqual(rules.describe_recurrence("daily"), "cada día")
        self.assertEqual(rules.describe_recurrence("weekly:0,3"), "lunes y jueves")
        self.assertEqual(rules.describe_recurrence("weekly:0,2,4"), "lunes, miércoles y viernes")
        self.assertEqual(rules.describe_recurrence("monthly:15"), "el día 15 de cada mes")


class RecurringCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = str(Path(self.tmp.name) / "protas.db")
        self.store = Store(path=self.db)
        self.addCleanup(self.store.close)

    def live(self, day):
        """Open ``day`` as if it were today: carry first, then spawn."""
        self.store.rollover(day)
        self.store.spawn_recurring(day)
        return self.store.day(day)

    def texts(self, day):
        workspace = self.store.day(day)
        if workspace is None:
            return []
        return [task.text for task in self.store.tasks_of(workspace.id)]


class SpawnTest(RecurringCase):
    def test_a_rule_puts_its_task_in_the_day_it_fires(self):
        self.store.add_recurrence("Regar las plantas", "lun,jue")

        self.live(MONDAY)
        self.live(TUESDAY)

        self.assertEqual(self.texts(MONDAY), ["Regar las plantas"])
        self.assertEqual(self.texts(TUESDAY), ["Regar las plantas"])  # carried, S1
        task = self.store.tasks_of(self.store.day(MONDAY).id)[0]
        self.assertFalse(self.store.is_done(task))

    def test_opening_the_day_again_does_not_spawn_again(self):
        self.store.add_recurrence("Regar las plantas", "day")

        self.live(MONDAY)
        self.live(MONDAY)

        self.assertEqual(self.texts(MONDAY), ["Regar las plantas"])

    def test_a_day_the_rule_does_not_name_gets_nothing(self):
        self.store.add_recurrence("Regar las plantas", "jue")

        self.live(MONDAY)

        self.assertEqual(self.texts(MONDAY), [])

    def test_a_pending_task_is_carried_and_no_new_one_is_born(self):
        self.store.add_recurrence("Regar las plantas", "day")

        self.live(MONDAY)
        self.live(TUESDAY)
        self.live(WEDNESDAY)

        self.assertEqual(self.texts(TUESDAY), ["Regar las plantas"])
        self.assertEqual(self.texts(WEDNESDAY), ["Regar las plantas"])

    def test_once_it_is_done_the_next_day_gets_a_new_one(self):
        self.store.add_recurrence("Regar las plantas", "day")
        self.live(MONDAY)
        tuesday = self.live(TUESDAY)
        carried = self.store.tasks_of(tuesday.id)[0]
        self.store.set_done(carried.id)

        wednesday = self.live(WEDNESDAY)

        tasks = self.store.tasks_of(wednesday.id)
        self.assertEqual([task.text for task in tasks], ["Regar las plantas"])
        self.assertFalse(self.store.is_done(tasks[0]))
        self.assertIsNone(tasks[0].origin_id)

    def test_days_that_were_never_opened_leave_no_backlog(self):
        self.store.add_recurrence("Regar las plantas", "day")

        self.live(THURSDAY)

        self.assertEqual(self.texts(THURSDAY), ["Regar las plantas"])
        self.assertEqual(
            [day.date for day in self.store.workspaces("day")], [THURSDAY]
        )

    def test_a_task_that_was_deleted_does_not_come_back_that_day(self):
        self.store.add_recurrence("Regar las plantas", "day")
        monday = self.live(MONDAY)
        self.store.delete_task(self.store.tasks_of(monday.id)[0].id)

        self.live(MONDAY)

        self.assertEqual(self.texts(MONDAY), [])

    def test_only_today_spawns_when_a_day_is_opened(self):
        self.store.add_recurrence("Regar las plantas", "day")

        self.store.open_day(MONDAY)
        self.assertEqual(self.texts(MONDAY), [])

        self.store.open_day()
        self.assertEqual(self.texts(today()), ["Regar las plantas"])

    def test_two_protas_opening_the_day_at_once_spawn_one_task(self):
        self.store.add_recurrence("Regar las plantas", "day")
        other = Store(path=self.db)
        self.addCleanup(other.close)
        add_task = self.store.add_task

        def add_while_the_other_opens(*args, **kwargs):
            # The other protas reaches the same rule in the middle of this one.
            other.spawn_recurring(MONDAY)
            return add_task(*args, **kwargs)

        self.store.add_task = add_while_the_other_opens
        self.store.spawn_recurring(MONDAY)

        self.assertEqual(self.texts(MONDAY), ["Regar las plantas"])

    def test_two_rules_each_get_their_task(self):
        self.store.add_recurrence("Regar las plantas", "day")
        self.store.add_recurrence("Revisar el correo", "lun")

        self.live(MONDAY)

        self.assertEqual(self.texts(MONDAY), ["Regar las plantas", "Revisar el correo"])


class RulesTest(RecurringCase):
    def test_rules_are_added_listed_and_removed(self):
        first = self.store.add_recurrence("Regar las plantas", "lun,jue")
        second = self.store.add_recurrence("Pagar el alquiler", "5")

        listed = self.store.recurrences()
        self.assertEqual(
            [(rule.id, rule.text, rule.pattern) for rule in listed],
            [(first.id, "Regar las plantas", "weekly:0,3"), (second.id, "Pagar el alquiler", "monthly:5")],
        )

        self.store.remove_recurrence(first.id)
        self.assertEqual([rule.id for rule in self.store.recurrences()], [second.id])

    def test_removing_a_rule_keeps_the_tasks_it_made(self):
        rule = self.store.add_recurrence("Regar las plantas", "day")
        self.live(MONDAY)

        self.store.remove_recurrence(rule.id)
        self.live(TUESDAY)

        self.assertEqual(self.texts(MONDAY), ["Regar las plantas"])
        self.assertEqual(self.texts(TUESDAY), ["Regar las plantas"])  # still carried
        self.store.set_done(self.store.tasks_of(self.store.day(TUESDAY).id)[0].id)
        self.live(WEDNESDAY)
        self.assertEqual(self.texts(WEDNESDAY), [])

    def test_a_rule_needs_a_text_and_a_known_pattern_and_an_existing_id(self):
        with self.assertRaises(ValueError):
            self.store.add_recurrence("   ", "day")
        with self.assertRaises(ValueError):
            self.store.add_recurrence("Regar", "cada 3 dias")
        with self.assertRaises(ValueError):
            self.store.remove_recurrence(99)
        self.assertEqual(self.store.recurrences(), [])


class RecurCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = str(Path(self.tmp.name) / "protas.db")

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["--db", self.db, *args])
        return code, out.getvalue(), err.getvalue()

    def test_add_list_and_rm(self):
        code, out, _ = self.run_cli("recur", "add", "Regar las plantas", "--every", "lun,jue")
        self.assertEqual((code, out), (0, "1\n"))
        self.run_cli("recur", "add", "Pagar el alquiler", "--every", "5")

        code, out, _ = self.run_cli("recur", "list")
        self.assertEqual(code, 0)
        self.assertEqual(
            out,
            "1  lunes y jueves  Regar las plantas\n"
            "2  el día 5 de cada mes  Pagar el alquiler\n",
        )
        self.assertEqual(self.run_cli("recur")[1], out)

        code, _, _ = self.run_cli("recur", "rm", "1")
        self.assertEqual(code, 0)
        self.assertEqual(
            self.run_cli("recur", "list")[1], "2  el día 5 de cada mes  Pagar el alquiler\n"
        )

    def test_list_as_json(self):
        self.run_cli("recur", "add", "Regar las plantas", "--every", "day")

        code, out, _ = self.run_cli("recur", "list", "--json")

        self.assertEqual(code, 0)
        self.assertEqual(
            json.loads(out),
            [{"id": 1, "text": "Regar las plantas", "pattern": "daily", "every": "cada día"}],
        )

    def test_an_empty_list_says_so(self):
        code, out, _ = self.run_cli("recur", "list")
        self.assertEqual((code, out), (0, "no hay tareas recurrentes\n"))

    def test_mistakes_are_reported_and_change_nothing(self):
        code, _, err = self.run_cli("recur", "add", "Regar", "--every", "cada 3 dias")
        self.assertEqual(code, 1)
        self.assertIn("protas:", err)

        code, _, err = self.run_cli("recur", "rm", "99")
        self.assertEqual(code, 1)
        self.assertIn("99", err)

        self.assertEqual(self.run_cli("recur", "list")[1], "no hay tareas recurrentes\n")

    def test_the_task_shows_up_when_today_is_opened(self):
        self.run_cli("recur", "add", "Regar las plantas", "--every", "day")

        code, out, _ = self.run_cli("show")

        self.assertEqual(code, 0)
        self.assertIn("[ ] Regar las plantas", out)


if __name__ == "__main__":
    unittest.main()
