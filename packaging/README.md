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

1. El repositorio tiene que ser público: el paquete se descarga desde
   GitHub y nadie puede bajar un repositorio privado.
2. Sube `version` en `pyproject.toml` y `pkgver` en `PKGBUILD` al mismo
   número, y deja `pkgrel=1`.
3. Crea la etiqueta y el release:

   ```bash
   git tag v0.1.0
   git push origin v0.1.0
   gh release create v0.1.0 --title "protas 0.1.0" --notes "…"
   ```

4. Llena la suma de verificación con `updpkgsums` (de `pacman-contrib`)
   dentro de esta carpeta y bórrale lo que descargó.

## Probar el paquete en tu equipo

```bash
cd packaging
makepkg -si        # compila, corre las pruebas e instala con pacman
protas version
```

`makepkg -s` instala lo que hace falta para compilar (`python-build`,
`python-installer`, `python-setuptools`, `python-wheel`) y pide la
contraseña para eso. Para quitarlo: `sudo pacman -R protas`.

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
