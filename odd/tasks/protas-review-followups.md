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
- [ ] T2 (S2) blocked on the user's decision.
- [ ] T3 (S3) inline.
- [ ] T4 (S4) inline.
- [ ] T5 (S5) blocked on the user's decision.

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
