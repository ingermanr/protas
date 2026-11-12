"""Interactive workspace (curses).

The TUI is the daily driver: one screen with the entries of a workspace,
the free form note of that workspace and a handful of keys. A day holds
tasks and mentions of projects; a project holds its own tasks. It never
leaves the terminal, so it stays fast on any machine.
"""

from __future__ import annotations

import curses
import sys
import termios
from datetime import date as Date
from datetime import timedelta
from typing import Optional

from .store import Store, Task, Workspace, check_date, describe_event, today

HELP = (
    "j/k mover | espacio completar | a tarea | A subtarea | p proyecto | "
    "e editar | n nota | x borrar | enter abrir | esc volver | ←/→ dia | "
    "h historia | s numeros | q salir | r actualizar | g/G inicio/fin"
)


class Editor:
    """A one line editor used for tasks and a line editor used for notes."""

    def __init__(
        self,
        prompt: str,
        kind: str,
        target_id: int | None = None,
        parent_id: int | None = None,
        workspace_id: int | None = None,
    ):
        self.prompt = prompt
        self.kind = kind
        self.target_id = target_id
        self.parent_id = parent_id
        self.workspace_id = workspace_id
        self.buffer = ""
        # The note is edited line by line: ``row`` is the line being typed.
        self.lines: list[str] = []
        self.row = 0

    @property
    def is_note(self) -> bool:
        return self.kind == "note"

    def text(self) -> str:
        if self.is_note:
            return "\n".join(self.lines).rstrip("\n")
        return self.buffer.strip()


NOTE_PROMPT = "Nota: ↑/↓ linea | Enter nueva linea | Ctrl-S guardar | Esc cancelar"


def note_editor(note: str) -> Editor:
    """An editor holding a note, placed at the end of its last line."""
    editor = Editor(NOTE_PROMPT, "note")
    editor.lines = note.splitlines() or [""]
    editor.row = len(editor.lines) - 1
    return editor


def _note_key(ch: int, editor: Editor) -> str:
    """Feed a special key to the note editor."""
    if ch == curses.KEY_UP:
        editor.row = max(editor.row - 1, 0)
    elif ch == curses.KEY_DOWN:
        editor.row = min(editor.row + 1, len(editor.lines) - 1)
    elif ch in (curses.KEY_BACKSPACE, 127, 8):
        if editor.lines[editor.row]:
            editor.lines[editor.row] = editor.lines[editor.row][:-1]
        elif editor.row > 0:
            # An empty line goes away and the one above becomes current.
            del editor.lines[editor.row]
            editor.row -= 1
    elif ch in (10, 13, curses.KEY_ENTER):
        editor.row += 1
        editor.lines.insert(editor.row, "")
    return "continue"


def _draft_lines(editor: Editor) -> list[tuple[str, bool]]:
    """The note being edited, ready to draw, marking the current line."""
    drawn: list[tuple[str, bool]] = []
    for index, line in enumerate(editor.lines):
        if index == editor.row:
            drawn.append((f" > {line}_", True))
        else:
            drawn.append((f"   {line}", False))
    return drawn


def _flatten(store: Store, workspace: Workspace) -> list[tuple[Task, int]]:
    """Flatten the entries of a workspace into drawable rows."""
    rows: list[tuple[Task, int]] = []

    def walk(tasks: list[Task], depth: int) -> None:
        for task in tasks:
            rows.append((task, depth))
            walk(task.children, depth + 1)

    walk(store.tasks_of(workspace.id), 0)
    return rows


def _clip(text: str, width: int) -> str:
    return text[: max(width - 1, 0)]


def _draw(
    stdscr,
    store: Store,
    workspace: Workspace,
    rows,
    selection: int,
    message: str,
    editor: Optional[Editor],
    view: str = "tasks",
) -> None:
    stdscr.erase()
    height, width = stdscr.getmaxyx()

    counts = store.counts(workspace.id)

    header = f" protas - {workspace.title} "
    if workspace.kind == "project":
        header += "(proyecto) "
    if workspace.note.strip():
        header += "- notas"
    stdscr.addstr(0, 0, _clip(header.ljust(max(width - 1, 0)), width), curses.A_BOLD)

    stats = (
        f" {counts['open']} pendientes | {counts['done']} hechas"
        f" | {counts['projects']} proyectos"
    )
    stdscr.addstr(1, 0, _clip(stats, width))

    if height > 3:
        stdscr.hline(2, 0, "-", max(width - 1, 0))

    body_top = 3
    body_bottom = height - 3
    visible = max(body_bottom - body_top, 0)

    if visible and view == "history":
        for index, line in enumerate(_history_lines(store, workspace)[:visible]):
            try:
                stdscr.addstr(body_top + index, 0, _clip(line.ljust(max(width - 1, 0)), width))
            except curses.error:
                pass
    elif visible and view == "stats":
        for index, line in enumerate(_stats_lines(store)[:visible]):
            try:
                stdscr.addstr(body_top + index, 0, _clip(line.ljust(max(width - 1, 0)), width))
            except curses.error:
                pass
    elif visible and editor is not None and editor.is_note:
        # While the note is open the body shows the draft, scrolled so the
        # line being edited stays on screen.
        draft = _draft_lines(editor)
        offset = max(editor.row - visible + 1, 0)
        for index, (line, current) in enumerate(draft[offset : offset + visible]):
            try:
                stdscr.addstr(
                    body_top + index,
                    0,
                    _clip(line.ljust(max(width - 1, 0)), width),
                    curses.A_BOLD if current else curses.A_NORMAL,
                )
            except curses.error:
                pass
    elif visible:
        note_lines = _note_lines(workspace)
        rows_top = body_top + len(note_lines)
        room = max(visible - len(note_lines), 0)

        for offset_index, line in enumerate(note_lines):
            try:
                stdscr.addstr(
                    body_top + offset_index, 0, _clip(line.ljust(max(width - 1, 0)), width)
                )
            except curses.error:
                pass

        offset = 0
        if selection >= room:
            offset = selection - room + 1
        for index, (task, depth) in enumerate(rows[offset : offset + room]):
            marker = "x" if store.is_done(task) else " "
            label = store.title_of(task)
            if task.is_mention:
                state = store.project_state(task.project_id)
                label += f"  (proyecto {state['done']}/{state['total']})" if state["total"] else "  (proyecto)"
            else:
                label += store.origin_label(task, workspace.date)
            line = f" {'    ' * depth}[{marker}] {label}"
            attribute = curses.A_DIM if store.is_done(task) else curses.A_NORMAL
            if index + offset == selection:
                attribute |= curses.A_REVERSE
            try:
                stdscr.addstr(
                    rows_top + index, 0, _clip(line.ljust(max(width - 1, 0)), width), attribute
                )
            except curses.error:
                pass
        if not rows and not note_lines:
            try:
                stdscr.addstr(body_top, 0, _clip(" (sin tareas todavia) ", width), curses.A_DIM)
            except curses.error:
                pass

    footer = message or HELP
    if height > 1:
        try:
            stdscr.addstr(height - 2, 0, _clip(footer.ljust(max(width - 1, 0)), width), curses.A_DIM)
        except curses.error:
            pass

    if editor is not None and height > 0:
        try:
            stdscr.addstr(height - 1, 0, _clip(editor.prompt + editor.buffer, width), curses.A_BOLD)
        except curses.error:
            pass

    stdscr.refresh()


def _stats_lines(store: Store, days: int = 14) -> list[str]:
    """The numbers of the last days, ready to draw."""
    stats = store.stats(days=days)
    peak = max((stat.done for stat in stats.window), default=0)

    lines = [" Ritmo"]
    for stat in stats.window:
        bar = "#" * round(stat.done * 20 / peak) if peak and stat.done else ""
        lines.append(f"  {stat.date[5:]}  {bar:<20} {stat.done}")

    lines.append("")
    lines.append(f" {stats.completed_per_day} completadas en {days} dias")
    if stats.started:
        percent = round(stats.finished / stats.started * 100)
        lines.append(f" Cumplimiento {percent}% ({stats.finished} de {stats.started})")
    lines.append(f" Racha {stats.streak} dias seguidos")

    if stats.projects:
        lines.append("")
        lines.append(" Proyectos")
        for project in stats.projects:
            lines.append(
                f"  {project.workspace.title[:28]:<28} {project.done}/{project.total}"
                f"  {project.days_active} dias"
            )
    return lines


def _note_lines(workspace: Workspace) -> list[str]:
    """The note of a workspace, ready to draw above the entries."""
    lines = [line for line in workspace.note.splitlines() if line.strip()]
    if not lines:
        return []
    return [f" {line}" for line in lines] + [""]


def _history_lines(store: Store, workspace: Workspace) -> list[str]:
    """The story of a project, ready to draw."""
    if not workspace.is_project:
        return [" (esto no es un proyecto)"]

    history = store.history(workspace.id)
    lines: list[str] = []
    current = None
    for entry in history.entries:
        if entry.date != current:
            current = entry.date
            lines.append("")
            lines.append(f" {entry.date}")
        lines.append(f"   {describe_event(entry)}")

    if history.first_day:
        lines.append("")
        lines.append(f" del {history.first_day} al {history.last_day}")
    else:
        lines.append("")
        lines.append(" todavia no hay actividad")
    return lines


def _read_key(stdscr) -> int | str | None:
    """Read one key: a character as text, anything else as a key code.

    ``get_wch`` decodes what the terminal sends with the locale, so an
    accented letter arrives whole instead of as loose bytes.
    """
    try:
        return stdscr.get_wch()
    except curses.error:
        return None


def _command_code(key: int | str | None) -> int:
    """The code the key bindings compare against.

    A typed character only counts while it is plain ASCII: beyond that its
    number could be mistaken for the code of an arrow or a function key.
    """
    if isinstance(key, int):
        return key
    if key and ord(key) < 128:
        return ord(key)
    return -1


def _editor_key(ch: int | str, editor: Editor) -> str:
    """Feed a key to the editor. Returns submit, save, cancel or continue.

    A character comes as text and a special key as its code.
    """
    if isinstance(ch, str):
        if ch.isprintable():
            ch_text = ch
            ch = -1
        else:
            ch_text = ""
            ch = ord(ch)
    else:
        ch_text = chr(ch) if 32 <= ch < 127 else ""

    if ch_text:
        if editor.is_note:
            editor.lines[editor.row] += ch_text
        else:
            editor.buffer += ch_text
        return "continue"

    if ch == 27:
        return "cancel"
    if ch == 19:  # Ctrl-S
        return "save"
    if editor.is_note:
        return _note_key(ch, editor)
    if ch in (curses.KEY_BACKSPACE, 127, 8):
        editor.buffer = editor.buffer[:-1]
        return "continue"
    if ch in (10, 13, curses.KEY_ENTER):
        return "submit"
    return "continue"


def _shift_date(date_str: str, days: int) -> str:
    current = Date.fromisoformat(date_str) + timedelta(days=days)
    return current.strftime("%Y-%m-%d")


def _release_ctrl_s() -> None:
    """Let Ctrl-S reach the application.

    Terminals keep Ctrl-S for themselves by default: it pauses the output
    and the key never arrives, so the note could not be saved. Curses
    restores the terminal as it was when the workspace is closed.
    """
    try:
        fd = sys.stdin.fileno()
        attributes = termios.tcgetattr(fd)
        attributes[0] &= ~termios.IXON
        termios.tcsetattr(fd, termios.TCSANOW, attributes)
        curses.def_prog_mode()
    except (termios.error, curses.error, OSError, ValueError):
        pass


def _run(stdscr, store: Store, date_str: str | None, project_id: int | None) -> None:
    curses.curs_set(0)
    stdscr.keypad(True)
    _release_ctrl_s()

    origin_day = store.open_day(date_str)
    current_day = origin_day
    if project_id:
        workspace = store.workspace(project_id)
        if workspace is None:
            workspace = origin_day
    else:
        workspace = origin_day

    selection = 0
    message = ""
    editor: Optional[Editor] = None
    view = "tasks"

    while True:
        # The workspace is refreshed every turn: the note and the title can
        # change while it is open.
        fresh = store.workspace(workspace.id)
        if fresh is not None:
            workspace = fresh

        rows = _flatten(store, workspace)
        if selection >= len(rows):
            selection = max(len(rows) - 1, 0)
        if selection < 0:
            selection = 0

        _draw(stdscr, store, workspace, rows, selection, message, editor, view)
        key = _read_key(stdscr)
        if key is None:
            continue

        if editor is not None:
            action = _editor_key(key, editor)
            if action == "cancel":
                editor = None
                message = ""
            elif action == "submit":
                try:
                    if editor.kind == "delete":
                        store.delete_task(editor.target_id)
                        message = "entrada borrada"
                    elif editor.kind == "edit":
                        store.set_text(editor.target_id, editor.text())
                        message = "tarea actualizada"
                    else:
                        target_workspace = editor.workspace_id or workspace.id
                        task = store.add_task(
                            editor.text(),
                            target_workspace,
                            editor.parent_id,
                            day_id=current_day.id,
                        )
                        if target_workspace == workspace.id:
                            rows = _flatten(store, workspace)
                            selection = next(
                                (i for i, (t, _) in enumerate(rows) if t.id == task.id), selection
                            )
                except ValueError as error:
                    message = str(error)
                editor = None
            elif action == "save":
                store.set_note(workspace.id, editor.text())
                editor = None
                message = "nota guardada"
            continue

        ch = _command_code(key)
        if ch in (ord("q"),):
            store.discard_if_empty(current_day.id)
            return
        elif ch in (ord("j"), curses.KEY_DOWN):
            selection = min(selection + 1, max(len(rows) - 1, 0))
            message = ""
        elif ch in (ord("k"), curses.KEY_UP):
            selection = max(selection - 1, 0)
            message = ""
        elif ch == ord("g"):
            selection = 0
        elif ch == ord("G"):
            selection = max(len(rows) - 1, 0)
        elif ch in (ord(" "), 10, 13, curses.KEY_ENTER):
            if rows:
                task, _ = rows[selection]
                if task.is_mention and ch != ord(" "):
                    # Enter opens the project, space completes it.
                    workspace = store.workspace(task.project_id) or workspace
                    selection = 0
                    message = ""
                else:
                    store.set_done(
                        task.id, not store.is_done(task), day_id=current_day.id
                    )
        elif ch == ord("a"):
            editor = Editor("Nueva tarea: ", "task")
        elif ch == ord("A"):
            if rows:
                task, _ = rows[selection]
                if task.is_mention:
                    editor = Editor(
                        "Nueva tarea en el proyecto: ", "task", workspace_id=task.project_id
                    )
                else:
                    project = store.promote(task.id, day_id=current_day.id)
                    editor = Editor(
                        f"Nueva subtarea de {project.title}: ", "task", workspace_id=project.id
                    )
                    message = "la tarea ahora es un proyecto"
            else:
                message = "no hay ninguna entrada a la que colgarla"
        elif ch == ord("p"):
            if rows:
                task, _ = rows[selection]
                if task.is_mention:
                    message = "esa entrada ya es un proyecto"
                else:
                    project = store.promote(task.id, day_id=current_day.id)
                    message = f"proyecto {project.id}: {project.title}"
            else:
                message = "no hay ninguna entrada que promover"
        elif ch == ord("e"):
            if rows:
                task, _ = rows[selection]
                editor = Editor("Editar: ", "edit", target_id=task.id)
                editor.buffer = store.title_of(task)
            else:
                message = "no hay ninguna entrada que editar"
        elif ch == ord("n"):
            editor = note_editor(store.note(workspace.id))
            view = "tasks"
        elif ch == ord("x"):
            if rows:
                task, _ = rows[selection]
                editor = Editor(
                    f"Borrar '{store.title_of(task)}'? (Enter si, Esc no): ", "delete", target_id=task.id
                )
            else:
                message = "no hay ninguna entrada que borrar"
        elif ch == ord("r"):
            store.open_day(current_day.date)
            message = "espacio actualizado"
        elif ch == ord("h"):
            if view == "history":
                view = "tasks"
            elif workspace.is_project:
                view = "history"
            else:
                message = "el historial es de los proyectos"
        elif ch == ord("s"):
            view = "tasks" if view == "stats" else "stats"
        elif ch == 27:
            # Escape goes back to the day when a project is open.
            if view in ("history", "stats"):
                view = "tasks"
            elif workspace.is_project:
                workspace = current_day
                selection = 0
                message = ""
        elif ch == curses.KEY_LEFT:
            if workspace.is_project:
                workspace = current_day
                selection = 0
            else:
                left_behind = current_day
                current_day = store.open_day(_shift_date(current_day.date, -1))
                store.discard_if_empty(left_behind.id)
                workspace = current_day
                selection = 0
                view = "tasks"
        elif ch == curses.KEY_RIGHT:
            if workspace.is_project:
                pass
            else:
                left_behind = current_day
                current_day = store.open_day(_shift_date(current_day.date, 1))
                store.discard_if_empty(left_behind.id)
                workspace = current_day
                selection = 0
                view = "tasks"


def _ensure_utf8_locale() -> None:
    """Curses only accepts what the locale encodes, so ask for UTF-8."""
    import locale

    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        pass
    if "utf" in locale.getpreferredencoding(False).lower():
        return
    for candidate in ("C.UTF-8", "en_US.UTF-8", "es_ES.UTF-8"):
        try:
            locale.setlocale(locale.LC_ALL, candidate)
            return
        except locale.Error:
            continue


def run_tui(store: Store, date_str: str | None = None, project_id: int | None = None) -> None:
    """Open the interactive workspace."""
    if date_str is not None:
        # Refuse a bad date before the terminal is taken over.
        check_date(date_str)
    _ensure_utf8_locale()
    curses.wrapper(_run, store, date_str, project_id)
