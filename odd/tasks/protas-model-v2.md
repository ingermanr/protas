# protas v2: el workspace como concepto central

## Objetivo

Que un proyecto sea un workspace propio, con su título, su nota y sus tareas,
en vez de una tarea con hijas que se duplica cada día. La agenda del día
pasa a "mencionar" proyectos.

Rama: `feature/workspace-model`. Entrega: work-unit commits en esta rama.
Runner: `python3 -m unittest discover -s tests`.

## Specs

- S1: Un workspace es de tipo `day` (título = fecha) o de tipo `project`
  (título = el texto de la tarea al promoverla). La tabla `workspaces` es la
  única que guarda título y nota.
- S2: Todo día es un workspace con `date` única.
- S3: Cualquier tarea puede promoverse a proyecto. Al promoverla se crea su
  workspace de proyecto, sus hijas se mudan adentro y la fila original pasa
  a ser una **mención** que apunta al proyecto.
- S4: Una mención conserva su posición en la agenda del día y su traza.
- S5: El estado de un proyecto es **vivo y único**: si todas sus tareas están
  hechas, el proyecto está hecho y todas sus menciones aparecen hechas.
  Reabrir una tarea del proyecto reabre el proyecto y sus menciones.
- S6: Completar una tarea dentro de un proyecto completa también sus hijas.
- S7: Las tareas que viven dentro de un proyecto **no se arrastran** al día
  siguiente. El día arrastra la *mención* del proyecto mientras el proyecto
  tenga trabajo abierto.
- S8: El arrastre sigue siendo idempotente: nada entra dos veces en el mismo
  día, ni siquiera si la copia se borra.
- S9: Agregar una subtarea sobre una tarea que no es proyecto la promueve y
  crea la subtarea dentro del proyecto.
- S10: Cada workspace tiene su propia nota: el día tiene su nota, el proyecto
  tiene su brief.
- S11: La búsqueda cubre tareas, títulos de workspace y notas de workspace.
- S12: Una base creada con la versión anterior se migra sola: los días
  pasan a workspaces de tipo `day` y las tareas con hijas pasan a proyectos.

## Tasks

- T1 (S1,S2): esquema `workspaces` + `tasks` con `project_id` — route: inline — commit: wu1
- T2 (S3,S4,S5,S6,S9): promover, menciones, estado vivo — route: inline — commit: wu2
- T3 (S7,S8): arrastre de tareas y de menciones — route: inline — commit: wu2
- T4 (S10,S11): notas por workspace y búsqueda — route: inline — commit: wu3
- T5 (S12): migración de la base anterior — route: inline — commit: wu3
- T6: CLI y TUI sobre el modelo nuevo — route: inline — commit: wu4

## Log

- L1: "creo que podemos reutilizar los workspace, cualquier tarea se puede
  volver proyecto y al volverla proyecto se convierte en un workspace con
  titulo de la tarea, no de la fecha del día, y dentro de el ya se pueden
  registrar las tareas hijas, es una idea, pero analicemos que es lo que
  mas nos conviene" (2026-11-11)
- L2: Decisión del usuario: la mención de un proyecto en el día tiene
  **estado vivo**, no una foto por día (2026-11-11).
- L3: No hay datos reales todavía (`~/.local/share/protas/` no existe), así
  que el cambio de esquema se hace ahora y no con una migración gradual
  sobre datos acumulados (2026-11-11).
