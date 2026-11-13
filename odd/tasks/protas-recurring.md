# protas: recurring tasks

Objective: rules that create a task on the days they name, carried like any
pending task. Branch: `feature/recurring-tasks` (from `main`). Delivery:
`ask-on-risk`. Test runner: `python -m unittest discover -s tests`.

## Specs

S1 is the user's answer of 2026-11-12; S2-S7 are the rules proposed that day
and approved as written ("adelante").

- S1: "se arrastra como cualquier pendiente" (a recurring task that is not
  completed on its day).
- S2: "Patrones: diario, días de la semana (por ejemplo lunes y jueves) y día
  del mes (por ejemplo el 15). Nada de "cada N días" por ahora."
- S3: "Cuándo nace: al abrir hoy, si la regla toca hoy. Igual que el arrastre,
  solo ocurre en el día actual."
- S4: "Sin duplicados: mientras la tarea anterior de esa regla siga pendiente
  (y arrastrándose), no nace una nueva. Si no, una diaria sin hacer se
  acumularía cada día."
- S5: "Días que no abriste: no generan tareas atrasadas. Si no abres protas
  del lunes al miércoles, el jueves no aparecen tres copias."
- S6: "Cómo se gestionan: un comando `protas recur` para crear, listar y
  quitar reglas. En la TUI las tareas recurrentes se ven y se marcan como
  cualquier otra; crear reglas desde la TUI quedaría para después."
- S7: "Quitar una regla deja intactas las tareas que ya generó."
- S8: "esto cambia el esquema de la base de datos (versión 3 a 4) [...] Lo
  haré con la cadena de actualización que ya existe (copia previa y todo o
  nada) y con una verificación independiente antes de fusionar."

Assumptions (mine, not requested): a rule for day 29-31 fires on the last day
of a shorter month; day names are accepted in Spanish and English; a rule's
task that was deleted does not come back the same day.

## Tasks

- [x] T1 (S8, commit de2698b, native review approved and acknowledged): schema 4 adds `recurrences` and `recurrence_tasks`; step 3→4
  registered; the move from days keeps the frozen version 3 shape. Route:
  inline. Risk: item 1 (schema migration), own commit.
- [x] T2 (S1-S5, S7): patterns in `rules`, rules and spawning in `Store`,
  wired into `open_day`. Route: inline.
- [x] T3 (S6): `protas recur add|list|rm`, help and README. Route: inline.
- [x] T4 (S8, verified at d8c34f4): independent verification of the whole feature before merge.
  Route: delegated (Verification trigger, item 1).

## Log

- L1 (2026-11-12, user): "se arrastra como cualquier pendiente"
- L2 (2026-11-12, user): "adelante" (to the six proposed rules, S2-S7, and
  the schema note, S8).
- L3 (2026-11-12): design. Two new tables only; `tasks` is not altered, so
  the step is additive. `recurrence_tasks (recurrence_id, date, task_id)` is
  the ledger that makes spawning idempotent per day. A rule whose earlier
  task was carried into today is linked to that copy instead of spawning.
- L4 (2026-11-12): T1 done. 264 tests pass. The older update, doctor and
  migration tests are pinned to a version 3 world (`tests/support.py`) so
  they keep testing the chain; `tests/test_schema_v4.py` covers the real
  step. Incident: the installed protas is editable and the Omarchy panel
  polls it, so the user's real database was updated to version 4 as soon as
  the step existed in the working tree (copy kept as `protas.db.v3.bak`,
  same row counts). Until this branch is merged, `main` refuses that
  database as newer.
- L5 (2026-11-12): T2 and T3 done in one commit. 288 tests pass. RED was
  observed for every new test file before the code existed. Differential
  check against `main` on a seeded database (show, list, list --json,
  projects, history, search, stats --json, export): identical output.
  Native review of T1 left advisories: the doctor command on a version 4
  database had no test (added in `tests/test_schema_v4.py`); the pin helper
  and a shared fixture are noted, not changed.
- L6 (2026-11-12): T4. Independent verifier at 96c618a against e171acc: S1-S3
  and S5-S8 PASS, including the real 3 to 4 update (row hashes identical,
  `.v3.bak` kept at version 3, one notice, no second copy, baseline refuses
  the updated file untouched, six simultaneous openers make one copy). One
  blocker on S4: two protas opening today at once could spawn the task
  twice (8 of 40 rounds with two processes). Fixed in d8c34f4 by claiming
  the ledger row before creating the task. Recheck by the same verifier:
  FIXED, 0 of 60 rounds with two processes and 0 of 40 with eight; suite 289
  OK. Advisories left open, both present at the baseline: simultaneous
  opens can duplicate a carried task, and `ensure_day` can raise
  IntegrityError in the losing process (data intact). Also open: reopening
  a past recurring task after its successor was born leaves two pending.
- L7 (2026-11-12): branch `fix/concurrent-open` (2feecff, e1b4977) closes
  the first two advisories: `ensure_day` inserts with `INSERT OR IGNORE`
  and re-reads, and `open_day` claims the `carries (origin_id,
  workspace_id)` row before copying, skipping a duplicate claim. Verified
  independently before merge: 8 processes x 20 rounds show/roll carry
  each entry once, no nonzero exit, `integrity_check` ok; baseline
  reproduces duplicates (4/20 rounds silently, exit 0) and the
  IntegrityError. Regression tests: `tests/test_concurrent_open.py` and
  `tests/test_concurrent_carry.py` (RED at e56898b, GREEN at 2feecff).
  Native review approved and acknowledged (risk, resilience, reliability
  lenses) with eight informational advisories, none blocking. 296 tests
  green. Still open: reopening a past recurring task after its successor
  was born leaves two pending.
- L8 (2026-11-13, user): "dale, corrige el error de las recurrentes". Fixed
  on `fix/reopen-recurring`: reproduced first (daily rule, yesterday's task
  done, today's born, yesterday's reopened, today opened again: two pending
  "Leer" today). `rollover` now skips an entry that descends from a rule
  (`_recurrence_of` follows `origin_id` back to the ledger) when the target
  day already holds a pending task of that rule (`_recurrence_task_in` with
  `pending_only=True`). The reopened task stays pending in its own day; if
  today's task is already done, the reopened one is carried as usual. RED
  observed for the two duplicate cases; 358 tests green. README documents
  "a lo sumo una pendiente por regla".
