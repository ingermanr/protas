# protas: el historial de un proyecto

## Objetivo

Que un proyecto cuente su propia historia: qué se hizo, qué se agregó y en
qué día. Hoy un proyecto no tiene fecha: sus tareas no saben en qué día se
crearon o completaron.

Rama: `feature/workspace-model`. Entrega: work-unit commit.
Runner: `python3 -m unittest discover -s tests`.

## Specs

- S1: Cada proyecto tiene una historia: una lista de eventos con fecha.
- S2: Los eventos se registran al crear el proyecto, al agregar una tarea,
  al completarla, al reabrirla y al completar o reabrir el proyecto entero.
- S3: La fecha de un evento es el día desde el que se estaba trabajando, no
  el reloj: el día de la agenda desde el que se abrió el proyecto.
- S4: Cuando no se indica ese día, se infiere: el último día en que el
  proyecto estuvo en la agenda, y hoy si nunca fue agendado.
- S5: Los días en que el proyecto estuvo en la agenda forman parte de la
  historia aunque no haya eventos.
- S6: La historia sobrevive a que se borre la mención del proyecto.
- S7: `protas history <id>` imprime la historia y `protas history <id>
  --json` la devuelve en formato legible por máquinas.
- S8: En la TUI, la tecla `h` muestra la historia del proyecto abierto.

## Tasks

- T1 (S1,S2,S3,S4,S5,S6): tabla de eventos, registro y construcción de la
  historia — route: inline — commit: wu5
- T2 (S7,S8): comando `history` y vista de historial en la TUI —
  route: inline — commit: wu5

## Log

- L1: "vamos con el historial" (2026-11-11)
- L2: Decisión: el registro de eventos es explícito, no timestamps sueltos.
  Un proyecto no tiene fecha propia, así que los timestamps de sus tareas
  no dicen en qué día de la agenda pasó cada cosa (2026-11-11)
- L3: El contexto por defecto se infiere del último día agendado del
  proyecto; la TUI manda el día desde el que se abrió el proyecto (2026-11-11)
