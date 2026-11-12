"""Install the Omarchy bar panel that ships with protas.

The panel is optional: protas works without it, and it only makes sense
on a machine running Omarchy. Installing it copies the plugin folder into
the user's Omarchy plugins and asks Omarchy itself to validate it, enable
it, and restart the bar, so the bar never keeps an older panel in memory.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from importlib import resources
from pathlib import Path

PLUGIN_ID = "german-ds.protas"

# Replacing the folder makes the bar reload the plugin, and while it does
# it answers nothing. Calls to the bar are repeated until it is back.
BAR_ATTEMPTS = 5
BAR_RETRY_PAUSE = 1.0

# No step of the install is slow; one that takes this long is stuck.
STEP_TIMEOUT = 30.0


class OmarchyError(Exception):
    """The panel could not be installed; the message says why."""


def plugins_dir() -> Path:
    """Where Omarchy looks for the user's plugins."""
    config = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(config) / "omarchy" / "plugins"


def install(restart: bool = True) -> list[str]:
    """Install or update the panel and return the lines that report it."""
    omarchy = shutil.which("omarchy")
    if omarchy is None:
        raise OmarchyError(
            "no encuentro el comando omarchy: el panel solo se instala en Omarchy"
        )

    target = plugins_dir() / PLUGIN_ID
    try:
        _replace_plugin(omarchy, target)
    except OSError as error:
        raise OmarchyError(f"no pude escribir el panel en {target}: {error}") from error

    # A folder that just appeared is unknown to the bar until it rescans.
    _ask_bar(omarchy, "shell", "shell", "rescanPlugins")
    _ask_bar(omarchy, "plugin", "enable", PLUGIN_ID)

    report = [f"Panel instalado en {target}"]
    if restart:
        _run(omarchy, "restart", "shell")
        report.append("Barra reiniciada: el panel ya está activo.")
    else:
        report.append("Para ver los cambios, reinicia la barra: omarchy restart shell")
    return report


def _replace_plugin(omarchy: str, target: Path) -> None:
    """Put the panel this protas ships where Omarchy reads it.

    The new copy is written and validated beside the plugins folder, and
    only then takes the place of the installed one, so a copy that cannot
    be written or does not validate leaves the previous panel untouched.
    """
    source = resources.files("protas") / "integrations" / "omarchy" / PLUGIN_ID
    if not source.is_dir():
        raise OmarchyError("esta instalación de protas no trae el panel de Omarchy")

    target.parent.mkdir(parents=True, exist_ok=True)
    # Outside the plugins folder, so the bar never sees a half-written
    # plugin, and on the same filesystem, so the swap is a rename.
    staging = Path(tempfile.mkdtemp(prefix=".protas-panel-", dir=target.parent.parent))
    try:
        fresh = staging / PLUGIN_ID
        fresh.mkdir()
        for item in source.iterdir():
            if item.is_file():
                (fresh / item.name).write_bytes(item.read_bytes())

        _run(omarchy, "plugin", "validate", str(fresh))

        previous = staging / "previous"
        replaced = os.path.lexists(target)
        if replaced:
            target.rename(previous)
        try:
            fresh.rename(target)
        except OSError:
            if replaced:
                previous.rename(target)
            raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _ask_bar(omarchy: str, *args: str) -> None:
    """Run a step the running bar has to answer, waiting while it is busy.

    Both steps are safe to repeat: a rescan changes nothing by itself and
    enabling an enabled plugin leaves it where it was.
    """
    for attempt in range(1, BAR_ATTEMPTS + 1):
        try:
            _run(omarchy, *args)
            return
        except OmarchyError:
            if attempt == BAR_ATTEMPTS:
                raise
            time.sleep(BAR_RETRY_PAUSE)


def _run(omarchy: str, *args: str) -> None:
    step = " ".join(("omarchy", *args))
    try:
        result = subprocess.run(
            [omarchy, *args], capture_output=True, text=True, timeout=STEP_TIMEOUT
        )
    except subprocess.TimeoutExpired as error:
        raise OmarchyError(f"«{step}» no respondió en {STEP_TIMEOUT:g} s") from error
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise OmarchyError(f"falló «{step}»: {detail}" if detail else f"falló «{step}»")
