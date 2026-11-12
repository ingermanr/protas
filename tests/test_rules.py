"""The rules work on plain rows, with no database."""

import unittest

from protas import rules


def entry(done=0, project_id=None):
    return {"done": done, "project_id": project_id}


def appearance(id, origin_id, day_date):
    return {"id": id, "origin_id": origin_id, "day_date": day_date}


class ProjectStateTest(unittest.TestCase):
    def test_a_project_inside_counts_with_its_live_state(self):
        rows = [entry(done=1), entry(done=0), entry(done=0, project_id=7)]

        counts = rules.project_counts(rows, frozenset({1}), lambda inner: inner == 7)

        self.assertEqual(counts, {"total": 3, "done": 2, "open": 1})

    def test_a_project_already_being_counted_is_not_asked_again(self):
        asked = []
        rows = [entry(done=1, project_id=1), entry(done=0, project_id=1)]

        counts = rules.project_counts(rows, frozenset({1}), asked.append)

        self.assertEqual(asked, [])
        self.assertEqual(counts, {"total": 2, "done": 1, "open": 1})

    def test_a_project_with_tasks_is_done_when_all_of_them_are(self):
        self.assertTrue(rules.project_is_done({"total": 2, "done": 2, "open": 0}, False))
        self.assertFalse(rules.project_is_done({"total": 2, "done": 1, "open": 1}, True))

    def test_a_project_without_tasks_keeps_its_state_on_its_mentions(self):
        empty = {"total": 0, "done": 0, "open": 0}

        self.assertTrue(rules.project_is_done(empty, True))
        self.assertFalse(rules.project_is_done(empty, False))


class LineageTest(unittest.TestCase):
    def test_only_the_newest_appearance_of_a_lineage_travels(self):
        rows = [
            appearance(1, None, "2026-03-01"),
            appearance(2, None, "2026-03-01"),
            appearance(3, 1, "2026-03-02"),
            appearance(4, 3, "2026-03-03"),
        ]

        heads = rules.lineage_heads(rows)

        self.assertEqual([head["id"] for head in heads], [4, 2])

    def test_copies_that_point_at_each_other_do_not_loop(self):
        rows = [appearance(1, 2, "2026-03-01"), appearance(2, 1, "2026-03-02")]

        self.assertEqual([head["id"] for head in rules.lineage_heads(rows)], [2])

    def test_no_rows_no_heads(self):
        self.assertEqual(rules.lineage_heads([]), [])


if __name__ == "__main__":
    unittest.main()
