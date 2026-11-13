# Paquete de Arch y de Omarchy

Esta carpeta tiene la receta para instalar protas como paquete del sistema:

- `PKGBUILD`: compila la rueda de Python desde el release `v$pkgver` de
  GitHub, corre las pruebas e instala `/usr/bin/protas`, la entrada del
  lanzador, el ícono y la licencia.
- `protas.desktop`: la entrada que hace aparecer protas en el lanzador de
  Omarchy (`Super + Space`) y en cualquier escritorio de Linux. Abre la TUI
  en una terminal.

El panel de la barra viaja dentro del paquete de Python, así que no hace
falta copiarlo aparte: después de instalar el paquete, cada persona lo
activa con `protas omarchy install`.

## Publicar una versión

Esta es la guía para sacar una versión nueva (por ejemplo `0.2.0`).

### 1. Antes de etiquetar

1. Corre las pruebas: `python -m unittest discover -s tests`. El paquete
   las vuelve a correr en `check()`, así que una que falle frena la
   publicación en Omarchy.
2. Sube la versión en los tres lugares, siempre al mismo número:
   - `version` en `pyproject.toml`
   - `__version__` en `protas/__init__.py`
   - `pkgver` en `packaging/PKGBUILD`, con `pkgrel=1`
3. Si cambiaste el panel (`protas/integrations/omarchy/…`), sube también
   `version` en su `manifest.json`. No hace falta para que se actualice
   (protas compara los archivos, no el número), pero deja registro de que
   cambió.
4. Si cambiaste el esquema de la base, sigue "Agregar un cambio de
   esquema" en el README principal: el paso nuevo va en `MIGRATIONS` de
   `protas/db.py`. Los usuarios no corren nada: la base se migra sola al
   abrirla.
5. Actualiza el README si cambió algún comando, opción o tecla.

### 2. Etiqueta y release

```bash
git tag -a v0.2.0 -m "protas 0.2.0"
git push origin v0.2.0
gh release create v0.2.0 --title "protas 0.2.0" --notes-file notas.md --verify-tag
```

El repositorio tiene que ser público: el paquete se descarga desde GitHub.

### 3. Suma de verificación de la receta de este repositorio

```bash
cd packaging
updpkgsums                      # de pacman-contrib
rm -rf src pkg *.tar.gz         # lo que descargó
git commit -am "build(packaging): checksum of the v0.2.0 release tarball"
git push
```

La receta que vive dentro del tarball de la etiqueta queda con la suma
anterior (la etiqueta es previa a este commit). No importa: Omarchy usa su
propia copia de la receta.

### 4. Lo que pasa en Omarchy sin que hagas nada

Una vez aceptado el paquete en
[omacom/omarchy-pkgs](https://github.com/omacom/omarchy-pkgs), su
`pkgbuilds/protas/.omarchy/package.json` vigila los releases de
`ingermanr/protas`:

1. Un bot revisa **cada 6 horas**; con `"auto_merge": true` revisaría cada
   hora. Al ver la etiqueta nueva abre un PR que sube `pkgver` y la suma.
2. CI compila el paquete (y corre las pruebas). Si pasa, **el PR se fusiona
   solo**.
3. Se publica en el canal `edge` en minutos. A `rc` y `stable` llega cuando
   los mantenedores promueven los canales, a mano y sin fecha fija.
4. Cada persona lo recibe con `omarchy update`.
5. `"rebuild_on": ["python"]` hace que el paquete se recompile cuando Arch
   sube la versión de Python; sin eso protas dejaría de encontrarse en el
   `site-packages` nuevo. Por eso no está en el anillo rápido.

Si el bot no puede (por ejemplo, porque la compilación falla), el PR queda
abierto en rojo y nada se publica hasta arreglarlo.

Para cambiar **solo la receta** sin versión nueva de protas, sube `pkgrel`
en el `PKGBUILD` de omarchy-pkgs; un cambio de receta sin mover la versión
no se compila ni se publica. No uses nunca `epoch` sin acordarlo en el PR.

### 5. Lo que recibe quien ya tiene protas

- **El programa:** con `omarchy update` (paquete) o reinstalando con
  `uv`/`pipx` desde el repositorio. Esas instalaciones no se actualizan
  solas.
- **La base:** se migra sola al abrirla, con una copia
  `protas.db.vN.bak` al lado.
- **El panel:** el primer comando de protas que corra en una terminal
  compara el panel instalado con el que trae la versión nueva (incluida la
  ruta del comando) y, si difieren, lo reemplaza y reinicia la barra. Las
  llamadas del propio panel no tienen terminal y nunca lo disparan.
  `PROTAS_NO_PANEL_UPDATE=1` lo apaga.

### Cosas que aprendimos

- `pip install` no funciona en Arch/Omarchy fuera de un entorno virtual
  (`externally-managed-environment`); por eso el README usa `uv` o `pipx`.
- Con mise, pyenv o asdf primero en el `PATH`, `makepkg` falla con
  `No module named build`: compila con `PATH=/usr/bin:$PATH makepkg -si`.
- Un `protas` en `~/.local/bin` (pip, uv, pipx) tapa al del paquete en
  `/usr/bin`; hay que desinstalarlo antes de pasar al paquete.
- Una instalación editable (`pip install -e .`) corre el código de la rama
  en la que esté el repositorio, y una rama con un cambio de esquema migra
  la base real. Para desarrollar, usa `--db` con una base aparte.
- `python -m protas` desde la raíz del repositorio carga el código de esa
  carpeta aunque `PYTHONPATH` apunte a otra copia.
- `uv tool install .` deja una carpeta `build/` en el repositorio (ya está
  en `.gitignore`).
- La barra no usa el `PATH` de la terminal: por eso el panel guarda la ruta
  completa del comando.
- Como el panel guarda la ruta completa, tener dos `protas` instalados
  (por ejemplo uno de desarrollo y el del paquete) y alternarlos en la
  terminal reemplaza el panel y reinicia la barra en cada cambio. Para
  desarrollar, exporta `PROTAS_NO_PANEL_UPDATE=1`.
- En omarchy-pkgs, un PR que no es borrador y solo toca `pkgbuilds/` se
  fusiona y publica solo al pasar CI. Los autores que no son colaboradores
  necesitan que un mantenedor ponga la etiqueta `build-approved` para que
  corra CI.

## Probar el paquete en tu equipo

```bash
cd packaging
makepkg -si        # compila, corre las pruebas e instala con pacman
protas version
```

`makepkg -s` instala lo que hace falta para compilar (`python-build`,
`python-installer`, `python-setuptools`, `python-wheel`) y pide la
contraseña para eso. Para quitarlo: `sudo pacman -R protas`.

Si usas un gestor de versiones de Python (mise, pyenv, asdf) que pone su
`python` antes que el del sistema en el `PATH`, la compilación falla con
`No module named build`: las herramientas de compilación se instalan en el
Python del sistema, pero `makepkg` corre el otro. Pon `/usr/bin` primero
solo para ese comando:

```bash
PATH=/usr/bin:$PATH makepkg -si
```

El paquete instalado usa `/usr/bin/python`, así que después funciona aunque
el gestor siga primero en tu `PATH`.

Si tenías protas instalado con `pip`, `uv` o `pipx`, desinstálalo antes:
el comando en `~/.local/bin` va antes que `/usr/bin` y taparía al del
paquete. Después corre `protas omarchy install` para que el panel use el
comando del paquete. Tus datos no se tocan.

## Proponerlo al repositorio de paquetes de Omarchy

Los paquetes que se instalan con `omarchy pkg add` viven en
[omacom/omarchy-pkgs](https://github.com/omacom/omarchy-pkgs). Su README
explica el proceso completo; en resumen:

1. Haz un fork y una rama desde `master`.
2. Copia este `PKGBUILD` a `pkgbuilds/protas/PKGBUILD`.
3. Crea `pkgbuilds/protas/.omarchy/package.json` para que las versiones
   nuevas lleguen solas:

   ```json
   {
     "source": "local",
     "upstream": { "watch": { "github": "ingermanr/protas", "pattern": "v(?P<version>[0-9]+(?:\\.[0-9]+)*)" } },
     "rebuild_on": ["python"]
   }
   ```

   `rebuild_on` hace que el paquete se recompile cuando cambia la versión de
   Python: protas se instala en `/usr/lib/python3.X/site-packages`, y sin
   recompilar dejaría de encontrarse con el Python nuevo. Por lo mismo no va
   en `"release_ring": "fast"`, que no se puede combinar con `rebuild_on`.

4. Compruébalo y compílalo con sus herramientas:

   ```bash
   python helpers/upstream-watch.py check pkgbuilds/protas
   bin/build --package protas
   ```

5. Abre un PR contra `master` con solo este paquete, diciendo qué es y cómo
   lo probaste. Un mantenedor tiene que aprobar la compilación.

Cuando el paquete esté publicado, cualquiera lo instala con:

```bash
omarchy pkg add protas
protas omarchy install    # opcional: el panel de la barra
```
