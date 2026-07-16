"""
plugin.py — Registro del plugin en QGIS: botón de barra de herramientas
y entrada de menú que abren el diálogo generador.
"""

import os

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction


def repo_base() -> str:
    """
    Raíz del repo Planos_auto. El plugin se instala como symlink dentro
    del perfil de QGIS, así que realpath resuelve a la copia real.
    """
    return os.path.dirname(os.path.dirname(os.path.realpath(__file__)))


class PlanosAutoPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dialogo = None

    def initGui(self):
        icono = QIcon(os.path.join(repo_base(), "assets", "logo_sinergia.jpg"))
        self.action = QAction(icono, "Generar planos…", self.iface.mainWindow())
        self.action.triggered.connect(self.abrir_dialogo)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("Planos Auto", self.action)

    def unload(self):
        self.iface.removePluginMenu("Planos Auto", self.action)
        self.iface.removeToolBarIcon(self.action)
        if self.dialogo:
            self.dialogo.close()
        self.action = None
        self.dialogo = None

    def abrir_dialogo(self):
        # Import tardío para que "Recargar plugin" tome cambios del diálogo
        from .dialogo import DialogoPlanos

        # Si hay una generación en curso, reusar el diálogo (la UI sigue viva
        # por processEvents y un clic aquí crearía un duplicado a media corrida)
        if self.dialogo and getattr(self.dialogo, "en_ejecucion", False):
            self.dialogo.show()
            self.dialogo.raise_()
            return

        # Se recrea cada vez: así refresca la lista de proyectos/capas
        self.dialogo = DialogoPlanos(repo_base(), self.iface.mainWindow())
        self.dialogo.show()
        self.dialogo.raise_()
