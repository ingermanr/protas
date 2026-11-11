# protas: las estadísticas

## Objetivo

Que la app diga si el trabajo está saliendo: cuántas cosas cerrás por día,
cuántas de las que arrancaste terminás, cómo van los proyectos y si la
racha sigue viva.

Rama: `feature/workspace-model`. Entrega: work-unit commit.
Runner: `python3 -m unittest discover -s tests`.

## Specs

- S1: El ritmo muestra las tareas completadas por día en una ventana
  configurable (por defecto 14 días).
- S2: El cumplimiento se cuenta **por linaje**, no por día: una tarea que
  sobrevive tres días es un compromiso, no tres.
- S3: Una tarea cuenta como terminada cuando su última copia está hecha.
- S4: La racha cuenta los días consecutivos con actividad. Hoy sin
  actividad todavía no rompe la racha: recién se rompe al faltar un día
  entero.
- S5: La actividad de un proyecto cuenta para la racha.
- S6: Cada proyecto informa su progreso, sus días activos y su primer y
  último día.
- S7: `protas stats` imprime las secciones y `protas stats --json` las
  devuelve en formato legible por máquinas.
- S8: En la TUI, la tecla `s` muestra los números.

## Tasks

- T1 (S1,S2,S3,S4,S5,S6): cálculo de las estadísticas — route: inline —
  commit: wu6
- T2 (S7,S8): comando `stats` y vista de números en la TUI — route: inline —
  commit: wu6

## Log

- L1: "vamos con las estadísticas" (2026-11-11)
- L2: Decisión: el cumplimiento se cuenta por linaje. Con el arrastre, una
  tarea pendiente vive en varias agendas; contar filas de agenda charge el
  mismo pendiente una vez por día y hacía el cumplimiento inútil (2026-11-11)
- L3: Bug encontrado por la demostración: el inicializador del linaje
  dejaba el estado de la primera fila sin registrar, así que el
  cumplimiento daba 0% con tareas completadas. Cubierto por un test
  (2026-11-11)
