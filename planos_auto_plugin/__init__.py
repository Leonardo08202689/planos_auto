"""Plugin de QGIS — Generador Automático de Planos (SINERGIA)."""


def classFactory(iface):
    from .plugin import PlanosAutoPlugin
    return PlanosAutoPlugin(iface)
