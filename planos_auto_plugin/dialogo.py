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

from qgis.PyQt.QtCore import QCoreApplication, Qt, QUrl
from qgis.PyQt.QtGui import QBrush, QColor, QDesktopServices
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

# Mismo azul de acento que usan los planos (estilo_moderno.color_acento)
_ACENTO = "#08306b"

_ESTILO = f"""
#dlgPlanos {{ background: #f4f6f9; }}
#cabecera {{ background: {_ACENTO}; }}
#titulo {{ color: white; font-size: 17pt; font-weight: 600; }}
#subtitulo {{ color: #c6d4e8; font-size: 9pt; }}
#pildora {{
    border: 1px solid rgba(255,255,255,0.35); border-radius: 12px;
    padding: 4px 12px; color: white; background: rgba(255,255,255,0.08);
}}
#pildora:hover {{ background: rgba(255,255,255,0.18); }}
#tarjeta {{ background: white; border: 1px solid #dde3ea; border-radius: 8px; }}
#seccion {{ color: #6b7a8c; font-size: 8pt; font-weight: 600; letter-spacing: 1px; }}
#conteo {{ color: #6b7a8c; }}
QPushButton#enlace {{
    border: none; background: transparent; color: {_ACENTO};
    padding: 2px 6px; font-weight: 600;
}}
QPushButton#enlace:hover {{ text-decoration: underline; }}
QPushButton#plano_btn, QPushButton#secundario {{
    border: 1px solid #cfd7e1; border-radius: 6px; background: white;
    padding: 6px 12px; color: #24313f;
}}
QPushButton#plano_btn:hover, QPushButton#secundario:hover {{
    background: #eef2f7; border-color: #b7c3d1;
}}
QPushButton#primario {{
    border: none; border-radius: 6px; background: {_ACENTO}; color: white;
    padding: 8px 22px; font-weight: 600;
}}
QPushButton#primario:hover {{ background: #0b4290; }}
QPushButton#primario:disabled {{ background: #9fb0c6; }}
QTreeWidget {{
    border: 1px solid #e3e8ee; border-radius: 6px;
    alternate-background-color: #f7f9fb; background: white;
}}
QTreeWidget::item {{ padding: 3px 0; }}
QHeaderView::section {{
    background: white; border: none; border-bottom: 1px solid #e3e8ee;
    padding: 4px 6px; color: #6b7a8c; font-weight: 600;
}}
QProgressBar {{ border: none; background: #dde3ea; border-radius: 2px; }}
QProgressBar::chunk {{ background: {_ACENTO}; border-radius: 2px; }}
#log {{
    border: 1px solid #dde3ea; border-radius: 8px; background: #1e2530;
    color: #d6dde6; font-family: monospace; font-size: 9pt; padding: 6px;
}}
"""


def _es_plantilla(nombre: str) -> bool:
    """Plantillas = proyectos que vienen en el repo (Plantilla_LAI y
    Plantilla_LAI_Municipal); el resto los crea el usuario."""
    return nombre.lower().startswith("plantilla")


_URL_FUENTES = (
    "https://github.com/Leonardo08202689/planos_auto/blob/main/fuentes_datos.md"
)

def _abrir_en_navegador_linux(ruta: str) -> bool:
    import shutil
    import subprocess

    if not shutil.which("gtk-launch"):
        return False
    for consulta in (
        ["xdg-settings", "get", "default-web-browser"],
        ["xdg-mime", "query", "default", "x-scheme-handler/https"],
    ):
        try:
            app = subprocess.run(
                consulta, capture_output=True, text=True, timeout=3
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            continue
        if app.endswith(".desktop"):
            subprocess.Popen(
                ["gtk-launch", app, ruta], start_new_session=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return True
    return False


_SOLO_PLANTILLA = "— Ninguno (usar la plantilla) —"


class _HandlerLogQt(logging.Handler):
    """Redirige los registros del logger 'Composiciones' al panel de texto."""

    def __init__(self, widget: QPlainTextEdit):
        super().__init__()
        self.widget = widget
        self.setFormatter(logging.Formatter("%(levelname)-8s %(message)s"))

    def emit(self, record):
        try:
            self.widget.appendPlainText(self.format(record))
            # La generación corre en el hilo principal: refrescar la UI aquí
            QCoreApplication.processEvents()
        except RuntimeError:
            # El widget de log fue destruido (diálogo cerrado); no abortar la corrida
            pass


class DialogoPlanos(QDialog):
    def __init__(self, base: str, parent=None):
        super().__init__(parent)
        self.base = base
        self.en_ejecucion = False
        if base not in sys.path:
            sys.path.insert(0, base)

        self.setWindowTitle("Planos Auto — Generador")
        self.resize(760, 800)
        self._cem_ruta = ""
        self._construir_ui()
        if not os.path.exists(os.path.join(base, ".env")):
            QMessageBox.information(
                self, "Planos Auto",
                "Antes de generar planos necesitas configurar la conexión "
                "al servidor de mapas. Pide los datos a tu administrador."
            )
            self._configurar_conexion()
        else:
            self._verificar_conexion()
        self._cargar_proyectos()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _construir_ui(self):
        self.setObjectName("dlgPlanos")
        self.setStyleSheet(_ESTILO)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 12)
        lay.setSpacing(10)

        # Encabezado: título + estado de la conexión
        cab = QFrame()
        cab.setObjectName("cabecera")
        fila_cab = QHBoxLayout(cab)
        fila_cab.setContentsMargins(18, 12, 14, 12)
        textos = QVBoxLayout()
        textos.setSpacing(0)
        titulo = QLabel("Planos Auto")
        titulo.setObjectName("titulo")
        subtitulo = QLabel("Generador de planos y figuras · SINERGIA Ambiental")
        subtitulo.setObjectName("subtitulo")
        textos.addWidget(titulo)
        textos.addWidget(subtitulo)
        fila_cab.addLayout(textos, 1)
        self.led_conexion = QPushButton("●  Verificando…")
        self.led_conexion.setObjectName("pildora")
        self.led_conexion.setCursor(Qt.PointingHandCursor)
        self.led_conexion.setToolTip("Clic para configurar la conexión")
        self.led_conexion.clicked.connect(self._configurar_conexion)
        fila_cab.addWidget(self.led_conexion)
        lay.addWidget(cab)

        cuerpo = QVBoxLayout()
        cuerpo.setContentsMargins(14, 0, 14, 0)
        cuerpo.setSpacing(10)
        lay.addLayout(cuerpo, 1)

        # Tarjeta: plantilla
        tarjeta_plant, lay_plant = self._tarjeta("PLANTILLA")
        self.combo_plantilla = QComboBox()
        self.combo_plantilla.setToolTip(
            "Juego de planos base. Se usa tal cual si no eliges proyecto, "
            "y es la que se copia al crear uno nuevo."
        )
        self.combo_plantilla.currentTextChanged.connect(self._seleccion_cambiada)
        lay_plant.addWidget(self.combo_plantilla)
        cuerpo.addWidget(tarjeta_plant)

        # Tarjeta: proyecto
        tarjeta_proy, lay_proy = self._tarjeta("PROYECTO")
        fila_proy = QHBoxLayout()
        self.combo_proyecto = QComboBox()
        self.combo_proyecto.currentTextChanged.connect(self._seleccion_cambiada)
        fila_proy.addWidget(self.combo_proyecto, 1)
        for texto, ayuda, accion in (
            ("Nuevo", "Crear un proyecto nuevo", self._nuevo_proyecto),
            ("Editar", "Editar los datos del proyecto", self._editar_proyecto),
            ("Eliminar", "Eliminar el proyecto", self._eliminar_proyecto),
        ):
            btn = QPushButton(texto)
            btn.setObjectName("plano_btn")
            btn.setToolTip(ayuda)
            btn.clicked.connect(accion)
            fila_proy.addWidget(btn)
            if texto == "Eliminar":
                self.btn_eliminar = btn
            elif texto == "Editar":
                self.btn_editar = btn
        lay_proy.addLayout(fila_proy)
        cuerpo.addWidget(tarjeta_proy)

        # Tarjeta: planos a generar
        tarjeta_planos, lay_planos = self._tarjeta("PLANOS A GENERAR")
        fila_sel = QHBoxLayout()
        self.lbl_conteo = QLabel("")
        self.lbl_conteo.setObjectName("conteo")
        fila_sel.addWidget(self.lbl_conteo)
        fila_sel.addStretch()
        for texto, valor in (("Todas", True), ("Ninguna", False)):
            btn = QPushButton(texto)
            btn.setObjectName("enlace")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, v=valor: self._marcar_todo(v))
            fila_sel.addWidget(btn)
        lay_planos.addLayout(fila_sel)
        self.lista_capas = QTreeWidget()
        self.lista_capas.setColumnCount(3)
        self.lista_capas.setHeaderLabels(["Nombre", "Tipo", "Escala"])
        self.lista_capas.setRootIsDecorated(False)
        self.lista_capas.setAlternatingRowColors(True)
        self.lista_capas.setUniformRowHeights(True)
        self.lista_capas.setSelectionMode(QAbstractItemView.NoSelection)
        self.lista_capas.setFocusPolicy(Qt.NoFocus)
        cabecera = self.lista_capas.header()
        cabecera.setStretchLastSection(False)
        cabecera.setSectionResizeMode(0, QHeaderView.Stretch)
        cabecera.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        cabecera.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.lista_capas.itemChanged.connect(lambda *_: self._actualizar_conteo())
        self.lista_capas.itemClicked.connect(self._alternar_item)
        lay_planos.addWidget(self.lista_capas, 1)
        cuerpo.addWidget(tarjeta_planos, 3)

        # Tarjeta: opciones
        tarjeta_opts, lay_opts = self._tarjeta("ACABADO")
        fila_opts = QHBoxLayout()
        self.chk_relieve = QCheckBox("Relieve (CEM)")
        fila_opts.addWidget(self.chk_relieve)
        fila_opts.addStretch()
        fila_opts.addWidget(QLabel("Resolución"))
        self.spin_dpi = QSpinBox()
        self.spin_dpi.setRange(72, 600)
        self.spin_dpi.setSingleStep(50)
        self.spin_dpi.setSuffix(" dpi")
        self.spin_dpi.setValue(200)
        fila_opts.addWidget(self.spin_dpi)
        lay_opts.addLayout(fila_opts)
        cuerpo.addWidget(tarjeta_opts)

        # Acciones
        fila_generar = QHBoxLayout()
        self.btn_actualizar = QPushButton("Buscar actualizaciones")
        self.btn_actualizar.setObjectName("plano_btn")
        self.btn_actualizar.clicked.connect(self._buscar_actualizacion)
        fila_generar.addWidget(self.btn_actualizar)
        fila_generar.addStretch()
        self.btn_guardar_capas = QPushButton("Guardar capas generadas…")
        self.btn_guardar_capas.setObjectName("secundario")
        self.btn_guardar_capas.setToolTip(
            "Exporta a un GeoPackage las capas temporales que quedan en el "
            "panel de QGIS tras generar los planos (polígonos recortados, "
            "centroides, etiquetas…), para que no se pierdan al cerrar QGIS."
        )
        self.btn_guardar_capas.clicked.connect(self._guardar_capas_generadas)
        fila_generar.addWidget(self.btn_guardar_capas)
        self.btn_generar = QPushButton("Generar planos")
        self.btn_generar.setObjectName("primario")
        self.btn_generar.setDefault(True)
        self.btn_generar.clicked.connect(self._generar)
        fila_generar.addWidget(self.btn_generar)
        cuerpo.addLayout(fila_generar)

        self.barra = QProgressBar()
        self.barra.setTextVisible(False)
        self.barra.setFixedHeight(4)
        self.barra.setRange(0, 0)
        self.barra.hide()
        cuerpo.addWidget(self.barra)

        # Registro (plegable)
        fila_log = QHBoxLayout()
        self.btn_log = QPushButton("▾  Registro")
        self.btn_log.setObjectName("enlace")
        self.btn_log.setCursor(Qt.PointingHandCursor)
        self.btn_log.clicked.connect(self._alternar_log)
        fila_log.addWidget(self.btn_log)
        fila_log.addStretch()
        self.lbl_estado = QLabel("")
        self.lbl_estado.setObjectName("conteo")
        fila_log.addWidget(self.lbl_estado)
        btn_fuentes = QPushButton("Fuentes de datos ↗")
        btn_fuentes.setObjectName("enlace")
        btn_fuentes.setCursor(Qt.PointingHandCursor)
        btn_fuentes.setToolTip("De qué dataset oficial sale cada capa (INEGI, CONANP, CONABIO…)")
        btn_fuentes.clicked.connect(self._abrir_fuentes)
        fila_log.addWidget(btn_fuentes)
        cuerpo.addLayout(fila_log)
        self.panel_log = QPlainTextEdit()
        self.panel_log.setObjectName("log")
        self.panel_log.setReadOnly(True)
        self.panel_log.setPlaceholderText(
            "Aquí aparece el avance cuando generes los planos."
        )
        self.panel_log.setMinimumHeight(140)
        self.panel_log.hide()  # se abre solo al generar
        self.btn_log.setText("▸  Registro")
        cuerpo.addWidget(self.panel_log, 2)

    def _tarjeta(self, titulo: str):
        marco = QFrame()
        marco.setObjectName("tarjeta")
        interior = QVBoxLayout(marco)
        interior.setContentsMargins(12, 10, 12, 12)
        interior.setSpacing(8)
        etiqueta = QLabel(titulo)
        etiqueta.setObjectName("seccion")
        interior.addWidget(etiqueta)
        return marco, interior

    def _abrir_fuentes(self):
        """Abre docs/fuentes_datos.html en el navegador (viene con la
        instalación); si no está, la versión de GitHub."""
        local = os.path.join(self.base, "docs", "fuentes_datos.html")
        if not os.path.exists(local):
            QDesktopServices.openUrl(QUrl(_URL_FUENTES))
            return
        # En Linux el .html puede estar asociado a otra app (p. ej. ChatGPT);
        # se abre con el navegador web predeterminado, no con esa asociación.
        if sys.platform.startswith("linux") and _abrir_en_navegador_linux(local):
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(local))

    def _alternar_log(self):
        visible = not self.panel_log.isVisible()
        self.panel_log.setVisible(visible)
        self.btn_log.setText(("▾" if visible else "▸") + "  Registro")

    def _alternar_item(self, item, columna):
        # Clic en cualquier parte de la fila marca/desmarca (no solo en la casilla)
        if columna != 0:
            item.setCheckState(
                0, Qt.Unchecked if item.checkState(0) == Qt.Checked else Qt.Checked
            )

    def _actualizar_conteo(self):
        total = self.lista_capas.topLevelItemCount()
        marcadas = len(self._capas_marcadas())
        self.lbl_conteo.setText(f"{marcadas} de {total} seleccionados")
        if not self.en_ejecucion:
            self.btn_generar.setText(
                f"Generar {marcadas} plano{'s' if marcadas != 1 else ''}"
                if marcadas else "Generar planos"
            )
            self.btn_generar.setEnabled(marcadas > 0)

    # ── Carga de datos ────────────────────────────────────────────────────────

    def _cargar_proyectos(self, seleccionar: str = None):
        carpeta = os.path.join(self.base, "config", "proyectos")
        proyectos = sorted(
            os.path.splitext(f)[0]
            for f in (os.listdir(carpeta) if os.path.isdir(carpeta) else [])
            if f.endswith(".json")
            # plantilla.json es el ejemplo genérico del repo: no se lista
            and os.path.splitext(f)[0] != "plantilla"
        )
        plantillas = [p for p in proyectos if _es_plantilla(p)]
        propios = sorted((p for p in proyectos if not _es_plantilla(p)), key=str.lower)

        # Señales bloqueadas durante todo el rearmado: _cargar_capas se llama
        # una sola vez, explícitamente, al final.
        anterior = self.combo_plantilla.currentText()
        for combo in (self.combo_plantilla, self.combo_proyecto):
            combo.blockSignals(True)
            combo.clear()
        self.combo_plantilla.addItems(plantillas)
        self.combo_proyecto.addItem(_SOLO_PLANTILLA)
        self.combo_proyecto.addItems(propios)

        if seleccionar in plantillas:
            self.combo_plantilla.setCurrentText(seleccionar)
        else:
            if anterior in plantillas:
                self.combo_plantilla.setCurrentText(anterior)
            if seleccionar in propios:
                self.combo_proyecto.setCurrentText(seleccionar)
        for combo in (self.combo_plantilla, self.combo_proyecto):
            combo.blockSignals(False)
        if not proyectos:
            QMessageBox.warning(
                self, "Planos Auto",
                f"No hay proyectos en:\n{carpeta}",
            )
        self._seleccion_cambiada()

    def _proyecto_activo(self) -> str:
        """El proyecto elegido; si no hay, la plantilla."""
        if self.combo_proyecto.currentIndex() > 0:
            return self.combo_proyecto.currentText()
        return self.combo_plantilla.currentText()

    def _seleccion_cambiada(self, *_):
        hay_proyecto = self.combo_proyecto.currentIndex() > 0
        self.btn_eliminar.setEnabled(hay_proyecto)
        self.btn_editar.setToolTip(
            "Editar los datos del proyecto" if hay_proyecto
            else "Editar los datos de la plantilla"
        )
        self._cargar_capas(self._proyecto_activo())

    def _configurar_conexion(self):
        from .configurar_conexion import DialogoConexion

        DialogoConexion(self.base, parent=self).exec_()
        self._verificar_conexion()

    def _buscar_actualizacion(self):
        respuesta = QMessageBox.question(
            self, "Buscar actualizaciones",
            "Esto descarga la última versión del programa desde GitHub y "
            "reemplaza sus archivos (tu conexión, tus proyectos y tus planos "
            "generados no se tocan). Vas a necesitar cerrar y volver a abrir "
            "QGIS después para que se apliquen los cambios.\n\n¿Continuar?",
        )
        if respuesta != QMessageBox.Yes:
            return
        self.setCursor(Qt.WaitCursor)
        try:
            from .actualizar import buscar_actualizacion
            buscar_actualizacion(self.base)
        except Exception as e:
            self.unsetCursor()
            QMessageBox.critical(self, "Buscar actualizaciones", str(e))
            return
        self.unsetCursor()
        QMessageBox.information(
            self, "Buscar actualizaciones",
            "Listo. Cierra y vuelve a abrir QGIS para que se apliquen los cambios."
        )

    def _verificar_conexion(self):
        from core.utils import leer_env

        env = leer_env(os.path.join(self.base, ".env"))
        ok = False
        error = "Falta configurar el servidor"
        self._cem_ruta = env.get("CEM_RUTA", "")
        if env.get("PG_HOST"):
            try:
                import psycopg2
                conn = psycopg2.connect(
                    host=env.get("PG_HOST", ""),
                    port=env.get("PG_PORT", "5432"),
                    dbname=env.get("PG_DBNAME", ""),
                    user=env.get("PG_USER", ""),
                    password=env.get("PG_PASSWORD", ""),
                    connect_timeout=3,
                )
                conn.close()
                ok = True
            except Exception as e:
                ok = False
                error = f"{type(e).__name__}: {e}".strip()
                self.panel_log.appendPlainText(
                    f"Sin conexión a {env.get('PG_HOST')}: {error}"
                )
        texto = "Conectado a la base de datos" if ok else "Sin conexión a la base de datos"
        if not ok and env.get("PG_HOST"):
            texto += f"\n{error}"
            if self.panel_log.isHidden():
                self._alternar_log()
        color = "#5fe39a" if ok else "#ff8a80"  # verde / rojo sobre el azul
        self.led_conexion.setText("●  Conectado" if ok else "●  Sin conexión")
        self.led_conexion.setStyleSheet(f"color: {color};")
        self.led_conexion.setToolTip(texto + "\nClic para configurar la conexión")

    def _nuevo_proyecto(self):
        from .editor_proyecto import DialogoProyecto

        dlg = DialogoProyecto(self.base, proyecto_existente=None, parent=self)
        # Copiar los planos de la plantilla elegida arriba
        if hasattr(dlg, "combo_plantilla"):
            dlg.combo_plantilla.setCurrentText(self.combo_plantilla.currentText())
        if dlg.exec_() and dlg.slug_guardado:
            self._cargar_proyectos(seleccionar=dlg.slug_guardado)

    def _editar_proyecto(self):
        from .editor_proyecto import DialogoProyecto

        proyecto = self._proyecto_activo()
        if not proyecto:
            QMessageBox.warning(self, "Planos Auto", "Elige un proyecto primero.")
            return
        dlg = DialogoProyecto(self.base, proyecto_existente=proyecto, parent=self)
        if dlg.exec_() and dlg.slug_guardado:
            self._cargar_proyectos(seleccionar=dlg.slug_guardado)

    def _eliminar_proyecto(self):
        proyecto = self._proyecto_activo()
        if not proyecto:
            QMessageBox.warning(self, "Planos Auto", "Elige un proyecto primero.")
            return
        ruta = os.path.join(self.base, "config", "proyectos", f"{proyecto}.json")
        n_planos = 0
        try:
            with open(ruta, encoding="utf-8") as fh:
                n_planos = sum(
                    1 for c in json.load(fh).get("capas", [])
                    if c.get("nombre_plano")
                )
        except (OSError, json.JSONDecodeError):
            pass
        respuesta = QMessageBox.question(
            self, "Planos Auto",
            f"¿Eliminar el proyecto '{proyecto}' ({n_planos} plano(s) definidos)?\n\n"
            f"Se borrará el archivo:\n{ruta}\n\n"
            f"Los PNG ya generados no se tocan.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if respuesta != QMessageBox.Yes:
            return
        try:
            os.remove(ruta)
        except OSError as exc:
            QMessageBox.warning(self, "Planos Auto", f"No se pudo eliminar:\n{exc}")
            return
        self._cargar_proyectos()

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
        self._cargar_opciones_estilo(cfg)
        self.lista_capas.blockSignals(True)
        for capa in cfg.get("capas", []):
            if not capa.get("nombre_plano"):
                continue  # entradas de comentario (_grupo)
            nombre = capa["nombre_plano"].strip()
            tipo = "Plano"
            for prefijo, etiqueta in (("PLANO.", "Plano"), ("FIGURA.", "Figura")):
                if nombre.upper().startswith(prefijo):
                    nombre, tipo = nombre[len(prefijo):].strip(), etiqueta
                    break
            nombre = nombre[:1].upper() + nombre[1:].lower()
            escala = capa.get("escala")
            item = QTreeWidgetItem([
                nombre, tipo,
                f"1:{int(escala):,}" if isinstance(escala, (int, float)) else "—",
            ])
            item.setToolTip(0, capa["nombre_plano"])
            item.setData(0, Qt.UserRole, capa["nombre_capa"])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Checked)
            item.setTextAlignment(2, Qt.AlignRight | Qt.AlignVCenter)
            item.setForeground(1, QBrush(QColor("#6b7a8c")))
            item.setForeground(2, QBrush(QColor("#6b7a8c")))
            self.lista_capas.addTopLevelItem(item)
        self.lista_capas.blockSignals(False)
        self._actualizar_conteo()

    def _cargar_opciones_estilo(self, cfg_proyecto: dict):
        """Casilla de relieve: el CEM se lee de la base (o de CEM_RUTA)."""
        self.chk_relieve.setChecked(True)
        self.chk_relieve.setEnabled(True)
        self.chk_relieve.setToolTip(
            "Sombreado de relieve a partir del Continuo de Elevaciones "
            "Mexicano (CEM 15 m) en los planos de escala detallada."
        )

    def _marcar_todo(self, marcado: bool):
        estado = Qt.Checked if marcado else Qt.Unchecked
        self.lista_capas.blockSignals(True)
        for i in range(self.lista_capas.topLevelItemCount()):
            self.lista_capas.topLevelItem(i).setCheckState(0, estado)
        self.lista_capas.blockSignals(False)
        self._actualizar_conteo()

    # ── Ejecución ─────────────────────────────────────────────────────────────

    def _capas_marcadas(self) -> list:
        items = [
            self.lista_capas.topLevelItem(i)
            for i in range(self.lista_capas.topLevelItemCount())
        ]
        return [
            it.data(0, Qt.UserRole) for it in items
            if it.checkState(0) == Qt.Checked
        ]

    def _generar(self):
        if self.en_ejecucion:
            return
        proyecto = self._proyecto_activo()
        if not proyecto:
            return
        marcadas = self._capas_marcadas()
        if not marcadas:
            QMessageBox.warning(
                self, "Planos Auto", "Marca al menos un plano para generar."
            )
            return
        # Todas marcadas = sin filtro (mismo comportamiento que SOLO_CAPAS = [])
        solo_capas = [] if len(marcadas) == self.lista_capas.topLevelItemCount() else marcadas

        self.panel_log.clear()
        if not self.panel_log.isVisible():
            self._alternar_log()
        self.en_ejecucion = True
        self.btn_generar.setEnabled(False)
        self.btn_generar.setText("Generando…")
        self.barra.show()
        self.lbl_estado.setText("")
        QCoreApplication.processEvents()
        resultado = "✓ Listo"
        try:
            self._ejecutar(proyecto, solo_capas, self.spin_dpi.value())
        except Exception:
            resultado = "✗ Terminó con error (ver registro)"
            self.panel_log.appendPlainText(
                "✗ ERROR INESPERADO:\n" + traceback.format_exc()
            )
        finally:
            self.en_ejecucion = False
            self.barra.hide()
            self.lbl_estado.setText(resultado)
            self._actualizar_conteo()

    def _ejecutar(self, proyecto: str, solo_capas: list, dpi: int):
        # Recargar módulos del repo para evitar caché en QGIS (igual que main.py):
        # utils y configuracion primero porque los demás importan de ellos.
        primero = ["core.utils", "core.configuracion"]
        for mod_name in primero + sorted(
            m for m in sys.modules
            if (m.startswith("core.") or m == "generar_planos") and m not in primero
        ):
            if mod_name not in sys.modules:
                continue
            try:
                importlib.reload(sys.modules[mod_name])
            except Exception:
                # En Windows la instalación usa una junction (no symlink real);
                # a veces eso hace que reload() no encuentre el spec del módulo
                # ya importado. En vez de tronar, se descarta la entrada en
                # caché: los "from ... import ..." de abajo lo vuelven a
                # importar de cero, logrando el mismo efecto de "sin caché".
                del sys.modules[mod_name]

        from qgis.core import QgsProject

        from core import utils
        from core.capas import resolver_capa_poligono
        from core.configuracion import cargar_config
        from generar_planos import generar_composiciones

        cfg = cargar_config(self.base, proyecto, solo_capas=solo_capas, dpi=dpi)
        # Casilla de relieve: solo afecta esta corrida, no toca los JSON.
        # El estilo moderno va siempre (lo controla config/global.json).
        em = cfg.get("estilo_moderno")
        if isinstance(em, dict):
            em = dict(em)
            if not self.chk_relieve.isChecked():
                em["cem_ruta"] = ""
            cfg["estilo_moderno"] = em

        # Pre-verificación con mensaje claro (el generador también valida,
        # pero su error quedaría solo como una línea en el log)
        capa_poly = resolver_capa_poligono(QgsProject.instance(), cfg["capa_poligono"])
        if not capa_poly:
            QMessageBox.warning(
                self, "Planos Auto",
                f"La capa '{cfg['capa_poligono']}' no está cargada "
                f"en el proyecto de QGIS."
            )
            return
        if not capa_poly.selectedFeatures():
            QMessageBox.warning(
                self, "Planos Auto",
                f"Selecciona el polígono de trabajo en la capa "
                f"'{cfg['capa_poligono']}' antes de generar."
            )
            return

        handler = _HandlerLogQt(self.panel_log)
        utils.EXTRA_HANDLERS.append(handler)
        try:
            generar_composiciones(cfg)
        finally:
            utils.EXTRA_HANDLERS.remove(handler)

    # ── Guardar capas temporales ─────────────────────────────────────────────

    def _guardar_capas_generadas(self):
        """Exporta a un GeoPackage las capas 'memory' que generar_planos.py
        deja bajo el grupo 'Planos Generados' (polígonos recortados,
        centroides, capas extra…). Son temporales: viven solo en la sesión
        de QGIS y se pierden al cerrar si no se guardan aparte."""
        from qgis.core import (
            QgsDataProvider,
            QgsMapLayerType,
            QgsProject,
            QgsVectorFileWriter,
        )
        from qgis.PyQt.QtXml import QDomDocument

        from core.utils import sanitizar_nombre

        project = QgsProject.instance()
        grupo = project.layerTreeRoot().findGroup("Planos Generados")
        if not grupo:
            QMessageBox.information(
                self, "Guardar capas",
                "No hay capas generadas todavía. Genera planos primero."
            )
            return

        # Todas las capas 'memory' del proyecto, no solo las del grupo: los
        # mapitas (ref_punto) y las leyendas filtradas viven fuera del árbol
        # y, si se quedan en 'memory', reaparecen vacías al reabrir.
        capas = [
            c for c in project.mapLayers().values()
            if c.type() == QgsMapLayerType.VectorLayer
            and c.dataProvider().name() == "memory"
        ]
        if not capas:
            QMessageBox.information(
                self, "Guardar capas",
                "No hay capas temporales para guardar (el fondo satelital y "
                "las demás capas ya vienen de archivo/servidor, no hace "
                "falta exportarlas)."
            )
            return

        proyecto = self._proyecto_activo() or "capas"
        sugerido = os.path.join(
            os.path.expanduser("~"),
            f"{sanitizar_nombre(proyecto)}_capas_generadas.gpkg",
        )
        ruta, _ = QFileDialog.getSaveFileName(
            self, "Guardar capas generadas como GeoPackage",
            sugerido, "GeoPackage (*.gpkg)",
        )
        if not ruta:
            return
        if not ruta.lower().endswith(".gpkg"):
            ruta += ".gpkg"

        usados: set = set()
        errores = []
        reapuntadas = []
        contexto = project.transformContext()
        for i, capa in enumerate(capas):
            nombre = sanitizar_nombre(capa.name()) or f"capa_{i + 1}"
            base, n = nombre, 1
            while nombre in usados:
                n += 1
                nombre = f"{base}_{n}"
            usados.add(nombre)

            opciones = QgsVectorFileWriter.SaveVectorOptions()
            opciones.driverName = "GPKG"
            opciones.layerName = nombre
            opciones.actionOnExistingFile = (
                QgsVectorFileWriter.CreateOrOverwriteFile if i == 0
                else QgsVectorFileWriter.CreateOrOverwriteLayer
            )
            if hasattr(QgsVectorFileWriter, "writeAsVectorFormatV3"):
                resultado = QgsVectorFileWriter.writeAsVectorFormatV3(
                    capa, ruta, contexto, opciones
                )
            else:  # QGIS < 3.24, sin writeAsVectorFormatV3
                resultado = QgsVectorFileWriter.writeAsVectorFormatV2(
                    capa, ruta, contexto, opciones
                )
            error = resultado[0]
            if error != QgsVectorFileWriter.NoError:
                mensaje = resultado[1] if len(resultado) > 1 else str(error)
                errores.append(f"{capa.name()}: {mensaje}")
                continue

            # Reapuntar la capa del proyecto al GeoPackage: si se queda en
            # 'memory' se pierde al cerrar QGIS aunque el archivo exista.
            estilo = QDomDocument()
            capa.exportNamedStyle(estilo)
            nombre_visible = capa.name()
            uri = f"{ruta}|layername={nombre}"
            try:
                capa.setDataSource(
                    uri, nombre_visible, "ogr", QgsDataProvider.ProviderOptions()
                )
            except TypeError:  # firmas antiguas sin ProviderOptions
                capa.setDataSource(uri, nombre_visible, "ogr")
            try:
                capa.importNamedStyle(estilo)
            except TypeError:  # bindings antiguos: el mensaje es parámetro
                capa.importNamedStyle(estilo, "")
            # Guardar el estilo dentro del GeoPackage (tabla layer_styles)
            # como predeterminado: así al cargar la capa a mano sale con formato.
            err_estilo = capa.saveStyleToDatabase(nombre, "", True, "")
            if err_estilo:
                errores.append(f"{capa.name()} (estilo): {err_estilo}")
            capa.triggerRepaint()
            reapuntadas.append(capa)

        if errores:
            QMessageBox.warning(
                self, "Guardar capas",
                f"Se guardaron {len(reapuntadas)} de {len(capas)} "
                f"capa(s) en:\n{ruta}\n\nErrores:\n" + "\n".join(errores),
            )
        elif not reapuntadas:
            return

        self._ofrecer_guardar_proyecto(ruta, len(reapuntadas))

    def _ofrecer_guardar_proyecto(self, ruta_gpkg, n_capas):
        """Las capas ya apuntan al GeoPackage, pero el proyecto de QGIS debe
        guardarse para que la próxima sesión las vuelva a cargar desde ahí."""
        from qgis.core import QgsProject

        project = QgsProject.instance()
        respuesta = QMessageBox.question(
            self, "Guardar capas",
            f"Se guardaron {n_capas} capa(s) en:\n{ruta_gpkg}\n\n"
            "Las capas del proyecto ya apuntan a ese archivo (dejaron de ser "
            "temporales).\n\n¿Guardar también el proyecto de QGIS ahora? "
            "Si no lo guardas, al reabrir QGIS no aparecerán.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
        )
        if respuesta != QMessageBox.Yes:
            return

        destino = project.fileName()
        if not destino:
            destino, _ = QFileDialog.getSaveFileName(
                self, "Guardar proyecto de QGIS",
                os.path.splitext(ruta_gpkg)[0] + ".qgz",
                "Proyecto QGIS (*.qgz)",
            )
            if not destino:
                return
            if not destino.lower().endswith((".qgz", ".qgs")):
                destino += ".qgz"

        if project.write(destino):
            QMessageBox.information(
                self, "Guardar capas",
                f"Proyecto guardado en:\n{destino}",
            )
        else:
            QMessageBox.warning(
                self, "Guardar capas",
                f"No se pudo guardar el proyecto en:\n{destino}",
            )
