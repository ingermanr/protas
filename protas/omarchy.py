"""Install the Omarchy bar panel that ships with protas.

The panel is optional: protas works without it, and it only makes sense
on a machine running Omarchy. Installing it copies the plugin folder into
the user's Omarchy plugins and asks Omarchy itself to validate it, enable
it, and restart the bar, so the bar never keeps an older panel in memory.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from importlib import resources
from pathlib import Path
from typing import Callable, Optional

PLUGIN_ID = "io.github.ingermanr.protas"

# The id the panel had before it took a public one. An install removes that
# copy so the bar does not show two panels.
OLD_PLUGIN_IDS = ("german-ds.protas",)

# The line of Panel.qml that names the command; the install writes the full
# path in, because the bar does not run with the user's shell PATH.
CLI_LINE = 'readonly property string cli: "protas"'

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


def install(
    restart: bool = True, notify: Optional[Callable[[str], None]] = None
) -> list[str]:
    """Install or update the panel and return the lines that report it.

    ``notify`` receives what is worth saying while the install is still
    running, such as the wait for a bar that is busy.
    """
    omarchy = shutil.which("omarchy")
    if omarchy is None:
        raise OmarchyError(
            "no encuentro el comando omarchy: el panel solo se instala en Omarchy"
        )

    command = protas_command()
    if command is None:
        raise OmarchyError(
            "no encuentro el comando protas: el panel lo necesita instalado,"
            " con uv tool install . o pipx install . (ver el README)"
        )

    target = plugins_dir() / PLUGIN_ID
    try:
        _replace_plugin(omarchy, target, command)
    except OSError as error:
        raise OmarchyError(f"no pude instalar el panel en {target}: {error}") from error

    # A folder that just appeared is unknown to the bar until it rescans.
    _ask_bar(omarchy, notify, "shell", "shell", "rescanPlugins")
    _ask_bar(omarchy, notify, "plugin", "enable", PLUGIN_ID)

    report = [f"Panel instalado en {target}"]
    for old_id in OLD_PLUGIN_IDS:
        if not os.path.lexists(target.parent / old_id):
            continue
        # The new panel is already enabled, so a removal that fails only
        # leaves an extra panel behind; the install still counts.
        try:
            _ask_bar(omarchy, notify, "plugin", "remove", old_id, "--yes")
            report.append(f"Panel anterior {old_id} quitado.")
        except OmarchyError as error:
            report.append(
                f"No pude quitar el panel anterior ({error});"
                f" quítalo con: omarchy plugin remove {old_id}"
            )
    if restart:
        _run(omarchy, "restart", "shell")
        report.append("Barra reiniciada: el panel ya está activo.")
    else:
        report.append("Para ver los cambios, reinicia la barra: omarchy restart shell")
    return report


def protas_command() -> Optional[str]:
    """The full path of the protas command the panel should run.

    The command that is running wins when it is the protas script itself;
    otherwise the one on the PATH. ``python -m protas`` is not a command
    the bar can run, so it does not count.
    """
    running = Path(sys.argv[0]) if sys.argv and sys.argv[0] else None
    if running is not None and running.name == "protas" and os.access(running, os.X_OK):
        return str(running.absolute())
    return shutil.which("protas")


def _replace_plugin(omarchy: str, target: Path, command: str) -> None:
    """Put the panel this protas ships where Omarchy reads it.

    The new copy is written and validated in a folder of its own, and only
    then takes the place of the installed one, so a copy that cannot be
    written or does not validate leaves the previous panel untouched.
    """
    source = resources.files("protas") / "integrations" / "omarchy" / PLUGIN_ID
    if not source.is_dir():
        raise OmarchyError("esta instalación de protas no trae el panel de Omarchy")

    target.parent.mkdir(parents=True, exist_ok=True)
    staging = _staging_dir(target)
    keep_staging = False
    try:
        fresh = staging / PLUGIN_ID
        fresh.mkdir()
        for item in source.iterdir():
            if item.is_file():
                (fresh / item.name).write_bytes(item.read_bytes())

        panel = fresh / "Panel.qml"
        text = panel.read_text(encoding="utf-8")
        if CLI_LINE not in text:
            raise OmarchyError("el panel de esta instalación no dice dónde está protas")
        # json.dumps quotes and escapes the path the way a QML string needs.
        panel.write_text(
            text.replace(CLI_LINE, f"readonly property string cli: {json.dumps(command)}"),
            encoding="utf-8",
        )

        _run(omarchy, "plugin", "validate", str(fresh))

        # ``shutil.move`` renames when it can and copies when the plugins
        # folder lives on another disk, where a rename is not possible.
        previous = staging / "previous"
        replaced = os.path.lexists(target)
        if replaced:
            shutil.move(str(target), str(previous))
        try:
            shutil.move(str(fresh), str(target))
        except OSError as error:
            if replaced:
                try:
                    # A copy cut short leaves a partial folder in the way.
                    shutil.rmtree(target, ignore_errors=True)
                    shutil.move(str(previous), str(target))
                except OSError:
                    keep_staging = True
                    raise OmarchyError(
                        f"no pude instalar el panel ({error}) ni devolver el anterior"
                        f" a su lugar; el panel anterior quedó en {previous}"
                    ) from error
            raise
    finally:
        if not keep_staging:
            shutil.rmtree(staging, ignore_errors=True)


def _staging_dir(target: Path) -> Path:
    """A private folder to prepare the panel in.

    Beside the plugins folder when possible: outside it, so the bar never
    sees a half-written plugin, and usually on the same disk, so the swap
    is a rename. When that place takes no new entries, the system's
    temporary folder does the job.
    """
    try:
        return Path(tempfile.mkdtemp(prefix=".protas-panel-", dir=target.parent.parent))
    except OSError:
        return Path(tempfile.mkdtemp(prefix=".protas-panel-"))


def _ask_bar(
    omarchy: str, notify: Optional[Callable[[str], None]], *args: str
) -> None:
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
            if attempt == 1 and notify is not None:
                notify("la barra de Omarchy no respondió, reintento…")
            time.sleep(BAR_RETRY_PAUSE)


def _run(omarchy: str, *args: str) -> None:
    step = " ".join(("omarchy", *args))
    try:
        result = subprocess.run(
            [omarchy, *args], capture_output=True, text=True, timeout=STEP_TIMEOUT
        )
    except subprocess.TimeoutExpired as error:
        raise OmarchyError(f"«{step}» no respondió en {STEP_TIMEOUT:g} s") from error
    except OSError as error:
        raise OmarchyError(f"no pude ejecutar «{step}»: {error}") from error
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise OmarchyError(f"falló «{step}»: {detail}" if detail else f"falló «{step}»")
