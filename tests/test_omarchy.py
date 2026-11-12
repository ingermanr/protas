"""Behaviour tests for installing the Omarchy panel."""

import contextlib
import io
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from protas import cli, omarchy

FAKE_OMARCHY = """#!/bin/sh
echo "$@" >> "$FAKE_OMARCHY_LOG"
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


class OmarchyInstallTest(unittest.TestCase):
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
        }
        pause = mock.patch.object(omarchy, "BAR_RETRY_PAUSE", 0)
        pause.start()
        self.addCleanup(pause.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def provide_omarchy(self):
        script = self.bin / "omarchy"
        script.write_text(FAKE_OMARCHY)
        script.chmod(script.stat().st_mode | stat.S_IXUSR)

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, self.env), contextlib.redirect_stdout(
            out
        ), contextlib.redirect_stderr(err):
            code = cli.main(["--db", str(self.db), "omarchy", *args])
        return code, out.getvalue(), err.getvalue()

    def test_install_copies_the_panel_then_enables_it_and_restarts_the_bar(self):
        self.provide_omarchy()

        code, out, _ = self.run_cli("install")

        self.assertEqual(code, 0)
        manifest = json.loads((self.target / "manifest.json").read_text())
        self.assertEqual(manifest["id"], omarchy.PLUGIN_ID)
        self.assertTrue((self.target / "Panel.qml").is_file())
        self.assertEqual(
            self.calls(),
            [
                f"plugin validate {self.target}",
                "shell shell rescanPlugins",
                f"plugin enable {omarchy.PLUGIN_ID}",
                "restart shell",
            ],
        )
        self.assertIn(str(self.target), out)
        self.assertFalse(self.db.exists())

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

        code, _, _ = self.run_cli("install")

        self.assertEqual(code, 0)
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
        self.assertEqual(self.calls(), [f"plugin validate {self.target}"])


if __name__ == "__main__":
    unittest.main()
