"""
dialogo.py — Diálogo del generador: selector de proyecto, lista de planos
con checkboxes, DPI y panel de log en vivo.

Reutiliza toda la lógica existente del repo (core/ + generar_planos.py);
aquí solo se arma el CONFIG y se muestra el progreso.
"""

import importlib
import json
import logging
import os
import sys
import traceback

from qgis.PyQt.QtCore import QCoreApplication, Qt
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)


class _HandlerLogQt(logging.Handler):
    """Redirige los registros del logger 'Composiciones' al panel de texto."""

    def __init__(self, widget: QPlainTextEdit):
        super().__init__()
        self.widget = widget
        self.setFormatter(logging.Formatter("%(levelname)-8s %(message)s"))

    def emit(self, record):
        self.widget.appendPlainText(self.format(record))
        # La generación corre en el hilo principal: refrescar la UI aquí
        QCoreApplication.processEvents()


class DialogoPlanos(QDialog):
    def __init__(self, base: str, parent=None):
        super().__init__(parent)
        self.base = base
        if base not in sys.path:
            sys.path.insert(0, base)

        self.setWindowTitle("Planos Auto — Generador")
        self.resize(700, 640)
        self._construir_ui()
        self._cargar_proyectos()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _construir_ui(self):
        lay = QVBoxLayout(self)

        fila_proy = QHBoxLayout()
        fila_proy.addWidget(QLabel("Proyecto:"))
        self.combo_proyecto = QComboBox()
        self.combo_proyecto.currentTextChanged.connect(self._cargar_capas)
        fila_proy.addWidget(self.combo_proyecto, 1)
        btn_nuevo_proy = QPushButton("Nuevo proyecto…")
        btn_nuevo_proy.clicked.connect(self._nuevo_proyecto)
        fila_proy.addWidget(btn_nuevo_proy)
        btn_editar_proy = QPushButton("Editar datos…")
        btn_editar_proy.clicked.connect(self._editar_proyecto)
        fila_proy.addWidget(btn_editar_proy)
        lay.addLayout(fila_proy)

        lay.addWidget(QLabel("Planos a generar:"))
        self.lista_capas = QListWidget()
        lay.addWidget(self.lista_capas, 2)

        fila_opts = QHBoxLayout()
        btn_todas = QPushButton("Todas")
        btn_todas.clicked.connect(lambda: self._marcar_todo(True))
        btn_ninguna = QPushButton("Ninguna")
        btn_ninguna.clicked.connect(lambda: self._marcar_todo(False))
        fila_opts.addWidget(btn_todas)
        fila_opts.addWidget(btn_ninguna)
        fila_opts.addStretch()
        fila_opts.addWidget(QLabel("DPI:"))
        self.spin_dpi = QSpinBox()
        self.spin_dpi.setRange(72, 600)
        self.spin_dpi.setValue(200)
        fila_opts.addWidget(self.spin_dpi)
        lay.addLayout(fila_opts)

        self.btn_generar = QPushButton("Generar planos")
        self.btn_generar.setDefault(True)
        self.btn_generar.clicked.connect(self._generar)
        lay.addWidget(self.btn_generar)

        lay.addWidget(QLabel("Log:"))
        self.panel_log = QPlainTextEdit()
        self.panel_log.setReadOnly(True)
        lay.addWidget(self.panel_log, 3)

    # ── Carga de datos ────────────────────────────────────────────────────────

    def _cargar_proyectos(self, seleccionar: str = None):
        carpeta = os.path.join(self.base, "config", "proyectos")
        proyectos = sorted(
            os.path.splitext(f)[0]
            for f in (os.listdir(carpeta) if os.path.isdir(carpeta) else [])
            if f.endswith(".json")
        )
        self.combo_proyecto.blockSignals(True)
        self.combo_proyecto.clear()
        self.combo_proyecto.addItems(proyectos)
        self.combo_proyecto.blockSignals(False)
        if seleccionar and seleccionar in proyectos:
            self.combo_proyecto.setCurrentText(seleccionar)
        if not proyectos:
            QMessageBox.warning(
                self, "Planos Auto",
                f"No hay proyectos en:\n{carpeta}",
            )
        self._cargar_capas(self.combo_proyecto.currentText())

    def _nuevo_proyecto(self):
        from .editor_proyecto import DialogoProyecto

        dlg = DialogoProyecto(self.base, proyecto_existente=None, parent=self)
        if dlg.exec_() and dlg.slug_guardado:
            self._cargar_proyectos(seleccionar=dlg.slug_guardado)

    def _editar_proyecto(self):
        from .editor_proyecto import DialogoProyecto

        proyecto = self.combo_proyecto.currentText()
        if not proyecto:
            QMessageBox.warning(self, "Planos Auto", "Elige un proyecto primero.")
            return
        dlg = DialogoProyecto(self.base, proyecto_existente=proyecto, parent=self)
        if dlg.exec_() and dlg.slug_guardado:
            self._cargar_proyectos(seleccionar=dlg.slug_guardado)

    def _cargar_capas(self, proyecto: str):
        self.lista_capas.clear()
        if not proyecto:
            return
        ruta = os.path.join(self.base, "config", "proyectos", f"{proyecto}.json")
        try:
            with open(ruta, encoding="utf-8") as fh:
                cfg = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            QMessageBox.warning(self, "Planos Auto", f"No se pudo leer:\n{ruta}\n\n{exc}")
            return

        self.spin_dpi.setValue(cfg.get("dpi", 200))
        for capa in cfg.get("capas", []):
            if not capa.get("nombre_plano"):
                continue  # entradas de comentario (_grupo)
            item = QListWidgetItem(
                f"{capa['nombre_plano']}   —   escala 1:{capa.get('escala', '?')}"
            )
            item.setData(Qt.UserRole, capa["nombre_capa"])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.lista_capas.addItem(item)

    def _marcar_todo(self, marcado: bool):
        estado = Qt.Checked if marcado else Qt.Unchecked
        for i in range(self.lista_capas.count()):
            self.lista_capas.item(i).setCheckState(estado)

    # ── Ejecución ─────────────────────────────────────────────────────────────

    def _capas_marcadas(self) -> list:
        return [
            self.lista_capas.item(i).data(Qt.UserRole)
            for i in range(self.lista_capas.count())
            if self.lista_capas.item(i).checkState() == Qt.Checked
        ]

    def _generar(self):
        proyecto = self.combo_proyecto.currentText()
        if not proyecto:
            return
        marcadas = self._capas_marcadas()
        if not marcadas:
            QMessageBox.warning(
                self, "Planos Auto", "Marca al menos un plano para generar."
            )
            return
        # Todas marcadas = sin filtro (mismo comportamiento que SOLO_CAPAS = [])
        solo_capas = [] if len(marcadas) == self.lista_capas.count() else marcadas

        self.panel_log.clear()
        self.btn_generar.setEnabled(False)
        self.btn_generar.setText("Generando…")
        QCoreApplication.processEvents()
        try:
            self._ejecutar(proyecto, solo_capas, self.spin_dpi.value())
        except Exception:
            self.panel_log.appendPlainText(
                "✗ ERROR INESPERADO:\n" + traceback.format_exc()
            )
        finally:
            self.btn_generar.setEnabled(True)
            self.btn_generar.setText("Generar planos")

    def _ejecutar(self, proyecto: str, solo_capas: list, dpi: int):
        # Recargar módulos del repo para evitar caché en QGIS (igual que main.py)
        for mod_name in sorted(sys.modules):
            if mod_name.startswith("core.") or mod_name == "generar_planos":
                importlib.reload(sys.modules[mod_name])

        from core import utils
        from core.configuracion import cargar_config
        from generar_planos import generar_composiciones

        handler = _HandlerLogQt(self.panel_log)
        utils.EXTRA_HANDLERS.append(handler)
        try:
            cfg = cargar_config(self.base, proyecto, solo_capas=solo_capas, dpi=dpi)
            generar_composiciones(cfg)
        finally:
            utils.EXTRA_HANDLERS.remove(handler)
