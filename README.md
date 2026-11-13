<p align="center">
  <img src="assets/logo.svg" width="120" alt="Logo de protas: una hoja de notas con una lista de tareas">
</p>

<h1 align="center">protas</h1>

<p align="center">
  <strong>pro</strong>yectos + no<strong>tas</strong>: las notas y tareas del día,
  con un espacio de trabajo por día.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-1f7a6d" alt="Python 3.11 o superior">
  <img src="https://img.shields.io/badge/dependencias-ninguna-1f7a6d" alt="Sin dependencias">
  <img src="https://img.shields.io/badge/datos-SQLite%20local-1f7a6d" alt="Datos en SQLite local">
  <img src="https://img.shields.io/badge/interfaz-CLI%20%2B%20TUI-1f7a6d" alt="Interfaz de línea de comandos y TUI">
  <img src="https://img.shields.io/badge/Omarchy-panel%20opcional-1f7a6d" alt="Panel opcional para Omarchy">
  <img src="https://img.shields.io/badge/licencia-MIT-1f7a6d" alt="Licencia MIT">
</p>

<p align="center">
  <a href="#instalación">Instalación</a> ·
  <a href="#uso-diario">Uso diario</a> ·
  <a href="#búsqueda">Búsqueda</a> ·
  <a href="#exportar-a-obsidian">Obsidian</a> ·
  <a href="#panel-de-omarchy">Panel de Omarchy</a> ·
  <a href="#roadmap">Roadmap</a>
</p>

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
protas tui 2026-11-10           # abre la TUI en otro día
protas tui --project 3          # abre la TUI en un proyecto
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
| `!` | cambiar la prioridad: alta, media, baja o sin prioridad |
| `E` | editar la estimación en minutos |
| `n` | editar la nota: `↑`/`↓` cambian de línea, `Enter` abre una línea, `Ctrl-S` guarda, `Esc` cancela |
| `x` | borrar la entrada |
| `/` | buscar; en los resultados, `j`/`k` mueven, `enter` abre y `esc` vuelve |
| `enter` | abrir el proyecto de una mención |
| `h` | ver la historia del proyecto |
| `s` | ver los números |
| `esc` | volver del proyecto al día |
| `←` / `→` | moverse entre días |
| `r` | actualizar el día (trae lo pendiente si es hoy) |
| `g` / `G` | ir a la primera o a la última entrada |
| `?` | ver todas las teclas en pantalla |
| `q` | salir |

La línea de ayuda de abajo se reparte en varias líneas cuando la ventana es
angosta, así que ninguna tecla queda fuera de vista; el cuerpo se achica para
dejarle lugar.

### Comandos

```bash
protas add "Preparar la reunion" --date 2026-11-11
protas add "Preparar la reunion" --priority alta --estimate 1h30
protas add "Esquema de la tabla" --project 3
protas set 6 --priority media --estimate 45m
protas set 6 --priority ninguna        # la deja sin prioridad
protas list --date 2026-11-11
protas list --all --json        # el día como datos, para otras herramientas
protas done 6
protas undone 6
protas rm 6                     # borra la entrada
protas note "Resumen de la sesion" --date 2026-11-11
protas promote 6                # la tarea pasa a ser un proyecto
protas mention 3 --date 2026-11-12
protas roll --to 2026-11-12
protas projects
protas recur add "Regar las plantas" --every lun,jue   # tarea recurrente
protas recur list
protas history 3               # la historia del proyecto
protas export --out ./protas-export
protas export --format obsidian --out ~/Boveda/protas   # notas para Obsidian
protas version                 # versión de protas y de su esquema
protas doctor                  # revisa la base sin cambiarla
protas omarchy install         # instala o actualiza el panel de Omarchy
```

Las fechas se escriben como `AAAA-MM-DD`. Cualquier otra cosa se rechaza
con un error y no crea ningún día.

`protas list --json` solo lee: no crea el día si falta ni arrastra lo
pendiente, así que un panel puede consultarlo cada pocos segundos sin
cambiar la base. Devuelve el espacio (`workspace`), los totales
(`counts`), la nota (`note`) y las entradas (`entries`) con su
profundidad, su origen, su prioridad y sus minutos estimados, y en las
menciones, el avance del proyecto.

### Prioridad y estimación

Cada entrada puede llevar una prioridad (`alta`, `media`, `baja`) y los
minutos que estimas que lleva:

```bash
protas add "Preparar la reunion" --priority alta --estimate 1h30
protas set 6 --priority media          # cambia solo la prioridad
protas set 6 --estimate 45m            # cambia solo la estimacion
protas set 6 --priority ninguna        # la deja sin prioridad
protas set 6 --estimate ninguna        # le quita la estimacion
```

La estimación acepta `30`, `30m`, `1h`, `1h30` y `1.5h`, y se muestra como
`30m`, `1h` o `1h 30m`. Las entradas con prioridad van primero, de alta a
baja; las que no tienen conservan el orden manual. `protas list`,
`protas show` y la TUI muestran los detalles al lado de la entrada. En la
TUI, `!` recorre las prioridades y `E` abre el editor de la estimación.

El arrastre copia la prioridad y la estimación junto con el texto, y
`protas stats` suma lo estimado de cada día.

### Tareas recurrentes

Una regla crea su tarea en los días que nombra:

```bash
protas recur add "Revisar el correo" --every day       # todos los días
protas recur add "Regar las plantas" --every lun,jue   # días de la semana
protas recur add "Pagar el alquiler" --every 5         # día del mes
protas recur list                                      # reglas con su número
protas recur rm 2                                      # quita la regla
```

Los días de la semana se escriben en español o en inglés (`lun,jue` o
`mon,thu`). Un día que el mes no tiene, como el 31 en febrero, cae en el
último día de ese mes.

- La tarea nace al abrir **hoy**, igual que el arrastre: un día que no
  abriste no deja tareas atrasadas.
- Si no la completas, se arrastra como cualquier pendiente, y mientras
  siga pendiente la regla no crea otra.
- Si la borras, no vuelve ese día.
- Quitar una regla deja intactas las tareas que ya creó.

En la TUI se ven y se marcan como cualquier otra tarea; las reglas se
gestionan con `protas recur`.

### Exportar a Obsidian

`protas export --format obsidian --out CARPETA` escribe una nota por día
(`AAAA-MM-DD.md`) y una por proyecto (`projects/Título.md`), listas para
abrir en una bóveda de Obsidian:

- Cada nota empieza con propiedades: `date` y la etiqueta `protas/dia` en
  los días; la etiqueta `protas/proyecto` y el `avance` en los proyectos.
- Las tareas son casillas (`- [ ]`, `- [x]`) y las subtareas van sangradas.
- La mención de un proyecto en un día es un enlace (`[[Título]]`), así que
  los backlinks de Obsidian muestran en qué días se trabajó cada proyecto.
- Un título que Obsidian no acepta como nombre de archivo se limpia, y el
  original queda como `aliases`. Dos proyectos con el mismo título reciben
  notas distintas.

Es una exportación de ida: lo que edites en Obsidian no vuelve a protas, y
exportar otra vez actualiza las notas. protas solo reemplaza las notas que
él mismo escribió (las que empiezan con `source: protas`): si en la carpeta
hay una nota tuya con el mismo nombre, no escribe nada y te avisa. Por eso
conviene darle una carpeta propia dentro de la bóveda.

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
  3 pendientes | 1 hechas | 2 proyectos | 3h estimadas

Ritmo (ultimos 14 dias)
  2026-10-29  ################         2  3h
  2026-10-30  ################         2  2h 30m
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
castiga dos veces. Cada día muestra también lo estimado para ese día: la
suma de la estimación de sus entradas, incluidas las que llegaron
arrastradas. En la TUI, la tecla `s` muestra los números.

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

En la TUI, `/` pide el texto y muestra los resultados con su fecha y su
tipo. `enter` abre el día o el proyecto del resultado y deja seleccionada
la tarea encontrada; `/` seguido de `enter` repite la última búsqueda, para
volver a la lista después de abrir un resultado. Una tarea pendiente que
se arrastró aparece una vez por cada día en que estuvo.

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
  hijas adentro y deja la tarea original como mención. Un día solo tiene
  entradas planas: agregar una subtarea a una tarea de un día (`A` en la
  TUI, `add --parent` en la línea de comandos) la promueve a proyecto.
- **Estado vivo**: un proyecto tiene un único estado. Si todas sus tareas
  están hechas, el proyecto está hecho y todas sus menciones aparecen
  hechas. Reabrir una tarea del proyecto reabre el proyecto. Un proyecto
  sin tareas se marca como cualquier entrada, y agregarle una tarea lo
  reabre. Un proyecto dentro de otro cuenta como una entrada más del
  externo, con su estado vivo: completar el externo completa también lo
  que hay dentro.
- **Arrastre**: lo pendiente se **copia** al día siguiente y la entrada
  original se queda donde estaba, así cada día conserva un registro honesto
  de lo que realmente pasó. Un registro de arrastes evita duplicados, y las
  subtareas de un proyecto no se duplican: el día arrastra la mención.
  Si borras una entrada arrastrada, no vuelve al día siguiente: el
  original queda pendiente en el día en que lo escribiste.
  El arrastre automático solo ocurre al abrir **hoy**: mirar un día futuro
  no copia nada. Para adelantar lo pendiente a otro día está
  `protas roll --to`.
- **Prioridad y estimación**: cada entrada puede guardar una prioridad
  (`alta`, `media`, `baja`) y una estimación en minutos. Las dos son
  opcionales y el arrastre las copia con el texto.
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

## Actualizaciones

La base lleva un número de versión de su esquema. Cuando una versión
nueva de `protas` cambia el esquema, la base se actualiza sola al abrirla,
sin correr ningún comando:

- **Copia primero.** Antes de tocar nada se guarda una copia al lado de
  la base, con la versión que tenía: `protas.db.v3.bak`. Una copia que ya
  existe solo se reutiliza si contiene exactamente lo mismo; si ese nombre
  lo ocupa otra cosa no se pisa y la copia nueva lleva número
  (`protas.db.v3.2.bak`). Sin copia no hay actualización.
- **Todo o nada.** Todos los pasos corren en una sola transacción. Si
  alguno falla, la base queda como estaba y `protas` sale con el error por
  la salida de error, diciendo dónde quedó la copia.
- **Un aviso, una vez.** Cuando la base se actualiza, `protas` lo dice en
  una línea por la salida de error, sin mezclarse con la respuesta del
  comando: `protas: database updated from version 3 to 4; the previous
  one is kept at …/protas.db.v3.bak`. Si no hubo cambios no dice nada.
- **Una base más nueva no se toca.** Si la base la escribió un `protas`
  más nuevo que el instalado, se rechaza con un mensaje claro y no se
  modifica. Actualiza `protas` para abrirla.
- **Las versiones viejas se siguen soportando.** Los pasos se encadenan
  (3 → 4 → 5…), así que una base antigua llega a la versión actual de una
  sola vez.

Una base creada antes de los workspaces también se migra sola al abrirla,
con las mismas garantías; su copia se llama
`protas.db.before-workspaces.bak`.

Para volver atrás, cierra `protas` y reemplaza la base por la copia.

### Revisar la instalación

`protas version` dice qué versión de `protas` está instalada y qué versión
de esquema entiende. No abre la base.

`protas doctor` revisa la base sin crearla, migrarla ni escribirla:

```
database:     /home/tu/.local/share/protas/protas.db
schema:       version 3, up to date
integrity:    ok
search index: ok
copies:       protas.db.v3.bak
```

Sale con código 1 cuando encuentra algo que `protas` no arregla solo: la
base es de un `protas` más nuevo, su versión no se puede leer, el archivo
no es una base o está dañado, o hay referencias rotas. Un índice de
búsqueda ausente o desactualizado se informa, pero no es un problema:
se reconstruye al abrir la base.

### Agregar un cambio de esquema

En `protas/db.py`: agrega lo nuevo a `SCHEMA` (lo que recibe una base
nueva) sin tocar `SCHEMA_V3`, que es la forma congelada de la que parten
los pasos; sube `SCHEMA_VERSION` y registra en `MIGRATIONS` el paso que
lleva una base de la versión anterior a la nueva. El paso recibe la conexión dentro de la
transacción y no debe hacer `commit` ni usar `executescript`.

## Panel de Omarchy

protas trae un widget opcional para la barra de Omarchy: muestra cuántas
entradas quedan pendientes hoy y, al abrirlo, la agenda del día con su
nota y el avance de los proyectos mencionados. Un clic en una entrada la
completa o la reabre (`protas done` / `protas undone`). Las menciones de
proyecto no responden al clic: completar una completa el proyecto entero,
y eso se hace desde la TUI.

protas funciona igual sin el panel. Si usas Omarchy y lo quieres:

```bash
protas omarchy install
```

El comando copia el panel a `~/.config/omarchy/plugins/german-ds.protas`,
le pide a Omarchy que lo valide y lo active, y reinicia la barra. Sirve
también para actualizarlo: reemplaza la copia anterior, y el reinicio es
necesario porque la barra no suelta el panel que ya tenía en memoria. Con
`--no-restart` deja la barra como está y te dice cómo reiniciarla después.

Para quitarlo: `omarchy plugin remove german-ds.protas`.

El panel espera el comando en `~/.local/bin/protas`. El intervalo de
refresco (60 s por defecto) se ajusta en la configuración del widget. Su
código está en `protas/integrations/omarchy/german-ds.protas/`.

## Roadmap

- Prioridades y estimación de tiempo.
- Crear y quitar tareas recurrentes desde la TUI.
- Validar que el README y las instrucciones de uso sirvan a cualquiera que
  clone o descargue el repositorio, con un aviso claro de que el panel de
  Omarchy no está disponible en Windows ni en iOS.

## Licencia

MIT. El texto completo está en [LICENSE](LICENSE).
