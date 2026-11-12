"""Behaviour tests for the Obsidian export."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from protas import cli
from protas.store import Store


class ObsidianExportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "protas.db")
        self.out = Path(self.tmp.name) / "vault" / "protas"
        self.store = Store(path=self.db)
        self.day = self.store.open_day("2026-03-02")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def export(self, *extra):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(
                ["--db", self.db, "export", "--format", "obsidian", "--out", str(self.out), *extra]
            )
        return code, out.getvalue(), err.getvalue()

    def test_a_day_becomes_a_note_with_properties_its_note_and_its_tasks(self):
        self.store.set_note(self.day.id, "Dia de jardin")
        parent = self.store.add_task("Regar las plantas", self.day.id)
        self.store.set_done(self.store.add_task("Podar el rosal", self.day.id).id)

        code, out, _ = self.export()

        self.assertEqual(code, 0)
        self.assertIn(str(self.out), out)
        self.assertEqual(
            (self.out / "2026-03-02.md").read_text(),
            "---\n"
            "source: protas\n"
            "date: 2026-03-02\n"
            "tags:\n"
            "  - protas/dia\n"
            "---\n"
            "\n"
            "Dia de jardin\n"
            "\n"
            "- [ ] Regar las plantas\n"
            "- [x] Podar el rosal\n",
        )
        self.assertIsNotNone(parent)

    def test_a_project_is_its_own_note_and_the_day_links_to_it(self):
        task = self.store.add_task("Huerta nueva", self.day.id)
        project = self.store.promote(task.id)
        self.store.set_note(project.id, "Empezar por el compost")
        first = self.store.add_task("Comprar semillas", project.id)
        self.store.add_task("Sobres de tomate", project.id, first.id)
        self.store.set_done(self.store.add_task("Medir el cantero", project.id).id)

        code, _, _ = self.export()

        self.assertEqual(code, 0)
        self.assertIn(
            "- [ ] [[Huerta nueva]] (1/3)\n", (self.out / "2026-03-02.md").read_text()
        )
        self.assertEqual(
            (self.out / "projects" / "Huerta nueva.md").read_text(),
            "---\n"
            "source: protas\n"
            "tags:\n"
            "  - protas/proyecto\n"
            'avance: "1/3"\n'
            "---\n"
            "\n"
            "Empezar por el compost\n"
            "\n"
            "- [ ] Comprar semillas\n"
            "\t- [ ] Sobres de tomate\n"
            "- [x] Medir el cantero\n",
        )

    def test_a_title_obsidian_cannot_use_as_a_file_keeps_its_name_as_an_alias(self):
        self.store.promote(self.store.add_task("Web: inicio/contacto", self.day.id).id)
        self.store.promote(self.store.add_task("Plan [v2]", self.day.id).id)

        self.export()

        note = self.out / "projects" / "Web inicio contacto.md"
        self.assertIn('aliases:\n  - "Web: inicio/contacto"\n', note.read_text())
        self.assertTrue((self.out / "projects" / "Plan v2.md").is_file())
        day = (self.out / "2026-03-02.md").read_text()
        self.assertIn("- [ ] [[Web inicio contacto|Web: inicio/contacto]]\n", day)
        # Brackets in the label would close the link early: the name stands alone.
        self.assertIn("- [ ] [[Plan v2]]\n", day)

    def test_two_projects_with_the_same_title_get_their_own_notes(self):
        first = self.store.promote(self.store.add_task("Mudanza", self.day.id).id)
        second = self.store.promote(self.store.add_task("Mudanza", self.day.id).id)

        self.export()

        names = sorted(path.name for path in (self.out / "projects").iterdir())
        self.assertEqual(names, [f"Mudanza ({second.id}).md", "Mudanza.md"])
        day = (self.out / "2026-03-02.md").read_text()
        self.assertIn("[[Mudanza]]", day)
        self.assertIn(f"[[Mudanza ({second.id})|Mudanza]]", day)
        self.assertNotEqual(first.id, second.id)

    def test_a_note_that_protas_did_not_write_is_never_replaced(self):
        self.store.add_task("Regar las plantas", self.day.id)
        self.store.open_day("2026-03-03")
        self.store.add_task("Otra", self.store.open_day("2026-03-03").id)
        self.out.mkdir(parents=True)
        mine = self.out / "2026-03-02.md"
        mine.write_text("Mi diario escrito a mano\n")

        code, _, err = self.export()

        self.assertEqual(code, 1)
        self.assertIn("2026-03-02.md", err)
        self.assertEqual(mine.read_text(), "Mi diario escrito a mano\n")
        self.assertEqual([path.name for path in self.out.iterdir()], ["2026-03-02.md"])

    def test_exporting_again_refreshes_the_notes_protas_wrote(self):
        task = self.store.add_task("Regar las plantas", self.day.id)
        self.export()
        self.store.set_done(task.id)

        code, _, _ = self.export()

        self.assertEqual(code, 0)
        self.assertIn("- [x] Regar las plantas", (self.out / "2026-03-02.md").read_text())

    def test_the_plain_export_is_still_the_default(self):
        self.store.add_task("Regar las plantas", self.day.id)
        plain = Path(self.tmp.name) / "plain"

        with contextlib.redirect_stdout(io.StringIO()):
            code = cli.main(["--db", self.db, "export", "--out", str(plain)])

        self.assertEqual(code, 0)
        self.assertEqual(
            (plain / "2026-03-02.md").read_text(),
            "# 2026-03-02\n\n- [ ] Regar las plantas\n",
        )


if __name__ == "__main__":
    unittest.main()
