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



class EmptyProjectTest(unittest.TestCase):
    """A project without tasks is completed like any other entry."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(path=Path(self.tmp.name) / "protas.db")
        self.day = self.store.ensure_day("2026-11-02")
        self.entry = self.store.add_task("Proyecto vacio", self.day.id)
        self.project = self.store.promote(self.entry.id)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def _kinds(self):
        return [entry.kind for entry in self.store.history(self.project.id).entries]

    def test_it_starts_pending(self):
        self.assertFalse(self.store.is_done(self.store.task(self.entry.id)))
        self.assertFalse(self.store.project_is_done(self.project.id))

    def test_marking_the_entry_completes_the_project(self):
        self.store.set_done(self.entry.id, True)

        self.assertTrue(self.store.is_done(self.store.task(self.entry.id)))
        self.assertTrue(self.store.project_is_done(self.project.id))
        self.assertEqual(self.store.counts(self.day.id)["done"], 1)
        self.assertEqual(self._kinds().count("project_completed"), 1)
        # finished work does not travel
        self.assertEqual(self.store.rollover("2026-11-03"), [])

    def test_it_can_be_reopened(self):
        self.store.set_done(self.entry.id, True)
        self.store.set_done(self.entry.id, False)

        self.assertFalse(self.store.project_is_done(self.project.id))
        self.assertEqual(self._kinds().count("project_reopened"), 1)
        self.assertEqual(len(self.store.rollover("2026-11-03")), 1)

    def test_every_day_that_mentions_it_shows_the_same_state(self):
        carried = self.store.rollover("2026-11-03")
        self.store.set_done(carried[0], True)

        self.assertTrue(self.store.is_done(self.store.task(self.entry.id)))
        self.assertTrue(self.store.is_done(self.store.task(carried[0])))

        later = self.store.ensure_day("2026-11-05")
        mention = self.store.add_mention(self.project.id, later.id)
        self.assertTrue(self.store.is_done(mention))

    def test_a_new_task_reopens_it(self):
        self.store.set_done(self.entry.id, True)
        task = self.store.add_task("Aparecio trabajo", self.project.id)

        self.assertFalse(self.store.project_is_done(self.project.id))

        # and it stays open if that task goes away again
        self.store.delete_task(task.id)
        self.assertFalse(self.store.project_is_done(self.project.id))

    def test_a_project_with_tasks_still_follows_its_tasks(self):
        first = self.store.add_task("Uno", self.project.id)
        second = self.store.add_task("Dos", self.project.id)

        self.store.set_done(first.id, True)
        self.assertFalse(self.store.project_is_done(self.project.id))

        self.store.set_done(self.entry.id, True)
        self.assertTrue(self.store.task(second.id).done)
        self.assertTrue(self.store.project_is_done(self.project.id))

        self.store.set_done(second.id, False)
        self.assertFalse(self.store.is_done(self.store.task(self.entry.id)))



class NestedProjectTest(unittest.TestCase):
    """A project inside a project counts with its live state."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(path=Path(self.tmp.name) / "protas.db")
        self.day = self.store.ensure_day("2026-11-02")
        self.entry = self.store.add_task("Externo", self.day.id)
        self.outer = self.store.promote(self.entry.id)
        self.inner_entry = self.store.add_task("Interno", self.outer.id)
        self.inner = self.store.promote(self.inner_entry.id)
        self.leaf = self.store.add_task("Hoja", self.inner.id)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_finishing_the_inner_project_finishes_the_outer_one(self):
        self.store.set_done(self.leaf.id, True)

        self.assertTrue(self.store.project_is_done(self.inner.id))
        self.assertEqual(
            self.store.project_state(self.outer.id), {"total": 1, "done": 1, "open": 0}
        )
        self.assertTrue(self.store.project_is_done(self.outer.id))
        self.assertTrue(self.store.is_done(self.store.task(self.entry.id)))
        self.assertEqual(self.store.rollover("2026-11-03"), [])

    def test_reopening_inside_reopens_the_outer_one(self):
        self.store.set_done(self.leaf.id, True)
        self.store.set_done(self.leaf.id, False)

        self.assertFalse(self.store.project_is_done(self.outer.id))
        self.assertEqual(
            self.store.project_state(self.outer.id), {"total": 1, "done": 0, "open": 1}
        )

    def test_completing_the_outer_project_completes_what_is_inside(self):
        self.store.set_done(self.entry.id, True)

        self.assertTrue(self.store.task(self.leaf.id).done)
        self.assertTrue(self.store.project_is_done(self.inner.id))
        self.assertTrue(self.store.project_is_done(self.outer.id))

        self.store.set_done(self.entry.id, False)
        self.assertFalse(self.store.task(self.leaf.id).done)
        self.assertFalse(self.store.project_is_done(self.outer.id))

    def test_plain_tasks_and_inner_projects_count_together(self):
        plain = self.store.add_task("Suelta", self.outer.id)

        self.store.set_done(self.leaf.id, True)
        self.assertEqual(
            self.store.project_state(self.outer.id), {"total": 2, "done": 1, "open": 1}
        )
        self.assertFalse(self.store.project_is_done(self.outer.id))

        self.store.set_done(plain.id, True)
        self.assertTrue(self.store.project_is_done(self.outer.id))

    def test_projects_that_mention_each_other_do_not_loop(self):
        self.store.add_mention(self.outer.id, self.inner.id)

        self.assertFalse(self.store.project_is_done(self.outer.id))
        self.store.set_done(self.entry.id, True)
        self.assertTrue(self.store.task(self.leaf.id).done)



class DaySubtaskTest(unittest.TestCase):
    """A day holds flat entries: a task that gets a subtask is a project."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(path=Path(self.tmp.name) / "protas.db")
        self.day = self.store.ensure_day("2026-11-02")
        self.parent = self.store.add_task("Padre", self.day.id)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_a_subtask_in_a_day_turns_the_task_into_a_project(self):
        child = self.store.add_task("Hijo", self.day.id, parent_id=self.parent.id)

        parent = self.store.task(self.parent.id)
        self.assertTrue(parent.is_mention)
        project = self.store.workspace(parent.project_id)
        self.assertEqual((project.kind, project.title), ("project", "Padre"))

        # the subtask lives inside the project, at the top
        self.assertEqual(child.workspace_id, project.id)
        self.assertIsNone(child.parent_id)
        self.assertEqual([t.text for t in self.store.tasks_of(project.id)], ["Hijo"])

        # and the day keeps one flat entry
        entries = self.store.tasks_of(self.day.id)
        self.assertEqual([(e.id, e.children) for e in entries], [(self.parent.id, [])])

        kinds = [entry.kind for entry in self.store.history(project.id).entries]
        self.assertEqual(kinds.count("created"), 1)
        self.assertEqual(kinds.count("task_added"), 1)

    def test_a_second_subtask_goes_into_the_same_project(self):
        self.store.add_task("Uno", self.day.id, parent_id=self.parent.id)
        self.store.add_task("Dos", self.day.id, parent_id=self.parent.id)

        self.assertEqual(len(self.store.projects()), 1)
        project_id = self.store.task(self.parent.id).project_id
        self.assertEqual([t.text for t in self.store.tasks_of(project_id)], ["Uno", "Dos"])

    def test_the_next_day_receives_the_project_and_not_loose_subtasks(self):
        self.store.add_task("Hijo", self.day.id, parent_id=self.parent.id)

        carried = self.store.rollover("2026-11-03")

        self.assertEqual(len(carried), 1)
        entry = self.store.task(carried[0])
        self.assertTrue(entry.is_mention)
        self.assertEqual(self.store.title_of(entry), "Padre")

    def test_a_parent_from_another_workspace_is_still_refused(self):
        other = self.store.ensure_day("2026-11-03")
        with self.assertRaises(ValueError):
            self.store.add_task("Hijo", other.id, parent_id=self.parent.id)
        self.assertFalse(self.store.task(self.parent.id).is_mention)

    def test_subtasks_inside_a_project_still_nest(self):
        project = self.store.create_project("Con arbol")
        top = self.store.add_task("Arriba", project.id)
        child = self.store.add_task("Abajo", project.id, parent_id=top.id)

        self.assertEqual(child.parent_id, top.id)
        self.assertEqual(len(self.store.projects()), 1)


if __name__ == "__main__":
    unittest.main()
