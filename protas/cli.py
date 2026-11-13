"""Command line interface for protas.

Every command is a thin, scriptable wrapper around the store. The
interactive workspace lives in the TUI (``protas`` with no arguments).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from . import rules, text
from . import __version__, db
from .db import MigrationError
from .store import Store, Task, Workspace, check_date, describe_event, today
from .models import format_estimate, parse_estimate, parse_priority


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="protas",
        description=(
            "Daily notes and tasks: one workspace per day, projects are workspaces too, "
            "pending work rolls forward."
        ),
    )
    parser.add_argument("--db", default=None, help="path to the database file")
    sub = parser.add_subparsers(dest="command")

    tui = sub.add_parser("tui", help="open the interactive workspace")
    tui.add_argument("date", nargs="?", help="day to open as YYYY-MM-DD (default: today)")
    tui.add_argument("--project", type=int, default=None, help="project to open")

    show = sub.add_parser("show", help="print a workspace")
    show.add_argument("date", nargs="?", help="day to show as YYYY-MM-DD (default: today)")
    show.add_argument("--project", type=int, default=None, help="project to show")

    listing = sub.add_parser("list", help="list the entries of a workspace")
    listing.add_argument("--date", default=None, help="day as YYYY-MM-DD (default: today)")
    listing.add_argument("--project", type=int, default=None)
    listing.add_argument("--all", action="store_true", help="include finished entries")
    listing.add_argument("--json", action="store_true", help="machine readable output")

    add = sub.add_parser("add", help="add a task")
    add.add_argument("text")
    add.add_argument("--date", default=None, help="day as YYYY-MM-DD (default: today)")
    add.add_argument("--project", type=int, default=None, help="add the task inside a project")
    add.add_argument(
        "--parent",
        type=int,
        default=None,
        help="id of the parent task (a task of a day becomes a project)",
    )
    add.add_argument(
        "--priority",
        default=None,
        metavar="ALTA|MEDIA|BAJA",
        help="how important the task is",
    )
    add.add_argument(
        "--estimate",
        default=None,
        metavar="30m|1h|1h30",
        help="how long the task is expected to take",
    )

    details = sub.add_parser("set", help="set the priority or the estimate of an entry")
    details.add_argument("id", type=int)
    details.add_argument(
        "--priority",
        default=argparse.SUPPRESS,
        metavar="ALTA|MEDIA|BAJA|NINGUNA",
        help="new priority; 'ninguna' clears it",
    )
    details.add_argument(
        "--estimate",
        default=argparse.SUPPRESS,
        metavar="30m|1h|1h30|NINGUNA",
        help="new estimate in minutes; 'ninguna' clears it",
    )

    done = sub.add_parser("done", help="mark an entry as completed")
    done.add_argument("id", type=int)

    undone = sub.add_parser("undone", help="reopen an entry")
    undone.add_argument("id", type=int)

    remove = sub.add_parser("rm", help="delete an entry")
    remove.add_argument("id", type=int)

    note = sub.add_parser("note", help="read or write the note of a workspace")
    note.add_argument("text", nargs="?")
    note.add_argument("--date", default=None, help="day as YYYY-MM-DD (default: today)")
    note.add_argument("--project", type=int, default=None)

    roll = sub.add_parser("roll", help="carry pending work into a day")
    roll.add_argument("--to", default=None, help="day as YYYY-MM-DD (default: today)")

    promote = sub.add_parser("promote", help="turn a task into a project")
    promote.add_argument("id", type=int)

    mention = sub.add_parser("mention", help="add a project to the agenda of a day")
    mention.add_argument("project", type=int)
    mention.add_argument("--date", default=None, help="day as YYYY-MM-DD (default: today)")

    sub.add_parser("projects", help="list every project")

    recur = sub.add_parser("recur", help="manage recurring tasks")
    recur_sub = recur.add_subparsers(dest="recur_command")
    recur_add = recur_sub.add_parser("add", help="add a recurring task")
    recur_add.add_argument("text")
    recur_add.add_argument(
        "--every",
        required=True,
        help="day, days of the week (lun,jue or mon,thu) or a day of the month (15)",
    )
    recur_list = recur_sub.add_parser("list", help="list the recurring tasks (default)")
    recur_list.add_argument("--json", action="store_true", help="machine readable output")
    recur_rm = recur_sub.add_parser("rm", help="remove a recurring task; its tasks stay")
    recur_rm.add_argument("id", type=int)

    stats = sub.add_parser("stats", help="numbers of the last days")
    stats.add_argument("--days", type=int, default=14, help="size of the window")
    stats.add_argument("--json", action="store_true", help="machine readable output")

    history = sub.add_parser("history", help="show the story of a project")
    history.add_argument("id", type=int, help="id of the project")
    history.add_argument("--json", action="store_true", help="machine readable output")

    export = sub.add_parser("export", help="export every day and project as markdown")
    export.add_argument("--out", default=None, help="output directory (default: ./protas-export)")
    export.add_argument(
        "--format",
        choices=("markdown", "obsidian"),
        default="markdown",
        help="markdown: plain files; obsidian: notes with properties and wikilinks",
    )

    sub.add_parser("version", help="print the version of protas and of its schema")
    sub.add_parser("doctor", help="check the database without changing it")

    omarchy = sub.add_parser("omarchy", help="manage the Omarchy bar panel")
    omarchy_sub = omarchy.add_subparsers(dest="omarchy_command", required=True)
    install = omarchy_sub.add_parser(
        "install", help="install or update the panel in the Omarchy bar"
    )
    install.add_argument(
        "--no-restart",
        action="store_true",
        help="do not restart the bar after installing",
    )

    search = sub.add_parser("search", help="search tasks, notes and workspaces")
    search.add_argument(
        "term",
        nargs="*",
        help="text to look for (use * for prefixes, quote it or type it loose)",
    )
    search.add_argument("--since", default=None, help="only results on or after this day")
    search.add_argument("--until", default=None, help="only results on or before this day")
    search.add_argument(
        "--kind",
        action="append",
        choices=["task", "note", "day", "project"],
        help="what to search, repeatable (default: all of them)",
    )
    search.add_argument("--open", dest="open_only", action="store_true", help="only pending tasks")
    search.add_argument("--done", action="store_true", help="only completed tasks")
    search.add_argument("--limit", type=int, default=50, help="0 for no limit")
    search.add_argument("--json", action="store_true", help="machine readable output")

    return parser


# ----------------------------------------------------------------------
# rendering
# ----------------------------------------------------------------------
def render_workspace(store: Store, workspace: Workspace) -> str:
    """Render a workspace as plain text."""
    lines = [workspace.title, "=" * max(len(workspace.title), 12)]

    if workspace.note.strip():
        lines.append("")
        lines.extend(workspace.note.strip().splitlines())
        lines.append("")

    tasks = store.tasks_of(workspace.id)
    if tasks:
        lines.append("")
        for task in tasks:
            lines.extend(render_entry(store, task, 0, workspace.date))
    else:
        lines.extend(["", "(no tasks yet)"])

    if workspace.is_project:
        mentions = [
            row["date"]
            for row in store.conn.execute(
                """SELECT DISTINCT w.date FROM tasks t
                   JOIN workspaces w ON w.id = t.workspace_id
                   WHERE t.project_id = ? AND w.kind = 'day' ORDER BY w.date""",
                (workspace.id,),
            ).fetchall()
        ]
        if mentions:
            lines.extend(["", "mencionado en: " + ", ".join(mentions)])

    return "\n".join(lines)


def render_entry(store: Store, task: Task, depth: int, reference_date: str | None = None) -> list[str]:
    """Render an entry and its children."""
    marker = "[x]" if store.is_done(task) else "[ ]"
    indent = "    " * depth
    line = f"{indent}{marker} {store.title_of(task)}"

    if task.is_mention:
        state = store.project_state(task.project_id)
        if state["total"]:
            line += f"  (proyecto {state['done']}/{state['total']})"
        else:
            line += "  (proyecto)"
    else:
        line += store.origin_label(task, reference_date)

    if task.details:
        line += f"  ({task.details})"

    lines = [line]
    for child in task.children:
        lines.extend(render_entry(store, child, depth + 1, reference_date))
    return lines


# ----------------------------------------------------------------------
# commands
# ----------------------------------------------------------------------
def _workspace_for(store: Store, args) -> Workspace:
    """Resolve the workspace a command works on."""
    if getattr(args, "project", None):
        workspace = store.workspace(args.project)
        if workspace is None:
            raise ValueError(f"project {args.project} does not exist")
        return workspace
    date_str = getattr(args, "date", None) or today()
    return store.open_day(date_str)


def _notice(message: str) -> None:
    """Things the user should know that are not the answer to the command."""
    print(f"protas: {message}", file=sys.stderr)


def cmd_omarchy(args) -> int:
    from . import omarchy

    try:
        report = omarchy.install(
            restart=not args.no_restart,
            notify=lambda message: print(f"protas: {message}", file=sys.stderr),
        )
    except omarchy.OmarchyError as error:
        print(f"protas: {error}", file=sys.stderr)
        return 1
    for line in report:
        print(line)
    return 0


def cmd_doctor(args) -> int:
    from .doctor import examine

    path = Path(args.db).expanduser() if args.db else db.default_db_path()
    report = examine(path)
    print("\n".join(report.lines))
    return 0 if report.healthy else 1


def cmd_show(store: Store, args) -> int:
    workspace = _workspace_for(store, args)
    print(render_workspace(store, workspace))
    # Looking at a day must not leave an empty day behind.
    store.discard_if_empty(workspace.id)
    return 0


def cmd_list(store: Store, args) -> int:
    if args.json:
        workspace = _read_workspace(store, args)
        tasks = (
            store.tasks_of(workspace.id, include_done=args.all) if workspace else []
        )
        date_str = workspace.date if workspace else (args.date or today())
        print(
            json.dumps(
                list_payload(store, workspace, date_str, tasks),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    workspace = _workspace_for(store, args)
    for node, depth in walk(store.tasks_of(workspace.id, include_done=args.all)):
        marker = "[x]" if store.is_done(node) else "[ ]"
        line = f"{node.id} {marker} {'  ' * depth}{store.title_of(node)}"
        if node.details:
            line += f"  ({node.details})"
        print(line)
    store.discard_if_empty(workspace.id)
    return 0


def _read_workspace(store: Store, args) -> Optional[Workspace]:
    """Resolve a workspace for a report without creating or rolling it.

    ``list --json`` feeds dashboards that poll it, so reading it must not
    write: a missing day stays missing and no pending work is carried.
    """
    if getattr(args, "project", None):
        workspace = store.workspace(args.project)
        if workspace is None:
            raise ValueError(f"project {args.project} does not exist")
        return workspace
    date_str = args.date or today()
    check_date(date_str)
    return store.day(date_str)


def list_payload(
    store: Store,
    workspace: Optional[Workspace],
    date_str: str,
    tasks: list[Task],
) -> dict:
    """The workspace as data: what the day holds, ready for other tools.

    Counts keep their live state, and a mention carries the progress of
    the project it points at, so a widget can show "2/5" without a second
    query.
    """
    entries = []
    for node, depth in walk(tasks):
        entries.append(
            {
                "id": node.id,
                "text": store.title_of(node),
                "done": store.is_done(node),
                "depth": depth,
                "parent_id": node.parent_id,
                "project_id": node.project_id,
                "origin": store.origin_date(node),
                "position": node.position,
                "priority": node.priority,
                "estimate_minutes": node.estimate,
                "progress": (
                    store.project_state(node.project_id) if node.is_mention else None
                ),
            }
        )

    if workspace is None:
        counts = {"total": 0, "done": 0, "open": 0, "projects": 0}
        kind = "day"
    else:
        counts = store.counts(workspace.id)
        kind = workspace.kind

    return {
        "workspace": {
            "id": workspace.id if workspace else None,
            "kind": kind,
            "date": date_str,
            "title": workspace.title if workspace else date_str,
        },
        "counts": counts,
        "note": workspace.note if workspace else "",
        "entries": entries,
    }


def walk(tasks: list[Task], depth: int = 0):
    """Yield every task of a tree with its depth."""
    for task in tasks:
        yield task, depth
        yield from walk(task.children, depth + 1)


def cmd_add(store: Store, args) -> int:
    if args.project:
        workspace = store.workspace(args.project)
        if workspace is None:
            raise ValueError(f"project {args.project} does not exist")
    else:
        workspace = store.open_day(args.date)
    priority = parse_priority(args.priority) if args.priority is not None else None
    estimate = parse_estimate(args.estimate) if args.estimate is not None else None
    task = store.add_task(
        args.text,
        workspace.id,
        parent_id=args.parent,
        priority=priority,
        estimate=estimate,
    )
    print(task.id)
    return 0


def cmd_set(store: Store, args) -> int:
    changes = {}
    if hasattr(args, "priority"):
        changes["priority"] = parse_priority(args.priority)
    if hasattr(args, "estimate"):
        changes["estimate"] = parse_estimate(args.estimate)
    if not changes:
        raise ValueError("set necesita --priority, --estimate o los dos")
    task = store.set_details(args.id, **changes)
    print(task.id)
    return 0


def cmd_done(store: Store, args) -> int:
    task = store.set_done(args.id, True)
    print(task.id)
    return 0


def cmd_undone(store: Store, args) -> int:
    task = store.set_done(args.id, False)
    print(task.id)
    return 0


def cmd_rm(store: Store, args) -> int:
    store.delete_task(args.id)
    return 0


def cmd_note(store: Store, args) -> int:
    workspace = _workspace_for(store, args)
    if args.text is None:
        print(store.note(workspace.id))
        store.discard_if_empty(workspace.id)
        return 0
    store.set_note(workspace.id, args.text)
    return 0


def cmd_roll(store: Store, args) -> int:
    target = args.to or today()
    carried = store.rollover(target)
    if not carried:
        print(f"nothing pending to carry into {target}")
        return 0
    for entry_id in carried:
        entry = store.task(entry_id)
        print(f"{entry.id} {store.title_of(entry)}")
    return 0


def cmd_promote(store: Store, args) -> int:
    project = store.promote(args.id)
    print(project.id)
    return 0


def cmd_mention(store: Store, args) -> int:
    day = store.open_day(args.date)
    entry = store.add_mention(args.project, day.id)
    print(entry.id)
    return 0


def cmd_projects(store: Store, args) -> int:
    projects = store.projects()
    if not projects:
        print("no projects yet")
        return 0
    for project in projects:
        state = f"{project.done}/{project.total}"
        days = f"  [{', '.join(project.days)}]" if project.days else ""
        print(f"{project.workspace.id}  {project.workspace.title}  ({state}){days}")
    return 0


def cmd_recur(store: Store, args) -> int:
    if args.recur_command == "add":
        print(store.add_recurrence(args.text, args.every).id)
        return 0
    if args.recur_command == "rm":
        store.remove_recurrence(args.id)
        return 0

    recurrences = store.recurrences()
    if getattr(args, "json", False):
        print(
            json.dumps(
                [
                    {
                        "id": rule.id,
                        "text": rule.text,
                        "pattern": rule.pattern,
                        "every": rules.describe_recurrence(rule.pattern),
                    }
                    for rule in recurrences
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if not recurrences:
        print("no hay tareas recurrentes")
        return 0
    for rule in recurrences:
        print(f"{rule.id}  {rules.describe_recurrence(rule.pattern)}  {rule.text}")
    return 0


def cmd_history(store: Store, args) -> int:
    history = store.history(args.id)

    if args.json:
        print(
            json.dumps(
                {
                    "project": history.project.title,
                    "first_day": history.first_day,
                    "last_day": history.last_day,
                    "days": history.days,
                    "entries": [
                        {
                            "date": entry.date,
                            "kind": entry.kind,
                            "text": entry.text,
                            "at": entry.at,
                        }
                        for entry in history.entries
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print(history.project.title)
    print("=" * max(len(history.project.title), 12))

    current = None
    for entry in history.entries:
        if entry.date != current:
            current = entry.date
            print()
            print(current)
        print(f"  {describe_event(entry)}")

    if history.first_day:
        print()
        print(
            f"del {history.first_day} al {history.last_day} "
            f"({len(history.days)} dia(s) con actividad)"
        )
    else:
        print()
        print("todavia no hay actividad")
    return 0


def cmd_stats(store: Store, args) -> int:
    # Opening today first carries the pending work in, so the window and the
    # "Hoy" line count what today holds on the first call of the day too.
    today_counts = store.counts(store.open_day(today()).id)
    stats = store.stats(days=args.days)

    if args.json:
        print(
            json.dumps(
                {
                    "today": today_counts,
                    "window_days": args.days,
                    "days": [
                        {
                            "date": stat.date,
                            "tasks": stat.tasks,
                            "done": stat.done,
                            "projects": stat.projects,
                            "estimate_minutes": stat.estimate,
                        }
                        for stat in stats.window
                    ],
                    "completed": stats.completed_per_day,
                    "active_days": stats.active_days,
                    "started": stats.started,
                    "finished": stats.finished,
                    "streak": stats.streak,
                    "projects": [
                        {
                            "title": project.workspace.title,
                            "done": project.done,
                            "total": project.total,
                            "days_active": project.days_active,
                            "first_day": project.first_day,
                            "last_day": project.last_day,
                        }
                        for project in stats.projects
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    today_stat = next((stat for stat in stats.window if stat.date == today()), None)
    today_estimate = today_stat.estimate if today_stat else 0

    print("Hoy")
    line = (
        f"  {today_counts['open']} pendientes | {today_counts['done']} hechas"
        f" | {today_counts['projects']} proyectos"
    )
    if today_estimate:
        line += f" | {format_estimate(today_estimate)} estimadas"
    print(line)

    print()
    print(f"Ritmo (ultimos {args.days} dias)")
    peak = max((stat.done for stat in stats.window), default=0)
    for stat in stats.window:
        bar = "#" * round(stat.done * 24 / peak) if peak and stat.done else ""
        estimate = f"  {format_estimate(stat.estimate)}" if stat.estimate else ""
        print(f"  {stat.date}  {bar:<24} {stat.done}{estimate}")
    average = stats.completed_per_day / stats.active_days if stats.active_days else 0
    print(
        f"  {stats.completed_per_day} completadas | {average:.1f} por dia activo"
        f" | {stats.active_days} dias con actividad"
    )

    print()
    print("Cumplimiento")
    if stats.started:
        percent = round(stats.finished / stats.started * 100)
        print(f"  {percent}% ({stats.finished} de {stats.started} tareas que arrancaste)")
    else:
        print("  sin tareas nuevas en el periodo")

    print()
    print("Proyectos")
    if stats.projects:
        for project in stats.projects:
            bar = _progress_bar(project.progress)
            span = ""
            if project.first_day and project.last_day:
                span = f"  del {project.first_day} al {project.last_day}"
            print(
                f"  {project.workspace.title:<28} {bar}  {project.done}/{project.total}"
                f"  {project.days_active} dias activos{span}"
            )
    else:
        print("  sin proyectos")

    print()
    print("Racha")
    print(f"  {stats.streak} dias seguidos con actividad")
    return 0


def _progress_bar(progress: float, width: int = 10) -> str:
    filled = round(progress * width)
    return "#" * filled + "." * (width - filled)


def cmd_export(store: Store, args) -> int:
    out_dir = Path(args.out or "protas-export")

    if args.format == "obsidian":
        from . import obsidian

        try:
            obsidian.write(obsidian.render(store), out_dir)
        except obsidian.ExportError as error:
            print(f"protas: {error}", file=sys.stderr)
            return 1
        print(out_dir)
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)

    for workspace in store.workspaces("day"):
        lines = [f"# {workspace.title}", ""]
        if workspace.note.strip():
            lines.extend([workspace.note.strip(), ""])
        for task in store.tasks_of(workspace.id):
            lines.extend(_render_markdown(store, task, 0))
        (out_dir / f"{workspace.date}.md").write_text("\n".join(lines) + "\n")

    projects_dir = out_dir / "projects"
    projects_dir.mkdir(exist_ok=True)
    for project in store.projects():
        workspace = project.workspace
        lines = [f"# {workspace.title}", "", f"project {project.done}/{project.total}", ""]
        if workspace.note.strip():
            lines.extend([workspace.note.strip(), ""])
        for task in store.tasks_of(workspace.id):
            lines.extend(_render_markdown(store, task, 0))
        (projects_dir / f"{workspace.id}-{_slug(workspace.title)}.md").write_text(
            "\n".join(lines) + "\n"
        )

    print(out_dir)
    return 0


def _slug(title: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "-_" else "-" for char in title)
    return "-".join(part for part in cleaned.split("-") if part) or "proyecto"


def _render_markdown(store: Store, task: Task, depth: int) -> list[str]:
    indent = "  " * depth
    marker = "x" if store.is_done(task) else " "
    title = store.title_of(task)
    if task.is_mention:
        state = store.project_state(task.project_id)
        title += f" (proyecto {state['done']}/{state['total']})" if state["total"] else " (proyecto)"
    lines = [f"{indent}- [{marker}] {title}"]
    for child in task.children:
        lines.extend(_render_markdown(store, child, depth + 1))
    return lines


def cmd_search(store: Store, args) -> int:
    query = " ".join(args.term).strip()
    if not query:
        print("protas: decime qué buscar", file=sys.stderr)
        return 2

    kinds = tuple(args.kind) if args.kind else ("task", "note", "day", "project")
    state = "open" if args.open_only else ("done" if args.done else None)

    hits = store.search(
        query,
        since=args.since,
        until=args.until,
        kinds=kinds,
        state=state,
        limit=args.limit,
    )

    if args.json:
        print(
            json.dumps(
                [
                    {
                        "kind": hit.kind,
                        "date": hit.date,
                        "text": hit.text,
                        "task_id": hit.task_id,
                    }
                    for hit in hits
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        terms = text.terms(query)
        for hit in hits:
            body = hit.text if hit.kind == "task" else text.snippet(hit.text, terms)
            print(f"{hit.date}  {hit.kind:<7} {body}")
        print(f"{len(hits)} resultado(s)", file=sys.stderr)

    return 0 if hits else 1


COMMANDS = {
    "show": cmd_show,
    "list": cmd_list,
    "add": cmd_add,
    "set": cmd_set,
    "done": cmd_done,
    "undone": cmd_undone,
    "rm": cmd_rm,
    "note": cmd_note,
    "roll": cmd_roll,
    "promote": cmd_promote,
    "mention": cmd_mention,
    "projects": cmd_projects,
    "stats": cmd_stats,
    "history": cmd_history,
    "export": cmd_export,
    "recur": cmd_recur,
    "search": cmd_search,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # These two answer without opening the database: they must work on
    # one that cannot be opened and must never create or change it.
    if args.command == "version":
        print(f"protas {__version__} (schema {db.SCHEMA_VERSION})")
        return 0
    if args.command == "doctor":
        return cmd_doctor(args)
    # The panel is installed around protas, not in it: no database needed.
    if args.command == "omarchy":
        return cmd_omarchy(args)

    try:
        store = Store(path=args.db, notify=_notice)
    except MigrationError as error:
        print(f"protas: {error}", file=sys.stderr)
        return 1

    try:
        if args.command in ("tui", None):
            # The TUI is loaded only when it opens: curses and termios are
            # missing on Windows, and every other command works without them.
            try:
                from .tui import run_tui
            except ImportError:
                print(
                    "protas: la TUI necesita curses, que este Python no trae"
                    " (en Windows no existe); los comandos funcionan igual,"
                    " prueba protas list o protas --help",
                    file=sys.stderr,
                )
                return 1
            if args.command == "tui":
                run_tui(store, args.date, args.project)
            else:
                run_tui(store, None, None)
            return 0

        handler = COMMANDS.get(args.command)
        if handler is None:
            parser.print_help()
            return 2
        return handler(store, args)
    except ValueError as error:
        print(f"protas: {error}", file=sys.stderr)
        return 1
    finally:
        store.close()
