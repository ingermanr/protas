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

    def test_walking_through_the_days_leaves_no_empty_days(self):
        sys.path.insert(0, str(REPO_ROOT))
        from protas.store import Store, today

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
                # three days forward, a task there, five days back, then out
                for chunk in (b"\x1bOC", b"\x1bOC", b"\x1bOC", b"aPara despues\r",
                              b"\x1bOD", b"\x1bOD", b"\x1bOD", b"\x1bOD", b"\x1bOD", b"q"):
                    os.write(master, chunk)
                    time.sleep(0.3)
                proc.wait(timeout=15)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=5)
                os.close(master)

            self.assertEqual(proc.returncode, 0)

            store = Store(path=db)
            try:
                days = {day.date: len(store.tasks_of(day.id)) for day in store.workspaces("day")}
            finally:
                store.close()
            # today stays, the day that got a task stays, the rest is gone
            self.assertEqual(len(days), 2)
            self.assertEqual(days[today()], 0)
            self.assertEqual(sorted(days.values()), [0, 1])

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

    def test_the_note_editor_edits_any_line(self):
        import curses

        sys.path.insert(0, str(REPO_ROOT))
        from protas.tui import _editor_key, note_editor

        editor = note_editor("uno\ndos\ntres")
        self.assertEqual((editor.lines, editor.row), (["uno", "dos", "tres"], 2))

        # the current line is edited at its end
        _editor_key("!", editor)
        self.assertEqual(editor.lines, ["uno", "dos", "tres!"])

        # the arrows walk the lines and stop at the edges
        for _ in range(5):
            self.assertEqual(_editor_key(curses.KEY_UP, editor), "continue")
        self.assertEqual(editor.row, 0)
        _editor_key(127, editor)
        _editor_key("a", editor)
        self.assertEqual(editor.lines, ["una", "dos", "tres!"])
        for _ in range(5):
            _editor_key(curses.KEY_DOWN, editor)
        self.assertEqual(editor.row, 2)

        # enter opens a line below the current one
        _editor_key(curses.KEY_UP, editor)
        self.assertEqual(_editor_key("\n", editor), "continue")
        self.assertEqual((editor.lines, editor.row), (["una", "dos", "", "tres!"], 2))
        _editor_key("x", editor)

        # backspace empties a line and then removes it
        _editor_key(127, editor)
        _editor_key(127, editor)
        self.assertEqual((editor.lines, editor.row), (["una", "dos", "tres!"], 1))

        # the first line is never removed, only emptied
        _editor_key(curses.KEY_UP, editor)
        for _ in range(6):
            _editor_key(127, editor)
        self.assertEqual((editor.lines, editor.row), (["", "dos", "tres!"], 0))

        self.assertEqual(_editor_key("\x13", editor), "save")
        self.assertEqual(editor.text(), "\ndos\ntres!")
        self.assertEqual(_editor_key("\x1b", editor), "cancel")

    def test_the_line_being_typed_is_part_of_the_saved_note(self):
        sys.path.insert(0, str(REPO_ROOT))
        from protas.tui import _editor_key, note_editor

        editor = note_editor("")
        self.assertEqual((editor.lines, editor.row), ([""], 0))
        for char in "sin enter":
            _editor_key(char, editor)

        self.assertEqual(editor.text(), "sin enter")

        # blank lines left at the end are not saved
        _editor_key("\n", editor)
        _editor_key("\n", editor)
        self.assertEqual(editor.text(), "sin enter")

    def test_the_draft_of_the_note_shows_the_line_being_edited(self):
        sys.path.insert(0, str(REPO_ROOT))
        from protas.tui import _draft_lines, note_editor

        editor = note_editor("uno\ndos")
        self.assertEqual(_draft_lines(editor), [("   uno", False), (" > dos_", True)])

    def test_an_existing_note_is_edited_in_the_workspace(self):
        sys.path.insert(0, str(REPO_ROOT))
        from protas.store import Store

        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "protas.db")
            store = Store(path=db)
            day = store.open_day()
            store.set_note(day.id, "uno\ndos")
            store.close()

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
                # open the note, go up one line, fix it, add a line, save
                for chunk in (b"n", b"\x1bOA", b"!", b"\r", b"medio", b"\x13", b"q"):
                    os.write(master, chunk)
                    time.sleep(0.4)
                proc.wait(timeout=15)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=5)
                os.close(master)

            self.assertEqual(proc.returncode, 0)

            store = Store(path=db)
            try:
                self.assertEqual(store.note(store.open_day().id), "uno!\nmedio\ndos")
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
