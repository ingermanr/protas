"""Smoke test for the interactive workspace.

The TUI needs a real terminal, so the test drives it through a pty: it
opens the workspace, types a task and leaves.
"""

import os
import pty
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class TuiSmokeTest(unittest.TestCase):
    def test_workspace_opens_and_quits(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "protas.db")
            master, slave = pty.openpty()

            env = dict(os.environ)
            env["TERM"] = "xterm-256color"
            env["PYTHONPATH"] = str(REPO_ROOT)

            proc = subprocess.Popen(
                [sys.executable, "-m", "protas", "--db", db, "tui"],
                stdin=slave,
                stdout=slave,
                stderr=slave,
                cwd=str(REPO_ROOT),
                env=env,
                close_fds=True,
            )
            os.close(slave)

            try:
                time.sleep(1.5)
                os.write(master, b"aTarea de prueba\r")
                time.sleep(0.5)
                os.write(master, b"q")
                proc.wait(timeout=15)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=5)
                os.close(master)

            self.assertEqual(proc.returncode, 0)

            # the task typed in the TUI must be in the database
            sys.path.insert(0, str(REPO_ROOT))
            from protas.store import Store

            store = Store(path=db)
            try:
                day = store.open_day()
                tasks = store.tasks_of(day.id)
                self.assertEqual([t.text for t in tasks], ["Tarea de prueba"])
            finally:
                store.close()

    def test_the_note_of_the_day_is_drawn_above_the_entries(self):
        sys.path.insert(0, str(REPO_ROOT))
        from protas.store import Store
        from protas.tui import _note_lines

        with tempfile.TemporaryDirectory() as tmp:
            store = Store(path=Path(tmp) / "protas.db")
            try:
                day = store.ensure_day("2026-11-11")
                store.set_note(day.id, "Dia tranquilo\nPrioridad: cerrar la migracion")
                day = store.workspace(day.id)

                lines = _note_lines(day)

                self.assertEqual(len(lines), 3)
                self.assertIn("Dia tranquilo", lines[0])
                self.assertIn("Prioridad", lines[1])
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
