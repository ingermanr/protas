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
from tests.support import child_env

REPO_ROOT = Path(__file__).resolve().parent.parent


class TuiSmokeTest(unittest.TestCase):
    def test_workspace_opens_and_quits(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "protas.db")
            master, slave = pty.openpty()

            env = child_env()
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

            env = child_env()
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
            env = child_env()
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

    def test_the_help_screen_lists_every_key(self):
        sys.path.insert(0, str(REPO_ROOT))
        from protas.tui import HELP, _help_lines

        lines = _help_lines()
        text = "\n".join(lines)
        for key in ("j / k", "g / G", "espacio", "enter", "a", "A", "p", "e / ! / E", "x", "n",
                    "h / s / R", "r", "←  / →", "esc", "?", "q"):
            self.assertTrue(
                any(line.strip().startswith(key + "  ") for line in lines), f"{key!r} in\n{text}"
            )
        # short enough to be read on a small terminal
        self.assertLessEqual(len(lines), 20)
        self.assertLessEqual(max(len(line) for line in lines), 78)
        # and the footer says how to get there before anything can be cut
        self.assertTrue(HELP.startswith("? ayuda | "))

    def test_the_question_mark_opens_the_help_screen(self):
        import select

        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "protas.db")
            master, slave = pty.openpty()
            env = child_env()
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

            def screen():
                data = b""
                while select.select([master], [], [], 0.5)[0]:
                    data += os.read(master, 65536)
                return data.decode("utf-8", "replace")

            try:
                time.sleep(1.5)
                before = screen()
                os.write(master, b"?")
                opened = screen()
                os.write(master, b"\x1b")
                time.sleep(0.3)
                os.write(master, b"aDespues de la ayuda\r")
                time.sleep(0.5)
                os.write(master, b"q")
                proc.wait(timeout=15)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=5)
                os.close(master)

            self.assertEqual(proc.returncode, 0)
            self.assertNotIn("completar o reabrir", before)
            self.assertIn("completar o reabrir", opened)

            sys.path.insert(0, str(REPO_ROOT))
            from protas.store import Store

            store = Store(path=db)
            try:
                tasks = store.tasks_of(store.open_day().id)
                self.assertEqual([t.text for t in tasks], ["Despues de la ayuda"])
            finally:
                store.close()

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
            env = child_env()
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

    def test_the_help_line_wraps_instead_of_being_cut_by_a_narrow_window(self):
        import curses

        sys.path.insert(0, str(REPO_ROOT))
        from protas.store import Store
        from protas.tui import HELP, _draw

        class Screen:
            """The part of a curses window that _draw uses."""

            def __init__(self, height, width):
                self.height = height
                self.width = width
                self.rows: dict[int, str] = {}

            def erase(self):
                self.rows = {}

            def getmaxyx(self):
                return self.height, self.width

            def addstr(self, y, x, text, *attributes):
                if y == self.height - 1 and x + len(text) >= self.width:
                    raise curses.error("writing the bottom right corner")
                self.rows[y] = self.rows.get(y, "")[:x].ljust(x) + text

            def hline(self, y, x, character, count):
                self.addstr(y, x, character * count)

            def refresh(self):
                pass

            def text(self):
                return "\n".join(line.rstrip() for line in self.rows.values())

        with tempfile.TemporaryDirectory() as tmp:
            store = Store(path=Path(tmp) / "protas.db")
            try:
                day = store.open_day("2026-11-11")
                for width in (60, 40, 24):
                    screen = Screen(height=24, width=width)
                    _draw(screen, store, day, [], 0, "", None)

                    drawn = screen.text()
                    for segment in HELP.split(" | "):
                        self.assertIn(segment, drawn, f"{segment!r} is missing at width {width}")
                    for line in screen.rows.values():
                        self.assertLessEqual(len(line), width - 1)
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


class TuiSearchTest(unittest.TestCase):
    """Searching inside the workspace and walking to a result."""

    def setUp(self):
        sys.path.insert(0, str(REPO_ROOT))
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "protas.db")

    def tearDown(self):
        self.tmp.cleanup()

    def drive(self, steps):
        """Run the workspace in a pty, typing ``steps`` and reading the screen.

        Returns the exit code and what the screen showed after each step.
        """
        import select

        master, slave = pty.openpty()
        env = child_env()
        env["TERM"] = "xterm-256color"
        env["PYTHONPATH"] = str(REPO_ROOT)
        proc = subprocess.Popen(
            [sys.executable, "-m", "protas", "--db", self.db, "tui"],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            cwd=str(REPO_ROOT),
            env=env,
            close_fds=True,
        )
        os.close(slave)

        def screen():
            data = b""
            while select.select([master], [], [], 0.5)[0]:
                data += os.read(master, 65536)
            return data.decode("utf-8", "replace")

        screens = []
        try:
            time.sleep(1.5)
            screen()
            for step in steps:
                os.write(master, step)
                screens.append(screen())
            os.write(master, b"q")
            proc.wait(timeout=15)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
            os.close(master)
        return proc.returncode, screens

    def test_search_lines_name_the_date_the_kind_and_the_matching_text(self):
        from protas.models import Hit
        from protas.tui import _search_lines

        lines = _search_lines(
            [
                Hit("task", "2026-03-02", "Calibrar el zorzal", 7),
                Hit("note", "2026-03-01", "Lunes\nEl zorzal canta temprano"),
                Hit("project", "", "Zorzal en el jardin"),
            ],
            "zorzal",
        )

        self.assertEqual(len(lines), 3)
        self.assertIn("2026-03-02", lines[0])
        self.assertIn("tarea", lines[0])
        self.assertIn("Calibrar el zorzal", lines[0])
        self.assertIn("nota", lines[1])
        self.assertIn("El zorzal canta temprano", lines[1])
        self.assertNotIn("Lunes", lines[1])
        self.assertIn("proyecto", lines[2])

    def test_a_result_is_opened_in_its_day_with_the_task_selected(self):
        from protas.store import Store

        # Finished entries stay in their day: pending ones would be carried
        # to today and found there too.
        store = Store(path=self.db)
        day = store.open_day("2026-03-02")
        store.set_done(store.add_task("Regar las plantas", day.id).id)
        target = store.add_task("Calibrar el zorzal", day.id)
        store.set_done(target.id)
        store.close()

        # Enter opens the day on the result, so the space reopens that entry.
        code, screens = self.drive([b"/zorzal\r", b"\r", b" "])

        self.assertEqual(code, 0)
        self.assertIn("Calibrar el zorzal", screens[0])
        self.assertIn("2026-03-02", screens[0])
        self.assertNotIn("Regar las plantas", screens[0])
        self.assertIn("Regar las plantas", screens[1])

        store = Store(path=self.db)
        try:
            done = {task.text: store.is_done(task) for task in store.tasks_of(day.id)}
            self.assertEqual(
                done, {"Regar las plantas": True, "Calibrar el zorzal": False}
            )
            self.assertFalse(store.is_done(store.task(target.id)))
        finally:
            store.close()

    def test_the_results_are_walked_with_the_keys_and_left_with_escape(self):
        from protas.store import Store, today

        store = Store(path=self.db)
        first = store.open_day("2026-03-02")
        store.set_done(store.add_task("Zorzal uno", first.id).id)
        second = store.open_day("2026-03-05")
        store.set_done(store.add_task("Zorzal dos", second.id).id)
        store.add_task("Tarea de hoy", store.open_day().id)
        store.close()

        # Escape leaves the results: the space lands on today's own entry.
        code, _ = self.drive([b"/zorzal\r", b"\x1b", b" "])
        self.assertEqual(code, 0)

        # Results come newest first: j moves to the older one, enter opens it.
        code, _ = self.drive([b"/zorzal\r", b"j", b"\r", b" "])
        self.assertEqual(code, 0)

        store = Store(path=self.db)
        try:
            state = {
                task.text: store.is_done(task)
                for day in (first, second, store.day(today()))
                for task in store.tasks_of(day.id)
            }
            self.assertEqual(
                state, {"Zorzal uno": False, "Zorzal dos": True, "Tarea de hoy": True}
            )
        finally:
            store.close()

    def test_a_search_without_results_says_so_and_stays_in_the_day(self):
        code, screens = self.drive([b"/zorzal\r", b"aSigo en el dia\r"])

        self.assertEqual(code, 0)
        self.assertIn("sin resultados", screens[0])

        from protas.store import Store

        store = Store(path=self.db)
        try:
            tasks = store.tasks_of(store.open_day().id)
            self.assertEqual([task.text for task in tasks], ["Sigo en el dia"])
        finally:
            store.close()

    def test_the_help_names_the_search_key(self):
        from protas.tui import HELP, _help_lines

        self.assertIn("/ buscar", HELP)
        self.assertTrue(any(line.strip().startswith("/  ") for line in _help_lines()))
        self.assertLessEqual(len(_help_lines()), 20)


class TuiDetailsTest(unittest.TestCase):
    """Priority and estimate from the workspace keys."""

    def setUp(self):
        sys.path.insert(0, str(REPO_ROOT))
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "protas.db")

    def tearDown(self):
        self.tmp.cleanup()

    def drive(self, steps):
        import select

        master, slave = pty.openpty()
        env = child_env()
        env["TERM"] = "xterm-256color"
        env["PYTHONPATH"] = str(REPO_ROOT)
        proc = subprocess.Popen(
            [sys.executable, "-m", "protas", "--db", self.db, "tui"],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            cwd=str(REPO_ROOT),
            env=env,
            close_fds=True,
        )
        os.close(slave)

        def screen():
            data = b""
            while select.select([master], [], [], 0.5)[0]:
                data += os.read(master, 65536)
            return data.decode("utf-8", "replace")

        screens = []
        try:
            time.sleep(1.5)
            screen()
            for step in steps:
                os.write(master, step)
                screens.append(screen())
            os.write(master, b"q")
            proc.wait(timeout=15)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
            os.close(master)
        return proc.returncode, screens

    def add_task(self, text, **details):
        from protas.store import Store

        store = Store(path=self.db)
        try:
            day = store.open_day()
            return store.add_task(text, day.id, **details).id
        finally:
            store.close()

    def read(self, task_id):
        from protas.store import Store

        store = Store(path=self.db)
        try:
            return store.task(task_id)
        finally:
            store.close()

    def test_the_bang_sets_a_priority_and_the_screen_shows_the_details(self):
        task_id = self.add_task("Comprar pan", estimate=60)

        code, screens = self.drive([b"!"])

        self.assertEqual(code, 0)
        self.assertIn("alta, 1h)", screens[0])
        task = self.read(task_id)
        self.assertEqual(task.priority, 1)
        self.assertEqual(task.estimate, 60)

    def test_the_bang_goes_through_the_three_and_back_to_none(self):
        task_id = self.add_task("Comprar pan")

        code, screens = self.drive([b"!", b"!", b"!", b"!"])

        self.assertEqual(code, 0)
        self.assertIn("alta", screens[0])
        self.assertIn("media", screens[1])
        self.assertIn("baja", screens[2])
        self.assertIn("sin prioridad", screens[3])
        self.assertIsNone(self.read(task_id).priority)

    def test_the_bang_keeps_the_selection_on_the_same_task(self):
        first_id = self.add_task("Comprar pan")
        second_id = self.add_task("Llamar a mama")

        code, _ = self.drive([b"j", b"!", b"!"])

        self.assertEqual(code, 0)
        self.assertEqual(self.read(second_id).priority, 2)
        self.assertIsNone(self.read(first_id).priority)

    def test_an_empty_estimate_editor_clears_the_estimate(self):
        task_id = self.add_task("Comprar pan", estimate=45)

        code, _ = self.drive([b"E", b"\x7f\x7f\x7f\r"])

        self.assertEqual(code, 0)
        self.assertIsNone(self.read(task_id).estimate)

    def test_shift_e_edits_the_estimate(self):
        task_id = self.add_task("Comprar pan", priority=2)

        code, screens = self.drive([b"E", b"1h30\r"])

        self.assertEqual(code, 0)
        self.assertIn("Estimacion", screens[0])
        task = self.read(task_id)
        self.assertEqual(task.estimate, 90)
        self.assertEqual(task.priority, 2)

    def test_the_estimate_editor_receives_the_current_value(self):
        task_id = self.add_task("Comprar pan", estimate=45)

        code, screens = self.drive([b"E", b"\r"])

        self.assertEqual(code, 0)
        self.assertIn("45m", screens[0])
        self.assertEqual(self.read(task_id).estimate, 45)


class TuiRecurringTest(unittest.TestCase):
    """The recurring rules from the TUI: R lists them, a adds, x removes."""

    def setUp(self):
        sys.path.insert(0, str(REPO_ROOT))
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "protas.db")

    def tearDown(self):
        self.tmp.cleanup()

    drive = TuiDetailsTest.drive

    def store(self):
        from protas.store import Store

        return Store(path=self.db)

    def add_rule(self, text, every):
        store = self.store()
        try:
            return store.add_recurrence(text, every).id
        finally:
            store.close()

    def rules(self):
        store = self.store()
        try:
            return [(rule.text, rule.pattern) for rule in store.recurrences()]
        finally:
            store.close()

    def today_texts(self):
        store = self.store()
        try:
            day = store.open_day()
            return [task.text for task in store.tasks_of(day.id)]
        finally:
            store.close()

    def test_shift_r_lists_the_rules_and_goes_back(self):
        self.add_rule("Regar las plantas", "lun,jue")

        code, screens = self.drive([b"R", b"R"])

        self.assertEqual(code, 0)
        self.assertIn("Recurrentes", screens[0])
        self.assertIn("Regar las plantas", screens[0])
        self.assertIn("lunes y jueves", screens[0])
        self.assertNotIn("Recurrentes", screens[1])

    def test_without_rules_the_view_says_so(self):
        code, screens = self.drive([b"R"])

        self.assertEqual(code, 0)
        self.assertIn("no hay tareas recurrentes", screens[0])

    def test_a_asks_the_text_then_the_frequency(self):
        code, screens = self.drive([b"R", b"a", b"Pagar el alquiler\r", b"5\r"])

        self.assertEqual(code, 0)
        self.assertIn("Cada", screens[2])
        self.assertEqual(self.rules(), [("Pagar el alquiler", "monthly:5")])
        self.assertIn("Pagar el alquiler", screens[3])

    def test_a_frequency_that_is_not_one_is_refused(self):
        code, screens = self.drive([b"R", b"a", b"Algo\r", b"nunca\r"])

        self.assertEqual(code, 0)
        self.assertIn("no entiendo", screens[3])
        self.assertEqual(self.rules(), [])

    def test_a_rule_that_fires_today_puts_its_task_in_today(self):
        code, _ = self.drive([b"R", b"a", b"Leer un rato\r", b"day\r"])

        self.assertEqual(code, 0)
        self.assertEqual(self.rules(), [("Leer un rato", "daily")])
        self.assertEqual(self.today_texts().count("Leer un rato"), 1)

    def test_x_removes_the_rule_and_keeps_the_tasks_it_made(self):
        self.add_rule("Revisar el correo", "day")
        self.assertIn("Revisar el correo", self.today_texts())

        code, screens = self.drive([b"R", b"x", b"\r"])

        self.assertEqual(code, 0)
        self.assertIn("Borrar", screens[1])
        self.assertEqual(self.rules(), [])
        self.assertIn("Revisar el correo", self.today_texts())

    def test_the_help_names_the_recurring_key(self):
        from protas.tui import HELP, _help_lines

        self.assertIn("R recurrentes", HELP)
        self.assertLessEqual(len(_help_lines()), 20)


class TestHarnessIsolationTest(unittest.TestCase):
    """The TUI tests run protas in a terminal, where it refreshes an
    installed Omarchy panel. They must never reach the real one."""

    def setUp(self):
        sys.path.insert(0, str(REPO_ROOT))
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.db = str(root / "protas.db")
        self.log = root / "omarchy.log"
        bin_dir = root / "bin"
        bin_dir.mkdir()
        for name, body in (
            ("omarchy", f'echo "$@" >> "{self.log}"\n'),
            ("protas", "exit 0\n"),
        ):
            script = bin_dir / name
            script.write_text("#!/bin/sh\n" + body)
            script.chmod(0o755)
        panel = root / "config" / "omarchy" / "plugins" / "io.github.ingermanr.protas"
        panel.mkdir(parents=True)
        (panel / "Panel.qml").write_text("an outdated panel")
        self.env = {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "XDG_CONFIG_HOME": str(root / "config"),
        }

    drive = TuiDetailsTest.drive

    def test_the_tui_harness_never_refreshes_a_panel(self):
        from unittest import mock

        with mock.patch.dict(os.environ, self.env):
            code, _ = self.drive([b"j"])

        self.assertEqual(code, 0)
        self.assertFalse(self.log.exists(), self.log.read_text() if self.log.exists() else "")
