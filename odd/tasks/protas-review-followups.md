# protas: pending items left by the 2026-11-11 review

Objective: close the items that stayed written down after the twelve review
findings were fixed. Branch: `feature/workspace-model`. Delivery: `ask-on-risk`.
Test runner: `python -m unittest discover -s tests` (pytest is not installed).

## Specs

- S1: "Los 7 avisos no bloqueantes de la revisión nativa sobre la copia de
  seguridad de la migración; el principal es que una copia `.bak` vieja se
  reutiliza sin comprobar que corresponde a la base actual."
  The seven: stale backup reused (`protas/db.py`, risk and reliability lenses),
  backup failure paths untested, `.partial` file left behind, `.partial` race,
  a failing ROLLBACK masks the original error, the statement splitter assumes
  one statement ends per line. Assumption (mine): the two verifier advisories
  on the same function go with them: `except Exception` skips the rollback on
  Ctrl-C, and a task pointing at a missing day reports a bare `KeyError` value.
- S2: "Tu base instalada tiene un día futuro con copias creadas por el
  comportamiento anterior." Touches the user's real data: needs the user's
  explicit go-ahead on what to delete.
- S3: "Navegar con las flechas sigue creando días vacíos."
- S4: "La ayuda de la TUI se corta en terminales estrechas; una pantalla de
  ayuda con `?` lo resolvería."
- S5: "La separación de `store.py` en dominio y persistencia, que comenté en la
  revisión." Open design decision: needs a proposal the user approves first.

## Tasks

- [x] T1 (S1) inline. Risk item 1 (migration of stored data): own commit,
  independent verifier and native review (results in the Log).
- [x] T2 (S2) closed without changes (see L7).
- [x] T3 (S3) inline. Commit `3d74792`.
- [x] T4 (S4) inline. Commit `bd7d851`.
- [x] T5 (S5) inline. Commits `cca598e`, `3f45e49`, `6f16e18`.

## Log

- L1 (2026-11-11, user): "agrega .atl/ al .gitignore y atendemos lo que quedó
  anotado". `.atl/` ignored in `c14c6e8`.
- L2: installed database inspected read-only: day 2026-11-12 holds two carried
  copies whose originals are still pending today, and day 2026-11-10 is empty.
- L3: T1 written test first: 8 of the 10 new tests in `BackupTest` failed before
  the change, 168 tests pass after. Decisions: a copy is trusted only when a
  digest of the old tables matches the database; a name taken by other content
  is never replaced and the new copy is numbered (`.2.bak`); the copy is
  written to a unique `.partial` name, checked, then linked into place; any
  failure (Ctrl-C included) rolls back and closes the connection; a database
  migrated by another process meanwhile is left alone.
- L4: slice `e8ac006..c14c6e8` (9 commits, 937 lines) assessed: medium,
  review not due (`under_budget`).
- L5 (2026-11-12): T3 and T4 committed. T3: `Store.discard_if_empty` forgets a
  day left without entries or note (never today, never a project); the TUI
  calls it when leaving a day with the arrows or `q`, and `show`, `list` and a
  read-only `note` call it too. Events only hang from projects, so nothing of
  the history is lost. T4: `?` opens a full key screen, `esc` or `?` closes it,
  and the footer starts with `? ayuda`. 177 tests pass.
- L6: slice `7c4c12d..bd7d851` assessed: medium, review not due
  (`under_budget`). Next: T2 and T5 wait for the user's decision.
- L7 (2026-11-12, user): "cierra, no importa si borras la base, nsolo tenía
  tareas de prueba". The future day became today, so its two copies are the
  ones today's rollover would create; nothing was deleted from the installed
  database. Next: T5 proposal.
- L8 (2026-11-12, user): "dale, aprobado" to the proposal: keep `Store` as the
  facade with its API untouched and extract what needs no database, in three
  commits. `models.py` holds the dataclasses and date helpers (re-exported by
  `store.py`), `stats.py` the counting (`compute_stats`, takes today as an
  argument), `rules.py` the project state and the lineage walk of the
  rollover. The full repository pattern was discarded: it rewrites 63 uses of
  the connection for a single backend. 185 tests pass (8 new, without a
  database). `store.py` went from 1305 to 1019 lines.
- L9: slice `7c4c12d..6f16e18` assessed: medium, review not due (`under_budget`).
