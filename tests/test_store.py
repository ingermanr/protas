"""Behaviour tests for workspaces, tasks and projects."""

import tempfile
import unittest
from pathlib import Path

from protas.store import Store


class WorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(path=Path(self.tmp.name) / "protas.db")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def day(self, date_str="2026-11-10"):
        return self.store.ensure_day(date_str)

    # ------------------------------------------------------------------
    # workspaces
    # ------------------------------------------------------------------
    def test_a_day_is_a_workspace_titled_with_its_date(self):
        day = self.day()
        self.assertEqual(day.kind, "day")
        self.assertEqual(day.title, "2026-11-10")
        self.assertEqual(day.note, "")

    def test_ensure_day_is_idempotent(self):
        self.assertEqual(self.day().id, self.day().id)

    def test_each_workspace_has_its_own_note(self):
        day = self.day()
        project = self.store.create_project("Migrar")

        self.store.set_note(day.id, "nota del dia")
        self.store.set_note(project.id, "brief del proyecto")

        self.assertEqual(self.store.note(day.id), "nota del dia")
        self.assertEqual(self.store.note(project.id), "brief del proyecto")

    # ------------------------------------------------------------------
    # tasks
    # ------------------------------------------------------------------
    def test_tasks_belong_to_a_workspace(self):
        day = self.day()
        self.store.add_task("Escribir la propuesta", day.id)

        entries = self.store.tasks_of(day.id)
        self.assertEqual([entry.text for entry in entries], ["Escribir la propuesta"])

    def test_set_done_records_the_timestamp(self):
        day = self.day()
        task = self.store.add_task("Cosas", day.id)

        self.store.set_done(task.id, True)

        stored = self.store.task(task.id)
        self.assertTrue(stored.done)
        self.assertIsNotNone(stored.done_at)

    def test_completing_a_task_completes_its_children(self):
        project = self.store.create_project("Proyecto")
        parent = self.store.add_task("Principal", project.id)
        child = self.store.add_task("Secundaria", project.id, parent_id=parent.id)

        self.store.set_done(parent.id, True)

        self.assertTrue(self.store.task(parent.id).done)
        self.assertTrue(self.store.task(child.id).done)

    def test_reopening_a_child_reopens_its_parent(self):
        project = self.store.create_project("Proyecto")
        parent = self.store.add_task("Principal", project.id)
        child = self.store.add_task("Secundaria", project.id, parent_id=parent.id)
        self.store.set_done(parent.id, True)

        self.store.set_done(child.id, False)

        self.assertFalse(self.store.task(parent.id).done)

    def test_deleting_a_task_deletes_its_children(self):
        project = self.store.create_project("Proyecto")
        parent = self.store.add_task("Principal", project.id)
        self.store.add_task("Secundaria", project.id, parent_id=parent.id)

        self.store.delete_task(parent.id)

        self.assertEqual(self.store.tasks_of(project.id), [])

    def test_counts_split_done_and_open(self):
        day = self.day()
        first = self.store.add_task("A", day.id)
        self.store.add_task("B", day.id)
        self.store.set_done(first.id, True)

        counts = self.store.counts(day.id)
        self.assertEqual(counts["total"], 2)
        self.assertEqual(counts["done"], 1)
        self.assertEqual(counts["open"], 1)
        self.assertEqual(counts["projects"], 0)

    # ------------------------------------------------------------------
    # projects
    # ------------------------------------------------------------------
    def test_promoting_a_task_creates_a_project_workspace(self):
        day = self.day()
        task = self.store.add_task("Migrar la base de datos", day.id)

        project = self.store.promote(task.id)

        self.assertEqual(project.kind, "project")
        self.assertEqual(project.title, "Migrar la base de datos")
        self.assertIsNone(project.date)

    def test_a_promoted_task_becomes_a_mention(self):
        day = self.day()
        task = self.store.add_task("Migrar la base de datos", day.id)

        project = self.store.promote(task.id)

        entry = self.store.tasks_of(day.id)[0]
        self.assertTrue(entry.is_mention)
        self.assertEqual(entry.project_id, project.id)
        self.assertEqual(self.store.title_of(entry), "Migrar la base de datos")

    def test_promoting_keeps_the_place_in_the_agenda(self):
        day = self.day()
        first = self.store.add_task("Primera", day.id)
        second = self.store.add_task("Segunda", day.id)

        self.store.promote(first.id)

        entries = self.store.tasks_of(day.id)
        self.assertEqual([entry.id for entry in entries], [first.id, second.id])

    def test_the_children_of_a_promoted_task_move_inside_the_project(self):
        day = self.day()
        task = self.store.add_task("Migrar la base de datos", day.id)
        project = self.store.workspace(self.store.promote(task.id).id)
        child = self.store.add_task("Esquema", project.id, parent_id=None)

        entries = self.store.tasks_of(project.id)
        self.assertEqual([entry.id for entry in entries], [child.id])

    def test_a_project_has_one_live_state_for_every_day(self):
        day = self.day()
        task = self.store.add_task("Migrar la base de datos", day.id)
        project = self.store.promote(task.id)
        self.store.add_task("Esquema", project.id)

        self.assertFalse(self.store.is_done(self.store.tasks_of(day.id)[0]))

        self.store.set_done(self.store.tasks_of(project.id)[0].id, True)

        self.assertTrue(self.store.is_done(self.store.tasks_of(day.id)[0]))

    def test_reopening_a_task_of_the_project_reopens_the_mention(self):
        day = self.day()
        task = self.store.add_task("Migrar la base de datos", day.id)
        project = self.store.promote(task.id)
        inner = self.store.add_task("Esquema", project.id)
        self.store.set_done(inner.id, True)

        self.store.set_done(inner.id, False)

        self.assertFalse(self.store.is_done(self.store.tasks_of(day.id)[0]))

    def test_completing_a_mention_completes_the_whole_project(self):
        day = self.day()
        task = self.store.add_task("Migrar la base de datos", day.id)
        project = self.store.promote(task.id)
        inner = self.store.add_task("Esquema", project.id)

        self.store.set_done(self.store.tasks_of(day.id)[0].id, True)

        self.assertTrue(self.store.task(inner.id).done)

    def test_deleting_a_mention_leaves_the_project_alive(self):
        day = self.day()
        task = self.store.add_task("Migrar la base de datos", day.id)
        project = self.store.promote(task.id)

        self.store.delete_task(self.store.tasks_of(day.id)[0].id)

        self.assertEqual(self.store.tasks_of(day.id), [])
        self.assertIsNotNone(self.store.workspace(project.id))

    def test_projects_are_listed_once_each(self):
        day = self.day()
        task = self.store.add_task("Migrar la base de datos", day.id)
        project = self.store.promote(task.id)
        self.store.add_task("Esquema", project.id)

        projects = self.store.projects()
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0].workspace.title, "Migrar la base de datos")
        self.assertEqual(projects[0].total, 1)
        self.assertEqual(projects[0].days, ["2026-11-10"])

    def test_a_project_can_be_added_to_the_agenda_of_another_day(self):
        first = self.day("2026-11-10")
        second = self.day("2026-11-11")
        task = self.store.add_task("Migrar la base de datos", first.id)
        project = self.store.promote(task.id)

        self.store.add_mention(project.id, second.id)

        self.assertEqual(len(self.store.tasks_of(second.id)), 1)
        self.assertEqual(self.store.projects()[0].days, ["2026-11-10", "2026-11-11"])


if __name__ == "__main__":
    unittest.main()
