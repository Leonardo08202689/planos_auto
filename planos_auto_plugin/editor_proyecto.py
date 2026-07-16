"""
editor_proyecto.py — Formulario para crear o editar los datos generales
de un proyecto (metadata + defaults_capa), sin tocar la lista de planos
('capas'), que se sigue editando en el JSON.
"""

import copy
import json
import os

from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
)

from core.configuracion import leer_proyecto, listar_proyectos
from core.utils import sanitizar_nombre, valida_id

_SIN_PLANTILLA = "(ninguno — proyecto vacío)"

_TIPOS_GEOM = ["MultiPolygon", "Polygon", "MultiPoint", "Point",
              "MultiLineString", "LineString"]


class DialogoProyecto(QDialog):
    """
    proyecto_existente=None  → modo "nuevo proyecto" (pide slug de archivo).
    proyecto_existente="xxx" → edita config/proyectos/xxx.json.
    """

    def __init__(self, base: str, proyecto_existente: str = None, parent=None):
        super().__init__(parent)
        self.base = base
        self.proyecto_existente = proyecto_existente
        self.datos_originales = {}
        self.slug_guardado = None

        self.setWindowTitle(
            "Editar proyecto" if proyecto_existente else "Nuevo proyecto"
        )
        self._construir_ui()
        self._cargar_datos()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _construir_ui(self):
        lay = QVBoxLayout(self)
        form = QFormLayout()

        self.edit_slug = QLineEdit()
        form.addRow("Identificador de archivo:", self.edit_slug)
        pista = (
            "Cambiarlo renombra el .json en config/proyectos/."
            if self.proyecto_existente else
            "Nombre del .json en config/proyectos/."
        )
        form.addRow(
            "", QLabel(
                f"<small>{pista} Solo letras, números y guion bajo.</small>"
            )
        )

        self.edit_nombre = QLineEdit()
        form.addRow("Nombre del proyecto:", self.edit_nombre)

        self.edit_tramite = QLineEdit()
        form.addRow("Tipo de trámite:", self.edit_tramite)

        self.edit_capa_poligono = QLineEdit("poligono_trabajo")
        form.addRow("Capa polígono de trabajo:", self.edit_capa_poligono)

        if not self.proyecto_existente:
            self.combo_plantilla = QComboBox()
            self.combo_plantilla.addItem(_SIN_PLANTILLA)
            self.combo_plantilla.addItems(listar_proyectos(self.base))
            self.combo_plantilla.currentTextChanged.connect(self._plantilla_cambiada)
            form.addRow("Copiar planos de:", self.combo_plantilla)

            self.spin_factor_escala = QDoubleSpinBox()
            self.spin_factor_escala.setRange(0.05, 20.0)
            self.spin_factor_escala.setSingleStep(0.1)
            self.spin_factor_escala.setValue(1.0)
            self.spin_factor_escala.setEnabled(False)
            form.addRow("Factor de escala:", self.spin_factor_escala)
            form.addRow(
                "", QLabel(
                    "<small>Multiplica la escala y el grid de todos los planos "
                    "copiados. 1.0 = igual, 2.0 = el doble, 0.5 = la mitad.</small>"
                )
            )

        form.addRow(QLabel("<b>Valores por defecto de cada plano</b>"))

        self.edit_geom_col = QLineEdit("geom")
        form.addRow("Columna de geometría:", self.edit_geom_col)

        self.combo_tipo_geom = QComboBox()
        self.combo_tipo_geom.addItems(_TIPOS_GEOM)
        form.addRow("Tipo de geometría:", self.combo_tipo_geom)

        self.edit_key = QLineEdit("gid")
        form.addRow("Columna llave (key):", self.edit_key)

        self.spin_escala = QSpinBox()
        self.spin_escala.setRange(100, 5_000_000)
        self.spin_escala.setSingleStep(500)
        self.spin_escala.setValue(5000)
        form.addRow("Escala por defecto:", self.spin_escala)

        self.spin_opacidad = QDoubleSpinBox()
        self.spin_opacidad.setRange(0.0, 1.0)
        self.spin_opacidad.setSingleStep(0.05)
        self.spin_opacidad.setValue(0.6)
        form.addRow("Opacidad por defecto:", self.spin_opacidad)

        self.spin_grid = QSpinBox()
        self.spin_grid.setRange(1, 1_000_000)
        self.spin_grid.setValue(300)
        form.addRow("Intervalo de grid (m):", self.spin_grid)

        lay.addLayout(form)

        if not self.proyecto_existente:
            self.lbl_aviso_planos = QLabel(
                "<small>Sin plantilla, los planos (\"capas\") se agregan después "
                "editando el JSON generado.</small>"
            )
            lay.addWidget(self.lbl_aviso_planos)

        botones = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        botones.accepted.connect(self._guardar)
        botones.rejected.connect(self.reject)
        lay.addWidget(botones)

    def _plantilla_cambiada(self, nombre_plantilla: str):
        con_plantilla = nombre_plantilla != _SIN_PLANTILLA
        self.spin_factor_escala.setEnabled(con_plantilla)
        if con_plantilla:
            datos_plantilla = leer_proyecto(self.base, nombre_plantilla)
            defaults = datos_plantilla.get("defaults_capa", {})
            self.edit_geom_col.setText(defaults.get("geom_col", "geom"))
            tipo_geom = defaults.get("tipo_geom", "MultiPolygon")
            if tipo_geom in _TIPOS_GEOM:
                self.combo_tipo_geom.setCurrentText(tipo_geom)
            self.edit_key.setText(defaults.get("key", "gid"))
            self.spin_escala.setValue(defaults.get("escala", 5000))
            self.spin_opacidad.setValue(defaults.get("opacidad", 0.6))
            self.spin_grid.setValue(defaults.get("grid_intervalo", 300))
            n_planos = sum(1 for c in datos_plantilla.get("capas", []) if c.get("nombre_plano"))
            self.lbl_aviso_planos.setText(
                f"<small>Se copiarán {n_planos} plano(s) de "
                f"'{nombre_plantilla}', con la escala y el grid "
                f"multiplicados por el factor.</small>"
            )
        else:
            self.lbl_aviso_planos.setText(
                "<small>Sin plantilla, los planos (\"capas\") se agregan después "
                "editando el JSON generado.</small>"
            )

    # ── Carga ─────────────────────────────────────────────────────────────────

    def _cargar_datos(self):
        if not self.proyecto_existente:
            return
        ruta = self._ruta(self.proyecto_existente)
        with open(ruta, encoding="utf-8") as fh:
            self.datos_originales = json.load(fh)

        d = self.datos_originales
        self.edit_slug.setText(self.proyecto_existente)
        self.edit_nombre.setText(d.get("nombre_proyecto", ""))
        self.edit_tramite.setText(d.get("tipo_tramite", ""))
        self.edit_capa_poligono.setText(d.get("capa_poligono", "poligono_trabajo"))

        defaults = d.get("defaults_capa", {})
        self.edit_geom_col.setText(defaults.get("geom_col", "geom"))
        tipo_geom = defaults.get("tipo_geom", "MultiPolygon")
        if tipo_geom in _TIPOS_GEOM:
            self.combo_tipo_geom.setCurrentText(tipo_geom)
        self.edit_key.setText(defaults.get("key", "gid"))
        self.spin_escala.setValue(defaults.get("escala", 5000))
        self.spin_opacidad.setValue(defaults.get("opacidad", 0.6))
        self.spin_grid.setValue(defaults.get("grid_intervalo", 300))

    # ── Guardado ──────────────────────────────────────────────────────────────

    def _ruta(self, slug: str) -> str:
        return os.path.join(self.base, "config", "proyectos", f"{slug}.json")

    def _clonar_planos(self, nombre_plantilla: str, factor: float) -> list:
        """
        Copia 'capas' de otro proyecto, multiplicando 'escala' y
        'grid_intervalo' de cada plano por 'factor' (factor=1.0 → copia igual).
        """
        capas = copy.deepcopy(leer_proyecto(self.base, nombre_plantilla).get("capas", []))
        if factor != 1.0:
            for capa in capas:
                for campo in ("escala", "grid_intervalo"):
                    if isinstance(capa.get(campo), (int, float)):
                        capa[campo] = round(capa[campo] * factor)
        return capas

    def _guardar(self):
        slug = self.edit_slug.text().strip()
        nombre = self.edit_nombre.text().strip()
        geom_col = self.edit_geom_col.text().strip()
        key = self.edit_key.text().strip()

        if not slug or sanitizar_nombre(slug) != slug:
            QMessageBox.warning(
                self, "Planos Auto",
                "El identificador de archivo debe usar solo letras, "
                "números y guion bajo (sin espacios ni tildes)."
            )
            return
        if not nombre:
            QMessageBox.warning(self, "Planos Auto", "Falta el nombre del proyecto.")
            return
        try:
            valida_id(geom_col, "columna de geometría")
            valida_id(key, "columna llave")
        except ValueError as exc:
            QMessageBox.warning(self, "Planos Auto", str(exc))
            return

        ruta = self._ruta(slug)
        renombrado = bool(self.proyecto_existente) and slug != self.proyecto_existente
        if (not self.proyecto_existente or renombrado) and os.path.exists(ruta):
            QMessageBox.warning(
                self, "Planos Auto",
                f"Ya existe un proyecto con ese identificador:\n{ruta}"
            )
            return

        datos = dict(self.datos_originales)  # conserva capas/ids/mapitas/etc.
        datos["nombre_proyecto"] = nombre
        datos["tipo_tramite"] = self.edit_tramite.text().strip()
        datos["capa_poligono"] = self.edit_capa_poligono.text().strip() or "poligono_trabajo"
        datos.setdefault("capas", [])

        if not self.proyecto_existente:
            nombre_plantilla = self.combo_plantilla.currentText()
            if nombre_plantilla != _SIN_PLANTILLA:
                datos["capas"] = self._clonar_planos(
                    nombre_plantilla, self.spin_factor_escala.value()
                )

        datos["defaults_capa"] = {
            **datos.get("defaults_capa", {}),
            "geom_col":       geom_col,
            "tipo_geom":      self.combo_tipo_geom.currentText(),
            "key":            key,
            "escala":         self.spin_escala.value(),
            "opacidad":       self.spin_opacidad.value(),
            "grid_intervalo": self.spin_grid.value(),
        }

        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(ruta, "w", encoding="utf-8") as fh:
            json.dump(datos, fh, ensure_ascii=False, indent=2)
            fh.write("\n")

        if renombrado:
            try:
                os.remove(self._ruta(self.proyecto_existente))
            except OSError as exc:
                QMessageBox.warning(
                    self, "Planos Auto",
                    f"Se guardó '{slug}.json' pero no se pudo borrar el "
                    f"archivo anterior '{self.proyecto_existente}.json':\n{exc}"
                )

        self.slug_guardado = slug
        self.accept()
