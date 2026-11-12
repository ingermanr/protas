# protas: cómo actualizar a los usuarios que ya la tienen instalada

Estado: **pendiente**. El usuario va a probar la app unos días y volvió
con esta pregunta; no se implementó nada de esto todavía.

## El problema

Hoy el esquema tiene versión (`meta.schema_version` = 3) y `connect()`
aplica la migración al abrir. Eso alcanza para un cambio, pero no para
un ciclo de mejoras: cada cambio de esquema future necesita un paso, y
alguien con la app instalada tiene su base con datos reales.

Preguntas abiertas:

- S1: ¿Cada cambio de esquema se migra solo al abrir, o el usuario tiene
  que correr algo explícito (`protas migrate`)?
- S2: ¿Se hace una copia de seguridad de la base antes de migrar? ¿Dónde
  y con qué nombre?
- S3: ¿Qué pasa si la migración falla a mitad de camino? Hoy las
  migraciones no usan transacciones explícitas.
- S4: ¿Hay un comando `protas version` y un `protas doctor` que diga qué
  versión tiene la base y si está sana?
- S5: ¿Se avisa al usuario de que la base va a cambiar? ¿Cómo, sin
  ensuciar la salida?
- S6: ¿Qué pasa con una base de una versión futura (el usuario bajó una
  versión nueva de la app y después volvió a la vieja)?
- S7: ¿Se soporta el esquema viejo indefinidamente o se deja de lado
  después de un tiempo?

## Decisiones ya tomadas (que hay que respetar)

- La migración de días a workspaces es todo o nada: corre en una sola
  transacción y, si falla, la base queda como estaba y la app sale con
  `protas: could not migrate ...` (responde S3 para esta migración).
- Antes de esa migración se guarda una copia junto a la base:
  `<base>.before-workspaces.bak`. Solo se reutiliza una copia que
  contiene exactamente lo mismo que la base; si el nombre lo ocupa otra
  cosa no se pisa y la copia nueva lleva número (`.2.bak`). Responde S2
  para esta migración; falta decidir la regla general y la limpieza.

- La base es un archivo SQLite en `~/.local/share/protas/protas.db`
  (XDG). Nunca dentro del repo.
- `PROTAS_DB` y `--db` permiten apuntar a otra base (tests, demos).
- El índice FTS5 es opcional: si el build de SQLite no lo tiene, la app
  arranca igual con un escaneo simple. Ese precedente vale para
  cualquier otra dependencia opcional.
- La migración v2 → v3 (días → workspaces) ya existe y está probada en
  `tests/test_migration.py`, incluida la migración de una base con
  tareas anidadas.

## Contexto

- La app está instalada en modo editable (`pip install -e .`), así que
  cada cambio de esquema se ve al instante durante el desarrollo. Eso
  **esconde** el problema: el desarrollador nunca ve la migración de
  una base vieja salvo que la haga a mano.
- Siguiente paso natural para probarlo: una base v3 real, una versión
  nueva del esquema, y el recorrido completo de actualización.
