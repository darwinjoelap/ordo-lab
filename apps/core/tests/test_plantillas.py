"""Las plantillas no llevan comentarios de una llave partidos en dos líneas.

Django sólo reconoce `{# ... #}` dentro de una misma línea. Partido, el lexer no lo ve
como comentario: lo imprime al usuario y, si cae dentro de una rejilla, entra además como
elemento de maquetación y desplaza lo que haya al lado.

Ha pasado dos veces en tres días —en `billing/grid.html` y en `results/capture.html`, ésta
desde la Fase 14— y las dos se encontraron mirando la pantalla, no con pruebas. Para
varias líneas se usa `{% comment %}`.
"""
import pathlib
import re

from django.conf import settings
from django.test import SimpleTestCase

# Una apertura `{#` que no se cierra en la misma línea.
ABRE_SIN_CERRAR = re.compile(r"\{#(?![^\n]*#\})")


class ComentariosDePlantillaTests(SimpleTestCase):
    def test_ningun_comentario_de_una_llave_queda_partido(self):
        raiz = pathlib.Path(settings.BASE_DIR) / "templates"
        culpables = []
        for ruta in sorted(raiz.rglob("*.html")) + sorted(raiz.rglob("*.js")):
            texto = ruta.read_text(encoding="utf-8")
            for numero, linea in enumerate(texto.splitlines(), 1):
                if ABRE_SIN_CERRAR.search(linea):
                    culpables.append(f"{ruta.relative_to(raiz)}:{numero}")

        assert not culpables, (
            "Comentarios `{# #}` partidos en varias líneas: Django los imprime como texto. "
            "Use `{% comment %}`. En: " + ", ".join(culpables)
        )
