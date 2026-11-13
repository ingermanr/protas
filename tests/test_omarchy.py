"""Behaviour tests for installing the Omarchy panel."""

import contextlib
import errno
import io
import json
import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from protas import cli, omarchy

FAKE_OMARCHY = """#!/bin/sh
echo "$@" >> "$FAKE_OMARCHY_LOG"
if [ "$1 $2" = "$FAKE_OMARCHY_HANG" ]; then
  exec sleep 5
fi
if [ "$1 $2" = "$FAKE_OMARCHY_FAIL" ]; then
  echo "fake failure" >&2
  exit 1
fi
if [ "$1 $2" = "$FAKE_OMARCHY_BUSY_ONCE" ] && [ ! -e "$FAKE_OMARCHY_LOG.busy" ]; then
  : > "$FAKE_OMARCHY_LOG.busy"
  echo "omarchy-shell is not responding" >&2
  exit 1
fi
exit 0
"""


class OmarchyCase(unittest.TestCase):
    """A fake omarchy and protas on a private PATH and config folder."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db = root / "protas.db"
        self.config = root / "config"
        self.bin = root / "bin"
        self.bin.mkdir()
        self.log = root / "omarchy.log"
        self.target = self.config / "omarchy" / "plugins" / omarchy.PLUGIN_ID
        self.env = {
            "PATH": str(self.bin),
            "XDG_CONFIG_HOME": str(self.config),
            "FAKE_OMARCHY_LOG": str(self.log),
            "FAKE_OMARCHY_FAIL": "",
            "FAKE_OMARCHY_BUSY_ONCE": "",
            "FAKE_OMARCHY_HANG": "",
        }
        pause = mock.patch.object(omarchy, "BAR_RETRY_PAUSE", 0)
        pause.start()
        self.addCleanup(pause.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def provide_omarchy(self, protas=True):
        script = self.bin / "omarchy"
        script.write_text(FAKE_OMARCHY)
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        if protas:
            command = self.bin / "protas"
            command.write_text("#!/bin/sh\nexit 0\n")
            command.chmod(command.stat().st_mode | stat.S_IXUSR)

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, self.env), contextlib.redirect_stdout(
            out
        ), contextlib.redirect_stderr(err):
            code = cli.main(["--db", str(self.db), "omarchy", *args])
        return code, out.getvalue(), err.getvalue()

class OmarchyInstallTest(OmarchyCase):
    def test_install_copies_the_panel_then_enables_it_and_restarts_the_bar(self):
        self.provide_omarchy()

        code, out, _ = self.run_cli("install")

        self.assertEqual(code, 0)
        manifest = json.loads((self.target / "manifest.json").read_text())
        self.assertEqual(manifest["id"], omarchy.PLUGIN_ID)
        self.assertTrue((self.target / "Panel.qml").is_file())
        calls = self.calls()
        self.assertRegex(calls[0], rf"^plugin validate .*/{omarchy.PLUGIN_ID}$")
        self.assertEqual(
            calls[1:],
            [
                "shell shell rescanPlugins",
                f"plugin enable {omarchy.PLUGIN_ID}",
                "restart shell",
            ],
        )
        self.assertIn(str(self.target), out)
        self.assertFalse(self.db.exists())

    def test_the_panel_has_a_public_id_and_no_personal_path(self):
        self.assertEqual(omarchy.PLUGIN_ID, "io.github.ingermanr.protas")
        self.provide_omarchy()

        code, _, _ = self.run_cli("install")

        self.assertEqual(code, 0)
        panel = (self.target / "Panel.qml").read_text()
        self.assertIn(f'readonly property string cli: "{self.bin / "protas"}"', panel)
        self.assertNotIn(".local/bin", panel)
        self.assertNotIn("german-ds", panel)
        manifest = json.loads((self.target / "manifest.json").read_text())
        self.assertNotIn("german-ds", json.dumps(manifest))

    def test_without_the_protas_command_nothing_is_installed(self):
        self.provide_omarchy(protas=False)

        code, out, err = self.run_cli("install")

        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("no encuentro el comando protas", err)
        self.assertNotIn("Traceback", err)
        self.assertFalse(self.target.exists())
        self.assertEqual(self.calls(), [])

    def test_the_old_panel_is_removed_after_the_new_one_is_enabled(self):
        self.provide_omarchy()
        old = self.target.parent / "german-ds.protas"
        old.mkdir(parents=True)
        other = self.target.parent / "german-ds.spotify"
        other.mkdir()

        code, out, _ = self.run_cli("install")

        self.assertEqual(code, 0)
        self.assertEqual(
            self.calls()[1:],
            [
                "shell shell rescanPlugins",
                f"plugin enable {omarchy.PLUGIN_ID}",
                "plugin remove german-ds.protas --yes",
                "restart shell",
            ],
        )
        self.assertIn("german-ds.protas", out)
        self.assertTrue(other.exists())

    def test_an_old_panel_that_cannot_be_removed_is_reported(self):
        self.provide_omarchy()
        (self.target.parent / "german-ds.protas").mkdir(parents=True)
        self.env["FAKE_OMARCHY_FAIL"] = "plugin remove"

        code, out, _ = self.run_cli("install")

        self.assertEqual(code, 0)
        self.assertTrue((self.target / "Panel.qml").is_file())
        self.assertIn("omarchy plugin remove german-ds.protas", out)
        self.assertIn("restart shell", self.calls())

    def test_install_replaces_an_older_copy(self):
        self.provide_omarchy()
        self.target.mkdir(parents=True)
        (self.target / "Panel.qml").write_text("old panel")
        (self.target / "Leftover.qml").write_text("gone in this version")

        code, _, _ = self.run_cli("install")

        self.assertEqual(code, 0)
        self.assertNotEqual((self.target / "Panel.qml").read_text(), "old panel")
        self.assertFalse((self.target / "Leftover.qml").exists())

    def test_no_restart_leaves_the_bar_running(self):
        self.provide_omarchy()

        code, out, _ = self.run_cli("install", "--no-restart")

        self.assertEqual(code, 0)
        self.assertNotIn("restart shell", self.calls())
        self.assertIn("omarchy restart shell", out)

    def test_without_omarchy_nothing_is_installed(self):
        code, _, err = self.run_cli("install")

        self.assertEqual(code, 1)
        self.assertIn("omarchy", err)
        self.assertFalse(self.target.exists())
        self.assertFalse(self.db.exists())

    def test_a_bar_busy_reloading_is_asked_again(self):
        self.provide_omarchy()
        self.env["FAKE_OMARCHY_BUSY_ONCE"] = "plugin enable"

        code, _, err = self.run_cli("install")

        self.assertEqual(code, 0)
        self.assertIn("reintento", err)
        enable = f"plugin enable {omarchy.PLUGIN_ID}"
        self.assertEqual(self.calls().count(enable), 2)
        self.assertEqual(self.calls()[-1], "restart shell")

    def test_a_bar_that_never_answers_stops_the_install(self):
        self.provide_omarchy()
        self.env["FAKE_OMARCHY_FAIL"] = "plugin enable"

        code, _, err = self.run_cli("install")

        self.assertEqual(code, 1)
        self.assertIn("plugin enable", err)
        self.assertNotIn("restart shell", self.calls())

    def test_a_step_that_fails_stops_the_install(self):
        self.provide_omarchy()
        self.env["FAKE_OMARCHY_FAIL"] = "plugin validate"

        code, _, err = self.run_cli("install")

        self.assertEqual(code, 1)
        self.assertIn("fake failure", err)
        self.assertEqual(len(self.calls()), 1)

    def test_a_panel_that_does_not_validate_leaves_the_previous_one(self):
        self.provide_omarchy()
        self.target.mkdir(parents=True)
        (self.target / "Panel.qml").write_text("old panel")
        self.env["FAKE_OMARCHY_FAIL"] = "plugin validate"

        code, _, _ = self.run_cli("install")

        self.assertEqual(code, 1)
        self.assertEqual((self.target / "Panel.qml").read_text(), "old panel")
        self.assertEqual(
            [path.name for path in self.target.parent.parent.iterdir()], ["plugins"]
        )

    def test_a_successful_install_leaves_nothing_else_behind(self):
        self.provide_omarchy()
        self.target.mkdir(parents=True)
        (self.target / "Panel.qml").write_text("old panel")

        self.run_cli("install")

        self.assertEqual(
            [path.name for path in self.target.parent.parent.iterdir()], ["plugins"]
        )
        self.assertEqual(
            [path.name for path in self.target.parent.iterdir()], [omarchy.PLUGIN_ID]
        )

    def test_a_folder_that_cannot_be_written_is_reported_without_a_traceback(self):
        self.provide_omarchy()
        (self.config / "omarchy").mkdir(parents=True)
        (self.config / "omarchy" / "plugins").write_text("not a folder")

        code, _, err = self.run_cli("install")

        self.assertEqual(code, 1)
        self.assertIn("protas:", err)
        self.assertEqual(self.calls(), [])

    def test_a_plugins_folder_on_another_disk_still_gets_the_panel(self):
        self.provide_omarchy()
        self.target.mkdir(parents=True)
        (self.target / "Panel.qml").write_text("old panel")
        across = OSError(errno.EXDEV, "Invalid cross-device link")

        with mock.patch("os.rename", side_effect=across):
            code, _, _ = self.run_cli("install")

        self.assertEqual(code, 0)
        self.assertNotEqual((self.target / "Panel.qml").read_text(), "old panel")
        self.assertTrue((self.target / "manifest.json").is_file())

    def test_a_config_folder_that_takes_no_new_entries_still_gets_the_panel(self):
        self.provide_omarchy()
        self.target.parent.mkdir(parents=True)
        (self.target.parent / "another.plugin").mkdir()
        locked = self.target.parent.parent
        locked.chmod(0o555)
        try:
            code, _, _ = self.run_cli("install")
        finally:
            locked.chmod(0o755)

        self.assertEqual(code, 0)
        self.assertTrue((self.target / "Panel.qml").is_file())
        self.assertEqual([path.name for path in locked.iterdir()], ["plugins"])

    def test_a_previous_panel_that_cannot_be_put_back_is_not_thrown_away(self):
        self.provide_omarchy()
        self.target.mkdir(parents=True)
        (self.target / "Panel.qml").write_text("old panel")
        real_move = shutil.move
        moves = []

        def move(source, destination):
            moves.append(source)
            if len(moves) > 1:
                raise OSError(errno.EIO, "Input/output error")
            return real_move(source, destination)

        with mock.patch.object(omarchy.shutil, "move", side_effect=move):
            code, _, err = self.run_cli("install")

        self.assertEqual(code, 1)
        kept = [word for word in err.split() if "protas-panel-" in word]
        self.assertEqual(len(kept), 1, err)
        saved = Path(kept[0].rstrip(".,;:"))
        self.addCleanup(shutil.rmtree, saved.parent, True)
        self.assertEqual((saved / "Panel.qml").read_text(), "old panel")

    def test_an_omarchy_that_cannot_be_run_is_named_as_the_cause(self):
        self.provide_omarchy()
        script = self.bin / "omarchy"
        script.write_text("#!/nonexistent/interpreter\n")
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        self.target.mkdir(parents=True)
        (self.target / "Panel.qml").write_text("old panel")

        code, _, err = self.run_cli("install")

        self.assertEqual(code, 1)
        self.assertIn("omarchy plugin validate", err)
        self.assertNotIn("Traceback", err)
        self.assertEqual((self.target / "Panel.qml").read_text(), "old panel")

    def test_a_step_that_hangs_is_given_up(self):
        self.provide_omarchy()
        self.env["FAKE_OMARCHY_HANG"] = "restart shell"

        with mock.patch.object(omarchy, "STEP_TIMEOUT", 0.3):
            code, _, err = self.run_cli("install")

        self.assertEqual(code, 1)
        self.assertIn("omarchy restart shell", err)


if __name__ == "__main__":
    unittest.main()


class PanelRefreshTest(OmarchyCase):
    """An installed panel that no longer matches this protas is replaced."""

    def install_panel(self):
        self.provide_omarchy()
        code, _, _ = self.run_cli("install")
        self.assertEqual(code, 0)
        self.log.unlink()

    def refresh(self):
        with mock.patch.dict(os.environ, self.env):
            return omarchy.refresh_installed()

    def run_command(self, *args, interactive=True, env=None):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {**self.env, **(env or {})}), mock.patch.object(
            cli, "_interactive", return_value=interactive
        ), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["--db", str(self.db), *args])
        return code, out.getvalue(), err.getvalue()

    def test_a_panel_that_matches_is_left_alone(self):
        self.install_panel()

        self.assertIsNone(self.refresh())
        self.assertEqual(self.calls(), [])

    def test_an_older_panel_is_replaced_and_the_bar_restarted(self):
        self.install_panel()
        (self.target / "Panel.qml").write_text("old panel")

        report = self.refresh()

        self.assertIsNotNone(report)
        panel = (self.target / "Panel.qml").read_text()
        self.assertIn(f'readonly property string cli: "{self.bin / "protas"}"', panel)
        self.assertEqual(
            self.calls()[1:],
            ["shell shell rescanPlugins", f"plugin enable {omarchy.PLUGIN_ID}", "restart shell"],
        )

    def test_a_panel_that_points_at_another_protas_is_fixed(self):
        self.install_panel()
        panel = self.target / "Panel.qml"
        panel.write_text(panel.read_text().replace(str(self.bin / "protas"), "/gone/protas"))

        self.assertIsNotNone(self.refresh())
        self.assertNotIn("/gone/protas", panel.read_text())

    def test_without_an_installed_panel_nothing_happens(self):
        self.provide_omarchy()

        self.assertIsNone(self.refresh())
        self.assertFalse(self.target.parent.exists())
        self.assertEqual(self.calls(), [])

    def test_without_omarchy_nothing_happens(self):
        self.install_panel()
        (self.bin / "omarchy").unlink()
        (self.target / "Panel.qml").write_text("old panel")

        self.assertIsNone(self.refresh())
        self.assertEqual((self.target / "Panel.qml").read_text(), "old panel")

    def test_a_command_in_a_terminal_refreshes_the_panel_and_says_so(self):
        self.install_panel()
        (self.target / "Panel.qml").write_text("old panel")

        code, out, err = self.run_command("add", "Comprar pan", "--date", "2026-11-11")

        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "1")
        self.assertIn("panel de Omarchy actualizado", err)
        self.assertNotEqual((self.target / "Panel.qml").read_text(), "old panel")

    def test_a_command_without_a_terminal_leaves_the_panel(self):
        self.install_panel()
        (self.target / "Panel.qml").write_text("old panel")

        code, _, err = self.run_command("list", "--all", "--json", interactive=False)

        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertEqual((self.target / "Panel.qml").read_text(), "old panel")
        self.assertEqual(self.calls(), [])

    def test_the_refresh_can_be_turned_off(self):
        self.install_panel()
        (self.target / "Panel.qml").write_text("old panel")

        code, _, _ = self.run_command("list", env={"PROTAS_NO_PANEL_UPDATE": "1"})

        self.assertEqual(code, 0)
        self.assertEqual((self.target / "Panel.qml").read_text(), "old panel")

    def test_a_refresh_that_fails_does_not_stop_the_command(self):
        self.install_panel()
        (self.target / "Panel.qml").write_text("old panel")
        self.env["FAKE_OMARCHY_FAIL"] = "plugin validate"

        code, out, err = self.run_command("add", "Comprar pan", "--date", "2026-11-11")

        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "1")
        self.assertIn("no pude actualizar el panel de Omarchy", err)
        self.assertIn("protas omarchy install", err)
        self.assertNotIn("Traceback", err)
        self.assertEqual((self.target / "Panel.qml").read_text(), "old panel")
