"""Several protas opening today at the same time.

The Omarchy panel, the workspace and a command can all reach the same
database within the same second, so opening the day has to give the same
result however many do it at once.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from protas.store import Store
from tests.support import child_env

REPO_ROOT = Path(__file__).resolve().parent.parent
ROUNDS = 12
PROCESSES = 8


class ConcurrentOpenTest(unittest.TestCase):
    def open_today_from_many(self, db):
        env = child_env(PYTHONPATH=str(REPO_ROOT))
        procs = [
            subprocess.Popen(
                [sys.executable, "-m", "protas", "--db", db, "show"],
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
            # communicate() drains and closes both pipes, so the test does
            # not leave file descriptors open behind it.
            _, err = proc.communicate(timeout=60)
            results.append((proc.returncode, err))
        return results

    def test_pending_work_is_carried_once_and_nobody_fails(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            for number in range(ROUNDS):
                db = str(Path(tmp) / f"round-{number}.db")
                store = Store(path=db)
                day = store.ensure_day(yesterday)
                store.add_task("Regar las plantas", day.id)
                project = store.promote(store.add_task("Huerta nueva", day.id).id)
                store.add_task("Semillas", project.id)
                store.close()

                results = self.open_today_from_many(db)

                self.assertEqual(
                    [result for result in results if result != (0, "")], [], f"round {number}"
                )
                store = Store(path=db)
                try:
                    today_tasks = store.tasks_of(store.day(date.today().isoformat()).id)
                    self.assertEqual(
                        sorted(store.title_of(task) for task in today_tasks),
                        ["Huerta nueva", "Regar las plantas"],
                        f"round {number}",
                    )
                finally:
                    store.close()


if __name__ == "__main__":
    unittest.main()
