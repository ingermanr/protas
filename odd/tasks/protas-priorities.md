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
  options, a `set` method, ordering by priority (then manual position); CLI `add
  --priority/--estimate`, `protas set`, list/show/JSON output. Route: inline.
- [x] T3 (S1, S5): commit `f6f467f`. TUI shows priority and estimate, `!` cycles the priority and
  `E` edits the estimate; help updated. Route: inline.
- [x] T4 (S1): commit `51570f3`. `stats` sums the estimate of each day in text, JSON and the TUI.
  Route: inline.
- [x] T5 (S5): commit `1d9bf3b`. README documents the new options, command and keys. Route:
  inline.
- [x] T6 (S2): independent verification of the whole feature before merge.
  Route: delegated (Verification trigger, item 1). Verdict: S1-S5 PASS, no
  blockers (see L10).
- [x] T7 (S1, S4): fix the verifier advisories 1-3. Route: inline. Commit: the
  `fix(details)` commit after `08e40de` (see L11).

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
- L7 (2026-11-12): T3 done in `f6f467f`; 330 tests green. The list line in the
  TUI carries the details, `!` cycles none, alta, media, baja, none and `E`
  opens the estimate editor prefilled with the current value. The help keeps
  one line for the three editing keys, so the screen still fits 20 lines.
- L8 (2026-11-12): T4 done in `51570f3`; 336 tests green. `DayStat.estimate`
  holds the minutes estimated for that day: every entry of the day adds its
  own estimate, mentions included, and a carried task is estimated again on
  the day it lands because that day is planned with it. `stats` prints the
  total next to the day and in the "Hoy" line, the JSON carries
  `estimate_minutes` per day, and the TUI draws the same number. A database
  without the columns reads `NULL` and the estimate is zero.
- L9 (2026-11-12): T5 done in `1d9bf3b`. README: keys table gains `!` and
  `E`, the commands block shows `add --priority/--estimate` and `protas set`,
  a "Prioridad y estimación" section documents the accepted formats, the
  ordering and the clear-with-`ninguna`, the statistics sample shows the
  estimate of the day, and the data model says the columns are optional and
  that the rollover copies them.
- L10 (2026-11-13): T6 done. Independent verifier at `5435099` against
  baseline `15e2095`: S1-S5 PASS, no blockers, 336 tests green (parent spot
  check re-ran the suite: OK). Migration 4 to 5 preserved every row, wrote
  `<db>.v4.bak` with an equal dump, and was idempotent; 35 baseline/branch
  commands were byte-identical apart from the requested JSON keys and new
  options; rejected commands left the data hash unchanged. Advisories, not
  fixed: (1) `cmd_stats` computes stats before `open_day`, so the first
  `stats` of a day lacks today's estimate (ordering predates the branch);
  (2) empty `--priority ''`/`--estimate ''` count as none and
  `--estimate "sin prioridad"` clears; (3) TUI selection stays on the index,
  not the task, after `!` re-sorts; (4) JSON always carries the new keys.
  T2 wording corrected: ordering is by priority, then manual position.
- L11 (2026-11-13, user): "corrije primero las observaciones". T7 fixes the
  three advisories, RED observed first for each: `cmd_stats` opens today
  before computing the window, so the first `stats` of a day counts the
  carried estimate; the CLI refuses an empty `--priority`/`--estimate` and
  `parse_estimate` no longer takes priority words (it takes "sin estimacion"
  instead); the TUI estimate editor still clears when left empty; `!` keeps
  the cursor on the same task after the re-sort. Advisory 4 (JSON keys) stays
  as accepted in L6. Differential against `08e40de`: only the first-call
  "Hoy"/today row and the empty-value exit code differ. 342 tests green.
  Gotcha: `python -m protas` from the repo root loads the working tree even
  with PYTHONPATH pointing at a base copy; run the base from its own cwd.
