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
- [ ] T4 (S8): independent verification of the whole feature before merge.
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

