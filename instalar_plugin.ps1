# Enlaza el plugin al perfil de QGIS en Windows (junction: los cambios en el
# repo se reflejan sin reinstalar; basta "Recargar plugin" o reabrir QGIS).
# No requiere permisos de administrador (usa junction, no symlink).
#
# Uso (desde PowerShell, parado en la carpeta del repo):
#   powershell -ExecutionPolicy Bypass -File .\instalar_plugin.ps1

$ErrorActionPreference = "Stop"

$Origen = Join-Path $PSScriptRoot "planos_auto_plugin"

$Perfil = Join-Path $env:APPDATA "QGIS\QGIS3\profiles\default"

if (-not (Test-Path $Perfil)) {
    Write-Host "ERROR: No se encontro el perfil de QGIS en:"
    Write-Host "  $Perfil"
    Write-Host "Abre QGIS al menos una vez para que cree su perfil, luego vuelve a correr este script."
    exit 1
}

$PluginsDir = Join-Path $Perfil "python\plugins"
if (-not (Test-Path $PluginsDir)) {
    New-Item -ItemType Directory -Path $PluginsDir -Force | Out-Null
}

$Destino = Join-Path $PluginsDir "planos_auto_plugin"
if (Test-Path $Destino) {
    (Get-Item $Destino).Delete()
}

New-Item -ItemType Junction -Path $Destino -Target $Origen | Out-Null
Write-Host "OK - Plugin enlazado en: $Destino"

Write-Host ""
Write-Host "En QGIS: Complementos -> Administrar e instalar complementos ->"
Write-Host "pestana 'Instalados' -> activar 'Planos Auto'."
Write-Host "(Marca 'Mostrar tambien complementos experimentales' en Configuracion si no aparece.)"
