"""Domain model: workspaces, tasks, projects and the daily rollover.

Core concepts
-------------
* A **workspace** is the unit the user works in. There are two kinds:

  - a **day**: one calendar day, its title is its date, it holds a note
    and the agenda of that day.
  - a **project**: a long lived space with its own title, its own note and
    its own tasks.

* A **task** lives inside a workspace. In a day it is a piece of work for
  that day. In a project it is part of the project.

* A **mention** is a day entry that points at a project. It keeps its place
  in the agenda and shows the live progress of the project.

* The **rollover** copies the pending work of a day into the next one. The
  original stays where it was, so every day keeps an honest record.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date as Date
from datetime import datetime
from pathlib import Path
from typing import Optional

from .db import connect, fts5_available
from .text import build_match_query
from .text import matches as text_matches
from .text import terms as text_terms

ISO_FORMAT = "%Y-%m-%d"


def today() -> str:
    """Today's date as an ISO string."""
    return Date.today().strftime(ISO_FORMAT)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class Workspace:
    """A day or a project."""

    id: int
    kind: str
    title: str
    date: Optional[str]
    note: str
    parent_id: Optional[int]

    @property
    def is_day(self) -> bool:
        return self.kind == "day"

    @property
    def is_project(self) -> bool:
        return self.kind == "project"


@dataclass
class Task:
    """A task inside a workspace."""

    id: int
    workspace_id: int
    project_id: Optional[int]
    parent_id: Optional[int]
    text: str
    done: bool
    origin_id: Optional[int]
    position: int
    created_at: str
    done_at: Optional[str] = None
    children: list["Task"] = field(default_factory=list)

    @property
    def is_mention(self) -> bool:
        """True when the task is a day entry pointing at a project."""
        return self.project_id is not None


@dataclass
class ProjectRef:
    """A project seen from the project list."""

    workspace: Workspace
    total: int
    done: int
    open: int
    mentions: int
    days: list[str]


class Store:
    """All persistence for workspaces, tasks and projects."""

    def __init__(self, path: Path | str | None = None, conn: sqlite3.Connection | None = None):
        self.conn = conn if conn is not None else connect(path)
        self.fts_enabled = fts5_available()

    # ------------------------------------------------------------------
    # workspaces
    # ------------------------------------------------------------------
    def _to_workspace(self, row: sqlite3.Row) -> Workspace:
        return Workspace(
            id=row["id"],
            kind=row["kind"],
            title=row["title"],
            date=row["date"],
            note=row["note"],
            parent_id=row["parent_id"],
        )

    def ensure_day(self, date_str: str) -> Workspace:
        """Return the day workspace, creating it when missing."""
        row = self.conn.execute(
            "SELECT * FROM workspaces WHERE kind = 'day' AND date = ?", (date_str,)
        ).fetchone()
        if row is not None:
            return self._to_workspace(row)

        cursor = self.conn.execute(
            """INSERT INTO workspaces (kind, title, date, note, parent_id, created_at)
               VALUES ('day', ?, ?, '', NULL, ?)""",
            (date_str, date_str, _now()),
        )
        self.conn.commit()
        return self.workspace(cursor.lastrowid)

    def create_project(self, title: str, parent_id: int | None = None) -> Workspace:
        """Create a project workspace."""
        title = title.strip()
        if not title:
            raise ValueError("a project needs a title")
        cursor = self.conn.execute(
            """INSERT INTO workspaces (kind, title, date, note, parent_id, created_at)
               VALUES ('project', ?, NULL, '', ?, ?)""",
            (title, parent_id, _now()),
        )
        self.conn.commit()
        return self.workspace(cursor.lastrowid)

    def workspace(self, workspace_id: int) -> Optional[Workspace]:
        row = self.conn.execute(
            "SELECT * FROM workspaces WHERE id = ?", (workspace_id,)
        ).fetchone()
        if row is None:
            return None
        return self._to_workspace(row)

    def day(self, date_str: str) -> Optional[Workspace]:
        row = self.conn.execute(
            "SELECT * FROM workspaces WHERE kind = 'day' AND date = ?", (date_str,)
        ).fetchone()
        if row is None:
            return None
        return self._to_workspace(row)

    def workspaces(self, kind: str | None = None) -> list[Workspace]:
        if kind:
            rows = self.conn.execute(
                "SELECT * FROM workspaces WHERE kind = ? ORDER BY date DESC, id DESC", (kind,)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM workspaces ORDER BY date DESC, id DESC"
            ).fetchall()
        return [self._to_workspace(row) for row in rows]

    def set_note(self, workspace_id: int, note: str) -> Workspace:
        workspace = self.workspace(workspace_id)
        if workspace is None:
            raise ValueError(f"workspace {workspace_id} does not exist")
        self.conn.execute(
            "UPDATE workspaces SET note = ? WHERE id = ?", (note, workspace_id)
        )
        self.conn.commit()
        return self.workspace(workspace_id)

    def note(self, workspace_id: int) -> str:
        workspace = self.workspace(workspace_id)
        return workspace.note if workspace else ""

    def open_day(self, date_str: str | None = None) -> Workspace:
        """Open a workspace, bringing pending work in when it is today or later."""
        date_str = date_str or today()
        day = self.ensure_day(date_str)
        if date_str >= today():
            self.rollover(date_str)
        return day

    # ------------------------------------------------------------------
    # tasks
    # ------------------------------------------------------------------
    def _to_task(self, row: sqlite3.Row) -> Task:
        return Task(
            id=row["id"],
            workspace_id=row["workspace_id"],
            project_id=row["project_id"],
            parent_id=row["parent_id"],
            text=row["text"],
            done=bool(row["done"]),
            origin_id=row["origin_id"],
            position=row["position"],
            created_at=row["created_at"],
            done_at=row["done_at"],
        )

    def add_task(
        self,
        text: str,
        workspace_id: int,
        parent_id: int | None = None,
    ) -> Task:
        """Create a task inside a workspace."""
        text = text.strip()
        if not text:
            raise ValueError("a task needs some text")
        workspace = self.workspace(workspace_id)
        if workspace is None:
            raise ValueError(f"workspace {workspace_id} does not exist")
        if parent_id is not None:
            parent = self.task(parent_id)
            if parent is None:
                raise ValueError(f"task {parent_id} does not exist")
            if parent.workspace_id != workspace_id:
                raise ValueError("the parent task belongs to another workspace")

        position = self._next_position(workspace_id, parent_id)
        cursor = self.conn.execute(
            """INSERT INTO tasks
               (workspace_id, project_id, parent_id, text, done, done_at, origin_id,
                position, created_at)
               VALUES (?, NULL, ?, ?, 0, NULL, NULL, ?, ?)""",
            (workspace_id, parent_id, text, position, _now()),
        )
        self.conn.commit()
        return self.task(cursor.lastrowid)

    def _next_position(self, workspace_id: int, parent_id: int | None) -> int:
        if parent_id is None:
            row = self.conn.execute(
                """SELECT COALESCE(MAX(position), -1) + 1 FROM tasks
                   WHERE workspace_id = ? AND parent_id IS NULL""",
                (workspace_id,),
            ).fetchone()
        else:
            row = self.conn.execute(
                """SELECT COALESCE(MAX(position), -1) + 1 FROM tasks
                   WHERE workspace_id = ? AND parent_id = ?""",
                (workspace_id, parent_id),
            ).fetchone()
        return row[0]

    def task(self, task_id: int) -> Optional[Task]:
        row = self.conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        return self._to_task(row)

    def tasks_of(self, workspace_id: int, include_done: bool = True) -> list[Task]:
        """Return the top level entries of a workspace with their children."""
        rows = self.conn.execute(
            "SELECT * FROM tasks WHERE workspace_id = ? ORDER BY position, id", (workspace_id,)
        ).fetchall()

        nodes = {row["id"]: self._to_task(row) for row in rows}
        roots: list[Task] = []
        for row in rows:
            node = nodes[row["id"]]
            parent = nodes.get(row["parent_id"]) if row["parent_id"] is not None else None
            if parent is None:
                roots.append(node)
            else:
                parent.children.append(node)

        if include_done:
            return roots
        return self._prune(roots)

    def _prune(self, tasks: list[Task]) -> list[Task]:
        """Drop finished entries, keeping parents that still hold open work."""
        kept: list[Task] = []
        for task in tasks:
            task.children = self._prune(task.children)
            if self.is_done(task) and not task.children:
                continue
            kept.append(task)
        return kept

    # ------------------------------------------------------------------
    # state
    # ------------------------------------------------------------------
    def is_done(self, task: Task) -> bool:
        """The live state of an entry.

        A mention follows the state of its project, because a project is
        one thing with one state, no matter how many days mention it.
        """
        if task.project_id is not None:
            return self.project_is_done(task.project_id)
        return task.done

    def project_state(self, project_id: int) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT done FROM tasks WHERE workspace_id = ?", (project_id,)
        ).fetchall()
        total = len(rows)
        done = sum(1 for row in rows if row["done"])
        return {"total": total, "done": done, "open": total - done}

    def project_is_done(self, project_id: int) -> bool:
        state = self.project_state(project_id)
        return state["total"] > 0 and state["open"] == 0

    def set_done(self, task_id: int, done: bool = True) -> Task:
        """Complete or reopen an entry.

        Completing a project entry completes the whole project. Completing
        a task inside a project completes its children too.
        """
        task = self.task(task_id)
        if task is None:
            raise ValueError(f"task {task_id} does not exist")

        if task.project_id is not None:
            self._set_project_done(task.project_id, done)
            self.conn.commit()
            return self.task(task_id)

        self._write_done(task_id, done)
        if done:
            for descendant in self._descendants(task_id):
                self._write_done(descendant, True)
        else:
            for ancestor in self._ancestors(task_id):
                self._write_done(ancestor, False)

        self.conn.commit()
        return self.task(task_id)

    def _set_project_done(self, project_id: int, done: bool) -> None:
        rows = self.conn.execute(
            "SELECT id FROM tasks WHERE workspace_id = ?", (project_id,)
        ).fetchall()
        for row in rows:
            self._write_done(row["id"], done)

    def _write_done(self, task_id: int, done: bool) -> None:
        self.conn.execute(
            "UPDATE tasks SET done = ?, done_at = ? WHERE id = ?",
            (1 if done else 0, _now() if done else None, task_id),
        )

    def _descendants(self, task_id: int) -> list[int]:
        found: list[int] = []
        frontier = [task_id]
        while frontier:
            current = frontier.pop()
            children = self.conn.execute(
                "SELECT id FROM tasks WHERE parent_id = ?", (current,)
            ).fetchall()
            for child in children:
                found.append(child["id"])
                frontier.append(child["id"])
        return found

    def _ancestors(self, task_id: int) -> list[int]:
        found: list[int] = []
        current = self.task(task_id)
        while current is not None and current.parent_id is not None:
            parent = self.task(current.parent_id)
            if parent is None:
                break
            found.append(parent.id)
            current = parent
        return found

    def set_text(self, task_id: int, text: str) -> Task:
        text = text.strip()
        if not text:
            raise ValueError("a task needs some text")
        task = self.task(task_id)
        if task is None:
            raise ValueError(f"task {task_id} does not exist")
        if task.project_id is not None:
            # A mention shows the title of its project.
            workspace = self.workspace(task.project_id)
            if workspace is not None:
                self.conn.execute(
                    "UPDATE workspaces SET title = ? WHERE id = ?", (text, task.project_id)
                )
                self.conn.commit()
                return self.task(task_id)
        self.conn.execute("UPDATE tasks SET text = ? WHERE id = ?", (text, task_id))
        self.conn.commit()
        return self.task(task_id)

    def delete_task(self, task_id: int) -> None:
        """Remove an entry. Removing a mention leaves the project alive."""
        if self.task(task_id) is None:
            raise ValueError(f"task {task_id} does not exist")
        self.conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        self.conn.commit()

    # ------------------------------------------------------------------
    # projects
    # ------------------------------------------------------------------
    def promote(self, task_id: int) -> Workspace:
        """Turn a task into a project workspace.

        The task becomes a mention of the project, keeping its place in the
        agenda, and its children move inside the new workspace.
        """
        task = self.task(task_id)
        if task is None:
            raise ValueError(f"task {task_id} does not exist")
        if task.project_id is not None:
            workspace = self.workspace(task.project_id)
            if workspace is None:
                raise ValueError(f"project {task.project_id} does not exist")
            return workspace

        project = self.create_project(task.text)

        children = self.conn.execute(
            "SELECT id FROM tasks WHERE parent_id = ?", (task_id,)
        ).fetchall()
        for child in children:
            self.conn.execute(
                "UPDATE tasks SET workspace_id = ?, parent_id = NULL WHERE id = ?",
                (project.id, child["id"]),
            )

        self.conn.execute(
            "UPDATE tasks SET project_id = ? WHERE id = ?", (project.id, task_id)
        )
        self.conn.commit()
        return project

    def add_mention(self, project_id: int, workspace_id: int) -> Task:
        """Add a project to the agenda of a day."""
        project = self.workspace(project_id)
        if project is None or not project.is_project:
            raise ValueError(f"project {project_id} does not exist")
        position = self._next_position(workspace_id, None)
        cursor = self.conn.execute(
            """INSERT INTO tasks
               (workspace_id, project_id, parent_id, text, done, done_at, origin_id,
                position, created_at)
               VALUES (?, ?, NULL, ?, 0, NULL, NULL, ?, ?)""",
            (workspace_id, project_id, project.title, position, _now()),
        )
        self.conn.commit()
        return self.task(cursor.lastrowid)

    def projects(self) -> list[ProjectRef]:
        """Every project with its live state and the days that mention it."""
        refs: list[ProjectRef] = []
        for workspace in self.workspaces("project"):
            state = self.project_state(workspace.id)
            mentions = self.conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE project_id = ?", (workspace.id,)
            ).fetchone()[0]
            days = [
                row["date"]
                for row in self.conn.execute(
                    """SELECT DISTINCT w.date FROM tasks t
                       JOIN workspaces w ON w.id = t.workspace_id
                       WHERE t.project_id = ? AND w.kind = 'day'
                       ORDER BY w.date""",
                    (workspace.id,),
                ).fetchall()
            ]
            refs.append(
                ProjectRef(
                    workspace=workspace,
                    total=state["total"],
                    done=state["done"],
                    open=state["open"],
                    mentions=mentions,
                    days=days,
                )
            )
        return refs

    def title_of(self, task: Task) -> str:
        """The title to show for an entry."""
        if task.project_id is not None:
            project = self.workspace(task.project_id)
            if project is not None:
                return project.title
        return task.text

    def counts(self, workspace_id: int) -> dict[str, int]:
        """Totals for a workspace, with the live state of its entries."""
        tasks = self.tasks_of(workspace_id)
        done = sum(1 for task in tasks if self.is_done(task))
        mentions = sum(1 for task in tasks if task.is_mention)
        return {
            "total": len(tasks),
            "done": done,
            "open": len(tasks) - done,
            "projects": mentions,
        }

    # ------------------------------------------------------------------
    # rollover
    # ------------------------------------------------------------------
    def rollover(self, target: str | None = None) -> list[int]:
        """Carry pending work into ``target`` and return the new entry ids.

        Only the newest appearance of every lineage travels, so a task
        walks one day at a time instead of piling up copies. A project is
        carried as a mention while it still has open work.
        """
        target_str = target or today()
        target_workspace = self.ensure_day(target_str)

        rows = self.conn.execute(
            """SELECT t.*, w.date AS day_date FROM tasks t
               JOIN workspaces w ON w.id = t.workspace_id
               WHERE w.kind = 'day' AND w.date < ?
               ORDER BY w.date, t.id""",
            (target_str,),
        ).fetchall()
        if not rows:
            return []

        by_id = {row["id"]: row for row in rows}
        descendants: dict[int, list[sqlite3.Row]] = defaultdict(list)
        for row in rows:
            if row["origin_id"] is not None:
                descendants[row["origin_id"]].append(row)

        def newest_in_lineage(task_id: int) -> sqlite3.Row:
            newest = by_id[task_id]
            seen = {task_id}
            frontier = [task_id]
            while frontier:
                current = frontier.pop()
                for child in descendants.get(current, []):
                    if child["id"] in seen:
                        continue
                    seen.add(child["id"])
                    frontier.append(child["id"])
                    if (child["day_date"], child["id"]) > (newest["day_date"], newest["id"]):
                        newest = child
            return newest

        carried: list[int] = []
        for row in rows:
            source = newest_in_lineage(row["id"])
            if self._entry_is_done(source):
                continue
            if self._already_carried(source["id"], target_workspace.id):
                continue
            carried.append(self._copy_entry(source, target_workspace.id))

        self.conn.commit()
        return carried

    def _entry_is_done(self, row: sqlite3.Row) -> bool:
        if row["project_id"] is not None:
            return self.project_is_done(row["project_id"])
        return bool(row["done"])

    def _already_carried(self, origin_id: int, workspace_id: int) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM carries WHERE origin_id = ? AND workspace_id = ?",
            (origin_id, workspace_id),
        ).fetchone()
        return row is not None

    def _copy_entry(self, row: sqlite3.Row, workspace_id: int) -> int:
        """Copy a day entry (a task or a project mention) into a day."""
        cursor = self.conn.execute(
            """INSERT INTO tasks
               (workspace_id, project_id, parent_id, text, done, done_at, origin_id,
                position, created_at)
               VALUES (?, ?, NULL, ?, 0, NULL, ?, ?, ?)""",
            (
                workspace_id,
                row["project_id"],
                row["text"],
                row["id"],
                row["position"],
                _now(),
            ),
        )
        self.conn.execute(
            "INSERT OR IGNORE INTO carries (origin_id, workspace_id, created_at) "
            "VALUES (?, ?, ?)",
            (row["id"], workspace_id, _now()),
        )
        return cursor.lastrowid

    # ------------------------------------------------------------------
    # search
    # ------------------------------------------------------------------
    def search(
        self,
        term: str,
        since: str | None = None,
        until: str | None = None,
        kinds: tuple[str, ...] = ("task", "note", "day", "project"),
        state: str | None = None,
        limit: int = 50,
    ) -> list[Hit]:
        """Search tasks, notes and workspace titles at once.

        Every term of the query must be present (AND). A trailing ``*``
        asks for a prefix match and the search ignores case and accents.
        """
        if not text_terms(term):
            return []

        hits: list[Hit] = []
        indexed = False

        if self.fts_enabled:
            try:
                hits = self._search_indexed(term, since, until, kinds, state)
                indexed = True
            except sqlite3.Error:
                hits = []

        if not indexed:
            hits = self._search_scanned(term, since, until, kinds, state)

        order = {"task": 0, "note": 1, "day": 2, "project": 3}
        hits.sort(key=lambda hit: hit.task_id or 0)
        hits.sort(key=lambda hit: order.get(hit.kind, 9))
        hits.sort(key=lambda hit: hit.date, reverse=True)

        if limit and limit > 0:
            hits = hits[:limit]
        return hits

    def _search_indexed(
        self,
        term: str,
        since: str | None,
        until: str | None,
        kinds: tuple[str, ...],
        state: str | None,
    ) -> list[Hit]:
        hits: list[Hit] = []

        if "task" in kinds:
            query = build_match_query(term)
            if query:
                sql = """SELECT t.id AS task_id, w.date AS date, t.text AS text,
                                bm25(tasks_fts) AS score
                         FROM tasks_fts
                         JOIN tasks t ON t.id = tasks_fts.rowid
                         JOIN workspaces w ON w.id = t.workspace_id
                         WHERE tasks_fts MATCH ?"""
                params: list = [query]
                if since:
                    sql += " AND w.date >= ?"
                    params.append(since)
                if until:
                    sql += " AND w.date <= ?"
                    params.append(until)
                if state == "open":
                    sql += " AND t.done = 0"
                elif state == "done":
                    sql += " AND t.done = 1"
                sql += " ORDER BY w.date DESC, t.id DESC"
                for row in self.conn.execute(sql, params):
                    hits.append(
                        Hit("task", row["date"] or "", row["text"], row["task_id"], row["score"])
                    )

        if "note" in kinds:
            query = build_match_query(term, column="note")
            if query:
                sql = """SELECT w.date AS date, w.title AS title, w.note AS text,
                                bm25(workspaces_fts) AS score
                         FROM workspaces_fts
                         JOIN workspaces w ON w.id = workspaces_fts.rowid
                         WHERE workspaces_fts MATCH ? AND w.note != ''"""
                params = [query]
                if since:
                    sql += " AND w.date >= ?"
                    params.append(since)
                if until:
                    sql += " AND w.date <= ?"
                    params.append(until)
                sql += " ORDER BY w.date DESC"
                for row in self.conn.execute(sql, params):
                    hits.append(Hit("note", row["date"] or "", row["text"], None, row["score"]))

        for kind in ("day", "project"):
            if kind not in kinds:
                continue
            query = build_match_query(term, column="title")
            if query:
                sql = """SELECT w.date AS date, w.title AS text, w.id AS workspace_id,
                                bm25(workspaces_fts) AS score
                         FROM workspaces_fts
                         JOIN workspaces w ON w.id = workspaces_fts.rowid
                         WHERE workspaces_fts MATCH ? AND w.kind = ?"""
                params = [query, kind]
                if since:
                    sql += " AND w.date >= ?"
                    params.append(since)
                if until:
                    sql += " AND w.date <= ?"
                    params.append(until)
                sql += " ORDER BY w.date DESC"
                for row in self.conn.execute(sql, params):
                    hits.append(
                        Hit(kind, row["date"] or "", row["text"], None, row["score"])
                    )

        return hits

    def _search_scanned(
        self,
        term: str,
        since: str | None,
        until: str | None,
        kinds: tuple[str, ...],
        state: str | None,
    ) -> list[Hit]:
        """Search without the index, comparing words in Python."""
        query_terms = text_terms(term)
        hits: list[Hit] = []

        if "task" in kinds:
            clauses: list[str] = []
            params: list = []
            if since:
                clauses.append("w.date >= ?")
                params.append(since)
            if until:
                clauses.append("w.date <= ?")
                params.append(until)
            if state == "open":
                clauses.append("t.done = 0")
            elif state == "done":
                clauses.append("t.done = 1")
            where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
            sql = f"""SELECT t.id AS task_id, w.date AS date, t.text AS text
                      FROM tasks t JOIN workspaces w ON w.id = t.workspace_id{where}
                      ORDER BY w.date DESC, t.id DESC"""
            for row in self.conn.execute(sql, params):
                if text_matches(row["text"], query_terms):
                    hits.append(Hit("task", row["date"] or "", row["text"], row["task_id"]))

        if "note" in kinds:
            clauses = []
            params = []
            if since:
                clauses.append("w.date >= ?")
                params.append(since)
            if until:
                clauses.append("w.date <= ?")
                params.append(until)
            clauses.append("w.note != ''")
            sql = (
                "SELECT w.date AS date, w.note AS text FROM workspaces w WHERE "
                + " AND ".join(clauses)
            )
            for row in self.conn.execute(sql, params):
                if text_matches(row["text"], query_terms):
                    hits.append(Hit("note", row["date"] or "", row["text"]))

        for kind in ("day", "project"):
            if kind not in kinds:
                continue
            clauses = []
            params = []
            if since:
                clauses.append("w.date >= ?")
                params.append(since)
            if until:
                clauses.append("w.date <= ?")
                params.append(until)
            clauses.append("w.kind = ?")
            params.append(kind)
            sql = (
                "SELECT w.date AS date, w.title AS text FROM workspaces w WHERE "
                + " AND ".join(clauses)
            )
            for row in self.conn.execute(sql, params):
                if text_matches(row["text"], query_terms):
                    hits.append(Hit(kind, row["date"] or "", row["text"]))

        return hits

    def close(self) -> None:
        self.conn.close()


@dataclass
class Hit:
    """A search result."""

    kind: str  # "task", "note", "day" or "project"
    date: str
    text: str
    task_id: Optional[int] = None
    score: float = 0.0
