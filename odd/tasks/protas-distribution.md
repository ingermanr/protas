# protas: install for anyone and ship as an Omarchy package

Objective: anyone who clones or downloads the repository can install and use
protas from the README, the Omarchy panel has no personal paths or ids, and
protas can be installed as an Omarchy (OPR) package. Branch:
`feature/distribution` (from `main` f1df9af). Delivery: `ask-on-risk`; the
user authorizes push, merge, release and the OPR PR. Test runner:
`python -m unittest discover -s tests`.

## Specs

- S1 (user, 2026-11-13): "analiza la aplicación concientemente en cuanto a
  cómo cualquier usuario la va a instalar en su equipo, que las instrucciones
  sean para el uso de cuallquier usuario y no referencias de mis rutas de
  trabajo o mi equipo sino adaptado al uso de cualquier usuario"
- S2 (user, 2026-11-12): "las indicaciones de uso del panel omarchy, que no lo
  van a poder usa usuarios de windows o iOS"
- S3 (user, 2026-11-13): "revisa que debemos hacer para que sea una
  aplicación de omarchy, como esta que te comparto:
  https://github.com/thisisgm/flea"
- S4 (approved plan, 2026-11-13): README explains clone or download, installs
  with `pipx` or `uv tool install` instead of `pip install -e .`, and states
  the platforms (CLI everywhere with Python 3.11+, TUI on Linux and macOS,
  panel only on Omarchy).
- S5 (approved plan): the panel finds `protas` on the `PATH` instead of
  `~/.local/bin/protas`, its id becomes `io.github.ingermanr.protas`, and
  `protas omarchy install` removes only the old `german-ds.protas` copy.
- S6 (approved plan): a `PKGBUILD` (`arch=any`, depends on `python`) installs
  `/usr/bin/protas` and the panel under `/usr/share/protas/`, plus a
  `.desktop` entry and icon that open the TUI in a terminal; tested locally
  with `makepkg` and `pacman -U`. The GitHub release and the OPR PR are the
  user's; the README of the work leaves the steps.

## Tasks

- [x] T1 (S1, S2, S4): README install, download and platforms; the TUI says
  it needs curses instead of a traceback. Route: inline. Commit: see L4.
- [x] T2 (S5): portable panel and new plugin id with cleanup of the old one.
  Route: inline. Risk: item 3 (renames the plugin id an installed panel uses).
  Commit: see L5.
- [x] T3 (S3, S6): Arch package, desktop entry and icon, local build and
  install; release and OPR steps documented. Route: inline. Risk: item 5
  (packaging and delivery). Commit: see L6. `pacman -U` pending: needs the
  user's sudo.

## Log

- L1 (2026-11-13, user): "vamos con el readme, pero analiza la aplicación
  concientemente en cuanto a cómo cualquier usuario la va a instalar en su
  equipo, que las instrucciones sean para el uso de cuallquier usuario y no
  referencias de mis rutas de trabajo o mi equipo sino adaptado al uso de
  cualquier usuario, también revisa que debemos hacer para que sea una
  aplicación de omarchy, como esta que te comparto:
  https://github.com/thisisgm/flea"
- L2 (2026-11-13): analysis. `pip install -e .` fails on Arch/Omarchy
  (`/usr/lib/python3.14/EXTERNALLY-MANAGED`) and ties the command to the
  clone; the README never says how to get the code; `Panel.qml` hardcodes
  `~/.local/bin/protas`; the plugin id `german-ds.protas` is the local user
  name (flea uses `io.github.thisisgm.flea-shelf`); the TUI needs `curses`
  and `termios` (not on Windows), the CLI loads it lazily. flea ships through
  `omacom/omarchy-pkgs` (`omarchy pkg add flea`): PKGBUILD building from a
  GitHub release tarball, `.omarchy/package.json` with an upstream watch, a
  PR a maintainer approves.
- L3 (2026-11-13, user): "dale" to the three-delivery plan.
- L4 (2026-11-13): T1. README "Instalación" rewritten: platforms table (CLI
  everywhere, TUI Linux/macOS/WSL, panel only Omarchy, no iOS/Android),
  `git clone` or Code → Download ZIP, `python3 -m protas` without
  installing, `uv tool install .` or `pipx install .`, why `pip install`
  fails on Arch (externally managed), update/uninstall, where the data
  lives. `uv tool install .` checked in a scratch tool dir: installs
  `protas` with the panel files. `protas`/`protas tui` without curses exit 1
  with "la TUI necesita curses…" (RED observed: ModuleNotFoundError
  traceback). Found: `ingermanr/protas` is private, so nobody else can clone
  it or build an OPR package from it until the user makes it public.
- L5 (2026-11-13): T2. Plugin folder and id are now
  `io.github.ingermanr.protas` (manifest author `ingermanr`, version 1.2.0).
  `Panel.qml` ships `readonly property string cli: "protas"` and
  `protas omarchy install` writes the full path of the command it finds
  (the running `protas` script, else `shutil.which`) with `json.dumps`;
  without a `protas` command it exits 1 and installs nothing. After enabling
  the new panel it runs `omarchy plugin remove german-ds.protas --yes` only
  when that folder exists; a failed removal is reported with the command to
  run and the install still succeeds. RED observed for the four new tests;
  355 tests green; the real `omarchy plugin validate` accepts the panel.
  README panel section updated.
- L6 (2026-11-13): T3. `packaging/PKGBUILD` (arch any, depends python,
  wheel built with python-build and installed with python-installer, check()
  runs the suite) builds from the GitHub tag tarball with a zero checksum to
  fill by `updpkgsums` after the release; `packaging/protas.desktop`
  (Terminal=true, passes `desktop-file-validate`) and `assets/logo.svg` as
  the hicolor icon. Deviation from S6: the panel is not copied to
  `/usr/share/protas/`; it already ships inside the Python package and
  `protas omarchy install` reads it from there. Local check: `makepkg -d`
  in a scratch dir with the build tools on PYTHONPATH (no sudo here), from
  a `git archive` of HEAD: 355 tests green inside check(), the package holds
  `/usr/bin/protas`, site-packages, the desktop entry, icon and license, and
  the packaged `protas` runs `version`, `add` and `list`. The first build
  showed `build/` committed by mistake in `7494c47` (from `uv tool install .`
  in the repo); `d6ea2d8` untracks it and ignores `build/` and `dist/`.
  `packaging/README.md` gives the release, local `makepkg -si` and
  omarchy-pkgs PR steps; the README links it and the Roadmap now lists only
  the OPR publication.
