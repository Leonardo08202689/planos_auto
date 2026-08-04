"""
configurar_conexion.py — Formulario para crear/editar el .env sin tocar
archivos de texto. Pensado para usuarios no técnicos: dirección del
servidor, si son administradores o no, contraseña y carpeta de salida.
"""

import os

from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from core.utils import leer_env

# Valores fijos de la empresa: no cambian de una computadora a otra.
_PG_PORT_DEFAULT = "5432"
_PG_DBNAME = "gis_empresa"
_PG_SCHEMA = "proyectos"


class DialogoConexion(QDialog):
    def __init__(self, base: str, parent=None):
        super().__init__(parent)
        self.base = base
        self.setWindowTitle("Conexión a la base de datos")
        self.resize(420, 0)
        self._construir_ui()
        self._cargar_valores_actuales()

    def _construir_ui(self):
        lay = QVBoxLayout(self)

        lay.addWidget(QLabel(
            "Pide estos datos a quien administra el servidor de mapas."
        ))

        form = QFormLayout()

        self.edit_direccion = QLineEdit()
        self.edit_direccion.setPlaceholderText("Ej. 100.77.90.48 (o scianas.local:55432 si el administrador te dio un puerto)")
        form.addRow("Dirección del servidor:", self.edit_direccion)

        self.chk_admin = QCheckBox("Puedo editar la base de datos (soy administrador)")
        form.addRow("", self.chk_admin)

        self.edit_password = QLineEdit()
        self.edit_password.setEchoMode(QLineEdit.Password)
        form.addRow("Contraseña:", self.edit_password)

        fila_carpeta = QHBoxLayout()
        self.edit_carpeta = QLineEdit()
        fila_carpeta.addWidget(self.edit_carpeta)
        btn_examinar = QPushButton("Examinar…")
        btn_examinar.clicked.connect(self._elegir_carpeta)
        fila_carpeta.addWidget(btn_examinar)
        form.addRow("Carpeta donde guardar los planos:", fila_carpeta)

        lay.addLayout(form)

        botones = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        botones.button(QDialogButtonBox.Save).setText("Guardar")
        botones.button(QDialogButtonBox.Cancel).setText("Cancelar")
        botones.accepted.connect(self._guardar)
        botones.rejected.connect(self.reject)
        lay.addWidget(botones)

    def _elegir_carpeta(self):
        carpeta = QFileDialog.getExistingDirectory(
            self, "Elige la carpeta donde se guardarán los planos", self.edit_carpeta.text()
        )
        if carpeta:
            self.edit_carpeta.setText(carpeta)

    def _cargar_valores_actuales(self):
        env = leer_env(os.path.join(self.base, ".env"))
        host = env.get("PG_HOST", "")
        puerto = env.get("PG_PORT", _PG_PORT_DEFAULT)
        if host and puerto and puerto != _PG_PORT_DEFAULT:
            host = f"{host}:{puerto}"
        self.edit_direccion.setText(host)
        self.chk_admin.setChecked(env.get("PG_USER") == "qgis_user")
        self.edit_password.setText(env.get("PG_PASSWORD", ""))
        self.edit_carpeta.setText(
            env.get("OUTPUT_BASE")
            or os.path.join(os.path.expanduser("~"), "planos_salida")
        )

    def _guardar(self):
        direccion = self.edit_direccion.text().strip()
        password  = self.edit_password.text()
        carpeta   = self.edit_carpeta.text().strip()

        if not direccion or not password or not carpeta:
            QMessageBox.warning(
                self, "Conexión a la base de datos",
                "Completa la dirección del servidor, la contraseña y la carpeta."
            )
            return

        os.makedirs(carpeta, exist_ok=True)

        host, _, puerto = direccion.partition(":")
        host = host.strip()
        puerto = puerto.strip() or _PG_PORT_DEFAULT

        usuario = "qgis_user" if self.chk_admin.isChecked() else "planos_lector"
        ruta_env = os.path.join(self.base, ".env")
        contenido = (
            f"PG_HOST={host}\n"
            f"PG_PORT={puerto}\n"
            f"PG_DBNAME={_PG_DBNAME}\n"
            f"PG_SCHEMA={_PG_SCHEMA}\n"
            f"PG_USER={usuario}\n"
            f"PG_PASSWORD={password}\n"
            f"OUTPUT_BASE={carpeta}\n"
        )
        with open(ruta_env, "w", encoding="utf-8") as fh:
            fh.write(contenido)
        try:
            os.chmod(ruta_env, 0o600)  # no-op inofensivo en Windows
        except OSError:
            pass

        self.accept()
