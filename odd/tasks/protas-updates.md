# protas: updating users who already have it installed

Objective: a general, safe path to change the database schema of an installed
protas. Branch: `feature/updates` (from `main`). Delivery: `ask-on-risk`.
Test runner: `python -m unittest discover -s tests` (pytest is not installed).

## Specs

Each spec is one open question from the original note and the decision the
user approved as written on 2026-11-12.

- S1: "¿Cada cambio de esquema se migra solo al abrir, o el usuario tiene que
  correr algo explícito (`protas migrate`)?" Decision: "Automática al abrir,
  con una lista ordenada de pasos (v3→v4, v4→v5…). Sin `protas migrate`."
- S2: "¿Se hace una copia de seguridad de la base antes de migrar? ¿Dónde y
  con qué nombre?" Decision: "Sí, siempre, junto a la base: `<base>.v3.bak`,
  con la misma regla que ya existe (no pisar, numerar)."
- S3: "¿Qué pasa si la migración falla a mitad de camino?" Decision: "Cada
  paso corre en una transacción. Si falla, la base queda como estaba y la app
  sale con el error."
- S4: "¿Hay un comando `protas version` y un `protas doctor` que diga qué
  versión tiene la base y si está sana?" Decision: "`protas version` (app y
  esquema) y `protas doctor` (versión, integridad, índice, copias
  presentes)."
- S5: "¿Se avisa al usuario de que la base va a cambiar? ¿Cómo, sin ensuciar
  la salida?" Decision: "Una línea por stderr solo cuando migra: qué versión,
  dónde quedó la copia."
- S6: "¿Qué pasa con una base de una versión futura (el usuario bajó una
  versión nueva de la app y después volvió a la vieja)?" Decision: "Se rechaza
  con un mensaje claro y no se toca." Evidence: before this work `_migrate`
  restamped any other version as the current one.
- S7: "¿Se soporta el esquema viejo indefinidamente o se deja de lado después
  de un tiempo?" Decision: "Indefinido: los pasos son baratos de mantener y se
  encadenan."

Decisions already taken that stay as they are: the move from days to
workspaces is all or nothing and keeps `<base>.before-workspaces.bak`; the
database lives in `~/.local/share/protas/protas.db`; `PROTAS_DB` and `--db`
point at another one; the FTS5 index is optional.

Assumptions (mine):

- The whole chain of steps runs in one transaction, not one per step. With one
  per step a failure in the second would leave the database at an intermediate
  version, which contradicts "la base queda como estaba" and the single
  `<base>.v3.bak` copy.
- Version 3 is the baseline: it is the shape the move from days to workspaces
  produces. A database that has workspaces and no stored version is version 3;
  one whose stored value cannot be read is refused, not guessed.
- `protas version` does not open the database. `protas doctor` reads it
  without creating, migrating or writing it.
- No real v3→v4 step exists yet, so the tests drive the chain with steps of
  their own.

## Tasks

- [x] T1 (S1, S2, S3, S6, S7) inline. Risk item 1 (migration of stored data):
  own commit `feafaeb`, independent verifier pass, native review approved.
  Regression probes in `tests/test_updates_chain.py` (commit `dccd00d`).
- [x] T2 (S5) inline. Commit `3999f65`.
- [x] T3 (S4) inline. Commit `3999f65`.

## Log

- L1 (2026-11-11, user, from the original note): "cómo actualizar a los
  usuarios que ya la tienen instalada". The user was going to try the app for
  a few days and came back with this question.
- L2 (2026-11-12, user): "bueno, hagamos primero el remoto y el main, luego
  vammos con la estrategia de actualizaciones". Remote and `main` created
  first (private repo `ingermanr/protas`).
- L3 (2026-11-12, user): "dale, aprobado" to the seven decisions quoted in the
  specs.
- L4: trap already known: the editable install hides the problem, because the
  developer never sees the migration of an old database unless it is done by
  hand.
- L5 (evidence, T1): the independent verifier read the whole document and
  probed `65ae68f..feafaeb` in a scratch copy. The suite ran 201 tests, OK;
  S1, S2, S3, S6 and S7 are met; no blockers. It reported one warning and four
  suggestions, all non-blocking. Functional RED exists at the baseline:
  `65ae68f` had no `MIGRATIONS` and no `version_backup_path`, and it re-stamped
  a database from a newer version. RED of the unit tests themselves was not
  recorded before the implementation: the tests were already written and green
  when this session resumed.
- L6 (review): native review of `main..feafaeb`, lens `reliability`, approved
  (lineage `review-84305f5a2ba24066`, authority burned). Its advisory findings,
  none of them blocking and none opening a correction: a database whose stamp
  names a newer version but that has no `workspaces` table goes through the
  legacy path and is re-stamped as 3 (pre-existing at the baseline);
  `_fingerprint` assumes every table has a `rowid`; no test asserts the search
  index after a step that rewrites indexed text; the two concurrent-version
  branches have no test; a step that raises `MigrationError` itself loses the
  "copy is kept at" sentence. They are follow-ups, not part of this feature.
- L7: the assumption about "no usable version" was narrowed to match the code:
  a missing stamp is version 3, an unreadable one is refused.
- L8 (delivery): `main..HEAD` is four commits and about 1,800 authored lines
  with the new files, over the 400-line review budget for one pull request.
  The chain strategy is still open and is asked when the pull request is
  prepared.
