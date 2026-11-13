# protas: priorities and time estimates

Objective: every task can carry a priority and an estimated duration, edited
from the CLI and the TUI, ordered and shown in the lists, and summed by the
statistics. Branch: `feature/task-priorities` (from `main`). Delivery:
`ask-on-risk`; no PR slicing: the user authorizes push and merge per
milestone. Test runner: `python -m unittest discover -s tests`.

## Specs

- S1 (user, 2026-11-12): "Cada tarea puede llevar prioridad (alta, media,
  baja) y minutos estimados. Se editan desde el CLI y la TUI, la lista ordena
  por prioridad y muestra el estimado, y las estadísticas suman lo estimado
  del día. Requiere esquema 5 con migración."
- S2 (derived from the project rules): the schema goes from 4 to 5 with the
  existing update chain: previous copy, one transaction, all or nothing, a
  new database is born at version 5, and `doctor` and `version` name it.
- S3 (derived from the project rules): with no priority or estimate set, every
  existing command produces exactly the same output as before.
- S4 (derived): invalid values are rejected with a clear message in Spanish,
  and the exit code is 1; nothing is written.
- S5 (derived from the project rules): README and the TUI help document the new
  options and keys.

Assumptions (mine, not requested): priority is one of alta, media, baja or
none; the estimate is whole minutes; "sin prioridad" sorts after baja;
estimates are copied by the rollover like the text; a mention keeps the
priority of the entry it was promoted from; export stays as it is (only text)
because the user did not ask for it.

## Tasks

- [x] T1 (S1, S2): commit `6918d2c`. Schema 5 adds `priority` and `estimate` to `tasks`, the
  4 to 5 step, and the version expectations of the existing tests. Route:
  inline. Risk: item 1 (schema migration), own commit.
- [x] T2 (S1, S3, S4): commit `da02213`. `Task` fields, parse and format helpers, `add_task`
  options, a `set` method, ordering by priority and estimate; CLI `add
  --priority/--estimate`, `protas set`, list/show/JSON output. Route: inline.
- [x] T3 (S1, S5): commit `PENDING-T3`. TUI shows priority and estimate, `!` cycles the priority and
  `E` edits the estimate; help updated. Route: inline.
- [ ] T4 (S1): `stats` sums the estimate of each day in text, JSON and the TUI.
  Route: inline.
- [ ] T5 (S5): README documents the new options, command and keys. Route:
  inline.
- [ ] T6 (S2): independent verification of the whole feature before merge.
  Route: delegated (Verification trigger, item 1).

## Log

- L1 (2026-11-12, user): "agrega una tarea de validar que el readme, las
  instrucciones y la definición de uso de la aplicación sea para cualquier
  persona que acceda al reporistorio, ya sea clonando o descargando, que todo
  esté indicado para el uso de cualquier persona, las indicaciones de uso del
  panel omarchy, que no lo van a poder usa usuarios de windows o iOS, continua
  con el roadmap" (the docs validation is now the last Roadmap item; this
  document covers the first one).
- L2 (2026-11-12, user): chose "Prioridad + estimación por tarea", with the
  quote in S1.
- L3 (2026-11-12): design. Two nullable columns on `tasks` (no new tables),
  `priority` 1/2/3 for alta/media/baja and `estimate` in minutes. `tasks_of`
  orders by `COALESCE(priority, 4), position, id`, so a database with no
  priorities keeps its manual order. The estimate lives on the entry, so the
  rollover copies it with the text; the statistics show it per day.
- L5 (2026-11-12): T1 done in `6918d2c`; 302 tests green. The version 4 to 5
  step adds both columns with CHECKs; a new database gets them after the
  baseline shape. `SCHEMA_V3` stays frozen, `SCHEMA_V4` is the frozen
  version 4 the tests pin, and `tests/support.py` gained
  `at_version_4`/`pin_version_4`.
- L6 (2026-11-12): T2 done in `da02213`; 326 tests green. `store.has_details`
  reads the columns and everything that touches them asks first, so the
  pinned old schemas of the update chain keep working. The details are written
  with a second UPDATE after the INSERT, so the pinned v3/v4 schemas and their
  tests never see the new columns. CLI: `add --priority/--estimate` and
  `protas set ID --priority/--estimate` (no flags is an error), text and JSON
  output gained the details; JSON adds `priority` and `estimate_minutes`.
  Difference against `6918d2c` on a database without details: identical `list`,
  `show`, `projects`, `history` and `stats` text, plus the two new JSON keys
  only. Tests were written after the implementation, so no RED was observed
  for this task; the differential check against the base commit was run
  instead.
- L7 (2026-11-12): T3 done in `PENDING-T3`; 330 tests green. The list line in the
  TUI carries the details, `!` cycles none, alta, media, baja, none and `E`
  opens the estimate editor prefilled with the current value. The help keeps
  one line for the three editing keys, so the screen still fits 20 lines.
