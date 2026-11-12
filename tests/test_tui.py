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

    def test_accented_text_typed_in_the_workspace_is_saved(self):
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
                os.write(master, "aDiseño según el año\r".encode("utf-8"))
                time.sleep(0.5)
                os.write(master, b"q")
                proc.wait(timeout=15)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=5)
                os.close(master)

            self.assertEqual(proc.returncode, 0)

            sys.path.insert(0, str(REPO_ROOT))
            from protas.store import Store

            store = Store(path=db)
            try:
                tasks = store.tasks_of(store.open_day().id)
                self.assertEqual([t.text for t in tasks], ["Diseño según el año"])
            finally:
                store.close()

    def test_the_editor_takes_characters_and_key_codes(self):
        sys.path.insert(0, str(REPO_ROOT))
        from protas.tui import Editor, _editor_key

        editor = Editor("Nueva tarea: ", "task")
        for key in ("a", "ñ", "o", "€"):
            self.assertEqual(_editor_key(key, editor), "continue")
        self.assertEqual(editor.buffer, "año€")

        # key codes keep working as before
        self.assertEqual(_editor_key(ord("s"), editor), "continue")
        self.assertEqual(editor.buffer, "año€s")
        self.assertEqual(_editor_key(127, editor), "continue")
        self.assertEqual(_editor_key("\x7f", editor), "continue")
        self.assertEqual(editor.buffer, "año")

        # an arrow is a key code, never the character with the same number
        self.assertEqual(_editor_key(260, editor), "continue")
        self.assertEqual(editor.buffer, "año")

        self.assertEqual(_editor_key("\n", editor), "submit")
        self.assertEqual(_editor_key(10, editor), "submit")
        self.assertEqual(_editor_key("\x1b", editor), "cancel")
        self.assertEqual(_editor_key("\x13", editor), "save")

    def test_the_help_line_names_the_keys_that_exist(self):
        sys.path.insert(0, str(REPO_ROOT))
        from protas.tui import HELP

        for label in (
            "j/k mover",
            "espacio completar",
            "a tarea",
            "A subtarea",
            "p proyecto",
            "e editar",
            "n nota",
            "x borrar",
            "enter abrir",
            "esc volver",
            "←/→ dia",
            "h historia",
            "s numeros",
            "r actualizar",
            "g/G inicio/fin",
            "q salir",
        ):
            self.assertIn(label, HELP)
        # the day is changed with the arrows, not with < and >
        self.assertNotIn("< >", HELP)

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
