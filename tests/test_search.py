"""Behaviour tests for the full text search."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from protas import cli
from protas.store import Store


class SearchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(path=Path(self.tmp.name) / "protas.db")

        first = self.store.ensure_day("2026-11-10")
        second = self.store.ensure_day("2026-11-12")

        self.store.add_task("Migrar la base de datos", first.id)
        self.store.add_task("Revisar el informe anual", first.id)
        self.store.add_task("Comprar cafe con German", second.id)
        self.store.set_note(first.id, "Sesion de trabajo con el equipo")
        self.store.set_note(second.id, "Pendiente: migrar la base de datos")

        project = self.store.create_project("Refactor del panel de control")
        self.store.add_task("Medir el arranque", project.id)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def texts(self, hits):
        return [hit.text for hit in hits]

    def test_finds_tasks(self):
        hits = self.store.search("migrar")
        self.assertIn("Migrar la base de datos", self.texts(hits))

    def test_search_is_case_insensitive(self):
        hits = self.store.search("MIGRAR")
        self.assertIn("Migrar la base de datos", self.texts(hits))

    def test_search_ignores_accents(self):
        hits = self.store.search("sesion")
        self.assertTrue(any(hit.kind == "note" for hit in hits))

    def test_finds_notes(self):
        hits = self.store.search("equipo", kinds=("note",))
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].date, "2026-11-10")

    def test_finds_days_by_date(self):
        hits = self.store.search("2026-11-12", kinds=("day",))
        self.assertEqual([hit.date for hit in hits], ["2026-11-12"])

    def test_finds_projects_by_title(self):
        hits = self.store.search("refactor", kinds=("project",))
        self.assertEqual(len(hits), 1)
        self.assertIn("Refactor", hits[0].text)

    def test_every_term_must_be_present(self):
        hits = self.store.search("migrar cafe")
        self.assertEqual(hits, [])

    def test_prefix_search(self):
        hits = self.store.search("migr*")
        self.assertIn("Migrar la base de datos", self.texts(hits))

    def test_filters_by_date_range(self):
        hits = self.store.search("migrar", since="2026-11-11")
        self.assertEqual([hit.date for hit in hits], ["2026-11-12"])

    def test_filters_by_kind(self):
        hits = self.store.search("migrar", kinds=("task",))
        self.assertTrue(all(hit.kind == "task" for hit in hits))

    def test_filters_by_state(self):
        day = self.store.ensure_day("2026-11-10")
        self.store.set_done(self.store.tasks_of(day.id)[0].id, True)

        hits = self.store.search("migrar", kinds=("task",), state="done")
        self.assertEqual(len(hits), 1)

        hits = self.store.search("migrar", kinds=("task",), state="open")
        self.assertEqual(len(hits), 0)

    def test_special_characters_do_not_break_the_query(self):
        hits = self.store.search('informe: (2026) "x"')
        self.assertIsInstance(hits, list)

    def test_limit_caps_the_results(self):
        hits = self.store.search("migrar", limit=1)
        self.assertEqual(len(hits), 1)

    def test_results_come_newest_first(self):
        hits = self.store.search("migrar")
        dates = [hit.date for hit in hits]
        self.assertEqual(dates, sorted(dates, reverse=True))


class SearchWithoutIndexTest(SearchTest):
    """The search must keep working when SQLite has no FTS5 support."""

    def setUp(self):
        super().setUp()
        self.store.fts_enabled = False

    def test_both_engines_return_the_same_results(self):
        queries = ["migrar", "sesion", "migr*", "2026-11-12", "cafe", "refactor"]

        self.store.fts_enabled = True
        indexed = {query: sorted(hit.text for hit in self.store.search(query)) for query in queries}

        self.store.fts_enabled = False
        scanned = {query: sorted(hit.text for hit in self.store.search(query)) for query in queries}

        self.assertEqual(indexed, scanned)


class SearchCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "protas.db")

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["--db", self.db, *args])
        return code, out.getvalue()

    def test_search_prints_the_matches(self):
        self.run_cli("add", "Preparar la reunion", "--date", "2026-11-11")

        code, out = self.run_cli("search", "reunion")

        self.assertEqual(code, 0)
        self.assertIn("Preparar la reunion", out)
        self.assertIn("2026-11-11", out)

    def test_search_without_results_returns_one(self):
        code, out = self.run_cli("search", "nada-de-esto")
        self.assertEqual(code, 1)
        self.assertEqual(out.strip(), "")

    def test_json_output_is_machine_readable(self):
        import json

        self.run_cli("add", "Preparar la reunion", "--date", "2026-11-11")

        code, out = self.run_cli("search", "reunion", "--json")

        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload[0]["text"], "Preparar la reunion")
        self.assertEqual(payload[0]["kind"], "task")

    def test_a_query_can_be_typed_without_quotes(self):
        self.run_cli("add", "Preparar la reunion", "--date", "2026-11-11")

        code, out = self.run_cli("search", "preparar", "la", "reunion")

        self.assertEqual(code, 0)
        self.assertIn("Preparar la reunion", out)

    def test_an_empty_query_is_rejected(self):
        code, _ = self.run_cli("search")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
