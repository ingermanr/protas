# protas

Notas y tareas del día, con un espacio de trabajo por día.

Cada día es un **espacio de trabajo** cuyo nombre es la fecha (`YYYY-MM-DD`).
Dentro hay una nota libre y una lista de entradas. Lo que no se completó se
arrastra al día siguiente de forma automática, y cualquier tarea puede
convertirse en un **proyecto**: un espacio de trabajo propio, con su título,
su nota y sus tareas.

## Instalación

Sin dependencias externas: solo Python 3.11 o superior.

```bash
# usar el modulo directamente
python3 -m protas

# o instalarlo como comando
pip install -e .
protas
```

La base de datos vive en `~/.local/share/protas/protas.db`. Se puede cambiar
con la variable `PROTAS_DB` o con la opción `--db`.

## Uso diario

```bash
protas              # abre el espacio de trabajo de hoy en la TUI
protas show         # imprime el espacio de trabajo de hoy
protas show 2026-11-10
protas show --project 3
```

Al abrir el día, las tareas pendientes del día anterior ya vienen cargadas.

### Teclas de la TUI

| Tecla | Acción |
| --- | --- |
| `j` / `k` | mover la selección |
| `espacio` | completar o reabrir la entrada |
| `a` | nueva tarea |
| `A` | nueva subtarea (promueve la tarea a proyecto si hace falta) |
| `p` | promover la tarea a proyecto |
| `e` | editar el texto |
| `n` | editar la nota del espacio de trabajo |
| `x` | borrar la entrada |
| `enter` | abrir el proyecto de una mención |
| `h` | ver la historia del proyecto |
| `s` | ver los números |
| `esc` | volver del proyecto al día |
| `←` / `→` | moverse entre días |
| `q` | salir |

### Comandos

```bash
protas add "Preparar la reunion" --date 2026-11-11
protas add "Esquema de la tabla" --project 3
protas list --date 2026-11-11
protas done 6
protas undone 6
protas note "Resumen de la sesion" --date 2026-11-11
protas promote 6                # la tarea pasa a ser un proyecto
protas mention 3 --date 2026-11-12
protas roll --to 2026-11-12
protas projects
protas history 3               # la historia del proyecto
protas export --out ./protas-export
```

Las fechas se escriben como `AAAA-MM-DD`. Cualquier otra cosa se rechaza
con un error y no crea ningún día.

### Historial

Cada proyecto lleva su propia historia: cuándo se creó, qué se le agregó,
qué se completó y en qué día. La fecha de cada evento es **el día desde el
que estabas trabajando**, no la hora del reloj: si abriste el proyecto desde
la agenda del 12, lo que hagas cuenta como del 12.

```
$ protas history 2
Migrar la base de datos
=======================

2026-11-09
  en la agenda
  creado el proyecto
  agregada "Diseno del esquema"

2026-11-10
  en la agenda
  agregada "Script de migracion"
  completada "Diseno del esquema"

del 2026-11-09 al 2026-11-10 (2 dia(s) con actividad)
```

En la TUI, la tecla `h` muestra la historia del proyecto abierto.

### Estadísticas

`protas stats` resume los últimos días: el ritmo, el cumplimiento, los
proyectos y la racha.

```
$ protas stats
Hoy
  3 pendientes | 1 hechas | 2 proyectos

Ritmo (ultimos 14 dias)
  2026-10-29  ################         2
  2026-10-30  ################         2
  ...
  31 completadas | 2.2 por dia activo | 14 dias con actividad

Cumplimiento
  76% (31 de 41 tareas que arrancaste)

Proyectos
  Migrar la base de datos      #####.....  2/4  3 dias activos  del 2026-11-08 al 2026-11-11

Racha
  14 dias seguidos con actividad
```

El **cumplimiento** cuenta por linaje, no por día: una tarea que sobrevive
tres días es un compromiso, no tres, así que tener pendientes no te
castiga dos veces. En la TUI, la tecla `s` muestra los números.

### Búsqueda

`protas search` busca en tareas, notas y espacios de trabajo al mismo tiempo.

```bash
protas search migrar                  # tareas, notas, días y proyectos
protas search base de datos           # los términos se combinan con AND
protas search 'migr*'                 # prefijo: migr* encuentra "migración"
protas search reunion --kind task     # solo tareas, notas, días o proyectos
protas search equipo --since 2026-11-01 --until 2026-11-30
protas search informe --open          # solo tareas pendientes
protas search migrar --json           # salida para scripts
```

La búsqueda ignora mayúsculas y tildes (`session` encuentra `Sesión`), y
sale con código 1 cuando no encuentra nada, como `grep`.

La búsqueda usa un índice FTS5 que SQLite mantiene sincronizado con las
tablas mediante triggers. Las bases creadas antes del índice se actualizan
solas la primera vez que se abren. Si el SQLite del sistema no trae FTS5,
la búsqueda sigue funcionando con un escaneo simple, solo que más lento.

## Modelo de datos

- **Workspace**: la unidad en la que se trabaja. Hay dos tipos:
  - **día**: un día calendario. Su título es la fecha y su `date` es única.
  - **proyecto**: un espacio con vida propia, con título, nota y tareas.
- **Entrada**: una tarea dentro de un workspace. En un día es trabajo para
  ese día; en un proyecto es parte del proyecto.
- **Mención**: una entrada de un día que apunta a un proyecto. Conserva su
  lugar en la agenda y muestra el progreso vivo del proyecto.
- **Promover**: convertir una tarea en proyecto crea su workspace, muda sus
  hijas adentro y deja la tarea original como mención.
- **Estado vivo**: un proyecto tiene un único estado. Si todas sus tareas
  están hechas, el proyecto está hecho y todas sus menciones aparecen
  hechas. Reabrir una tarea del proyecto reabre el proyecto. Un proyecto
  sin tareas se marca como cualquier entrada, y agregarle una tarea lo
  reabre.
- **Arrastre**: lo pendiente se **copia** al día siguiente y la entrada
  original se queda donde estaba, así cada día conserva un registro honesto
  de lo que realmente pasó. Un registro de arrastes evita duplicados, y las
  subtareas de un proyecto no se duplican: el día arrastra la mención.
  Si borras una entrada arrastrada, no vuelve al día siguiente: el
  original queda pendiente en el día en que lo escribiste.
  El arrastre automático solo ocurre al abrir **hoy**: mirar un día futuro
  no copia nada. Para adelantar lo pendiente a otro día está
  `protas roll --to`.
- **Procedencia**: una entrada arrastrada lo dice: `(de ayer)` o
  `(de 2026-11-08)`. Al abrir el día, lo que quedó sin marcar ayer ya está
  en la agenda de hoy: no hay que importar nada.

Completar un proyecto completa también sus tareas. Completar una tarea
completa sus hijas. El proyecto tiene su propia nota (el brief) y puede
anidarse dentro de otro proyecto.

## Pruebas

```bash
python3 -m unittest discover -s tests
```

## Actualizar una base antigua

Una base creada antes de los workspaces se migra sola al abrirla. Antes
de tocarla se guarda una copia al lado, `protas.db.before-workspaces.bak`,
y la migración es todo o nada: si falla, la base queda como estaba y
`protas` avisa por la salida de error.

## Roadmap

- **Actualizaciones**: qué pasa cuando la app cambia de versión y el
  usuario ya tiene su base con datos (migración, copia de seguridad,
  `protas doctor`). Está documentado en
  [`odd/tasks/protas-updates.md`](odd/tasks/protas-updates.md).
- Panel de Omarchy: widget en la barra con las pendientes del día y un
  panel para marcarlas, leyendo la misma base de datos.
- Resultados de búsqueda dentro de la TUI, navegables.
- Tareas recurrentes, prioridades y estimación de tiempo.
- Exportación a Markdown (ya disponible) y a Obsidian.
