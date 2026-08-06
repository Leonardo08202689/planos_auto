#!/usr/bin/env bash
# Enlaza el plugin al perfil por defecto de QGIS (symlink: los cambios en el
# repo se reflejan sin reinstalar; basta "Recargar plugin" o reabrir QGIS).
# Detecta instalaciones nativas (~/.local/share) y Flatpak (~/.var/app).
set -e

ORIGEN="$(cd "$(dirname "$0")" && pwd)/planos_auto_plugin"

RUTAS=(
    "$HOME/.var/app/org.qgis.qgis/data/QGIS/QGIS3/profiles/default/python/plugins"
    "$HOME/.local/share/QGIS/QGIS3/profiles/default/python/plugins"
)

ENLAZADO=0
for PLUGINS_DIR in "${RUTAS[@]}"; do
    # Solo enlazar donde exista el perfil de QGIS correspondiente
    PERFIL="${PLUGINS_DIR%/python/plugins}"
    if [ -d "$PERFIL" ]; then
        mkdir -p "$PLUGINS_DIR"
        ln -sfn "$ORIGEN" "$PLUGINS_DIR/planos_auto_plugin"
        echo "✓ Plugin enlazado en: $PLUGINS_DIR/planos_auto_plugin"
        ENLAZADO=1
    fi
done

if [ "$ENLAZADO" -eq 0 ]; then
    echo "✗ No se encontró ningún perfil de QGIS. Rutas buscadas:"
    printf '  %s\n' "${RUTAS[@]}"
    exit 1
fi

echo
echo "En QGIS: Complementos → Administrar e instalar complementos →"
echo "pestaña 'Instalados' → activar 'Planos Auto'."
echo "(Marca 'Mostrar también complementos experimentales' en Configuración si no aparece.)"
