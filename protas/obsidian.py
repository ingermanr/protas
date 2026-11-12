"""Render the workspaces as notes for an Obsidian vault.

Each day and each project becomes one note. A note starts with the
properties Obsidian reads (date, tags, aliases), the tasks are checkboxes,
and a day points at its projects with wikilinks, so the vault's own
backlinks show where every project was worked on.

Rendering is separate from writing: ``render`` returns what every file
would hold, and ``write`` refuses to replace a note protas did not write.
"""

from __future__ import annotations

import json
from pathlib import Path

from .store import Store, Task, Workspace

# First property of every exported note. A file without it is the
# user's own and is never replaced.
MARKER = "source: protas"

PROJECTS_DIR = "projects"

# Characters a file name or a wikilink target cannot hold in Obsidian.
_FORBIDDEN = set('\\/:*?"<>|#^[]')
# A link label holding these would end the link early.
_UNSAFE_IN_LABEL = set("[]|")


class ExportError(Exception):
    """The export would replace notes that are not from protas."""


def render(store: Store) -> dict[str, str]:
    """Every note of the export, keyed by its path inside the folder."""
    projects = store.projects()
    names = _note_names([project.workspace for project in projects])
    titles = {project.workspace.id: project.workspace.title for project in projects}

    def link(project_id: int) -> str:
        name = names.get(project_id)
        title = titles.get(project_id, "")
        if name is None:
            return title
        if name == title or _UNSAFE_IN_LABEL & set(title):
            return f"[[{name}]]"
        return f"[[{name}|{title}]]"

    notes: dict[str, str] = {}
    for day in store.workspaces("day"):
        properties = [f"date: {day.date}", "tags:", "  - protas/dia"]
        notes[f"{day.date}.md"] = _note(store, day, properties, link)

    for project in projects:
        workspace = project.workspace
        name = names[workspace.id]
        properties = ["tags:", "  - protas/proyecto", f'avance: "{project.done}/{project.total}"']
        if name != workspace.title:
            # The title as the user wrote it stays searchable and linkable.
            properties += ["aliases:", f"  - {json.dumps(workspace.title, ensure_ascii=False)}"]
        notes[f"{PROJECTS_DIR}/{name}.md"] = _note(store, workspace, properties, link)

    return notes


def write(notes: dict[str, str], out_dir: Path) -> None:
    """Write the notes, or nothing at all if one would replace a foreign file."""
    foreign = sorted(
        path for path in notes if (out_dir / path).exists() and not _is_ours(out_dir / path)
    )
    if foreign:
        raise ExportError(
            "no reemplazo notas que no escribió protas: "
            + ", ".join(foreign)
            + f" (en {out_dir}); elige otra carpeta o mueve esas notas"
        )

    for path, content in notes.items():
        target = out_dir / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _is_ours(path: Path) -> bool:
    try:
        with path.open(encoding="utf-8") as handle:
            return handle.readline().strip() == "---" and handle.readline().strip() == MARKER
    except (OSError, UnicodeDecodeError):
        return False


def _note(store: Store, workspace: Workspace, properties: list[str], link) -> str:
    lines = ["---", MARKER, *properties, "---", ""]
    if workspace.note.strip():
        lines += [workspace.note.strip(), ""]
    for task in store.tasks_of(workspace.id):
        lines += _task_lines(store, task, 0, link)
    return "\n".join(lines).rstrip("\n") + "\n"


def _task_lines(store: Store, task: Task, depth: int, link) -> list[str]:
    marker = "x" if store.is_done(task) else " "
    if task.is_mention:
        state = store.project_state(task.project_id)
        label = link(task.project_id)
        if state["total"]:
            label += f" ({state['done']}/{state['total']})"
    else:
        label = store.title_of(task)
    lines = ["\t" * depth + f"- [{marker}] {label}"]
    for child in task.children:
        lines += _task_lines(store, child, depth + 1, link)
    return lines


def _note_names(workspaces: list[Workspace]) -> dict[int, str]:
    """A file name per project: its title made safe, and unique.

    Names are compared without case because a vault may live on a file
    system that does not tell ``Plan`` from ``plan``.
    """
    names: dict[int, str] = {}
    taken: set[str] = set()
    for workspace in sorted(workspaces, key=lambda item: item.id):
        name = _safe_name(workspace.title)
        if name.casefold() in taken:
            name = f"{name} ({workspace.id})"
        taken.add(name.casefold())
        names[workspace.id] = name
    return names


def _safe_name(title: str) -> str:
    cleaned = "".join(" " if char in _FORBIDDEN or ord(char) < 32 else char for char in title)
    cleaned = " ".join(cleaned.split()).strip(". ")
    return cleaned or "Proyecto"
