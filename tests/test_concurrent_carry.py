"""Regression: many protas carrying at once move each entry exactly once.

Covers the two races fixed on fix/concurrent-open: creating today's day
from several processes (IntegrityError) and copying the pending work from
several processes (duplicated agenda rows).  S1, S2 and S3 of the
concurrency spec.
"""

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from protas.store import Store
from tests.support import child_env

REPO_ROOT = Path(__file__).resolve().parent.parent
PROCESSES = 8
ROUNDS = 20


def run_many(db, *args):
    env = child_env(PYTHONPATH=str(REPO_ROOT))
    procs = [
        subprocess.Popen(
            [sys.executable, "-m", "protas", "--db", db, *args],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            cwd=str(REPO_ROOT),
            env=env,
            text=True,
        )
        for _ in range(PROCESSES)
    ]
    results = []
    for proc in procs:
        _, err = proc.communicate(timeout=120)
        results.append((proc.returncode, err))
    return results


class ConcurrentCarryTest(unittest.TestCase):
    def seed(self, db, yesterday):
        """A pending task, a done task and a project mention with open work."""
        store = Store(path=db)
        try:
            day = store.ensure_day(yesterday)
            store.add_task("Regar las plantas", day.id)
            done = store.add_task("Tarea hecha", day.id)
            store.set_done(done.id, True)
            mention = store.add_task("Huerta nueva", day.id)
            project = store.promote(mention.id)
            store.add_task("Semillas", project.id)
        finally:
            store.close()

    def snapshot(self, db, day_date):
        store = Store(path=db)
        try:
            day = store.day(day_date)
            self.assertIsNotNone(day, "the day must exist after carrying")
            tasks = store.tasks_of(day.id)
            origins = [task.origin_id for task in tasks]
            carries = [
                tuple(row)
                for row in store.conn.execute(
                    "SELECT origin_id, workspace_id FROM carries WHERE workspace_id = ?",
                    (day.id,),
                ).fetchall()
            ]
            return {
                "titles": sorted(store.title_of(task) for task in tasks),
                "duplicates": sorted(
                    {origin for origin in origins if origin is not None and origins.count(origin) > 1}
                ),
                "carries": carries,
                "integrity": store.conn.execute("PRAGMA integrity_check").fetchone()[0],
                "foreign_keys": store.conn.execute("PRAGMA foreign_key_check").fetchall(),
            }
        finally:
            store.close()

    def assert_carried_once(self, db, day_date, label):
        snapshot = self.snapshot(db, day_date)
        self.assertEqual(
            snapshot["titles"], ["Huerta nueva", "Regar las plantas"], label
        )
        self.assertEqual(snapshot["duplicates"], [], label)
        self.assertEqual(len(snapshot["carries"]), 2, label)
        self.assertEqual(len(set(snapshot["carries"])), 2, label)
        self.assertEqual(snapshot["integrity"], "ok", label)
        self.assertEqual(snapshot["foreign_keys"], [], label)

    def test_opening_today_many_times_carries_each_entry_once(self):
        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            for number in range(ROUNDS):
                db = str(Path(tmp) / f"show-{number}.db")
                self.seed(db, yesterday)
                results = run_many(db, "show")
                self.assertEqual(
                    [result for result in results if result != (0, "")], [], f"round {number}"
                )
                self.assert_carried_once(db, today, f"round {number}")

    def test_rolling_many_times_carries_each_entry_once(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            for number in range(ROUNDS):
                db = str(Path(tmp) / f"roll-{number}.db")
                self.seed(db, yesterday)
                results = run_many(db, "roll", "--to", tomorrow)
                self.assertEqual(
                    [result for result in results if result != (0, "")], [], f"round {number}"
                )
                self.assert_carried_once(db, tomorrow, f"round {number}")

    def test_opening_again_adds_nothing(self):
        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "again.db")
            self.seed(db, yesterday)
            first = run_many(db, "show")
            self.assertEqual([r for r in first if r != (0, "")], [])
            before = self.snapshot(db, today)
            second = run_many(db, "show")
            self.assertEqual([r for r in second if r != (0, "")], [])
            after = self.snapshot(db, today)
            self.assertEqual(before, after)

    def test_a_day_whose_work_is_done_carries_nothing(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        today = date.today().isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "done.db")
            store = Store(path=db)
            day = store.ensure_day(yesterday)
            for text in ("A", "B"):
                task = store.add_task(text, day.id)
                store.set_done(task.id, True)
            store.close()
            results = run_many(db, "show")
            self.assertEqual([result for result in results if result != (0, "")], [])
            snapshot = self.snapshot(db, today)
            self.assertEqual(snapshot["titles"], [])
            self.assertEqual(snapshot["carries"], [])

    def test_a_failed_copy_leaves_no_claim_behind(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        today = date.today().isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "failure.db")
            store = Store(path=db)
            day = store.ensure_day(yesterday)
            store.add_task("Pendiente", day.id)
            store.close()

            store = Store(path=db)
            store._copy_entry = lambda *args, **kwargs: (_ for _ in ()).throw(
                sqlite3.OperationalError("simulated copy failure")
            )
            with self.assertRaises(sqlite3.OperationalError):
                store.rollover(today)
            store.close()  # what the CLI does on the way out

            store = Store(path=db)
            try:
                day = store.day(today)
                carries = store.conn.execute(
                    "SELECT COUNT(*) FROM carries WHERE workspace_id = ?", (day.id,)
                ).fetchone()[0]
                self.assertEqual(carries, 0)
            finally:
                store.close()

            store = Store(path=db)
            try:
                day = store.open_day(today)
                self.assertEqual(
                    sorted(store.title_of(task) for task in store.tasks_of(day.id)),
                    ["Pendiente"],
                )
                carries = store.conn.execute(
                    "SELECT COUNT(*) FROM carries WHERE workspace_id = ?", (day.id,)
                ).fetchone()[0]
                self.assertEqual(carries, 1)
            finally:
                store.close()

    def test_a_pending_recurring_task_is_carried_once_and_not_spawned_again(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        today = date.today().isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            for number in range(ROUNDS // 2):
                db = str(Path(tmp) / f"recur-{number}.db")
                store = Store(path=db)
                store.add_recurrence("Regar", "day")
                store.spawn_recurring(yesterday)
                store.close()
                results = run_many(db, "show")
                self.assertEqual(
                    [result for result in results if result != (0, "")], [], f"round {number}"
                )
                snapshot = self.snapshot(db, today)
                self.assertEqual(snapshot["titles"], ["Regar"], f"round {number}")
                self.assertEqual(len(snapshot["carries"]), 1, f"round {number}")


if __name__ == "__main__":
    unittest.main()
